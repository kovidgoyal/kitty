#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import os
import sys
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any, Literal, Union

from kitty.constants import fonts_dir, is_macos
from kitty.fast_data_types import (
    Screen,
    concat_cells,
    create_test_font_group,
    current_fonts,
    get_fallback_font,
    render_decoration,
    set_builtin_nerd_font,
    set_font_data,
    set_options,
    set_send_sprite_to_gpu,
    sprite_idx_to_pos,
    sprite_map_set_limits,
    test_render_line,
    test_shape,
)
from kitty.options.types import Options, defaults
from kitty.options.utils import parse_font_spec
from kitty.types import _T
from kitty.typing_compat import CoreTextFont, FontConfigPattern
from kitty.utils import log_error

from . import family_name_to_key
from .common import get_font_files

if is_macos:
    from .core_text import font_for_family as font_for_family_macos
else:
    from .fontconfig import font_for_family as font_for_family_fontconfig

if TYPE_CHECKING:
    from kitty.fast_data_types import CTFace, DecorationTypes, Face
else:
    DecorationTypes = str

FontObject = Union[CoreTextFont, FontConfigPattern]
current_faces: list[tuple[FontObject, bool, bool]] = []
builtin_nerd_font_descriptor: FontObject | None = None


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


def descriptor_for_idx(idx: int) -> tuple[FontObject | str, bool, bool]:
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


def set_font_family(opts: Options | None = None, override_font_size: float | None = None, add_builtin_nerd_font: bool = False) -> None:
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
        descriptor_for_idx,
        indices['bold'], indices['italic'], indices['bi'], num_symbol_fonts,
        sm, sz, ns
    )


if TYPE_CHECKING:
    CBufType = ctypes.Array[ctypes.c_ubyte]
else:
    CBufType = None
UnderlineCallback = Callable[[CBufType, int, int, int, int], None]


class setup_for_testing:

    xnum = 100000
    ynum = 100
    baseline = 0

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

        sprite_map_set_limits(self.xnum, self.ynum)
        set_send_sprite_to_gpu(send_to_gpu)
        self.orig_desc_overrides = descriptor_overrides
        descriptor_overrides = {}
        if self.main_face_path:
            descriptor_overrides[0] = self.main_face_path, False, False
        try:
            set_font_family(opts)
            cell_width, cell_height, self.baseline = create_test_font_group(self.size, self.dpi, self.dpi)
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
        sp = line.sprite_at(i)
        sp &= 0x7fffffff
        if not sp and not found_content:
            continue
        found_content = True
        cells.append(sprites[sprite_idx_to_pos(sp, setup_for_testing.xnum, setup_for_testing.ynum)])
    return cell_width, cell_height, list(reversed(cells))


def shape_string(
    text: str = "abcd", family: str = 'monospace', size: float = 11.0, dpi: float = 96.0, path: str | None = None
) -> list[tuple[int, int, int, tuple[int, ...]]]:
    with setup_for_testing(family, size, dpi) as (sprites, cell_width, cell_height):
        s = Screen(None, 1, len(text)*2)
        line = s.line(0)
        s.draw(text)
        return test_shape(line, path)


def show(rgba_data: bytes | memoryview, width: int, height: int, fmt: int = 32) -> None:
    from base64 import standard_b64encode

    from kittens.tui.images import GraphicsCommand

    data = memoryview(standard_b64encode(rgba_data))
    cmd = GraphicsCommand()
    cmd.a = 'T'
    cmd.f = fmt
    cmd.s = width
    cmd.v = height

    sys.stdout.flush()
    while data:
        chunk, data = data[:4096], data[4096:]
        cmd.m = 1 if data else 0
        sys.stdout.buffer.write(cmd.serialize(chunk))
        cmd.clear()
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


def test_fallback_font(qtext: str | None = None, bold: bool = False, italic: bool = False) -> None:
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


def create_face(path: str) -> 'Union[CTFace, Face]':
    if is_macos:
        from kitty.fast_data_types import CTFace
        return CTFace(path=path)
    from kitty.fast_data_types import Face
    return Face(path=path)


def test_render_codepoint(chars: str = '😺', path: str = '/t/Noto-COLRv1.ttf', font_size: float = 160.0) -> None:
    f = create_face(path=path)
    f.set_size(font_size, 96, 96)
    for char in chars:
        bitmap, w, h = f.render_codepoint(ord(char))
        print('Rendered:', char)
        display_bitmap(bitmap, w, h)
        print('\n')


def test_render_decoration(which: DecorationTypes, cell_width: int, cell_height: int, underline_position: int, underline_thickness: int) -> None:
    buf = render_decoration(which, cell_width, cell_height, underline_position, underline_thickness)
    cells = buf, buf, buf, buf, buf
    rgb_data = concat_cells(cell_width, cell_height, False, cells)
    display_bitmap(rgb_data, cell_width * len(cells), cell_height)
