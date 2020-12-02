#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import os
import sys
from base64 import standard_b64encode
from collections import defaultdict, deque
from contextlib import suppress
from itertools import count
from typing import (
    Any, Callable, DefaultDict, Deque, Dict, List, Optional, Sequence, Tuple,
    Union
)

from kitty.typing import (
    CompletedProcess, GRT_a, GRT_d, GRT_f, GRT_m, GRT_o, GRT_t, HandlerType
)
from kitty.utils import ScreenSize, fit_image

from .operations import cursor

try:
    fsenc = sys.getfilesystemencoding() or 'utf-8'
    codecs.lookup(fsenc)
except Exception:
    fsenc = 'utf-8'


class ImageData:

    def __init__(self, fmt: str, width: int, height: int, mode: str):
        self.width, self.height, self.fmt, self.mode = width, height, fmt, mode
        self.transmit_fmt: GRT_f = (24 if self.mode == 'rgb' else 32)


class OpenFailed(ValueError):

    def __init__(self, path: str, message: str):
        ValueError.__init__(
            self, 'Failed to open image: {} with error: {}'.format(path, message)
        )
        self.path = path


class ConvertFailed(ValueError):

    def __init__(self, path: str, message: str):
        ValueError.__init__(
            self, 'Failed to convert image: {} with error: {}'.format(path, message)
        )
        self.path = path


class NoImageMagick(Exception):
    pass


def run_imagemagick(path: str, cmd: Sequence[str], keep_stdout: bool = True) -> CompletedProcess:
    import subprocess
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE if keep_stdout else subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise NoImageMagick('ImageMagick is required to process images')
    if p.returncode != 0:
        raise OpenFailed(path, p.stderr.decode('utf-8'))
    return p


def identify(path: str) -> ImageData:
    p = run_imagemagick(path, ['identify', '-format', '%m %w %h %A', '--', path])
    parts: Tuple[str, ...] = tuple(filter(None, p.stdout.decode('utf-8').split()))
    mode = 'rgb' if parts[3].lower() == 'false' else 'rgba'
    return ImageData(parts[0].lower(), int(parts[1]), int(parts[2]), mode)


def convert(
    path: str, m: ImageData,
    available_width: int, available_height: int,
    scale_up: bool,
    tdir: Optional[str] = None
) -> Tuple[str, int, int]:
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
    cmd += ['-depth', '8']
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


def can_display_images() -> bool:
    import shutil
    ans: Optional[bool] = getattr(can_display_images, 'ans', None)
    if ans is None:
        ans = shutil.which('convert') is not None
        setattr(can_display_images, 'ans', ans)
    return ans


ImageKey = Tuple[str, int, int]
SentImageKey = Tuple[int, int, int]


class GraphicsCommand:
    a: GRT_a = 't'  # action
    f: GRT_f = 32   # image data format
    t: GRT_t = 'd'  # transmission medium
    s: int = 0        # sent image width
    v: int = 0        # sent image height
    S: int = 0        # size of data to read from file
    O: int = 0        # offset of data to read from file
    i: int = 0        # image id
    p: int = 0        # placement id
    o: Optional[GRT_o] = None  # type of compression
    m: GRT_m = 0    # 0 or 1 whether there is more chunked data
    x: int = 0        # left edge of image area to display
    y: int = 0        # top edge of image area to display
    w: int = 0        # image width to display
    h: int = 0        # image height to display
    X: int = 0        # X-offset within cell
    Y: int = 0        # Y-offset within cell
    c: int = 0        # number of cols to display image over
    r: int = 0        # number of rows to display image over
    z: int = 0        # z-index
    d: GRT_d = 'a'  # what to delete

    def serialize(self, payload: bytes = b'') -> bytes:
        items = []
        for k in GraphicsCommand.__annotations__:
            val: Union[str, None, int] = getattr(self, k)
            defval: Union[str, None, int] = getattr(GraphicsCommand, k)
            if val != defval and val is not None:
                items.append('{}={}'.format(k, val))

        ans: List[bytes] = []
        w = ans.append
        w(b'\033_G')
        w(','.join(items).encode('ascii'))
        if payload:
            w(b';')
            w(payload)
        w(b'\033\\')
        return b''.join(ans)

    def clear(self) -> None:
        for k in GraphicsCommand.__annotations__:
            defval: Union[str, None, int] = getattr(GraphicsCommand, k)
            setattr(self, k, defval)


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
        self.filesystem_ok: Optional[bool] = None
        self.image_data: Dict[str, ImageData] = {}
        self.failed_images: Dict[str, Exception] = {}
        self.converted_images: Dict[ImageKey, ImageKey] = {}
        self.sent_images: Dict[ImageKey, int] = {}
        self.image_id_to_image_data: Dict[int, ImageData] = {}
        self.image_id_to_converted_data: Dict[int, ImageKey] = {}
        self.transmission_status: Dict[int, Union[str, int]] = {}
        self.placements_in_flight: DefaultDict[int, Deque[Placement]] = defaultdict(deque)
        self.update_image_placement_for_resend: Optional[Callable[[int, Placement], bool]]

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

    def send_image(self, path: str, max_cols: Optional[int] = None, max_rows: Optional[int] = None, scale_up: bool = False) -> SentImageKey:
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

    def show_image(self, image_id: int, x: int, y: int, src_rect: Optional[Tuple[int, int, int, int]] = None) -> None:
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
        rgba_path, width, height = convert(path, image_data, available_width, available_height, scale_up, tdir=self.tdir)
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
