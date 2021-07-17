#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import contextlib
import os
import re
import signal
import socket
import sys
import zlib
from base64 import standard_b64encode
from math import ceil
from tempfile import NamedTemporaryFile
from typing import (
    Dict, Generator, List, NamedTuple, Optional, Pattern, Tuple, Union
)

from kitty.cli import parse_args
from kitty.cli_stub import IcatCLIOptions
from kitty.constants import appname
from kitty.guess_mime_type import guess_type
from kitty.types import run_once
from kitty.typing import GRT_f, GRT_t
from kitty.utils import (
    TTYIO, ScreenSize, ScreenSizeGetter, fit_image, screen_size_function
)

from ..tui.images import (
    ConvertFailed, Dispose, GraphicsCommand, NoImageMagick, OpenFailed,
    OutdatedImageMagick, RenderedImage, fsenc, identify,
    render_as_single_image, render_image
)
from ..tui.operations import clear_images_on_screen, raw_mode

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
Do not print out anything to STDOUT during operation.


--z-index -z
default=0
Z-index of the image. When negative, text will be displayed on top of the image. Use
a double minus for values under the threshold for drawing images under cell background
colors. For example, --1 evaluates as -1,073,741,825.


--loop -l
default=-1
type=int
Number of times to loop animations. Negative values loop forever. Zero means
only the first frame of the animation is displayed. Otherwise, the animation
is looped the specified number of times.


--hold
type=bool-set
Wait for a key press before exiting after displaying the images.
'''


screen_size: Optional[ScreenSizeGetter] = None
can_transfer_with_files = False


def get_screen_size_function() -> ScreenSizeGetter:
    global screen_size
    if screen_size is None:
        screen_size = screen_size_function()
    return screen_size


def get_screen_size() -> ScreenSize:
    screen_size = get_screen_size_function()
    return screen_size()


@run_once
def options_spec() -> str:
    return OPTIONS.format(appname='{}-icat'.format(appname))


def write_gr_cmd(cmd: GraphicsCommand, payload: Optional[bytes] = None) -> None:
    sys.stdout.buffer.write(cmd.serialize(payload or b''))
    sys.stdout.flush()


def calculate_in_cell_x_offset(width: int, cell_width: int, align: str) -> int:
    if align == 'left':
        return 0
    extra_pixels = width % cell_width
    if not extra_pixels:
        return 0
    if align == 'right':
        return cell_width - extra_pixels
    return (cell_width - extra_pixels) // 2


def set_cursor(cmd: GraphicsCommand, width: int, height: int, align: str) -> None:
    ss = get_screen_size()
    cw = int(ss.width / ss.cols)
    num_of_cells_needed = int(ceil(width / cw))
    if num_of_cells_needed > ss.cols:
        w, h = fit_image(width, height, ss.width, height)
        ch = int(ss.height / ss.rows)
        num_of_rows_needed = int(ceil(height / ch))
        cmd.c, cmd.r = ss.cols, num_of_rows_needed
    else:
        cmd.X = calculate_in_cell_x_offset(width, cw, align)
        extra_cells = 0
        if align == 'center':
            extra_cells = (ss.cols - num_of_cells_needed) // 2
        elif align == 'right':
            extra_cells = (ss.cols - num_of_cells_needed)
        if extra_cells:
            sys.stdout.buffer.write(b' ' * extra_cells)


def set_cursor_for_place(place: 'Place', cmd: GraphicsCommand, width: int, height: int, align: str) -> None:
    x = place.left + 1
    ss = get_screen_size()
    cw = int(ss.width / ss.cols)
    num_of_cells_needed = int(ceil(width / cw))
    cmd.X = calculate_in_cell_x_offset(width, cw, align)
    extra_cells = 0
    if align == 'center':
        extra_cells = (place.width - num_of_cells_needed) // 2
    elif align == 'right':
        extra_cells = place.width - num_of_cells_needed
    sys.stdout.buffer.write('\033[{};{}H'.format(place.top + 1, x + extra_cells).encode('ascii'))


def write_chunked(cmd: GraphicsCommand, data: bytes) -> None:
    cmd = cmd.clone()
    if cmd.f != 100:
        data = zlib.compress(data)
        cmd.o = 'z'
    data = standard_b64encode(data)
    ac = cmd.a
    quiet = cmd.q
    while data:
        chunk, data = data[:4096], data[4096:]
        cmd.m = 1 if data else 0
        write_gr_cmd(cmd, chunk)
        cmd.clear()
        cmd.a = ac
        cmd.q = quiet


def show(
    outfile: str,
    width: int, height: int, zindex: int,
    fmt: 'GRT_f',
    transmit_mode: 'GRT_t' = 't',
    align: str = 'center',
    place: Optional['Place'] = None,
    use_number: int = 0
) -> None:
    cmd = GraphicsCommand()
    cmd.a = 'T'
    cmd.f = fmt
    cmd.s = width
    cmd.v = height
    cmd.z = zindex
    if use_number:
        cmd.I = use_number  # noqa
        cmd.q = 2
    if place:
        set_cursor_for_place(place, cmd, width, height, align)
    else:
        set_cursor(cmd, width, height, align)
    if can_transfer_with_files:
        cmd.t = transmit_mode
        write_gr_cmd(cmd, standard_b64encode(os.path.abspath(outfile).encode(fsenc)))
    else:
        with open(outfile, 'rb') as f:
            data = f.read()
        if transmit_mode == 't':
            os.unlink(outfile)
        if fmt == 100:
            cmd.S = len(data)
        write_chunked(cmd, data)


def show_frames(frame_data: RenderedImage, use_number: int, loops: int) -> None:
    transmit_cmd = GraphicsCommand()
    transmit_cmd.a = 'f'
    transmit_cmd.I = use_number  # noqa
    transmit_cmd.q = 2
    if can_transfer_with_files:
        transmit_cmd.t = 't'
    transmit_cmd.f = 24 if frame_data.mode == 'rgb' else 32

    def control(frame_number: int = 0, loops: Optional[int] = None, gap: Optional[int] = 0, animation_control: int = 0) -> None:
        cmd = GraphicsCommand()
        cmd.a = 'a'
        cmd.I = use_number  # noqa
        cmd.r = frame_number
        if loops is not None:
            cmd.v = loops + 1
        if gap is not None:
            cmd.z = gap if gap > 0 else -1
        if animation_control:
            cmd.s = animation_control
        write_gr_cmd(cmd)

    anchor_frame = 0

    for frame in frame_data.frames:
        frame_number = frame.index + 1
        if frame.dispose < Dispose.previous:
            anchor_frame = frame_number
        if frame_number == 1:
            control(frame_number, gap=frame.gap, loops=None if loops < 1 else loops)
            continue
        if frame.dispose is Dispose.previous:
            if anchor_frame != frame_number:
                transmit_cmd.c = anchor_frame
        else:
            transmit_cmd.c = (frame_number - 1) if frame.needs_blend else 0
        transmit_cmd.s = frame.width
        transmit_cmd.v = frame.height
        transmit_cmd.x = frame.canvas_x
        transmit_cmd.y = frame.canvas_y
        transmit_cmd.z = frame.gap if frame.gap > 0 else -1
        if can_transfer_with_files:
            write_gr_cmd(transmit_cmd, standard_b64encode(os.path.abspath(frame.path).encode(fsenc)))
        else:
            with open(frame.path, 'rb') as f:
                data = f.read()
            write_chunked(transmit_cmd, data)
        if frame_number == 2:
            control(animation_control=2)
    control(animation_control=3)


def parse_z_index(val: str) -> int:
    origin = 0
    if val.startswith('--'):
        val = val[1:]
        origin = -1073741824
    return origin + int(val)


class ParsedOpts:

    place: Optional['Place'] = None
    z_index: int = 0


def process(path: str, args: IcatCLIOptions, parsed_opts: ParsedOpts, is_tempfile: bool) -> bool:
    m = identify(path)
    ss = get_screen_size()
    available_width = parsed_opts.place.width * (ss.width // ss.cols) if parsed_opts.place else ss.width
    available_height = parsed_opts.place.height * (ss.height // ss.rows) if parsed_opts.place else 10 * m.height
    needs_scaling = m.width > available_width or m.height > available_height
    needs_scaling = needs_scaling or args.scale_up
    file_removed = False
    use_number = 0
    if m.fmt == 'png' and not needs_scaling:
        outfile = path
        transmit_mode: 'GRT_t' = 't' if is_tempfile else 'f'
        fmt: 'GRT_f' = 100
        width, height = m.width, m.height
        file_removed = transmit_mode == 't'
    else:
        fmt = 24 if m.mode == 'rgb' else 32
        transmit_mode = 't'
        if len(m) == 1 or args.loop == 0:
            outfile, width, height = render_as_single_image(path, m, available_width, available_height, args.scale_up)
        else:
            import struct
            use_number = max(1, struct.unpack('@I', os.urandom(4))[0])
            with NamedTemporaryFile() as f:
                prefix = f.name
            frame_data = render_image(path, prefix, m, available_width, available_height, args.scale_up)
            outfile, width, height = frame_data.frames[0].path, frame_data.width, frame_data.height
    show(
        outfile, width, height, parsed_opts.z_index, fmt, transmit_mode,
        align=args.align, place=parsed_opts.place, use_number=use_number
    )
    if use_number:
        show_frames(frame_data, use_number, args.loop)
        if not can_transfer_with_files:
            for fr in frame_data.frames:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(fr.path)
    if not args.place:
        print()  # ensure cursor is on a new line
    return file_removed


def scan(d: str) -> Generator[Tuple[str, str], None, None]:
    for dirpath, dirnames, filenames in os.walk(d):
        for f in filenames:
            mt = guess_type(f)
            if mt and mt.startswith('image/'):
                yield os.path.join(dirpath, f), mt


def detect_support(wait_for: float = 10, silent: bool = False) -> bool:
    global can_transfer_with_files
    if not silent:
        print('Checking for graphics ({}s max. wait)...'.format(wait_for), end='\r')
    sys.stdout.flush()
    try:
        received = b''
        responses: Dict[int, bool] = {}

        def parse_responses() -> None:
            for m in re.finditer(b'\033_Gi=([1|2]);(.+?)\033\\\\', received):
                iid = m.group(1)
                if iid in (b'1', b'2'):
                    iid_ = int(iid.decode('ascii'))
                    if iid_ not in responses:
                        responses[iid_] = m.group(2) == b'OK'

        def more_needed(data: bytes) -> bool:
            nonlocal received
            received += data
            parse_responses()
            return 1 not in responses or 2 not in responses

        with NamedTemporaryFile() as f:
            f.write(b'abcd'), f.flush()
            gc = GraphicsCommand()
            gc.a = 'q'
            gc.s = gc.v = gc.i = 1
            write_gr_cmd(gc, standard_b64encode(b'abcd'))
            gc.t = 'f'
            gc.i = 2
            write_gr_cmd(gc, standard_b64encode(f.name.encode(fsenc)))
            with TTYIO() as io:
                io.recv(more_needed, timeout=wait_for)
    finally:
        if not silent:
            sys.stdout.buffer.write(b'\033[J'), sys.stdout.flush()
    can_transfer_with_files = bool(responses.get(2))
    return responses.get(1, False)


class Place(NamedTuple):
    width: int
    height: int
    left: int
    top: int


def parse_place(raw: str) -> Optional[Place]:
    if raw:
        area, pos = raw.split('@', 1)
        w, h = map(int, area.split('x'))
        l, t = map(int, pos.split('x'))
        return Place(w, h, l, t)
    return None


help_text = (
        'A cat like utility to display images in the terminal.'
        ' You can specify multiple image files and/or directories.'
        ' Directories are scanned recursively for image files. If STDIN'
        ' is not a terminal, image data will be read from it as well.'
        ' You can also specify HTTP(S) or FTP URLs which will be'
        ' automatically downloaded and displayed.'
)
usage = 'image-file-or-url-or-directory ...'


@contextlib.contextmanager
def socket_timeout(seconds: int) -> Generator[None, None, None]:
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old)


def process_single_item(
    item: Union[bytes, str],
    args: IcatCLIOptions,
    parsed_opts: ParsedOpts,
    url_pat: Optional[Pattern] = None,
    maybe_dir: bool = True
) -> None:
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
                    with socket_timeout(30):
                        urlretrieve(item, filename=tf.name)
                except Exception as e:
                    raise SystemExit('Failed to download image at URL: {} with error: {}'.format(item, e))
                item = tf.name
            is_tempfile = True
            file_removed = process(item, args, parsed_opts, is_tempfile)
        elif item.lower().startswith('file://'):
            from urllib.parse import urlparse
            from urllib.request import url2pathname
            pitem = urlparse(item)
            if os.sep == '\\':
                item = pitem.netloc + pitem.path
            else:
                item = pitem.path
            item = url2pathname(item)
            file_removed = process(item, args, parsed_opts, is_tempfile)
        else:
            if maybe_dir and os.path.isdir(item):
                for (x, mt) in scan(item):
                    process_single_item(x, args, parsed_opts, url_pat=None, maybe_dir=False)
            else:
                file_removed = process(item, args, parsed_opts, is_tempfile)
    finally:
        if is_tempfile and not file_removed:
            os.remove(item)


def main(args: List[str] = sys.argv) -> None:
    global can_transfer_with_files
    cli_opts, items_ = parse_args(args[1:], options_spec, usage, help_text, '{} +kitten icat'.format(appname), result_class=IcatCLIOptions)
    items: List[Union[str, bytes]] = list(items_)

    if cli_opts.print_window_size:
        screen_size_function.cache_clear()
        with open(os.ctermid()) as tty:
            ss = screen_size_function(tty)()
        print('{}x{}'.format(ss.width, ss.height), end='')
        raise SystemExit(0)

    if not sys.stdout.isatty():
        sys.stdout = open(os.ctermid(), 'w')
    stdin_data = None
    if cli_opts.stdin == 'yes' or (not sys.stdin.isatty() and cli_opts.stdin == 'detect'):
        stdin_data = sys.stdin.buffer.read()
        if stdin_data:
            items.insert(0, stdin_data)
        sys.stdin.close()
        sys.stdin = open(os.ctermid(), 'r')

    screen_size = get_screen_size_function()
    signal.signal(signal.SIGWINCH, lambda signum, frame: setattr(screen_size, 'changed', True))
    if screen_size().width == 0:
        if cli_opts.detect_support:
            raise SystemExit(1)
        raise SystemExit(
            'Terminal does not support reporting screen sizes via the TIOCGWINSZ ioctl'
        )
    parsed_opts = ParsedOpts()
    if cli_opts.place:
        try:
            parsed_opts.place = parse_place(cli_opts.place)
        except Exception:
            raise SystemExit('Not a valid place specification: {}'.format(cli_opts.place))

    try:
        parsed_opts.z_index = parse_z_index(cli_opts.z_index)
    except Exception:
        raise SystemExit('Not a valid z-index specification: {}'.format(cli_opts.z_index))

    if cli_opts.detect_support:
        if not detect_support(wait_for=cli_opts.detection_timeout, silent=True):
            raise SystemExit(1)
        print('file' if can_transfer_with_files else 'stream', end='', file=sys.stderr)
        return
    if cli_opts.transfer_mode == 'detect':
        if not detect_support(wait_for=cli_opts.detection_timeout, silent=cli_opts.silent):
            raise SystemExit('This terminal emulator does not support the graphics protocol, use a terminal emulator such as kitty that does support it')
    else:
        can_transfer_with_files = cli_opts.transfer_mode == 'file'
    errors = []
    if cli_opts.clear:
        sys.stdout.write(clear_images_on_screen(delete_data=True))
        if not items:
            return
    if not items:
        raise SystemExit('You must specify at least one file to cat')
    if parsed_opts.place:
        if len(items) > 1 or (isinstance(items[0], str) and os.path.isdir(items[0])):
            raise SystemExit(f'The --place option can only be used with a single image, not {items}')
        sys.stdout.buffer.write(b'\0337')  # save cursor
    url_pat = re.compile(r'(?:https?|ftp)://', flags=re.I)
    for item in items:
        try:
            process_single_item(item, cli_opts, parsed_opts, url_pat)
        except NoImageMagick as e:
            raise SystemExit(str(e))
        except OutdatedImageMagick as e:
            print(e.detailed_error, file=sys.stderr)
            raise SystemExit(str(e))
        except ConvertFailed as e:
            raise SystemExit(str(e))
        except OpenFailed as e:
            errors.append(e)
    if parsed_opts.place:
        sys.stdout.buffer.write(b'\0338')  # restore cursor
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
    if cli_opts.hold:
        with open(os.ctermid()) as tty:
            with raw_mode(tty.fileno()):
                tty.buffer.read(1)
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = options_spec
    cd['help_text'] = help_text
