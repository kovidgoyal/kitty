#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import fcntl
import mimetypes
import os
import re
import signal
import struct
import subprocess
import sys
import termios
import zlib
from base64 import standard_b64encode
from collections import namedtuple
from math import ceil, floor
from tempfile import NamedTemporaryFile

from kitty.constants import appname
from kitty.cli import parse_args
from kitty.utils import read_with_timeout

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


OPTIONS = '''\
--align
type=choices
choices=center,left,right
default=center
Horizontal alignment for the displayed image.


--place
Choose where on the screen to display the image. The image will
be scaled to fit into the specified rectangle. The syntax for
specifying rectanges is <|_ width|>x<|_ height|>@<|_ left|>x<|_ top|>. All measurements
are in cells (i.e. cursor positions) with the origin |_ (0, 0)| at
the top-left corner of the screen.


--clear
type=bool-set
Remove all images currently displayed on the screen.


--transfer-mode
type=choices
choices=detect,file,stream
default=detect
Which mechanism to use to transfer images to the terminal. The default is to
auto-detect. |_ file| means to use a temporary file and |_ stream| means to
send the data via terminal escape codes. Note that if you use the |_ file|
transfer mode and you are connecting over a remote session then image display
will not work.


--detect-support
type=bool-set
Detect support for image display in the terminal. If not supported, will exit
with exit code 1, otherwise will exit with code 0 and print the supported
transfer mode to stderr, which can be used with the |_ --transfer-mode| option.


--detection-timeout
type=float
default=10
The amount of time (in seconds) to wait for a response form the terminal, when
detecting image display support.
'''


def options_spec():
    if not hasattr(options_spec, 'ans'):
        options_spec.ans = OPTIONS.format(
            appname='{}-icat'.format(appname),
        )
    return options_spec.ans


Size = namedtuple('Size', 'rows cols width height')


def screen_size(refresh=False):
    if refresh or getattr(screen_size, 'ans', None) is None:
        s = struct.pack('HHHH', 0, 0, 0, 0)
        x = fcntl.ioctl(1, termios.TIOCGWINSZ, s)
        screen_size.ans = Size(*struct.unpack('HHHH', x))
    return screen_size.ans


def write_gr_cmd(cmd, payload=None):
    cmd = ','.join('{}={}'.format(k, v) for k, v in cmd.items())
    w = sys.stdout.buffer.write
    w(b'\033_G'), w(cmd.encode('ascii'))
    if payload:
        w(b';')
        w(payload)
    w(b'\033\\')
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


def set_cursor(cmd, width, height, align):
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
        extra_cells = 0
        if align == 'center':
            extra_cells = (ss.cols - num_of_cells_needed) // 2
        elif align == 'right':
            extra_cells = (ss.cols - num_of_cells_needed)
        if extra_cells:
            sys.stdout.buffer.write(b' ' * extra_cells)


def set_cursor_for_place(place, cmd, width, height, align):
    x = place.left + 1
    ss = screen_size()
    cw = int(ss.width / ss.cols)
    num_of_cells_needed = int(ceil(width / cw))
    x_off = width % cw
    cmd['X'] = x_off
    extra_cells = 0
    if align == 'center':
        extra_cells = (place.width - num_of_cells_needed) // 2
    elif align == 'right':
        extra_cells = place.width - num_of_cells_needed
    sys.stdout.buffer.write('\033[{};{}H'.format(place.top + 1, x + extra_cells).encode('ascii'))


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


def show(outfile, width, height, fmt, transmit_mode='t', align='center', place=None):
    cmd = {'a': 'T', 'f': fmt, 's': width, 'v': height}
    if place:
        set_cursor_for_place(place, cmd, width, height, align)
    else:
        set_cursor(cmd, width, height, align)
    if detect_support.has_files:
        cmd['t'] = transmit_mode
        write_gr_cmd(cmd, standard_b64encode(os.path.abspath(outfile).encode(fsenc)))
    else:
        with open(outfile, 'rb') as f:
            data = f.read()
        if transmit_mode == 't':
            os.unlink(outfile)
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


def convert(path, m, available_width, available_height):
    width, height = m.width, m.height
    cmd = ['convert', '-background', 'none', path]
    if width > available_width or height > available_height:
        width, height = fit_image(width, height, available_width, available_height)
        cmd += ['-resize', '{}x{}'.format(width, height)]
    with NamedTemporaryFile(prefix='icat-', suffix='.' + m.mode, delete=False) as outfile:
        run_imagemagick(path, cmd + [outfile.name])
    return outfile.name, width, height


def process(path, args):
    m = identify(path)
    ss = screen_size()
    available_width = args.place.width * (ss.width / ss.cols) if args.place else ss.width
    available_height = args.place.height * (ss.height / ss.rows) if args.place else 10 * m.height
    needs_scaling = m.width > available_width or m.height > available_height
    if m.fmt == 'png' and not needs_scaling:
        outfile = path
        transmit_mode = 'f'
        fmt = 100
        width, height = m.width, m.height
    else:
        fmt = 24 if m.mode == 'rgb' else 32
        transmit_mode = 't'
        outfile, width, height = convert(path, m, available_width, available_height)
    show(outfile, width, height, fmt, transmit_mode, align=args.align, place=args.place)
    if not args.place:
        print()  # ensure cursor is on a new line


def scan(d):
    for dirpath, dirnames, filenames in os.walk(d):
        for f in filenames:
            mt = mimetypes.guess_type(f)[0]
            if mt and mt.startswith('image/'):
                yield os.path.join(dirpath, f), mt


def detect_support(wait_for=10, silent=False):
    if not silent:
        print('Checking for graphics ({}s max. wait)...'.format(wait_for), end='\r')
    sys.stdout.flush()
    try:
        received = b''
        responses = {}

        def parse_responses():
            for m in re.finditer(b'\033_Gi=([1|2]);(.+?)\033\\\\', received):
                iid = m.group(1)
                if iid in (b'1', b'2'):
                    iid = int(iid.decode('ascii'))
                    if iid not in responses:
                        responses[iid] = m.group(2) == b'OK'

        def more_needed(data):
            nonlocal received
            received += data
            parse_responses()
            return 1 not in responses or 2 not in responses

        with NamedTemporaryFile() as f:
            f.write(b'abcd'), f.flush()
            write_gr_cmd(dict(a='q', s=1, v=1, i=1), standard_b64encode(b'abcd'))
            write_gr_cmd(dict(a='q', s=1, v=1, i=2, t='f'), standard_b64encode(f.name.encode(fsenc)))
            read_with_timeout(more_needed, timeout=wait_for)
    finally:
        if not silent:
            sys.stdout.buffer.write(b'\033[J'), sys.stdout.flush()
    detect_support.has_files = bool(responses.get(2))
    return responses.get(1, False)


def parse_place(raw):
    if raw:
        area, pos = raw.split('@', 1)
        w, h = map(int, area.split('x'))
        l, t = map(int, pos.split('x'))
        return namedtuple('Place', 'width height left top')(w, h, l, t)


def main(args=sys.argv):
    msg = (
        'A cat like utility to display images in the terminal.'
        ' You can specify multiple image files and/or directories.'
        ' Directories are scanned recursively for image files.')
    args, items = parse_args(args[1:], options_spec, 'image-file ...', msg, '{} icat'.format(appname))

    signal.signal(signal.SIGWINCH, lambda: screen_size(refresh=True))
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        raise SystemExit(
            'Must be run in a terminal, stdout and/or stdin is currently not a terminal'
        )
    if screen_size().width == 0:
        if args.detect_support:
            raise SystemExit(1)
        raise SystemExit(
            'Terminal does not support reporting screen sizes via the TIOCGWINSZ ioctl'
        )
    try:
        args.place = parse_place(args.place)
    except Exception:
        raise SystemExit('Not a valid place specification: {}'.format(args.place))

    if args.detect_support:
        if not detect_support(wait_for=args.detection_timeout, silent=True):
            raise SystemExit(1)
        print('file' if detect_support.has_files else 'stream', end='', file=sys.stderr)
        return
    if args.transfer_mode == 'detect':
        if not detect_support(wait_for=args.detection_timeout):
            raise SystemExit('This terminal emulator does not support the graphics protocol, use a terminal emulator such as kitty that does support it')
    else:
        detect_support.has_files = args.transfer_mode == 'file'
    errors = []
    if args.clear:
        write_gr_cmd({'a': 'd'})
        if not items:
            return
    if not items:
        raise SystemExit('You must specify at least one file to cat')
    if args.place:
        if len(items) > 1 or os.path.isdir(items[0]):
            raise SystemExit('The --place option can only be used with a single image')
        sys.stdout.buffer.write(b'\0337')  # save cursor
    for item in items:
        try:
            if os.path.isdir(item):
                for x in scan(item):
                    process(item, args)
            else:
                process(item, args)
        except OpenFailed as e:
            errors.append(e)
    if args.place:
        sys.stdout.buffer.write(b'\0338')  # restore cursor
    if not errors:
        return
    for err in errors:
        print(err, file=sys.stderr)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
