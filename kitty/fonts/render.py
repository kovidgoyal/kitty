#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
from collections import namedtuple
from math import sin, pi, ceil, floor, sqrt

from kitty.constants import isosx
from kitty.utils import get_logical_dpi
from kitty.fast_data_types import set_font, set_font_size
from .box_drawing import render_box_char, is_renderable_box_char
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


FontState = namedtuple('FontState', 'family pt_sz xdpi ydpi cell_width cell_height baseline underline_position underline_thickness')


def get_fallback_font(text, bold, italic):
    state = set_font_family.state
    return create_face(font_for_text(text, state.family, state.pt_sz, state.xdpi, state.ydpi, bold, italic))


def set_font_family(opts, override_font_size=None):
    if hasattr(set_font_family, 'state'):
        raise ValueError('Cannot set font family more than once, use resize_fonts() to change size')
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
    cell_width, cell_height, baseline, underline_position, underline_thickness = set_font(get_fallback_font, sm, sfaces, sz, xdpi, ydpi, *faces)
    set_font_family.state = FontState(opts.font_family, sz, xdpi, ydpi, cell_width, cell_height, baseline, underline_position, underline_thickness)
    return cell_width, cell_height


def resize_fonts(new_sz, xdpi=None, ydpi=None):
    s = set_font_family.state
    xdpi = xdpi or s.xdpi
    ydpi = ydpi or s.ydpi
    cell_width, cell_height, baseline, underline_position, underline_thickness = set_font_size(new_sz, xdpi, ydpi)
    set_font_family.state = FontState(
        s.family, new_sz, xdpi, ydpi, cell_width, cell_height, baseline, underline_position, underline_thickness)


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
        buf[cell_width * y + x] = min(255, buf[cell_width * y + x] + int(255 * (1 - distance)))

    for x_exact in range(cell_width):
        y_exact = yfactor * sin(x_exact * xfactor) + position
        y_below = clamp_y(floor(y_exact))
        y_above = clamp_y(ceil(y_exact))
        x_before, x_after = map(clamp_x, (x_exact - 1, x_exact + 1))
        for x in {x_before, x_exact, x_after}:
            for y in {y_below, y_above}:
                dist = sqrt((x - x_exact)**2 + (y - y_exact)**2) / 2
                add_intensity(x, y, dist)


def render_cell(text=' ', bold=False, italic=False, underline=0, strikethrough=False):
    s = set_font_family.state
    cell_width, cell_height, baseline = s.cell_width, s.cell_height, s.baseline
    underline_thickness, underline_position = s.underline_thickness, s.underline_position
    CharTexture = ctypes.c_ubyte * cell_width * cell_height
    if is_renderable_box_char(text):
        first, second = render_box_char(text, CharTexture(), cell_width, cell_height), None
    else:
        first = CharTexture()
        second = None

    def dl(f, *a):
        f(first, cell_width, *a)
        if second is not None:
            f(second, cell_width, *a)

    if underline:
        t = underline_thickness
        if underline == 2:
            t = max(1, min(cell_height - underline_position - 1, t))
        dl(add_curl if underline == 2 else add_line, underline_position, t, cell_height)
    if strikethrough:
        pos = int(0.65 * baseline)
        dl(add_line, pos, underline_thickness, cell_height)

    return first, second


class Buf:

    def __init__(self, buf):
        self.buf = buf

    def __call__(self):
        return ctypes.addressof(self.buf)


def render_cell_wrapper(text, bold, italic, underline, strikethrough, is_second):
    first, second = render_cell(text, bold, italic, underline, strikethrough)
    ans = second if is_second else first
    ans = ans or render_cell()[0]
    return Buf(ans)


def join_cells(cell_width, cell_height, *cells):
    dstride = len(cells) * cell_width
    ans = (ctypes.c_ubyte * (cell_height * dstride))()
    for r in range(cell_height):
        soff = r * cell_width
        doff = r * dstride
        for cnum, cell in enumerate(cells):
            doff2 = doff + (cnum * cell_width)
            ans[doff2:doff2 + cell_width] = cell[soff:soff + cell_width]
    return ans


def display_bitmap(data, w, h):
    from PIL import Image
    img = Image.new('L', (w, h))
    img.putdata(data)
    img.show()


def render_string(text='\'Qing👁a⧽', underline=2, strikethrough=True):
    import unicodedata
    cells = []
    current_text = ''

    def render_one(c):
        f, s = render_cell(c, underline=underline, strikethrough=strikethrough)
        cells.append(f)
        if s is not None:
            cells.append(s)

    for c in text:
        if unicodedata.combining(c):
            current_text += c
        else:
            if current_text:
                render_one(current_text)
            current_text = c
    if current_text:
        render_one(current_text)
    s = set_font_family.state
    cell_width, cell_height = s.cell_width, s.cell_height
    char_data = join_cells(cell_width, cell_height, *cells)
    return char_data, cell_width * len(cells), cell_height


def test_rendering(text='\'Ping👁a⧽', sz=144, family='monospace', underline=2, strikethrough=True):
    from kitty.config import defaults
    from kitty.fast_data_types import glfw_init, glfw_terminate
    if not glfw_init():
        raise SystemExit('Failed to initialize glfw')
    try:
        opts = defaults._replace(font_family=family, font_size=sz)
        set_font_family(opts)
        display_bitmap(*render_string(text, underline=underline, strikethrough=strikethrough))
    finally:
        glfw_terminate()
