#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import codecs
import fcntl
import mimetypes
import os
import re
import selectors
import signal
import struct
import subprocess
import sys
import termios
import tty
import zlib
from base64 import standard_b64encode
from collections import namedtuple
from gettext import gettext as _
from math import ceil, floor
from tempfile import NamedTemporaryFile
from time import monotonic

try:
    from kitty.constants import appname
except ImportError:
    appname = ''

try:
    fsenc = sys.getfilesystemencoding() or 'utf-8'
    codecs.lookup(fsenc)
except Exception:
    fsenc = 'utf-8'


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


def write_chunked(cmd, data):
    if cmd['f'] != 100:
        data = zlib.compress(data)
        cmd['o'] = 'z'
    data = standard_b64encode(data)
    while data:
        chunk, data = data[:4096], data[4096:]
        m = 1 if data else 0
        cmd['m'] = m
        write_gr_cmd(cmd, chunk)
        cmd.clear()


def show(outfile, width, height, fmt, transmit_mode='t'):
    cmd = {'a': 'T', 'f': fmt, 's': width, 'v': height}
    set_cursor(cmd, width, height)
    if detect_support.has_files:
        cmd['t'] = transmit_mode
        write_gr_cmd(cmd, standard_b64encode(os.path.abspath(outfile).encode(fsenc)))
    else:
        with open(outfile, 'rb') as f:
            data = f.read()
        if fmt == 100:
            cmd['S'] = len(data)
        write_chunked(cmd, data)


ImageData = namedtuple('ImageData', 'fmt width height mode')


def run_imagemagick(path, cmd, keep_stdout=True):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE if keep_stdout else subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit('ImageMagick is required to cat images')
    if p.returncode != 0:
        raise OpenFailed(path, p.stderr.decode('utf-8'))
    return p


def identify(path):
    p = run_imagemagick(path, ['identify', '-format', '%m %w %h %A', path])
    parts = tuple(filter(None, p.stdout.decode('utf-8').split()))
    mode = 'rgb' if parts[3].lower() == 'false' else 'rgba'
    return ImageData(parts[0].lower(), int(parts[1]), int(parts[2]), mode)


def convert(path, m, ss):
    width, height = m.width, m.height
    cmd = ['convert', '-background', 'none', path]
    if width > ss.width:
        width, height = fit_image(width, height, ss.width, height)
        cmd += ['-resize', '{}x{}'.format(width, height)]
    with NamedTemporaryFile(prefix='icat-', suffix='.' + m.mode, delete=False) as outfile:
        run_imagemagick(path, cmd + [outfile.name])
    return outfile.name, width, height


def process(path):
    m = identify(path)
    ss = screen_size()
    needs_scaling = m.width > ss.width
    if m.fmt == 'png' and not needs_scaling:
        outfile = path
        transmit_mode = 'f'
        fmt = 100
        width, height = m.width, m.height
    else:
        fmt = 24 if m.mode == 'rgb' else 32
        transmit_mode = 't'
        outfile, width, height = convert(path, m, ss)
    show(outfile, width, height, fmt, transmit_mode)
    print()  # ensure cursor is on a new line


def scan(d):
    for dirpath, dirnames, filenames in os.walk(d):
        for f in filenames:
            mt = mimetypes.guess_type(f)[0]
            if mt and mt.startswith('image/'):
                yield os.path.join(dirpath, f), mt


def detect_support(wait_for=10):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    oldfl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, oldfl | os.O_NONBLOCK)
    print('Checking for graphics ({}s max. wait)...'.format(wait_for), end='\r')
    sys.stdout.flush()
    tty.setraw(fd)
    try:
        received = b''
        start_time = monotonic()
        responses = {}

        def parse_responses():
            for m in re.finditer(b'\033_Gi=([1|2]);(.+?)\033\\\\', received):
                iid = m.group(1)
                if iid in (b'1', b'2'):
                    iid = int(iid.decode('ascii'))
                    if iid not in responses:
                        responses[iid] = m.group(2) == b'OK'

        def read():
            nonlocal received
            d = sys.stdin.buffer.read()
            if not d:  # EOF
                responses[1] = responses[2] = False
                return
            received += d
            parse_responses()

        with NamedTemporaryFile() as f:
            f.write(b'abcd'), f.flush()
            write_gr_cmd(dict(a='q', s=1, v=1, i=1), standard_b64encode(b'abcd'))
            write_gr_cmd(dict(a='q', s=1, v=1, i=2, t='f'), standard_b64encode(f.name.encode(fsenc)))
            sel = selectors.DefaultSelector()
            sel.register(sys.stdin, selectors.EVENT_READ, read)
            while monotonic() - start_time < wait_for and 1 not in responses and 2 not in responses:
                for key, mask in sel.select(0.1):
                    read()
    finally:
        sys.stdout.buffer.write(b'\033[J'), sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        fcntl.fcntl(fd, fcntl.F_SETFL, oldfl)
    detect_support.has_files = bool(responses.get(2))
    return responses.get(1, False)


def main(args=sys.argv):
    signal.signal(signal.SIGWINCH, lambda: screen_size(refresh=True))
    if not sys.stdout.isatty() or not sys.stdin.isatty():
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
    if not detect_support():
        raise SystemExit('This terminal emulator does not support the graphics protocol, use a terminal emulator such as kitty that does support it')
    errors = []
    for item in args.items:
        try:
            if os.path.isdir(item):
                for x in scan(item):
                    process(item)
            else:
                process(item)
        except OpenFailed as e:
            errors.append(e)
    if not errors:
        return
    for err in errors:
        print(err, file=sys.stderr)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
