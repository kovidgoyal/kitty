#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
from collections import namedtuple
from math import ceil, floor, pi, sin, sqrt

from kitty.constants import isosx
from kitty.config import defaults
from kitty.fast_data_types import (
    send_prerendered_sprites, set_font, set_font_size
)
from kitty.fonts.box_drawing import render_box_char, render_missing_glyph
from kitty.utils import get_logical_dpi

if isosx:
    from .core_text import get_font_files, font_for_text, face_from_font, font_for_family, save_medium_face
else:
    from .fontconfig import get_font_files, font_for_text, face_from_font, font_for_family

    def save_medium_face(f):
        pass


def create_face(font):
    s = set_font_family.state
    return face_from_font(font, s.pt_sz, s.xdpi, s.ydpi)


def create_symbol_map(opts):
    val = opts.symbol_map
    family_map = {}
    faces = []
    for family in val.values():
        if family not in family_map:
            font = font_for_family(family)
            o = create_face(font)
            family_map[family] = len(faces)
            faces.append((o, font.bold, font.italic))
    sm = tuple((a, b, family_map[f]) for (a, b), f in val.items())
    return sm, tuple(faces)


FontState = namedtuple(
    'FontState',
    'family pt_sz xdpi ydpi cell_width cell_height baseline underline_position underline_thickness'
)


def get_fallback_font(text, bold, italic):
    state = set_font_family.state
    return create_face(
        font_for_text(
            text, state.family, state.pt_sz, state.xdpi, state.ydpi, bold,
            italic
        )
    )


def set_font_family(opts=None, override_font_size=None, override_dpi=None):
    opts = opts or defaults
    sz = override_font_size or opts.font_size
    xdpi, ydpi = get_logical_dpi(override_dpi)
    set_font_family.state = FontState('', sz, xdpi, ydpi, 0, 0, 0, 0, 0)
    font_map = get_font_files(opts)
    faces = [create_face(font_map['medium'])]
    save_medium_face(faces[0])
    for k in 'bold italic bi'.split():
        if k in font_map:
            faces.append(create_face(font_map[k]))
    sm, sfaces = create_symbol_map(opts)
    cell_width, cell_height, baseline, underline_position, underline_thickness = set_font(
        get_fallback_font, render_box_drawing, sm, sfaces, sz, xdpi, ydpi, *faces
    )
    set_font_family.state = FontState(
        opts.font_family, sz, xdpi, ydpi, cell_width, cell_height, baseline,
        underline_position, underline_thickness
    )
    prerender()
    return cell_width, cell_height


def resize_fonts(new_sz, xdpi=None, ydpi=None):
    s = set_font_family.state
    xdpi = xdpi or s.xdpi
    ydpi = ydpi or s.ydpi
    cell_width, cell_height, baseline, underline_position, underline_thickness = set_font_size(
        new_sz, xdpi, ydpi
    )
    set_font_family.state = FontState(
        s.family, new_sz, xdpi, ydpi, cell_width, cell_height, baseline,
        underline_position, underline_thickness
    )
    prerender()


def add_line(buf, cell_width, position, thickness, cell_height):
    y = position - thickness // 2
    while thickness:
        thickness -= 1
        offset = cell_width * y
        for x in range(cell_width):
            buf[offset + x] = 255
        y += 1


def add_curl(buf, cell_width, position, thickness, cell_height):
    xfactor = 2.0 * pi / cell_width
    yfactor = thickness

    def clamp_y(y):
        return max(0, min(int(y), cell_height - 1))

    def clamp_x(x):
        return max(0, min(int(x), cell_width - 1))

    def add_intensity(x, y, distance):
        buf[cell_width * y + x] = min(
            255, buf[cell_width * y + x] + int(255 * (1 - distance))
        )

    for x_exact in range(cell_width):
        y_exact = yfactor * sin(x_exact * xfactor) + position
        y_below = clamp_y(floor(y_exact))
        y_above = clamp_y(ceil(y_exact))
        x_before, x_after = map(clamp_x, (x_exact - 1, x_exact + 1))
        for x in {x_before, x_exact, x_after}:
            for y in {y_below, y_above}:
                dist = sqrt((x - x_exact)**2 + (y - y_exact)**2) / 2
                add_intensity(x, y, dist)


def render_special(underline=0, strikethrough=False, missing=False):
    s = set_font_family.state
    cell_width, cell_height, baseline = s.cell_width, s.cell_height, s.baseline
    underline_position, underline_thickness = s.underline_position, s.underline_thickness
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    ans = CharTexture if missing else CharTexture()

    def dl(f, *a):
        f(ans, cell_width, *a)

    if underline:
        t = underline_thickness
        if underline == 2:
            t = max(1, min(cell_height - underline_position - 1, t))
        dl(
            add_curl
            if underline == 2 else add_line, underline_position, t, cell_height
        )
    if strikethrough:
        pos = int(0.65 * baseline)
        dl(add_line, pos, underline_thickness, cell_height)

    if missing:
        buf = bytearray(cell_width * cell_height)
        render_missing_glyph(buf, cell_width, cell_height)
        ans = CharTexture.from_buffer(buf)
    return ans


def prerender():
    # Pre-render the special blank, underline and strikethrough cells
    cells = render_special(1), render_special(2), render_special(0, True), render_special(missing=True)
    if send_prerendered_sprites(*map(ctypes.addressof, cells)) != len(cells):
        raise RuntimeError('Your GPU has too small a max texture size')


def render_box_drawing(codepoint):
    s = set_font_family.state
    cell_width, cell_height = s.cell_width, s.cell_height
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    buf = render_box_char(
        chr(codepoint), CharTexture(), cell_width, cell_height
    )
    return ctypes.addressof(buf), buf


def test_render_string(text='Hello, world!', family='monospace', size=144.0, dpi=96.0):
    from tempfile import NamedTemporaryFile
    from kitty.fast_data_types import concat_cells, set_send_sprite_to_gpu, Screen, sprite_map_set_limits, test_render_line
    from kitty.icat import detect_support, show
    if not detect_support():
        raise SystemExit('Your terminal does not support the graphics protocol')
    sprites = {}

    def send_to_gpu(x, y, z, data):
        sprites[(x, y, z)] = data

    sprite_map_set_limits(100000, 100)
    set_send_sprite_to_gpu(send_to_gpu)
    opts = defaults._replace(font_family=family)
    try:
        cell_width, cell_height = set_font_family(opts, override_dpi=(dpi, dpi), override_font_size=size)
        s = Screen(None, 1, len(text)*2)
        line = s.line(0)
        s.draw(text)
        test_render_line(line)
    finally:
        set_send_sprite_to_gpu(None)
    cells = []
    for i in range(s.columns):
        sp = line.sprite_at(i)
        if sp != (0, 0, 0):
            cells.append(sprites[sp])
    rgb_data = concat_cells(cell_width, cell_height, tuple(cells))
    with NamedTemporaryFile(delete=False) as f:
        f.write(rgb_data)
    print('Rendered string {!r} below: ({}x{})'.format(text, cell_width, cell_height))
    show(f.name, cell_width * len(cells), cell_height, 24)
    print('\n')


def showcase():
    test_render_string(family='Fira Code Medium')
    test_render_string('==A=== -> -->', family='Fira Code Medium')
