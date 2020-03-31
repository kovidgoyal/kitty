#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import sys
from functools import partial
from math import ceil, cos, floor, pi
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

from kitty.config import defaults
from kitty.constants import is_macos
from kitty.fast_data_types import (
    Screen, create_test_font_group, get_fallback_font, set_font_data,
    set_options, set_send_sprite_to_gpu, sprite_map_set_limits,
    test_render_line, test_shape
)
from kitty.fonts.box_drawing import (
    BufType, render_box_char, render_missing_glyph
)
from kitty.options_stub import Options as OptionsStub
from kitty.typing import CoreTextFont, FontConfigPattern
from kitty.utils import log_error

if is_macos:
    from .core_text import get_font_files as get_font_files_coretext, font_for_family as font_for_family_macos
else:
    from .fontconfig import get_font_files as get_font_files_fontconfig, font_for_family as font_for_family_fontconfig

FontObject = Union[CoreTextFont, FontConfigPattern]
current_faces: List[Tuple[FontObject, bool, bool]] = []


def get_font_files(opts: OptionsStub) -> Dict[str, Any]:
    if is_macos:
        return get_font_files_coretext(opts)
    return get_font_files_fontconfig(opts)


def font_for_family(family: str) -> Tuple[FontObject, bool, bool]:
    if is_macos:
        return font_for_family_macos(family)
    return font_for_family_fontconfig(family)


def coalesce_symbol_maps(maps: Dict[Tuple[int, int], str]) -> Dict[Tuple[int, int], str]:
    if not maps:
        return maps
    items = tuple((k, maps[k]) for k in sorted(maps))
    ans = [items[0]]

    def merge(prev_item: Tuple[Tuple[int, int], str], item: Tuple[Tuple[int, int], str]) -> None:
        s, e = item[0]
        pe = prev_item[0][1]
        ans[-1] = ((prev_item[0][0], max(pe, e)), prev_item[1])

    for item in items[1:]:
        current_item = ans[-1]
        if current_item[1] != item[1] or item[0][0] > current_item[0][1] + 1:
            ans.append(item)
        else:
            merge(current_item, item)

    return dict(ans)


def create_symbol_map(opts: OptionsStub) -> Tuple[Tuple[int, int, int], ...]:
    val = coalesce_symbol_maps(opts.symbol_map)
    family_map: Dict[str, int] = {}
    count = 0
    for family in val.values():
        if family not in family_map:
            font, bold, italic = font_for_family(family)
            family_map[family] = count
            count += 1
            current_faces.append((font, bold, italic))
    sm = tuple((a, b, family_map[f]) for (a, b), f in val.items())
    return sm


def descriptor_for_idx(idx: int) -> Tuple[FontObject, bool, bool]:
    return current_faces[idx]


def dump_faces(ftypes: List[str], indices: Dict[str, int]) -> None:
    def face_str(f: Tuple[FontObject, bool, bool]) -> str:
        fo = f[0]
        if 'index' in fo:
            return '{}:{}'.format(fo['path'], cast('FontConfigPattern', fo)['index'])
        fo = cast('CoreTextFont', fo)
        return fo['path']

    log_error('Preloaded font faces:')
    log_error('normal face:', face_str(current_faces[0]))
    for ftype in ftypes:
        if indices[ftype]:
            log_error(ftype, 'face:', face_str(current_faces[indices[ftype]]))
    si_faces = current_faces[max(indices.values())+1:]
    if si_faces:
        log_error('Symbol map faces:')
        for face in si_faces:
            log_error(face_str(face))


def set_font_family(opts: Optional[OptionsStub] = None, override_font_size: Optional[float] = None, debug_font_matching: bool = False) -> None:
    global current_faces
    opts = opts or defaults
    sz = override_font_size or opts.font_size
    font_map = get_font_files(opts)
    current_faces = [(font_map['medium'], False, False)]
    ftypes = 'bold italic bi'.split()
    indices = {k: 0 for k in ftypes}
    for k in ftypes:
        if k in font_map:
            indices[k] = len(current_faces)
            current_faces.append((font_map[k], 'b' in k, 'i' in k))
    before = len(current_faces)
    sm = create_symbol_map(opts)
    num_symbol_fonts = len(current_faces) - before
    if debug_font_matching:
        dump_faces(ftypes, indices)
    set_font_data(
        render_box_drawing, prerender_function, descriptor_for_idx,
        indices['bold'], indices['italic'], indices['bi'], num_symbol_fonts,
        sm, sz, opts.font_features
    )


UnderlineCallback = Callable[[ctypes.Array, int, int, int, int], None]


def add_line(buf: ctypes.Array, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    y = position - thickness // 2
    while thickness > 0 and -1 < y < cell_height:
        thickness -= 1
        ctypes.memset(ctypes.addressof(buf) + (cell_width * y), 255, cell_width)
        y += 1


def add_dline(buf: ctypes.Array, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    a = min(position - thickness, cell_height - 1)
    b = min(position, cell_height - 1)
    top, bottom = min(a, b), max(a, b)
    deficit = 2 - (bottom - top)
    if deficit > 0:
        if bottom + deficit < cell_height:
            bottom += deficit
        elif bottom < cell_height - 1:
            bottom += 1
            if deficit > 1:
                top -= deficit - 1
        else:
            top -= deficit
    top = max(0, min(top, cell_height - 1))
    bottom = max(0, min(bottom, cell_height - 1))
    for y in {top, bottom}:
        ctypes.memset(ctypes.addressof(buf) + (cell_width * y), 255, cell_width)


def add_curl(buf: ctypes.Array, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    max_x, max_y = cell_width - 1, cell_height - 1
    xfactor = 2.0 * pi / max_x
    half_height = max(thickness // 2, 1)

    def add_intensity(x: int, y: int, val: int) -> None:
        y += position
        y = min(y, max_y)
        idx = cell_width * y + x
        buf[idx] = min(255, buf[idx] + val)

    # Ensure all space at bottom of cell is used
    if position + half_height < max_y:
        position += max_y - (position + half_height)
    if position + half_height > max_y:
        position -= position + half_height - max_y

    # Use the Wu antialias algorithm to draw the curve
    # cosine waves always have slope <= 1 so are never steep
    for x in range(cell_width):
        y = half_height * cos(x * xfactor)
        y1, y2 = floor(y), ceil(y)
        i1 = int(255 * abs(y - y1))
        add_intensity(x, y1, 255 - i1)
        add_intensity(x, y2, i1)


def render_special(
    underline: int = 0,
    strikethrough: bool = False,
    missing: bool = False,
    cell_width: int = 0, cell_height: int = 0,
    baseline: int = 0,
    underline_position: int = 0,
    underline_thickness: int = 0,
    strikethrough_position: int = 0,
    strikethrough_thickness: int = 0
) -> ctypes.Array:
    underline_position = min(underline_position, cell_height - underline_thickness)
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)

    if missing:
        buf = bytearray(cell_width * cell_height)
        render_missing_glyph(buf, cell_width, cell_height)
        return CharTexture.from_buffer(buf)

    ans = CharTexture()

    def dl(f: UnderlineCallback, *a: Any) -> None:
        try:
            f(ans, cell_width, *a)
        except Exception as e:
            log_error('Failed to render {} at cell_width={} and cell_height={} with error: {}'.format(
                f.__name__, cell_width, cell_height, e))

    if underline:
        t = underline_thickness
        if underline > 1:
            t = max(1, min(cell_height - underline_position - 1, t))
        dl([add_line, add_line, add_dline, add_curl][underline], underline_position, t, cell_height)
    if strikethrough:
        dl(add_line, strikethrough_position, strikethrough_thickness, cell_height)

    return ans


def render_cursor(
    which: int,
    cursor_beam_thickness: float,
    cursor_underline_thickness: float,
    cell_width: int = 0,
    cell_height: int = 0,
    dpi_x: float = 0,
    dpi_y: float = 0
) -> ctypes.Array:
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    ans = CharTexture()

    def vert(edge: str, width_pt: float = 1) -> None:
        width = max(1, min(int(round(width_pt * dpi_x / 72.0)), cell_width))
        left = 0 if edge == 'left' else max(0, cell_width - width)
        for y in range(cell_height):
            offset = y * cell_width + left
            for x in range(offset, offset + width):
                ans[x] = 255

    def horz(edge: str, height_pt: float = 1) -> None:
        height = max(1, min(int(round(height_pt * dpi_y / 72.0)), cell_height))
        top = 0 if edge == 'top' else max(0, cell_height - height)
        for y in range(top, top + height):
            offset = y * cell_width
            for x in range(cell_width):
                ans[offset + x] = 255

    if which == 1:  # beam
        vert('left', cursor_beam_thickness)
    elif which == 2:  # underline
        horz('bottom', cursor_underline_thickness)
    elif which == 3:  # hollow
        vert('left')
        vert('right')
        horz('top')
        horz('bottom')
    return ans


def prerender_function(
    cell_width: int,
    cell_height: int,
    baseline: int,
    underline_position: int,
    underline_thickness: int,
    strikethrough_position: int,
    strikethrough_thickness: int,
    cursor_beam_thickness: float,
    cursor_underline_thickness: float,
    dpi_x: float,
    dpi_y: float
) -> Tuple[Union[int, ctypes.Array], ...]:
    # Pre-render the special underline, strikethrough and missing and cursor cells
    f = partial(
        render_special, cell_width=cell_width, cell_height=cell_height, baseline=baseline,
        underline_position=underline_position, underline_thickness=underline_thickness,
        strikethrough_position=strikethrough_position, strikethrough_thickness=strikethrough_thickness)
    c = partial(
        render_cursor, cursor_beam_thickness=cursor_beam_thickness,
        cursor_underline_thickness=cursor_underline_thickness, cell_width=cell_width,
        cell_height=cell_height, dpi_x=dpi_x, dpi_y=dpi_y)
    cells = f(1), f(2), f(3), f(0, True), f(missing=True), c(1), c(2), c(3)
    return tuple(map(ctypes.addressof, cells)) + (cells,)


def render_box_drawing(codepoint: int, cell_width: int, cell_height: int, dpi: float) -> Tuple[int, ctypes.Array]:
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    buf = CharTexture()
    render_box_char(
        chr(codepoint), cast(BufType, buf), cell_width, cell_height, dpi
    )
    return ctypes.addressof(buf), buf


class setup_for_testing:

    def __init__(self, family: str = 'monospace', size: float = 11.0, dpi: float = 96.0):
        self.family, self.size, self.dpi = family, size, dpi

    def __enter__(self) -> Tuple[Dict[Tuple[int, int, int], bytes], int, int]:
        opts = defaults._replace(font_family=self.family, font_size=self.size)
        set_options(opts)
        sprites = {}

        def send_to_gpu(x: int, y: int, z: int, data: bytes) -> None:
            sprites[(x, y, z)] = data

        sprite_map_set_limits(100000, 100)
        set_send_sprite_to_gpu(send_to_gpu)
        try:
            set_font_family(opts)
            cell_width, cell_height = create_test_font_group(self.size, self.dpi, self.dpi)
            return sprites, cell_width, cell_height
        except Exception:
            set_send_sprite_to_gpu(None)
            raise

    def __exit__(self, *args: Any) -> None:
        set_send_sprite_to_gpu(None)


def render_string(text: str, family: str = 'monospace', size: float = 11.0, dpi: float = 96.0) -> Tuple[int, int, List[bytes]]:
    with setup_for_testing(family, size, dpi) as (sprites, cell_width, cell_height):
        s = Screen(None, 1, len(text)*2)
        line = s.line(0)
        s.draw(text)
        test_render_line(line)
    cells = []
    found_content = False
    for i in reversed(range(s.columns)):
        sp = list(line.sprite_at(i))
        sp[2] &= 0xfff
        tsp = sp[0], sp[1], sp[2]
        if tsp == (0, 0, 0) and not found_content:
            continue
        found_content = True
        cells.append(sprites[tsp])
    return cell_width, cell_height, list(reversed(cells))


def shape_string(
    text: str = "abcd", family: str = 'monospace', size: float = 11.0, dpi: float = 96.0, path: Optional[str] = None
) -> List[Tuple[int, int, int, Tuple[int, ...]]]:
    with setup_for_testing(family, size, dpi) as (sprites, cell_width, cell_height):
        s = Screen(None, 1, len(text)*2)
        line = s.line(0)
        s.draw(text)
        return test_shape(line, path)


def display_bitmap(rgb_data: bytes, width: int, height: int) -> None:
    from tempfile import NamedTemporaryFile
    from kittens.icat.main import detect_support, show
    if not hasattr(display_bitmap, 'detected') and not detect_support():
        raise SystemExit('Your terminal does not support the graphics protocol')
    setattr(display_bitmap, 'detected', True)
    with NamedTemporaryFile(suffix='.rgba', delete=False) as f:
        f.write(rgb_data)
    assert len(rgb_data) == 4 * width * height
    show(f.name, width, height, 0, 32, align='left')


def test_render_string(
        text: str = 'Hello, world!',
        family: str = 'monospace',
        size: float = 64.0,
        dpi: float = 96.0
) -> None:
    from kitty.fast_data_types import concat_cells, current_fonts

    cell_width, cell_height, cells = render_string(text, family, size, dpi)
    rgb_data = concat_cells(cell_width, cell_height, True, tuple(cells))
    cf = current_fonts()
    fonts = [cf['medium'].display_name()]
    fonts.extend(f.display_name() for f in cf['fallback'])
    msg = 'Rendered string {} below, with fonts: {}\n'.format(text, ', '.join(fonts))
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(msg.encode('utf-8') + b'\n')
    display_bitmap(rgb_data, cell_width * len(cells), cell_height)
    print('\n')


def test_fallback_font(qtext: Optional[str] = None, bold: bool = False, italic: bool = False) -> None:
    with setup_for_testing():
        if qtext:
            trials = [qtext]
        else:
            trials = ['你', 'He\u0347\u0305', '\U0001F929']
        for text in trials:
            f = get_fallback_font(text, bold, italic)
            try:
                print(text, f)
            except UnicodeEncodeError:
                sys.stdout.buffer.write((text + ' %s\n' % f).encode('utf-8'))


def showcase() -> None:
    f = 'monospace' if is_macos else 'Liberation Mono'
    test_render_string('He\u0347\u0305llo\u0337, w\u0302or\u0306l\u0354d!', family=f)
    test_render_string('你好,世界', family=f)
    test_render_string('│😁│🙏│😺│', family=f)
    test_render_string('A=>>B!=C', family='Fira Code')
