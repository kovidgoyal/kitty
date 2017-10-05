#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import fcntl
import mimetypes
import os
import signal
import struct
import subprocess
import sys
import termios
import zlib
from base64 import standard_b64encode
from collections import namedtuple
from gettext import gettext as _
from math import ceil, floor

try:
    from kitty.constants import appname
except ImportError:
    appname = ''


class OpenFailed(ValueError):

    def __init__(self, path, message):
        ValueError.__init__(
            self, 'Failed to open: {} with error: {}'.format(path, message)
        )
        self.path = path


def option_parser():
    parser = argparse.ArgumentParser(
        prog=appname + '-icat' if appname else 'icat',
        description=_('Display images in the terminal')
    )
    a = parser.add_argument
    a(
        'items',
        nargs='+',
        help=_(
            'Image files or directories. Directories are scanned recursively.'
        )
    )
    return parser


Size = namedtuple('Size', 'rows cols width height')


def screen_size(refresh=False):
    if refresh or getattr(screen_size, 'ans', None) is None:
        s = struct.pack('HHHH', 0, 0, 0, 0)
        x = fcntl.ioctl(1, termios.TIOCGWINSZ, s)
        screen_size.ans = Size(*struct.unpack('HHHH', x))
    return screen_size.ans


def write_gr_cmd(cmd, payload):
    cmd = ','.join('{}={}'.format(k, v) for k, v in cmd.items())
    w = sys.stdout.buffer.write
    w(b'\033_G'), w(cmd.encode('ascii')), w(b';'), w(payload), w(b'\033\\')
    sys.stdout.flush()


def add_format_code(cmd, mode, width, height):
    cmd['f'] = {'RGB': '24', 'RGBA': '32', 'PNG': '100'}[mode]
    if mode != 'PNG':
        cmd['s'], cmd['v'] = width, height


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
        cmd['c'], cmd['r'] = ss.cols, num_of_rows_needed
        cmd['Y'] = y_off
    else:
        x_off = width % cw
        cmd['X'] = x_off
        extra_cells = (ss.cols - num_of_cells_needed) // 2
        if extra_cells:
            sys.stdout.buffer.write(b' ' * extra_cells)


def write_chunked(data, mode, width, height):
    cmd = {'a': 'T'}
    if mode == 'PNG':
        cmd['S'] = len(data)
    else:
        data = zlib.compress(data)
        cmd['o'] = 'z'
    data = standard_b64encode(data)
    add_format_code(cmd, mode, width, height)
    set_cursor(cmd, width, height)
    while data:
        chunk, data = data[:4096], data[4096:]
        m = 1 if data else 0
        cmd['m'] = m
        write_gr_cmd(cmd, chunk)
        cmd.clear()


def show(data, mode, width, height):
    write_chunked(data, mode, width, height)


def convert_svg(path):
    try:
        with open(os.devnull, 'wb') as null:
            return subprocess.check_output(['rsvg-convert', '-f', 'png', path],
                                           stderr=null)
    except OSError:
        raise SystemExit(
            'Could not find the program rsvg-convert, needed to display svg files'
        )
    except subprocess.CalledProcessError:
        raise OpenFailed(path, 'rsvg-convert could not process the image')


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


def main(args=sys.argv):
    signal.signal(signal.SIGWINCH, lambda: screen_size(refresh=True))
    if not sys.stdout.isatty():
        raise SystemExit(
            'Must be run in a terminal, stdout is currently not a terminal'
        )
    if screen_size().width == 0:
        raise SystemExit(
            'Terminal does not support reporting screen sizes via the TIOCGWINSZ ioctl'
        )
    args = option_parser().parse_args(args[1:])
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


if __name__ == '__main__':
    main()
