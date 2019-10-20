#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import mimetypes
import os
import re
import signal
import sys
import zlib
from base64 import standard_b64encode
from collections import namedtuple
from math import ceil
from tempfile import NamedTemporaryFile

from kitty.cli import parse_args
from kitty.constants import appname
from kitty.utils import TTYIO, fit_image, screen_size_function

from ..tui.images import (
    ConvertFailed, NoImageMagick, OpenFailed, convert, fsenc, identify
)
from ..tui.operations import clear_images_on_screen, serialize_gr_command

OPTIONS = '''\
--align
type=choices
choices=center,left,right
default=center
Horizontal alignment for the displayed image.


--place
Choose where on the screen to display the image. The image will
be scaled to fit into the specified rectangle. The syntax for
specifying rectangles is <:italic:`width`>x<:italic:`height`>@<:italic:`left`>x<:italic:`top`>.
All measurements are in cells (i.e. cursor positions) with the
origin :italic:`(0, 0)` at the top-left corner of the screen.


--scale-up
type=bool-set
When used in combination with :option:`--place` it will cause images that
are smaller than the specified area to be scaled up to use as much
of the specified area as possible.


--clear
type=bool-set
Remove all images currently displayed on the screen.


--transfer-mode
type=choices
choices=detect,file,stream
default=detect
Which mechanism to use to transfer images to the terminal. The default is to
auto-detect. :italic:`file` means to use a temporary file and :italic:`stream` means to
send the data via terminal escape codes. Note that if you use the :italic:`file`
transfer mode and you are connecting over a remote session then image display
will not work.


--detect-support
type=bool-set
Detect support for image display in the terminal. If not supported, will exit
with exit code 1, otherwise will exit with code 0 and print the supported
transfer mode to stderr, which can be used with the :option:`--transfer-mode` option.


--detection-timeout
type=float
default=10
The amount of time (in seconds) to wait for a response form the terminal, when
detecting image display support.


--print-window-size
type=bool-set
Print out the window size as :italic:`widthxheight` (in pixels) and quit. This is a
convenience method to query the window size if using kitty icat from a
scripting language that cannot make termios calls.


--stdin
type=choices
choices=detect,yes,no
default=detect
Read image data from stdin. The default is to do it automatically, when STDIN is not a terminal,
but you can turn it off or on explicitly, if needed.


--silent
type=bool-set
Do not print out anything to stdout during operation.
'''


screen_size = None


def get_screen_size_function():
    global screen_size
    if screen_size is None:
        screen_size = screen_size_function()
    return screen_size


def get_screen_size():
    screen_size = get_screen_size_function()
    return screen_size()


def options_spec():
    if not hasattr(options_spec, 'ans'):
        options_spec.ans = OPTIONS.format(
            appname='{}-icat'.format(appname),
        )
    return options_spec.ans


def write_gr_cmd(cmd, payload=None):
    sys.stdout.buffer.write(serialize_gr_command(cmd, payload))
    sys.stdout.flush()


def calculate_in_cell_x_offset(width, cell_width, align):
    if align == 'left':
        return 0
    extra_pixels = width % cell_width
    if not extra_pixels:
        return 0
    if align == 'right':
        return cell_width - extra_pixels
    return (cell_width - extra_pixels) // 2


def set_cursor(cmd, width, height, align):
    ss = get_screen_size()
    cw = int(ss.width / ss.cols)
    num_of_cells_needed = int(ceil(width / cw))
    if num_of_cells_needed > ss.cols:
        w, h = fit_image(width, height, ss.width, height)
        ch = int(ss.height / ss.rows)
        num_of_rows_needed = int(ceil(height / ch))
        cmd['c'], cmd['r'] = ss.cols, num_of_rows_needed
    else:
        cmd['X'] = calculate_in_cell_x_offset(width, cw, align)
        extra_cells = 0
        if align == 'center':
            extra_cells = (ss.cols - num_of_cells_needed) // 2
        elif align == 'right':
            extra_cells = (ss.cols - num_of_cells_needed)
        if extra_cells:
            sys.stdout.buffer.write(b' ' * extra_cells)


def set_cursor_for_place(place, cmd, width, height, align):
    x = place.left + 1
    ss = get_screen_size()
    cw = int(ss.width / ss.cols)
    num_of_cells_needed = int(ceil(width / cw))
    cmd['X'] = calculate_in_cell_x_offset(width, cw, align)
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


def process(path, args, is_tempfile):
    m = identify(path)
    ss = get_screen_size()
    available_width = args.place.width * (ss.width / ss.cols) if args.place else ss.width
    available_height = args.place.height * (ss.height / ss.rows) if args.place else 10 * m.height
    needs_scaling = m.width > available_width or m.height > available_height
    needs_scaling = needs_scaling or args.scale_up
    file_removed = False
    if m.fmt == 'png' and not needs_scaling:
        outfile = path
        transmit_mode = 't' if is_tempfile else 'f'
        fmt = 100
        width, height = m.width, m.height
        file_removed = transmit_mode == 't'
    else:
        fmt = 24 if m.mode == 'rgb' else 32
        transmit_mode = 't'
        outfile, width, height = convert(path, m, available_width, available_height, args.scale_up)
    show(outfile, width, height, fmt, transmit_mode, align=args.align, place=args.place)
    if not args.place:
        print()  # ensure cursor is on a new line
    return file_removed


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
            with TTYIO() as io:
                io.recv(more_needed, timeout=float(wait_for))
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


help_text = (
        'A cat like utility to display images in the terminal.'
        ' You can specify multiple image files and/or directories.'
        ' Directories are scanned recursively for image files. If STDIN'
        ' is not a terminal, image data will be read from it as well.'
        ' You can also specify HTTP(S) or FTP URLs which will be'
        ' automatically downloaded and displayed.'
)
usage = 'image-file-or-url-or-directory ...'


def process_single_item(item, args, url_pat=None, maybe_dir=True):
    is_tempfile = False
    file_removed = False
    try:
        if isinstance(item, bytes):
            tf = NamedTemporaryFile(prefix='stdin-image-data-', delete=False)
            tf.write(item), tf.close()
            item = tf.name
            is_tempfile = True
        if url_pat is not None and url_pat.match(item) is not None:
            from urllib.request import urlretrieve
            with NamedTemporaryFile(prefix='url-image-data-', delete=False) as tf:
                try:
                    urlretrieve(item, filename=tf.name)
                except Exception as e:
                    raise SystemExit('Failed to download image at URL: {} with error: {}'.format(item, e))
                item = tf.name
            is_tempfile = True
            file_removed = process(item, args, is_tempfile)
        elif item.lower().startswith('file://'):
            from urllib.parse import urlparse
            from urllib.request import url2pathname
            item = urlparse(item)
            if os.sep == '\\':
                item = item.netloc + item.path
            else:
                item = item.path
            item = url2pathname(item)
            file_removed = process(item, args, is_tempfile)
        else:
            if maybe_dir and os.path.isdir(item):
                for (x, mt) in scan(item):
                    process_single_item(x, args, url_pat=None, maybe_dir=False)
            else:
                file_removed = process(item, args, is_tempfile)
    finally:
        if is_tempfile and not file_removed:
            os.remove(item)


def main(args=sys.argv):
    args, items = parse_args(args[1:], options_spec, usage, help_text, '{} +kitten icat'.format(appname))

    if args.print_window_size:
        screen_size_function.ans = None
        with open(os.ctermid()) as tty:
            ss = screen_size_function(tty)()
        print('{}x{}'.format(ss.width, ss.height), end='')
        raise SystemExit(0)

    if not sys.stdout.isatty():
        sys.stdout = open(os.ctermid(), 'w')
    stdin_data = None
    if args.stdin == 'yes' or (not sys.stdin.isatty() and args.stdin == 'detect'):
        stdin_data = sys.stdin.buffer.read()
        if stdin_data:
            items.insert(0, stdin_data)
        sys.stdin.close()
        sys.stdin = open(os.ctermid(), 'r')

    screen_size = get_screen_size_function()
    signal.signal(signal.SIGWINCH, lambda signum, frame: setattr(screen_size, 'changed', True))
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
        if not detect_support(wait_for=args.detection_timeout, silent=args.silent):
            raise SystemExit('This terminal emulator does not support the graphics protocol, use a terminal emulator such as kitty that does support it')
    else:
        detect_support.has_files = args.transfer_mode == 'file'
    errors = []
    if args.clear:
        sys.stdout.buffer.write(clear_images_on_screen(delete_data=True))
        if not items:
            return
    if not items:
        raise SystemExit('You must specify at least one file to cat')
    if args.place:
        if len(items) > 1 or (isinstance(items[0], str) and os.path.isdir(items[0])):
            raise SystemExit(f'The --place option can only be used with a single image, not {items}')
        sys.stdout.buffer.write(b'\0337')  # save cursor
    url_pat = re.compile(r'(?:https?|ftp)://', flags=re.I)
    for item in items:
        try:
            process_single_item(item, args, url_pat)
        except NoImageMagick as e:
            raise SystemExit(str(e))
        except ConvertFailed as e:
            raise SystemExit(str(e))
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
elif __name__ == '__doc__':
    sys.cli_docs['usage'] = usage
    sys.cli_docs['options'] = options_spec
    sys.cli_docs['help_text'] = help_text
