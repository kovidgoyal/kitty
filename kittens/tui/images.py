#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import os
import sys
from base64 import standard_b64encode
from collections import defaultdict, deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from enum import IntEnum
from itertools import count
from typing import Any, ClassVar, DefaultDict, Deque, Generic, Optional, TypeVar, Union, cast

from kitty.conf.utils import positive_float, positive_int
from kitty.fast_data_types import create_canvas
from kitty.typing_compat import CompletedProcess, GRT_f, GRT_o, HandlerType
from kitty.utils import ScreenSize, fit_image, which

from .operations import cursor

try:
    fsenc = sys.getfilesystemencoding() or 'utf-8'
    codecs.lookup(fsenc)
except Exception:
    fsenc = 'utf-8'


class Dispose(IntEnum):
    undefined = 0
    none = 1
    background = 2
    previous = 3


class Frame:
    gap: int  # milliseconds
    canvas_width: int
    canvas_height: int
    width: int
    height: int
    index: int
    xdpi: float
    ydpi: float
    canvas_x: int
    canvas_y: int
    mode: str
    needs_blend: bool
    dimensions_swapped: bool
    dispose: Dispose
    path: str = ''

    def __init__(self, identify_data: Union['Frame', dict[str, str]]):
        if isinstance(identify_data, Frame):
            for k in Frame.__annotations__:
                setattr(self, k, getattr(identify_data, k))
        else:
            self.gap = max(0, int(identify_data['gap']) * 10)
            sz, pos = identify_data['canvas'].split('+', 1)
            self.canvas_width, self.canvas_height = map(positive_int, sz.split('x', 1))
            self.canvas_x, self.canvas_y = map(int, pos.split('+', 1))
            self.width, self.height = map(positive_int, identify_data['size'].split('x', 1))
            self.xdpi, self.ydpi = map(positive_float, identify_data['dpi'].split('x', 1))
            self.index = positive_int(identify_data['index'])
            q = identify_data['transparency'].lower()
            self.mode = 'rgba' if q in ('blend', 'true') else 'rgb'
            self.needs_blend = q == 'blend'
            self.dispose = getattr(Dispose, identify_data['dispose'].lower())
            self.dimensions_swapped = identify_data.get('orientation') in ('5', '6', '7', '8')
            if self.dimensions_swapped:
                self.canvas_width, self.canvas_height = self.canvas_height, self.canvas_width
                self.width, self.height = self.height, self.width

    def __repr__(self) -> str:
        canvas = f'{self.canvas_width}x{self.canvas_height}:{self.canvas_x}+{self.canvas_y}'
        geom = f'{self.width}x{self.height}'
        return f'Frame(index={self.index}, gap={self.gap}, geom={geom}, canvas={canvas}, dispose={self.dispose.name})'


class ImageData:

    def __init__(self, fmt: str, width: int, height: int, mode: str, frames: list[Frame]):
        self.width, self.height, self.fmt, self.mode = width, height, fmt, mode
        self.transmit_fmt: GRT_f = (24 if self.mode == 'rgb' else 32)
        self.frames = frames

    def __len__(self) -> int:
        return len(self.frames)

    def __iter__(self) -> Iterator[Frame]:
        yield from self.frames

    def __repr__(self) -> str:
        frames = '\n  '.join(map(repr, self.frames))
        return f'Image(fmt={self.fmt}, mode={self.mode},\n  {frames}\n)'


class OpenFailed(ValueError):

    def __init__(self, path: str, message: str):
        ValueError.__init__(
            self, f'Failed to open image: {path} with error: {message}'
        )
        self.path = path


class ConvertFailed(ValueError):

    def __init__(self, path: str, message: str):
        ValueError.__init__(
            self, f'Failed to convert image: {path} with error: {message}'
        )
        self.path = path


class NoImageMagick(Exception):
    pass


class OutdatedImageMagick(ValueError):

    def __init__(self, detailed_error: str):
        super().__init__('ImageMagick on this system is too old ImageMagick 7+ required which was first released in 2016')
        self.detailed_error = detailed_error


last_imagemagick_cmd: Sequence[str] = ()


def run_imagemagick(path: str, cmd: Sequence[str], keep_stdout: bool = True) -> 'CompletedProcess[bytes]':
    global last_imagemagick_cmd
    import subprocess
    last_imagemagick_cmd = cmd
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE if keep_stdout else subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise NoImageMagick('ImageMagick is required to process images')
    if p.returncode != 0:
        raise OpenFailed(path, p.stderr.decode('utf-8'))
    return p


def identify(path: str) -> ImageData:
    import json
    q = (
        '{"fmt":"%m","canvas":"%g","transparency":"%A","gap":"%T","index":"%p","size":"%wx%h",'
        '"dpi":"%xx%y","dispose":"%D","orientation":"%[EXIF:Orientation]"},'
    )
    exe = which('magick')
    if exe:
        cmd = [exe, 'identify']
    else:
        cmd = ['identify']
    p = run_imagemagick(path, cmd + ['-format', q, '--', path])
    raw = p.stdout.rstrip(b',')
    data = json.loads(b'[' + raw + b']')
    first = data[0]
    frames = list(map(Frame, data))
    image_fmt = first['fmt'].lower()
    if image_fmt == 'gif' and not any(f.gap > 0 for f in frames):
        # Some broken GIF images have all zero gaps, browsers with their usual
        # idiot ideas render these with a default 100ms gap https://bugzilla.mozilla.org/show_bug.cgi?id=125137
        # Browsers actually force a 100ms gap at any zero gap frame, but that
        # just means it is impossible to deliberately use zero gap frames for
        # sophisticated blending, so we dont do that.
        for f in frames:
            f.gap = 100
    mode = 'rgb'
    for f in frames:
        if f.mode == 'rgba':
            mode = 'rgba'
            break
    return ImageData(image_fmt, frames[0].canvas_width, frames[0].canvas_height, mode, frames)


class RenderedImage(ImageData):

    def __init__(self, fmt: str, width: int, height: int, mode: str):
        super().__init__(fmt, width, height, mode, [])


def render_image(
    path: str, output_prefix: str,
    m: ImageData,
    available_width: int, available_height: int,
    scale_up: bool,
    only_first_frame: bool = False,
    remove_alpha: str = '',
    flip: bool = False, flop: bool = False,
) -> RenderedImage:
    import tempfile
    has_multiple_frames = len(m) > 1
    get_multiple_frames = has_multiple_frames and not only_first_frame
    exe = which('magick')
    if exe:
        cmd = [exe, 'convert']
    else:
        exe = which('convert')
        if exe is None:
            raise OSError('Failed to find the ImageMagick convert executable, make sure it is present in PATH')
        cmd = [exe]
    if remove_alpha:
        cmd += ['-background', remove_alpha, '-alpha', 'remove']
    else:
        cmd += ['-background', 'none']
    if flip:
        cmd.append('-flip')
    if flop:
        cmd.append('-flop')
    cmd += ['--', path]
    if only_first_frame and has_multiple_frames:
        cmd[-1] += '[0]'
    cmd.append('-auto-orient')
    scaled = False
    width, height = m.width, m.height
    if scale_up:
        if width < available_width:
            r = available_width / width
            width, height = available_width, int(height * r)
            scaled = True
    if scaled or width > available_width or height > available_height:
        width, height = fit_image(width, height, available_width, available_height)
        resize_cmd = ['-resize', f'{width}x{height}!']
        if get_multiple_frames:
            # we have to coalesce, resize and de-coalesce all frames
            resize_cmd = ['-coalesce'] + resize_cmd + ['-deconstruct']
        cmd += resize_cmd
    cmd += ['-depth', '8', '-set', 'filename:f', '%w-%h-%g-%p']
    ans = RenderedImage(m.fmt, width, height, m.mode)
    if only_first_frame:
        ans.frames = [Frame(m.frames[0])]
    else:
        ans.frames = list(map(Frame, m.frames))
    bytes_per_pixel = 3 if m.mode == 'rgb' else 4

    def check_resize(frame: Frame) -> None:
        # ImageMagick sometimes generates RGBA images smaller than the specified
        # size. See https://github.com/kovidgoyal/kitty/issues/276 for examples
        sz = os.path.getsize(frame.path)
        expected_size = bytes_per_pixel * frame.width * frame.height
        if sz < expected_size:
            missing = expected_size - sz
            if missing % (bytes_per_pixel * width) != 0:
                raise ConvertFailed(
                    path, 'ImageMagick failed to convert {} correctly,'
                    ' it generated {} < {} of data (w={}, h={}, bpp={})'.format(
                        path, sz, expected_size, frame.width, frame.height, bytes_per_pixel))
            frame.height -= missing // (bytes_per_pixel * frame.width)
            if frame.index == 0:
                ans.height = frame.height
                ans.width = frame.width

    with tempfile.TemporaryDirectory(dir=os.path.dirname(output_prefix)) as tdir:
        output_template = os.path.join(tdir, f'im-%[filename:f].{m.mode}')
        if get_multiple_frames:
            cmd.append('+adjoin')
        run_imagemagick(path, cmd + [output_template])
        unseen = {x.index for x in m}
        for x in os.listdir(tdir):
            try:
                parts = x.split('.', 1)[0].split('-')
                index = int(parts[-1])
                unseen.discard(index)
                f = ans.frames[index]
                f.width, f.height = map(positive_int, parts[1:3])
                sz, pos = parts[3].split('+', 1)
                f.canvas_width, f.canvas_height = map(positive_int, sz.split('x', 1))
                f.canvas_x, f.canvas_y = map(int, pos.split('+', 1))
            except Exception:
                raise OutdatedImageMagick(f'Unexpected output filename: {x!r} produced by ImageMagick command: {last_imagemagick_cmd}')
            f.path = output_prefix + f'-{index}.{m.mode}'
            os.rename(os.path.join(tdir, x), f.path)
            check_resize(f)
    f = ans.frames[0]
    if f.width != ans.width or f.height != ans.height:
        with open(f.path, 'r+b') as ff:
            data = ff.read()
            ff.seek(0)
            ff.truncate()
            cd = create_canvas(data, f.width, f.canvas_x, f.canvas_y, ans.width, ans.height, 3 if ans.mode == 'rgb' else 4)
            ff.write(cd)
    if get_multiple_frames:
        if unseen:
            raise ConvertFailed(path, f'Failed to render {len(unseen)} out of {len(m)} frames of animation')
    elif not ans.frames[0].path:
        raise ConvertFailed(path, 'Failed to render image')

    return ans


def render_as_single_image(
    path: str, m: ImageData,
    available_width: int, available_height: int,
    scale_up: bool,
    tdir: str | None = None,
    remove_alpha: str = '', flip: bool = False, flop: bool = False,
) -> tuple[str, int, int]:
    import tempfile
    fd, output = tempfile.mkstemp(prefix='tty-graphics-protocol-', suffix=f'.{m.mode}', dir=tdir)
    os.close(fd)
    result = render_image(
        path, output, m, available_width, available_height, scale_up,
        only_first_frame=True, remove_alpha=remove_alpha, flip=flip, flop=flop)
    os.rename(result.frames[0].path, output)
    return output, result.width, result.height


def can_display_images() -> bool:
    ans: bool | None = getattr(can_display_images, 'ans', None)
    if ans is None:
        ans = which('convert') is not None
        setattr(can_display_images, 'ans', ans)
    return ans


ImageKey = tuple[str, int, int]
SentImageKey = tuple[int, int, int]
T = TypeVar('T')


class Alias(Generic[T]):

    currently_processing: ClassVar[str] = ''

    def __init__(self, defval: T) -> None:
        self.name = ''
        self.defval = defval

    def __get__(self, instance: Optional['GraphicsCommand'], cls: type['GraphicsCommand'] | None = None) -> T:
        if instance is None:
            return self.defval
        return cast(T, instance._actual_values.get(self.name, self.defval))

    def __set__(self, instance: 'GraphicsCommand', val: T) -> None:
        if val == self.defval:
            instance._actual_values.pop(self.name, None)
        else:
            instance._actual_values[self.name] = val

    def __set_name__(self, owner: type['GraphicsCommand'], name: str) -> None:
        if len(name) == 1:
            Alias.currently_processing = name
        self.name = Alias.currently_processing


class GraphicsCommand:
    a = action = Alias('t')
    q = quiet = Alias(0)
    f = format = Alias(32)
    t = transmission_type = Alias('d')
    s = data_width = animation_state = Alias(0)
    v = data_height = loop_count = Alias(0)
    S = data_size = Alias(0)
    O = data_offset = Alias(0)  # noqa
    i = image_id = Alias(0)
    I = image_number = Alias(0)  # noqa
    p = placement_id = Alias(0)
    o = compression = Alias(cast(Optional[GRT_o], None))
    m = more = Alias(0)
    x = left_edge = Alias(0)
    y = top_edge = Alias(0)
    w = width = Alias(0)
    h = height = Alias(0)
    X = cell_x_offset = blend_mode = Alias(0)
    Y = cell_y_offset = bgcolor = Alias(0)
    c = columns = other_frame_number = dest_frame = Alias(0)
    r = rows = frame_number = source_frame = Alias(0)
    z = z_index = gap = Alias(0)
    C = cursor_movement = compose_mode = Alias(0)
    d = delete_action = Alias('a')

    def __init__(self) -> None:
        self._actual_values: dict[str, Any] = {}

    def __repr__(self) -> str:
        return self.serialize().decode('ascii').replace('\033', '^]')

    def clone(self) -> 'GraphicsCommand':
        ans = GraphicsCommand()
        ans._actual_values = self._actual_values.copy()
        return ans

    def serialize(self, payload: bytes | memoryview | str = b'') -> bytes:
        items = []
        for k, val in self._actual_values.items():
            items.append(f'{k}={val}')

        ans: list[bytes|memoryview] = []
        w = ans.append
        w(b'\033_G')
        w(','.join(items).encode('ascii'))
        if payload:
            w(b';')
            if isinstance(payload, str):
                payload = standard_b64encode(payload.encode('utf-8'))
            w(payload)
        w(b'\033\\')
        return b''.join(ans)

    def clear(self) -> None:
        self._actual_values = {}

    def iter_transmission_chunks(self, data: bytes | None = None, level: int = -1, compression_threshold: int = 1024) -> Iterator[bytes]:
        if data is None:
            yield self.serialize()
            return
        gc = self.clone()
        gc.S = len(data)
        if level and len(data) >= compression_threshold:
            import zlib
            compressed = zlib.compress(data, level)
            if len(compressed) < len(data):
                gc.o = 'z'
                data = compressed
                gc.S = len(data)
        data = standard_b64encode(data)
        while data:
            chunk, data = data[:4096], data[4096:]
            gc.m = 1 if data else 0
            yield gc.serialize(chunk)
            gc.clear()


class Placement:
    cmd: GraphicsCommand
    x: int = 0
    y: int = 0

    def __init__(self, cmd: GraphicsCommand, x: int = 0, y: int = 0):
        self.cmd = cmd
        self.x = x
        self.y = y


class ImageManager:

    def __init__(self, handler: HandlerType):
        self.image_id_counter = count()
        self.handler = handler
        self.filesystem_ok: bool | None = None
        self.image_data: dict[str, ImageData] = {}
        self.failed_images: dict[str, Exception] = {}
        self.converted_images: dict[ImageKey, ImageKey] = {}
        self.sent_images: dict[ImageKey, int] = {}
        self.image_id_to_image_data: dict[int, ImageData] = {}
        self.image_id_to_converted_data: dict[int, ImageKey] = {}
        self.transmission_status: dict[int, str | int] = {}
        self.placements_in_flight: DefaultDict[int, Deque[Placement]] = defaultdict(deque)
        self.update_image_placement_for_resend: Callable[[int, Placement], bool] | None

    @property
    def next_image_id(self) -> int:
        return next(self.image_id_counter) + 2

    @property
    def screen_size(self) -> ScreenSize:
        return self.handler.screen_size

    def __enter__(self) -> None:
        import tempfile
        self.tdir = tempfile.mkdtemp(prefix='kitten-images-')
        with tempfile.NamedTemporaryFile(dir=self.tdir, delete=False) as f:
            f.write(b'abcd')
        gc = GraphicsCommand()
        gc.a = 'q'
        gc.s = gc.v = gc.i = 1
        gc.t = 'f'
        self.handler.cmd.gr_command(gc, standard_b64encode(f.name.encode(fsenc)))

    def __exit__(self, *a: Any) -> None:
        import shutil
        shutil.rmtree(self.tdir, ignore_errors=True)
        self.handler.cmd.clear_images_on_screen(delete_data=True)
        self.delete_all_sent_images()
        del self.handler

    def delete_all_sent_images(self) -> None:
        gc = GraphicsCommand()
        gc.a = 'd'
        for img_id in self.transmission_status:
            gc.i = img_id
            self.handler.cmd.gr_command(gc)
        self.transmission_status.clear()

    def handle_response(self, apc: str) -> None:
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

    def resend_image(self, image_id: int, pl: Placement) -> None:
        if self.update_image_placement_for_resend is not None and not self.update_image_placement_for_resend(image_id, pl):
            return
        image_data = self.image_id_to_image_data[image_id]
        skey = self.image_id_to_converted_data[image_id]
        self.transmit_image(image_data, image_id, *skey)
        with cursor(self.handler.write):
            self.handler.cmd.set_cursor_position(pl.x, pl.y)
            self.handler.cmd.gr_command(pl.cmd)

    def send_image(self, path: str, max_cols: int | None = None, max_rows: int | None = None, scale_up: bool = False) -> SentImageKey:
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

    def hide_image(self, image_id: int) -> None:
        gc = GraphicsCommand()
        gc.a = 'd'
        gc.i = image_id
        self.handler.cmd.gr_command(gc)

    def show_image(self, image_id: int, x: int, y: int, src_rect: tuple[int, int, int, int] | None = None) -> None:
        gc = GraphicsCommand()
        gc.a = 'p'
        gc.i = image_id
        if src_rect is not None:
            gc.x, gc.y, gc.w, gc.h = map(int, src_rect)
        self.placements_in_flight[image_id].append(Placement(gc, x, y))
        with cursor(self.handler.write):
            self.handler.cmd.set_cursor_position(x, y)
            self.handler.cmd.gr_command(gc)

    def convert_image(self, path: str, available_width: int, available_height: int, image_data: ImageData, scale_up: bool = False) -> ImageKey:
        rgba_path, width, height = render_as_single_image(path, image_data, available_width, available_height, scale_up, tdir=self.tdir)
        return rgba_path, width, height

    def transmit_image(self, image_data: ImageData, image_id: int, rgba_path: str, width: int, height: int) -> int:
        self.transmission_status[image_id] = 0
        gc = GraphicsCommand()
        gc.a = 't'
        gc.f = image_data.transmit_fmt
        gc.s = width
        gc.v = height
        gc.i = image_id
        if self.filesystem_ok:
            gc.t = 'f'
            self.handler.cmd.gr_command(
                gc, standard_b64encode(rgba_path.encode(fsenc)))
        else:
            import zlib
            with open(rgba_path, 'rb') as f:
                data = f.read()
            gc.S = len(data)
            data = zlib.compress(data)
            gc.o = 'z'
            data = standard_b64encode(data)
            while data:
                chunk, data = data[:4096], data[4096:]
                gc.m = 1 if data else 0
                self.handler.cmd.gr_command(gc, chunk)
                gc.clear()
        return image_id
