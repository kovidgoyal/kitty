#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import os
import sys
from collections.abc import Generator
from functools import partial
from math import ceil, cos, floor, pi
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Union, cast

from kitty.constants import fonts_dir, is_macos
from kitty.fast_data_types import (
    NUM_UNDERLINE_STYLES,
    Screen,
    create_test_font_group,
    current_fonts,
    get_fallback_font,
    get_options,
    set_builtin_nerd_font,
    set_font_data,
    set_options,
    set_send_sprite_to_gpu,
    sprite_map_set_limits,
    test_render_line,
    test_shape,
)
from kitty.fonts.box_drawing import BufType, distribute_dots, render_box_char, render_missing_glyph
from kitty.options.types import Options, defaults
from kitty.options.utils import parse_font_spec
from kitty.types import _T
from kitty.typing import CoreTextFont, FontConfigPattern
from kitty.utils import log_error

from . import family_name_to_key
from .common import get_font_files

if is_macos:
    from .core_text import font_for_family as font_for_family_macos
else:
    from .fontconfig import font_for_family as font_for_family_fontconfig

FontObject = Union[CoreTextFont, FontConfigPattern]
current_faces: list[tuple[FontObject, bool, bool]] = []
builtin_nerd_font_descriptor: Optional[FontObject] = None


def font_for_family(family: str) -> tuple[FontObject, bool, bool]:
    if is_macos:
        return font_for_family_macos(family)
    return font_for_family_fontconfig(family)


def merge_ranges(
    a: tuple[tuple[int, int], _T], b: tuple[tuple[int, int], _T], priority_map: dict[tuple[int, int], int]
) -> Generator[tuple[tuple[int, int], _T], None, None]:
    a_start, a_end = a[0]
    b_start, b_end = b[0]
    a_val, b_val = a[1], b[1]
    a_prio, b_prio = priority_map[a[0]], priority_map[b[0]]
    if b_start > a_end:
        if b_start == a_end + 1 and a_val == b_val:
            # ranges can be coalesced
            r = ((a_start, b_end), a_val)
            priority_map[r[0]] = max(a_prio, b_prio)
            yield r
            return
        # disjoint ranges
        yield a
        yield b
        return
    if a_val == b_val:
        # mergeable ranges
        r = ((a_start, max(a_end, b_end)), a_val)
        priority_map[r[0]] = max(a_prio, b_prio)
        yield r
        return
    before_range = mid_range = after_range = None
    before_range_prio = mid_range_prio = after_range_prio = 0
    if b_start > a_start:
        before_range = ((a_start, b_start - 1), a_val)
        before_range_prio = a_prio
    mid_end = min(a_end, b_end)
    if mid_end >= b_start:
        # overlap range
        mid_range = ((b_start, mid_end), a_val if priority_map[a[0]] >= priority_map[b[0]] else b_val)
        mid_range_prio = max(a_prio, b_prio)
    # after range
    if mid_end is a_end:
        if b_end > a_end:
            after_range = ((a_end + 1, b_end), b_val)
            after_range_prio = b_prio
    else:
        if a_end > b_end:
            after_range = ((b_end + 1, a_end), a_val)
            after_range_prio = a_prio
    # check if the before, mid and after ranges can be coalesced
    ranges: list[tuple[tuple[int, int], _T]] = []
    priorities: list[int] = []
    for rq, prio in ((before_range, before_range_prio), (mid_range, mid_range_prio), (after_range, after_range_prio)):
        if rq is None:
            continue
        r = rq
        if ranges:
            x = ranges[-1]
            if x[0][1] + 1 == r[0][0] and x[1] == r[1]:
                ranges[-1] = ((x[0][0], r[0][1]), x[1])
                priorities[-1] = max(priorities[-1], prio)
            else:
                ranges.append(r)
                priorities.append(prio)
        else:
            ranges.append(r)
            priorities.append(prio)
    for r, p in zip(ranges, priorities):
        priority_map[r[0]] = p
    yield from ranges


def coalesce_symbol_maps(maps: dict[tuple[int, int], _T]) -> dict[tuple[int, int], _T]:
    if not maps:
        return maps
    priority_map = {r: i for i, r in enumerate(maps.keys())}
    ranges = tuple((r, maps[r]) for r in sorted(maps))
    ans = [ranges[0]]

    for i in range(1, len(ranges)):
        r = ranges[i]
        new_ranges = merge_ranges(ans[-1], r, priority_map)
        if ans:
            del ans[-1]
        if not ans:
            ans = list(new_ranges)
        else:
            for r in new_ranges:
                prev = ans[-1]
                if prev[0][1] + 1 == r[0][0] and prev[1] == r[1]:
                    ans[-1] = (prev[0][0], r[0][1]), prev[1]
                else:
                    ans.append(r)
    return dict(ans)


def create_symbol_map(opts: Options) -> tuple[tuple[int, int, int], ...]:
    val = coalesce_symbol_maps(opts.symbol_map)
    family_map: dict[str, int] = {}
    count = 0
    for family in val.values():
        if family not in family_map:
            font, bold, italic = font_for_family(family)
            fkey = family_name_to_key(family)
            if fkey in ('symbolsnfm', 'symbols nerd font mono') and font['postscript_name'] != 'SymbolsNFM' and builtin_nerd_font_descriptor:
                font = builtin_nerd_font_descriptor
                bold = italic = False
            family_map[family] = count
            count += 1
            current_faces.append((font, bold, italic))
    sm = tuple((a, b, family_map[f]) for (a, b), f in val.items())
    return sm


def create_narrow_symbols(opts: Options) -> tuple[tuple[int, int, int], ...]:
    return tuple((a, b, v) for (a, b), v in coalesce_symbol_maps(opts.narrow_symbols).items())


descriptor_overrides: dict[int, tuple[str, bool, bool]] = {}


def descriptor_for_idx(idx: int) -> tuple[Union[FontObject, str], bool, bool]:
    ans = descriptor_overrides.get(idx)
    if ans is None:
        return current_faces[idx]
    return ans


def dump_font_debug() -> None:
    cf = current_fonts()
    log_error('Text fonts:')
    for key, text in {'medium': 'Normal', 'bold': 'Bold', 'italic': 'Italic', 'bi': 'Bold-Italic'}.items():
        log_error(f'  {text}:', cf[key].identify_for_debug())  # type: ignore
    ss = cf['symbol']
    if ss:
        log_error('Symbol map fonts:')
        for s in ss:
            log_error('  ' + s.identify_for_debug())


def set_font_family(opts: Optional[Options] = None, override_font_size: Optional[float] = None, add_builtin_nerd_font: bool = False) -> None:
    global current_faces, builtin_nerd_font_descriptor
    opts = opts or defaults
    sz = override_font_size or opts.font_size
    font_map = get_font_files(opts)
    current_faces = [(font_map['medium'], False, False)]
    ftypes: list[Literal['bold', 'italic', 'bi']] = ['bold', 'italic', 'bi']
    indices = {k: 0 for k in ftypes}
    for k in ftypes:
        if k in font_map:
            indices[k] = len(current_faces)
            current_faces.append((font_map[k], 'b' in k, 'i' in k))
    before = len(current_faces)
    if add_builtin_nerd_font:
        builtin_nerd_font_path = os.path.join(fonts_dir, 'SymbolsNerdFontMono-Regular.ttf')
        if os.path.exists(builtin_nerd_font_path):
            builtin_nerd_font_descriptor = set_builtin_nerd_font(builtin_nerd_font_path)
        else:
            log_error(f'No builtin NERD font found in {fonts_dir}')
    sm = create_symbol_map(opts)
    ns = create_narrow_symbols(opts)
    num_symbol_fonts = len(current_faces) - before
    set_font_data(
        render_box_drawing, prerender_function, descriptor_for_idx,
        indices['bold'], indices['italic'], indices['bi'], num_symbol_fonts,
        sm, sz, ns
    )


if TYPE_CHECKING:
    CBufType = ctypes.Array[ctypes.c_ubyte]
else:
    CBufType = None
UnderlineCallback = Callable[[CBufType, int, int, int, int], None]


def add_line(buf: CBufType, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    y = position - thickness // 2
    while thickness > 0 and -1 < y < cell_height:
        thickness -= 1
        ctypes.memset(ctypes.addressof(buf) + (cell_width * y), 255, cell_width)
        y += 1


def add_dline(buf: CBufType, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
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


def add_curl(buf: CBufType, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    max_x, max_y = cell_width - 1, cell_height - 1
    opts = get_options()
    xfactor = (4.0 if 'dense' in opts.undercurl_style else 2.0) * pi / max_x

    max_height = cell_height - (position - thickness // 2)  # descender from the font
    half_height = max(1, max_height // 4)
    if 'thick' in opts.undercurl_style:
        thickness = max(half_height, thickness)
    else:
        thickness = max(1, thickness) - (1 if thickness < 3 else 2)

    def add_intensity(x: int, y: int, val: int) -> None:
        y += position
        y = min(y, max_y)
        idx = cell_width * y + x
        buf[idx] = min(255, buf[idx] + val)

    # Ensure curve doesn't exceed cell boundary at the bottom
    position += half_height * 2
    if position + half_height > max_y:
        position = max_y - half_height

    # Use the Wu antialias algorithm to draw the curve
    # cosine waves always have slope <= 1 so are never steep
    for x in range(cell_width):
        y = half_height * cos(x * xfactor)
        y1, y2 = floor(y - thickness), ceil(y)
        i1 = int(255 * abs(y - floor(y)))
        add_intensity(x, y1, 255 - i1)  # upper bound
        add_intensity(x, y2, i1)  # lower bound
        # fill between upper and lower bound
        for t in range(1, thickness + 1):
            add_intensity(x, y1 + t, 255)


def add_dots(buf: CBufType, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    spacing, size = distribute_dots(cell_width, cell_width // (2 * thickness))
    y = position - thickness // 2
    buf_addr = ctypes.addressof(buf)
    while thickness > 0 and -1 < y < cell_height:
        offset = buf_addr + cell_width * y
        for j, s in enumerate(spacing):
            ctypes.memset(offset + j * size + s, 255, size)
        thickness -= 1
        y += 1


def add_dashes(buf: CBufType, cell_width: int, position: int, thickness: int, cell_height: int) -> None:
    halfspace_width = cell_width // 4
    y = position - thickness // 2
    dash_width = cell_width - 3 * halfspace_width
    second_dash_start = 3 * halfspace_width
    buf_addr = ctypes.addressof(buf)
    while thickness > 0 and -1 < y < cell_height:
        offset = buf_addr + cell_width * y
        ctypes.memset(offset, 255, dash_width)
        ctypes.memset(offset + second_dash_start, 255, dash_width)
        thickness -= 1
        y += 1


def render_special(
    underline: int = 0,
    strikethrough: bool = False,
    missing: bool = False,
    cell_width: int = 0, cell_height: int = 0,
    baseline: int = 0,
    underline_position: int = 0,
    underline_thickness: int = 0,
    strikethrough_position: int = 0,
    strikethrough_thickness: int = 0,
    dpi_x: float = 96.,
    dpi_y: float = 96.,
) -> CBufType:
    underline_position = min(underline_position, cell_height - sum(divmod(underline_thickness, 2)))
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
            log_error(f'Failed to render {f.__name__} at cell_width={cell_width} and cell_height={cell_height} with error: {e}')

    if underline:
        t = underline_thickness
        if underline > 1:
            t = max(1, min(cell_height - underline_position - 1, t))
        dl([add_line, add_line, add_dline, add_curl, add_dots, add_dashes][underline], underline_position, t, cell_height)
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
) -> CBufType:
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
) -> tuple[tuple[int, ...], tuple[CBufType, ...]]:
    # Pre-render the special underline, strikethrough and missing and cursor cells
    f = partial(
        render_special, cell_width=cell_width, cell_height=cell_height, baseline=baseline,
        underline_position=underline_position, underline_thickness=underline_thickness,
        strikethrough_position=strikethrough_position, strikethrough_thickness=strikethrough_thickness,
        dpi_x=dpi_x, dpi_y=dpi_y
    )
    c = partial(
        render_cursor, cursor_beam_thickness=cursor_beam_thickness,
        cursor_underline_thickness=cursor_underline_thickness, cell_width=cell_width,
        cell_height=cell_height, dpi_x=dpi_x, dpi_y=dpi_y)
    # If you change the mapping of these cells you will need to change
    # NUM_UNDERLINE_STYLES and BEAM_IDX in shader.c and STRIKE_SPRITE_INDEX in
    # window.py and MISSING_GLYPH in font.c
    cells = list(map(f, range(1, NUM_UNDERLINE_STYLES + 1)))  # underline sprites
    cells.append(f(0, strikethrough=True))  # strikethrough sprite
    cells.append(f(missing=True))  # missing glyph
    cells.extend((c(1), c(2), c(3)))  # cursor glyphs
    tcells = tuple(cells)
    return tuple(map(ctypes.addressof, tcells)), tcells


def render_box_drawing(codepoint: int, cell_width: int, cell_height: int, dpi: float) -> tuple[int, CBufType]:
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    buf = CharTexture()
    render_box_char(
        chr(codepoint), cast(BufType, buf), cell_width, cell_height, dpi
    )
    return ctypes.addressof(buf), buf


class setup_for_testing:

    def __init__(self, family: str = 'monospace', size: float = 11.0, dpi: float = 96.0, main_face_path: str = ''):
        self.family, self.size, self.dpi = family, size, dpi
        self.main_face_path = main_face_path

    def __enter__(self) -> tuple[dict[tuple[int, int, int], bytes], int, int]:
        global descriptor_overrides
        opts = defaults._replace(font_family=parse_font_spec(self.family), font_size=self.size)
        set_options(opts)
        sprites = {}

        def send_to_gpu(x: int, y: int, z: int, data: bytes) -> None:
            sprites[(x, y, z)] = data

        sprite_map_set_limits(100000, 100)
        set_send_sprite_to_gpu(send_to_gpu)
        self.orig_desc_overrides = descriptor_overrides
        descriptor_overrides = {}
        if self.main_face_path:
            descriptor_overrides[0] = self.main_face_path, False, False
        try:
            set_font_family(opts)
            cell_width, cell_height = create_test_font_group(self.size, self.dpi, self.dpi)
            return sprites, cell_width, cell_height
        except Exception:
            set_send_sprite_to_gpu(None)
            raise

    def __exit__(self, *args: Any) -> None:
        global descriptor_overrides
        descriptor_overrides = self.orig_desc_overrides
        set_send_sprite_to_gpu(None)


def render_string(text: str, family: str = 'monospace', size: float = 11.0, dpi: float = 96.0) -> tuple[int, int, list[bytes]]:
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
) -> list[tuple[int, int, int, tuple[int, ...]]]:
    with setup_for_testing(family, size, dpi) as (sprites, cell_width, cell_height):
        s = Screen(None, 1, len(text)*2)
        line = s.line(0)
        s.draw(text)
        return test_shape(line, path)


def show(rgba_data: bytes, width: int, height: int, fmt: int = 32) -> None:
    from base64 import standard_b64encode

    from kittens.tui.images import GraphicsCommand

    data = memoryview(standard_b64encode(rgba_data))
    cmd = GraphicsCommand()
    cmd.a = 'T'
    cmd.f = fmt
    cmd.s = width
    cmd.v = height

    while data:
        chunk, data = data[:4096], data[4096:]
        cmd.m = 1 if data else 0
        sys.stdout.buffer.write(cmd.serialize(chunk))
        cmd.clear()
    sys.stdout.flush()
    sys.stdout.buffer.flush()


def display_bitmap(rgb_data: bytes, width: int, height: int) -> None:
    assert len(rgb_data) == 4 * width * height
    show(rgb_data, width, height)


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
    fonts = [cf['medium'].postscript_name()]
    fonts.extend(f.postscript_name() for f in cf['fallback'])
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
                sys.stdout.buffer.write(f'{text} {f}\n'.encode())


def showcase() -> None:
    f = 'monospace' if is_macos else 'Liberation Mono'
    test_render_string('He\u0347\u0305llo\u0337, w\u0302or\u0306l\u0354d!', family=f)
    test_render_string('你好,世界', family=f)
    test_render_string('│😁│🙏│😺│', family=f)
    test_render_string('A=>>B!=C', family='Fira Code')
