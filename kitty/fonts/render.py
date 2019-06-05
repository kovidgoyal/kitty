#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import sys
from functools import partial
from math import ceil, pi, cos, floor

from kitty.config import defaults
from kitty.constants import is_macos
from kitty.fast_data_types import (
    Screen, create_test_font_group, get_fallback_font, set_font_data,
    set_options, set_send_sprite_to_gpu, sprite_map_set_limits,
    test_render_line, test_shape
)
from kitty.fonts.box_drawing import render_box_char, render_missing_glyph
from kitty.utils import log_error

if is_macos:
    from .core_text import get_font_files, font_for_family
else:
    from .fontconfig import get_font_files, font_for_family

current_faces = None


def create_symbol_map(opts):
    val = opts.symbol_map
    family_map = {}
    count = 0
    for family in val.values():
        if family not in family_map:
            font, bold, italic = font_for_family(family)
            family_map[family] = count
            count += 1
            current_faces.append((font, bold, italic))
    sm = tuple((a, b, family_map[f]) for (a, b), f in val.items())
    return sm


def descriptor_for_idx(idx):
    return current_faces[idx]


def dump_faces(ftypes, indices):
    def face_str(f):
        f = f[0]
        if is_macos:
            return f
        return '{}:{}'.format(f['path'], f['index'])

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


def set_font_family(opts=None, override_font_size=None, debug_font_matching=False):
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
        sm, sz
    )


def add_line(buf, cell_width, position, thickness, cell_height):
    y = position - thickness // 2
    while thickness > 0 and -1 < y < cell_height:
        thickness -= 1
        ctypes.memset(ctypes.addressof(buf) + (cell_width * y), 255, cell_width)
        y += 1


def add_dline(buf, cell_width, position, thickness, cell_height):
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


def add_curl(buf, cell_width, position, thickness, cell_height):
    max_x, max_y = cell_width - 1, cell_height - 1
    xfactor = 2.0 * pi / max_x
    half_height = max(thickness // 2, 1)

    def add_intensity(x, y, val):
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
        underline=0, strikethrough=False, missing=False,
        cell_width=None, cell_height=None, baseline=None, underline_position=None, underline_thickness=None):
    underline_position = min(underline_position, cell_height - underline_thickness)
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    ans = CharTexture if missing else CharTexture()

    def dl(f, *a):
        try:
            f(ans, cell_width, *a)
        except Exception as e:
            log_error('Failed to render {} at cell_width={} and cell_height={} with error: {}'.format(
                f.__name__, cell_width, cell_height, e))

    if underline:
        t = underline_thickness
        if underline > 1:
            t = max(1, min(cell_height - underline_position - 1, t))
        dl([None, add_line, add_dline, add_curl][underline], underline_position, t, cell_height)
    if strikethrough:
        pos = int(0.65 * baseline)
        dl(add_line, pos, underline_thickness, cell_height)

    if missing:
        buf = bytearray(cell_width * cell_height)
        render_missing_glyph(buf, cell_width, cell_height)
        ans = CharTexture.from_buffer(buf)
    return ans


def render_cursor(which, cell_width=0, cell_height=0, dpi_x=0, dpi_y=0):
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    ans = CharTexture()

    def vert(edge, width_pt=1):
        width = max(1, int(round(width_pt * dpi_x / 72.0)))
        left = 0 if edge == 'left' else max(0, cell_width - width)
        for y in range(cell_height):
            offset = y * cell_width + left
            for x in range(offset, offset + width):
                ans[x] = 255

    def horz(edge, height_pt=1):
        height = max(1, int(round(height_pt * dpi_y / 72.0)))
        top = 0 if edge == 'top' else max(0, cell_height - height)
        for y in range(top, top + height):
            offset = y * cell_width
            for x in range(cell_width):
                ans[offset + x] = 255

    if which == 1:  # beam
        vert('left', 1.5)
    elif which == 2:  # underline
        horz('bottom', 2.0)
    elif which == 3:  # hollow
        vert('left'), vert('right'), horz('top'), horz('bottom')
    return ans


def prerender_function(cell_width, cell_height, baseline, underline_position, underline_thickness, dpi_x, dpi_y):
    # Pre-render the special underline, strikethrough and missing and cursor cells
    f = partial(
        render_special, cell_width=cell_width, cell_height=cell_height, baseline=baseline,
        underline_position=underline_position, underline_thickness=underline_thickness)
    c = partial(
        render_cursor, cell_width=cell_width, cell_height=cell_height, dpi_x=dpi_x, dpi_y=dpi_y)
    cells = f(1), f(2), f(3), f(0, True), f(missing=True), c(1), c(2), c(3)
    return tuple(map(ctypes.addressof, cells)) + (cells,)


def render_box_drawing(codepoint, cell_width, cell_height, dpi):
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    buf = render_box_char(
        chr(codepoint), CharTexture(), cell_width, cell_height, dpi
    )
    return ctypes.addressof(buf), buf


class setup_for_testing:

    def __init__(self, family='monospace', size=11.0, dpi=96.0):
        self.family, self.size, self.dpi = family, size, dpi

    def __enter__(self):
        from collections import OrderedDict
        opts = defaults._replace(font_family=self.family, font_size=self.size)
        set_options(opts)
        sprites = OrderedDict()

        def send_to_gpu(x, y, z, data):
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

    def __exit__(self, *args):
        set_send_sprite_to_gpu(None)


def render_string(text, family='monospace', size=11.0, dpi=96.0):
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
        sp = tuple(sp)
        if sp == (0, 0, 0) and not found_content:
            continue
        found_content = True
        cells.append(sprites[sp])
    return cell_width, cell_height, list(reversed(cells))


def shape_string(text="abcd", family='monospace', size=11.0, dpi=96.0, path=None):
    with setup_for_testing(family, size, dpi) as (sprites, cell_width, cell_height):
        s = Screen(None, 1, len(text)*2)
        line = s.line(0)
        s.draw(text)
        return test_shape(line, path)


def display_bitmap(rgb_data, width, height):
    from tempfile import NamedTemporaryFile
    from kittens.icat.main import detect_support, show
    if not hasattr(display_bitmap, 'detected') and not detect_support():
        raise SystemExit('Your terminal does not support the graphics protocol')
    display_bitmap.detected = True
    with NamedTemporaryFile(suffix='.rgba', delete=False) as f:
        f.write(rgb_data)
    assert len(rgb_data) == 4 * width * height
    show(f.name, width, height, 32, align='left')


def test_render_string(text='Hello, world!', family='monospace', size=64.0, dpi=96.0):
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


def test_fallback_font(qtext=None, bold=False, italic=False):
    with setup_for_testing():
        trials = (qtext,) if qtext else ('你', 'He\u0347\u0305', '\U0001F929')
        for text in trials:
            f = get_fallback_font(text, bold, italic)
            try:
                print(text, f)
            except UnicodeEncodeError:
                sys.stdout.buffer.write((text + ' %s\n' % f).encode('utf-8'))


def showcase():
    f = 'monospace' if is_macos else 'Liberation Mono'
    test_render_string('He\u0347\u0305llo\u0337, w\u0302or\u0306l\u0354d!', family=f)
    test_render_string('你好,世界', family=f)
    test_render_string('│😁│🙏│😺│', family=f)
    test_render_string('A=>>B!=C', family='Fira Code')
