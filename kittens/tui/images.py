#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import os
import shutil
import subprocess
import sys
import tempfile
from base64 import standard_b64encode

from kitty.utils import screen_size_function

from .operations import serialize_gr_command

try:
    fsenc = sys.getfilesystemencoding() or 'utf-8'
    codecs.lookup(fsenc)
except Exception:
    fsenc = 'utf-8'
screen_size = screen_size_function()


class ImageData:

    def __init__(self, fmt, width, height, mode):
        self.width, self.height, self.fmt, self.mode = width, height, fmt, mode
        self.transmit_fmt = str(24 if self.mode == 'rgb' else 32)


class OpenFailed(ValueError):

    def __init__(self, path, message):
        ValueError.__init__(
            self, 'Failed to open: {} with error: {}'.format(path, message)
        )
        self.path = path


def run_imagemagick(path, cmd, keep_stdout=True):
    p = subprocess.run(cmd, stdout=subprocess.PIPE if keep_stdout else subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise OpenFailed(path, p.stderr.decode('utf-8'))
    return p


def identify(path):
    p = run_imagemagick(path, ['identify', '-format', '%m %w %h %A', path])
    parts = tuple(filter(None, p.stdout.decode('utf-8').split()))
    mode = 'rgb' if parts[3].lower() == 'false' else 'rgba'
    return ImageData(parts[0].lower(), int(parts[1]), int(parts[2]), mode)


def can_display_images():
    ans = getattr(can_display_images, 'ans', None)
    if ans is None:
        ans = shutil.which('convert') is not None
        can_display_images.ans = ans
    return ans


class ImageManager:

    def __init__(self, handler):
        self.handler = handler
        self.sent_ids = set()
        self.filesystem_ok = None
        self.image_data = {}
        self.converted_images = {}
        self.sent_images = {}
        self.image_id_map = {}
        self.transmission_status = {}

    def __enter__(self):
        self.tdir = tempfile.mkdtemp(prefix='kitten-images-')
        with tempfile.NamedTemporaryFile(dir=self.tdir, delete=False) as f:
            f.write(b'abcd')
        self.handler.write(serialize_gr_command(dict(a='q', s=1, v=1, i=1, t='f'), standard_b64encode(f.name.encode(fsenc))))
        self.sent_ids.add(1)

    def __exit__(self, *a):
        shutil.rmtree(self.tdir, ignore_errors=True)
        self.handler.cmd.clear_images_on_screen(delete_data=True)
        self.delete_all_sent_images()
        del self.handler

    def delete_all_sent_images(self):
        for img_id in self.sent_ids:
            self.handler.write(serialize_gr_command({'a': 'D', 'i': str(img_id)}))
        self.sent_ids = set()

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

    def send_image(self, path, max_cols=None, max_rows=None, scale_up=False):
        path = os.path.abspath(path)
        if path not in self.image_data:
            self.image_data[path] = identify(path)
        m = self.image_data[path]
        ss = screen_size()
        if max_cols is None:
            max_cols = ss.cols
        if max_rows is None:
            max_rows = ss.rows
        available_width = max_cols * ss.cell_width
        available_height = max_rows * ss.cell_height
        key = path, available_width, available_height
        skey = self.converted_images.get(key)
        if skey is None:
            self.converted_images[key] = skey = self.convert_image(path, available_width, available_height, m, scale_up)
        final_width, final_height = skey[1:]
        if final_width == 0:
            return 0, 0, 0
        image_id = self.sent_images.get(skey)
        if image_id is None:
            image_id = self.sent_image[skey] = self.transmit_image(m, key, *skey)
        return image_id, skey[0], skey[1]

    def convert_image(self, path, available_width, available_height, image_data, scale_up=False):
        from kitty.icat import convert
        try:
            rgba_path, width, height = convert(path, image_data, available_width, available_height, scale_up, tdir=self.tdir, exc_class=ValueError)
        except ValueError:
            rgba_path = None
            width = height = 0
        return rgba_path, width, height

    def transmit_image(self, image_data, key, rgba_path, width, height):
        image_id = len(self.sent_ids) + 1
        self.image_id_map[key] = image_id
        self.sent_ids.add(image_id)
        self.transmission_status[image_id] = 0
        cmd = {'a': 't', 'f': image_data.transmit_fmt, 's': width, 'v': height, 'i': image_id}
        if self.filesystem_ok:
            cmd['t'] = 'f'
            self.handler.write(serialize_gr_command(
                cmd, standard_b64encode(rgba_path.encode(fsenc))))
        else:
            import zlib
            data = open(rgba_path, 'rb').read()
            cmd['S'] = len(data)
            data = zlib.compress(data)
            cmd['o'] = 'z'
            data = standard_b64encode(data)
            while data:
                chunk, data = data[:4096], data[4096:]
                m = 1 if data else 0
                cmd['m'] = m
                self.handler.write(serialize_gr_command(cmd, chunk))
                cmd.clear()
        return image_id
