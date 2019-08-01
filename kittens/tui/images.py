#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import os
import sys
from base64 import standard_b64encode
from collections import defaultdict, deque
from itertools import count
from contextlib import suppress

from kitty.utils import fit_image

from .operations import cursor

try:
    fsenc = sys.getfilesystemencoding() or 'utf-8'
    codecs.lookup(fsenc)
except Exception:
    fsenc = 'utf-8'


class ImageData:

    def __init__(self, fmt, width, height, mode):
        self.width, self.height, self.fmt, self.mode = width, height, fmt, mode
        self.transmit_fmt = str(24 if self.mode == 'rgb' else 32)


class OpenFailed(ValueError):

    def __init__(self, path, message):
        ValueError.__init__(
            self, 'Failed to open image: {} with error: {}'.format(path, message)
        )
        self.path = path


class ConvertFailed(ValueError):

    def __init__(self, path, message):
        ValueError.__init__(
            self, 'Failed to convert image: {} with error: {}'.format(path, message)
        )
        self.path = path


class NoImageMagick(Exception):
    pass


def run_imagemagick(path, cmd, keep_stdout=True):
    import subprocess
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE if keep_stdout else subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise NoImageMagick('ImageMagick is required to process images')
    if p.returncode != 0:
        raise OpenFailed(path, p.stderr.decode('utf-8'))
    return p


def identify(path):
    p = run_imagemagick(path, ['identify', '-format', '%m %w %h %A', '--', path])
    parts = tuple(filter(None, p.stdout.decode('utf-8').split()))
    mode = 'rgb' if parts[3].lower() == 'false' else 'rgba'
    return ImageData(parts[0].lower(), int(parts[1]), int(parts[2]), mode)


def convert(path, m, available_width, available_height, scale_up, tdir=None):
    from tempfile import NamedTemporaryFile
    width, height = m.width, m.height
    cmd = ['convert', '-background', 'none', '--', path]
    scaled = False
    if scale_up:
        if width < available_width:
            r = available_width / width
            width, height = available_width, int(height * r)
            scaled = True
    if scaled or width > available_width or height > available_height:
        width, height = fit_image(width, height, available_width, available_height)
        cmd += ['-resize', '{}x{}!'.format(width, height)]
    with NamedTemporaryFile(prefix='icat-', suffix='.' + m.mode, delete=False, dir=tdir) as outfile:
        run_imagemagick(path, cmd + [outfile.name])
    # ImageMagick sometimes generated rgba images smaller than the specified
    # size. See https://github.com/kovidgoyal/kitty/issues/276 for examples
    sz = os.path.getsize(outfile.name)
    bytes_per_pixel = 3 if m.mode == 'rgb' else 4
    expected_size = bytes_per_pixel * width * height
    if sz < expected_size:
        missing = expected_size - sz
        if missing % (bytes_per_pixel * width) != 0:
            raise ConvertFailed(
                path, 'ImageMagick failed to convert {} correctly,'
                ' it generated {} < {} of data (w={}, h={}, bpp={})'.format(
                    path, sz, expected_size, width, height, bytes_per_pixel))
        height -= missing // (bytes_per_pixel * width)

    return outfile.name, width, height


def can_display_images():
    import shutil
    ans = getattr(can_display_images, 'ans', None)
    if ans is None:
        ans = shutil.which('convert') is not None
        can_display_images.ans = ans
    return ans


class ImageManager:

    def __init__(self, handler):
        self.image_id_counter = count()
        self.handler = handler
        self.filesystem_ok = None
        self.image_data = {}
        self.failed_images = {}
        self.converted_images = {}
        self.sent_images = {}
        self.image_id_to_image_data = {}
        self.image_id_to_converted_data = {}
        self.transmission_status = {}
        self.placements_in_flight = defaultdict(deque)

    @property
    def next_image_id(self):
        return next(self.image_id_counter) + 2

    @property
    def screen_size(self):
        return self.handler.screen_size

    def __enter__(self):
        import tempfile
        self.tdir = tempfile.mkdtemp(prefix='kitten-images-')
        with tempfile.NamedTemporaryFile(dir=self.tdir, delete=False) as f:
            f.write(b'abcd')
        self.handler.cmd.gr_command(dict(a='q', s=1, v=1, i=1, t='f'), standard_b64encode(f.name.encode(fsenc)))

    def __exit__(self, *a):
        import shutil
        shutil.rmtree(self.tdir, ignore_errors=True)
        self.handler.cmd.clear_images_on_screen(delete_data=True)
        self.delete_all_sent_images()
        del self.handler

    def delete_all_sent_images(self):
        for img_id in self.transmission_status:
            self.handler.cmd.gr_command({'a': 'd', 'i': img_id})
        self.transmission_status.clear()

    def handle_response(self, apc):
        cdata, payload = apc[1:].partition(';')[::2]
        control = {}
        for x in cdata.split(','):
            k, v = x.partition('=')[::2]
            control[k] = v
        try:
            image_id = int(control.get('i', '0'))
        except Exception:
            image_id = 0
        if image_id == 1:
            self.filesystem_ok = payload == 'OK'
            return
        if not image_id:
            return
        if not self.transmission_status.get(image_id):
            self.transmission_status[image_id] = payload
        else:
            in_flight = self.placements_in_flight[image_id]
            if in_flight:
                pl = in_flight.popleft()
                if payload.startswith('ENOENT:'):
                    with suppress(Exception):
                        self.resend_image(image_id, pl)
                if not in_flight:
                    self.placements_in_flight.pop(image_id, None)

    def resend_image(self, image_id, pl):
        image_data = self.image_id_to_image_data[image_id]
        skey = self.image_id_to_converted_data[image_id]
        self.transmit_image(image_data, image_id, *skey)
        with cursor(self.handler.write):
            self.handler.cmd.set_cursor_position(pl['x'], pl['y'])
            self.handler.cmd.gr_command(pl['cmd'])

    def send_image(self, path, max_cols=None, max_rows=None, scale_up=False):
        path = os.path.abspath(path)
        if path in self.failed_images:
            raise self.failed_images[path]
        if path not in self.image_data:
            try:
                self.image_data[path] = identify(path)
            except Exception as e:
                self.failed_images[path] = e
                raise
        m = self.image_data[path]
        ss = self.screen_size
        if max_cols is None:
            max_cols = ss.cols
        if max_rows is None:
            max_rows = ss.rows
        available_width = max_cols * ss.cell_width
        available_height = max_rows * ss.cell_height
        key = path, available_width, available_height
        skey = self.converted_images.get(key)
        if skey is None:
            try:
                self.converted_images[key] = skey = self.convert_image(path, available_width, available_height, m, scale_up)
            except Exception as e:
                self.failed_images[path] = e
                raise
        final_width, final_height = skey[1:]
        if final_width == 0:
            return 0, 0, 0
        image_id = self.sent_images.get(skey)
        if image_id is None:
            image_id = self.next_image_id
            self.transmit_image(m, image_id, *skey)
            self.sent_images[skey] = image_id
        self.image_id_to_converted_data[image_id] = skey
        self.image_id_to_image_data[image_id] = m
        return image_id, skey[1], skey[2]

    def hide_image(self, image_id):
        self.handler.cmd.gr_command({'a': 'd', 'i': image_id})

    def show_image(self, image_id, x, y, src_rect=None):
        cmd = {'a': 'p', 'i': image_id}
        if src_rect is not None:
            cmd['x'], cmd['y'], cmd['w'], cmd['h'] = map(int, src_rect)
        self.placements_in_flight[image_id].append({'cmd': cmd, 'x': x, 'y': y})
        with cursor(self.handler.write):
            self.handler.cmd.set_cursor_position(x, y)
            self.handler.cmd.gr_command(cmd)

    def convert_image(self, path, available_width, available_height, image_data, scale_up=False):
        rgba_path, width, height = convert(path, image_data, available_width, available_height, scale_up, tdir=self.tdir)
        return rgba_path, width, height

    def transmit_image(self, image_data, image_id, rgba_path, width, height):
        self.transmission_status[image_id] = 0
        cmd = {'a': 't', 'f': image_data.transmit_fmt, 's': width, 'v': height, 'i': image_id}
        if self.filesystem_ok:
            cmd['t'] = 'f'
            self.handler.cmd.gr_command(
                cmd, standard_b64encode(rgba_path.encode(fsenc)))
        else:
            import zlib
            with open(rgba_path, 'rb') as f:
                data = f.read()
            cmd['S'] = len(data)
            data = zlib.compress(data)
            cmd['o'] = 'z'
            data = standard_b64encode(data)
            while data:
                chunk, data = data[:4096], data[4096:]
                m = 1 if data else 0
                cmd['m'] = m
                self.handler.cmd.gr_command(cmd, chunk)
                cmd.clear()
        return image_id
