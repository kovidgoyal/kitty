#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
from math import sin, pi, ceil, floor, sqrt

from kitty.constants import isosx
from .box_drawing import render_box_char, is_renderable_box_char
if isosx:
    from .core_text import set_font_family, render_cell as rc, current_cell  # noqa
else:
    from .freetype import set_font_family, render_cell as rc, current_cell  # noqa


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
    CharTexture, cell_width, cell_height, baseline, underline_thickness, underline_position = current_cell()
    if is_renderable_box_char(text):
        first, second = render_box_char(text, CharTexture(), cell_width, cell_height), None
    else:
        first, second = rc(text, bold, italic)

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


def render_string(text='\'Qing👁a⧽'):
    cells = []
    for c in text:
        f, s = render_cell(c, underline=2, strikethrough=True)
        cells.append(f)
        if s is not None:
            cells.append(s)
    cell_width, cell_height = current_cell()[1:3]
    char_data = join_cells(cell_width, cell_height, *cells)
    return char_data, cell_width * len(cells), cell_height


def test_rendering(text='\'Ping👁a⧽', sz=144, family='monospace'):
    from kitty.config import defaults
    opts = defaults._replace(font_family=family, font_size=sz)
    set_font_family(opts)
    display_bitmap(*render_string(text))
