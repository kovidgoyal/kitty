#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import fcntl
import mimetypes
import os
import struct
import subprocess
import sys
import termios
import zlib
from base64 import standard_b64encode
from collections import namedtuple
from gettext import gettext as _
from math import ceil, floor

from kitty.constants import appname

# from kitty.fast_data_types import shm_write, shm_unlink


class OpenFailed(ValueError):

    def __init__(self, path, message):
        ValueError.__init__(
            self, 'Failed to open: {} with error: {}'.format(path, message)
        )
        self.path = path


def option_parser():
    parser = argparse.ArgumentParser(
        prog=appname + ' icat',
        description=_('Display images in the terminal')
    )
    a = parser.add_argument
    a(
        'items',
        nargs=argparse.REMAINDER,
        help=_(
            'Image files or directories. Directories are scanned recursively.'
        )
    )
    return parser


Size = namedtuple('Size', 'cols rows width height')


def screen_size():
    if getattr(screen_size, 'ans', None) is None:
        s = struct.pack('HHHH', 0, 0, 0, 0)
        x = fcntl.ioctl(1, termios.TIOCGWINSZ, s)
        screen_size.ans = Size(*struct.unpack('HHHH', x))
    return screen_size.ans


def write_gr_cmd(cmd, payload):
    sys.stdout.write('\033_G{};{}\033\\'.format(cmd, payload).encode('ascii'))
    sys.stdout.flush()


def add_format_code(cmd, mode, width, height):
    cmd += ',f=' + {'RGB': '24', 'RGBA': '32', 'PNG': '100'}[mode]
    if mode != 'PNG':
        cmd += ',s={},v={}'.format(width, height)
    return cmd


def fit_image(width, height, pwidth, pheight):
    if height > pheight:
        corrf = pheight / float(height)
        width, height = floor(corrf * width), pheight
    if width > pwidth:
        corrf = pwidth / float(width)
        width, height = pwidth, floor(corrf * height)
    if height > pheight:
        corrf = pheight / float(height)
        width, height = floor(corrf * width), pheight

    return int(width), int(height)


def set_cursor(cmd, width, height):
    ss = screen_size()
    cw = int(ss.width / ss.cols)
    num_of_cells_needed = int(ceil(width / cw))
    if num_of_cells_needed > ss.cols:
        w, h = fit_image(width, height, ss.width, height)
        ch = int(ss.height / ss.rows)
        num_of_rows_needed = int(ceil(height / ch))
        y_off = height % ch
        cmd += 'c={},r={},Y={}'.format(ss.cols, num_of_rows_needed, y_off)
    else:
        x_off = width % cw
        cmd += 'c={},X={}'.format(num_of_cells_needed, x_off)
        extra_cells = (ss.cols - num_of_cells_needed) // 2
        if extra_cells:
            sys.stdout.write(b' ' * extra_cells)
    return cmd


def write_chunked(data, mode, width, height):
    data = standard_b64encode(zlib.compress(data))
    cmd = add_format_code('a=T,o=z', mode, width, height)
    cmd = set_cursor(cmd, width, height)
    i = -1
    while data:
        i += 1
        chunk, data = data[:4096], data[4096:]
        m = 1 if data else 0
        if i == 0:
            c = cmd + ',' + 'm={}'.format(m)
        else:
            c = 'm={}'.format(m)
        write_gr_cmd(c, chunk)


def show(data, mode, width, height):
    write_chunked(data, mode, width, height)


def convert_svg(path):
    try:
        return subprocess.check_output(['rsvg-convert', '-f', 'png', path])
    except OSError:
        raise SystemExit(
            'Could not find the program rsvg-convert, needed to display svg files'
        )


def process(path, mt):
    if mt == 'image/svg+xml':
        data = convert_svg(path)
        width = height = 0
        mode = 'PNG'
    else:
        try:
            from PIL import Image
        except ImportError:
            raise SystemExit(
                'You need to install the python-pillow package for image support'
            )
        try:
            im = Image.open(path)
        except Exception as e:
            raise OpenFailed(path, str(e))
        if im.mode not in ('RGB', 'RGBA'):
            im = im.convert('RGBA')
        data = im.tobytes()
        width, height = im.size
        mode = im.mode
    show(data, mode, width, height)
    print()  # ensure cursor is on a new line


def scan(d):
    for dirpath, dirnames, filenames in os.walk(d):
        for f in filenames:
            mt = mimetypes.guess_type(f)[0]
            if mt and mt.startswith('image/'):
                yield os.path.join(dirpath, f), mt


def main():
    if not sys.stdout.isatty():
        raise SystemExit(
            'Must be run in a terminal, stdout is currently not a terminal'
        )
    if screen_size().width == 0:
        raise SystemExit(
            'Terminal does not support reporting screen sizes via the TIOCGWINSZ ioctl'
        )
    args = option_parser().parse_args()
    if not args.items:
        raise SystemExit('You must specify at least one file to cat')
    errors = []
    for item in args.items:
        try:
            if os.path.isdir(item):
                for x, mt in scan(item):
                    process(item, mt)
            else:
                process(
                    item,
                    mimetypes.guess_type(item)[0] or 'application/octet-stream'
                )
        except OpenFailed as e:
            errors.append(e)
    if not errors:
        return
    for err in errors:
        print(err, file=sys.stderr)
    raise SystemExit(1)
