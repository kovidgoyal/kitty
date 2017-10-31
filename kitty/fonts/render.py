#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
from collections import namedtuple
from math import ceil, floor, pi, sin, sqrt

from kitty.constants import isosx
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
            o = create_face(font_for_family(family))
            family_map[family] = len(faces)
            faces.append(o)
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


def set_font_family(opts, override_font_size=None):
    if hasattr(set_font_family, 'state'):
        raise ValueError(
            'Cannot set font family more than once, use resize_fonts() to change size'
        )
    sz = override_font_size or opts.font_size
    xdpi, ydpi = get_logical_dpi()
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
    CharTexture = ctypes.c_ubyte * cell_width * cell_height
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
    CharTexture = ctypes.c_ubyte * cell_width * cell_height
    buf = render_box_char(
        chr(codepoint), CharTexture(), cell_width, cell_height
    )
    return ctypes.addressof(buf), buf
