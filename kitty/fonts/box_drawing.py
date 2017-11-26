#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import math
from functools import partial as p
from itertools import repeat

from kitty.utils import get_logical_dpi


def thickness(level=0, horizontal=True):
    dpi = get_logical_dpi()[0 if horizontal else 1]
    pts = (0.001, 1, 1.5, 2)[level]
    return int(math.ceil(pts * dpi / 72.0))


def draw_hline(buf, width, x1, x2, y, level):
    ' Draw a horizontal line between [x1, x2) centered at y with the thickness given by level '
    sz = thickness(level=level, horizontal=False)
    start = y - sz // 2
    for y in range(start, start + sz):
        offset = y * width
        for x in range(x1, x2):
            buf[offset + x] = 255


def draw_vline(buf, width, y1, y2, x, level):
    ' Draw a vertical line between [y1, y2) centered at x with the thickness given by level '
    sz = thickness(level=level, horizontal=True)
    start = x - sz // 2
    for x in range(start, start + sz):
        for y in range(y1, y2):
            buf[x + y * width] = 255


def half_hline(buf, width, height, level=0, which='left', extend_by=0):
    x1, x2 = (0, extend_by + width // 2) if which == 'left' else (width // 2 - extend_by, width)
    draw_hline(buf, width, x1, x2, height // 2, level)


def half_vline(buf, width, height, level=0, which='top', extend_by=0):
    y1, y2 = (0, height // 2 + extend_by) if which == 'top' else (height // 2 - extend_by, height)
    draw_vline(buf, width, y1, y2, width // 2, level)


def get_holes(sz, hole_sz, num):
    if num == 1:
        pts = [sz // 2]
    elif num == 2:
        ssz = (sz - 2 * hole_sz) // 3
        pts = (ssz + hole_sz // 2, 2 * ssz + hole_sz // 2 + hole_sz)
    elif num == 3:
        ssz = (sz - 3 * hole_sz) // 4
        pts = (ssz + hole_sz // 2, 2 * ssz + hole_sz // 2 + hole_sz, 3 * ssz + 2 * hole_sz + hole_sz // 2)
    holes = []
    for c in pts:
        holes.append(tuple(range(c - hole_sz // 2, c - hole_sz // 2 + hole_sz)))
    return holes


hole_factor = 8


def add_hholes(buf, width, height, level=0, num=1):
    line_sz = thickness(level=level, horizontal=True)
    hole_sz = width // hole_factor
    start = height // 2 - line_sz // 2
    holes = get_holes(width, hole_sz, num)
    for y in range(start, start + line_sz):
        offset = y * width
        for hole in holes:
            for x in hole:
                buf[offset + x] = 0


def add_vholes(buf, width, height, level=0, num=1):
    line_sz = thickness(level=level, horizontal=False)
    hole_sz = height // hole_factor
    start = width // 2 - line_sz // 2
    holes = get_holes(height, hole_sz, num)
    for x in range(start, start + line_sz):
        for hole in holes:
            for y in hole:
                buf[x + width * y] = 0


def hline(*a, level=0):
    half_hline(*a, level=level)
    half_hline(*a, level=level, which='right')


def vline(*a, level=0):
    half_vline(*a, level=level)
    half_vline(*a, level=level, which='bottom')


def hholes(*a, level=0, num=1):
    hline(*a, level=level)
    add_hholes(*a, level=level, num=num)


def vholes(*a, level=0, num=1):
    vline(*a, level=level)
    add_vholes(*a, level=level, num=num)


def corner(*a, hlevel=0, vlevel=0, which=None):
    wh = 'right' if which in '┌└' else 'left'
    half_hline(*a, level=hlevel, which=wh, extend_by=thickness(vlevel, horizontal=True) // 2)
    wv = 'top' if which in '└┘' else 'bottom'
    half_vline(*a, level=vlevel, which=wv)


def vert_t(*args, a=1, b=1, c=1, which=None):
    half_vline(*args, level=a, which='top')
    half_hline(*args, level=b, which='left' if which == '┤' else 'right')
    half_vline(*args, level=c, which='bottom')


def horz_t(*args, a=1, b=1, c=1, which=None):
    half_hline(*args, level=a, which='left')
    half_hline(*args, level=b, which='right')
    half_vline(*args, level=c, which='top' if which == '┴' else 'bottom')


def cross(*s, a=1, b=1, c=1, d=1):
    half_hline(*s, level=a)
    half_hline(*s, level=b, which='right')
    half_vline(*s, level=c)
    half_vline(*s, level=d, which='bottom')


def line_equation(x1, y1, x2, y2):
    m = (y2 - y1) / (x2 - x1)
    c = y1 - m * x1

    def y(x):
        return m * x + c

    return y


def triangle(buf, width, height, left=True):
    ay1, by1, y2 = 0, height - 1, height // 2
    if left:
        x1, x2 = 0, width - 1
    else:
        x1, x2 = width - 1, 0
    uppery = line_equation(x1, ay1, x2, y2)
    lowery = line_equation(x1, by1, x2, y2)
    xlimits = [(uppery(x), lowery(x)) for x in range(width)]
    for y in range(height):
        offset = y * width
        for x, (upper, lower) in zip(range(width), xlimits):
            buf[x + offset] = 255 if upper <= y <= lower else 0
    # Anti-alias the diagonals, simple y-axis anti-aliasing
    for x in range(width):
        for y in xlimits[x]:
            for ypx in range(int(math.floor(y)), int(math.ceil(y)) + 1):
                if 0 <= ypx < height:
                    off = ypx * width + x
                    buf[off] = min(255, buf[off] + int((1 - abs(y - ypx)) * 255))


def half_dhline(buf, width, height, level=0, which='left', only=None):
    x1, x2 = (0, width // 2) if which == 'left' else (width // 2, width)
    gap = thickness(level + 1, horizontal=False)
    if only != 'bottom':
        draw_hline(buf, width, x1, x2, height // 2 - gap, level)
    if only != 'top':
        draw_hline(buf, width, x1, x2, height // 2 + gap, level)
    return height // 2 - gap, height // 2 + gap


def half_dvline(buf, width, height, level=0, which='top', only=None):
    y1, y2 = (0, height // 2) if which == 'top' else (height // 2, height)
    gap = thickness(level + 1, horizontal=True)
    if only != 'right':
        draw_vline(buf, width, y1, y2, width // 2 - gap, level)
    if only != 'left':
        draw_vline(buf, width, y1, y2, width // 2 + gap, level)
    return width // 2 - gap, width // 2 + gap


def dvline(*s, only=None, level=0):
    half_dvline(*s, only=only, level=level)
    return half_dvline(*s, only=only, which='bottom', level=level)


def dhline(*s, only=None, level=0):
    half_dhline(*s, only=only, level=level)
    return half_dhline(*s, only=only, which='bottom', level=level)


def dvcorner(*s, level=0, which='╒'):
    hw = 'right' if which in '╒╘' else 'left'
    half_dhline(*s, which=hw)
    vw = 'top' if which in '╘╛' else 'bottom'
    gap = thickness(level + 1, horizontal=False)
    half_vline(*s, which=vw, extend_by=gap // 2 + thickness(level, horizontal=False))


def dhcorner(*s, level=0, which='╓'):
    vw = 'top' if which in '╙╜' else 'bottom'
    half_dvline(*s, which=vw)
    hw = 'right' if which in '╓╙' else 'left'
    gap = thickness(level + 1, horizontal=True)
    half_hline(*s, which=hw, extend_by=gap // 2 + thickness(level, horizontal=True))


def dcorner(buf, width, height, level=0, which='╔'):
    hw = 'right' if which in '╔╚' else 'left'
    vw = 'top' if which in '╚╝' else 'bottom'
    hgap = thickness(level + 1, horizontal=False)
    vgap = thickness(level + 1, horizontal=True)
    x1, x2 = (0, width // 2) if hw == 'left' else (width // 2, width)
    ydelta = hgap if vw == 'top' else -hgap
    if hw == 'left':
        x2 += vgap
    else:
        x1 -= vgap
    draw_hline(buf, width, x1, x2, height // 2 + ydelta, level)
    if hw == 'left':
        x2 -= 2 * vgap
    else:
        x1 += 2 * vgap
    draw_hline(buf, width, x1, x2, height // 2 - ydelta, level)
    y1, y2 = (0, height // 2) if vw == 'top' else (height // 2, height)
    xdelta = vgap if hw == 'right' else -vgap
    yd = thickness(level, horizontal=True) // 2
    if vw == 'top':
        y2 += hgap + yd
    else:
        y1 -= hgap + yd
    draw_vline(buf, width, y1, y2, width // 2 - xdelta, level)
    if vw == 'top':
        y2 -= 2 * hgap
    else:
        y1 += 2 * hgap
    draw_vline(buf, width, y1, y2, width // 2 + xdelta, level)


def dpip(*a, level=0, which='╟'):
    if which in '╟╢':
        left, right = dvline(*a)
        x1, x2 = (0, left) if which == '╢' else (right, a[1])
        draw_hline(a[0], a[1], x1, x2, a[2] // 2, level)
    else:
        top, bottom = dhline(*a)
        y1, y2 = (0, top) if which == '╧' else (bottom, a[2])
        draw_vline(a[0], a[1], y1, y2, a[1] // 2, level)


def inner_corner(buf, width, height, which='tl', level=0):
    hgap = thickness(level + 1, horizontal=True)
    vgap = thickness(level + 1, horizontal=False)
    vthick = thickness(level, horizontal=True) // 2
    x1, x2 = (0, width // 2 - hgap + vthick + 1) if 'l' in which else (width // 2 + hgap - vthick, width)
    yd = -1 if 't' in which else 1
    draw_hline(buf, width, x1, x2, height // 2 + (yd * vgap), level)
    y1, y2 = (0, height // 2 - vgap) if 't' in which else (height // 2 + vgap, height)
    xd = -1 if 'l' in which else 1
    draw_vline(buf, width, y1, y2, width // 2 + (xd * hgap), level)


box_chars = {
    '─': [hline],
    '━': [p(hline, level=3)],
    '│': [vline],
    '┃': [p(vline, level=3)],
    '╌': [hholes],
    '╍': [p(hholes, level=3)],
    '┄': [p(hholes, num=2)],
    '┅': [p(hholes, num=2, level=3)],
    '┈': [p(hholes, num=3)],
    '┉': [p(hholes, num=3, level=3)],
    '╎': [vholes],
    '╏': [p(vholes, level=3)],
    '┆': [p(vholes, num=2)],
    '┇': [p(vholes, num=2, level=3)],
    '┊': [p(vholes, num=3)],
    '┋': [p(vholes, num=3, level=3)],
    '╴': [half_hline],
    '╵': [half_vline],
    '╶': [p(half_hline, which='right')],
    '╷': [p(half_vline, which='bottom')],
    '╸': [p(half_hline, level=3)],
    '╹': [p(half_vline, level=3)],
    '╺': [p(half_hline, which='right', level=3)],
    '╻': [p(half_vline, which='bottom', level=3)],
    '╼': [half_hline, p(half_hline, level=3, which='right')],
    '╽': [half_vline, p(half_vline, level=3, which='bottom')],
    '╾': [p(half_hline, level=3), p(half_hline, which='right')],
    '╿': [p(half_vline, level=3), p(half_vline, which='bottom')],
    '': [triangle],
    '': [p(triangle, left=False)],
    '═': [dhline],
    '║': [dvline],
    '╞': [vline, p(half_dhline, which='right')],
    '╡': [vline, half_dhline],
    '╥': [hline, p(half_dvline, which='bottom')],
    '╨': [hline, half_dvline],
    '╪': [vline, half_dhline, p(half_dhline, which='right')],
    '╫': [hline, half_dvline, p(half_dvline, which='bottom')],
    '╬': [p(inner_corner, which=x) for x in 'tl tr bl br'.split()],
    '╠': [p(inner_corner, which='tr'), p(inner_corner, which='br'), p(dvline, only='left')],
    '╣': [p(inner_corner, which='tl'), p(inner_corner, which='bl'), p(dvline, only='right')],
    '╦': [p(inner_corner, which='bl'), p(inner_corner, which='br'), p(dhline, only='top')],
    '╩': [p(inner_corner, which='tl'), p(inner_corner, which='tr'), p(dhline, only='bottom')],
}

t, f = 0, 3
for start in '┌┐└┘':
    for i, (hlevel, vlevel) in enumerate(((t, t), (f, t), (t, f), (f, f))):
        box_chars[chr(ord(start) + i)] = [p(corner, which=start, hlevel=hlevel, vlevel=vlevel)]
for ch, c in zip('╭╮╯╰', '┌┐┘└'):
    box_chars[ch] = [p(corner, which=c)]  # TODO: Make these rounded

for i, (a, b, c, d) in enumerate((
        (t, t, t, t), (f, t, t, t), (t, f, t, t), (f, f, t, t), (t, t, f, t), (t, t, t, f), (t, t, f, f),
        (f, t, f, t), (t, f, f, t), (f, t, t, f), (t, f, t, f), (f, f, f, t), (f, f, t, f), (f, t, f, f),
        (t, f, f, f), (f, f, f, f)
)):
    box_chars[chr(ord('┼') + i)] = [p(cross, a=a, b=b, c=c, d=d)]

for starts, func, pattern in (
        ('├┤', vert_t, ((t, t, t), (t, f, t), (f, t, t), (t, t, f), (f, t, f), (f, f, t), (t, f, f), (f, f, f))),
        ('┬┴', horz_t, ((t, t, t), (f, t, t), (t, f, t), (f, f, t), (t, t, f), (f, t, f), (t, f, f), (f, f, f))),
):
    for start in starts:
        for i, (a, b, c) in enumerate(pattern):
            box_chars[chr(ord(start) + i)] = [p(func, which=start, a=a, b=b, c=c)]

for chars, func in (('╒╕╘╛', dvcorner), ('╓╖╙╜', dhcorner), ('╔╗╚╝', dcorner), ('╟╢╤╧', dpip)):
    for ch in chars:
        box_chars[ch] = [p(func, which=ch)]

is_renderable_box_char = box_chars.__contains__


def render_box_char(ch, buf, width, height):
    for func in box_chars[ch]:
        func(buf, width, height)
    return buf


def render_missing_glyph(buf, width, height):
    hgap = thickness(level=0, horizontal=True) + 1
    vgap = thickness(level=0, horizontal=False) + 1
    draw_hline(buf, width, hgap, width - hgap + 1, vgap, 0)
    draw_hline(buf, width, hgap, width - hgap + 1, height - vgap, 0)
    draw_vline(buf, width, vgap, height - vgap + 1, hgap, 0)
    draw_vline(buf, width, vgap, height - vgap + 1, width - hgap, 0)


def join_rows(width, height, rows):
    import ctypes
    ans = (ctypes.c_ubyte * (width * height * len(rows)))()
    pos = ctypes.addressof(ans)
    row_sz = width * height
    for row in rows:
        ctypes.memmove(pos, ctypes.addressof(row), row_sz)
        pos += row_sz
    return ans


def test_drawing(sz=32, family='monospace'):
    from .render import join_cells, display_bitmap, render_cell, set_font_family
    from kitty.config import defaults
    opts = defaults._replace(font_family=family, font_size=sz)
    width, height = set_font_family(opts)
    pos = 0x2500
    rows = []
    space = render_cell()[0]
    space_row = join_cells(width, height, *repeat(space, 32))

    for r in range(8):
        row = []
        for i in range(16):
            row.append(render_cell(chr(pos))[0]), row.append(space)
            pos += 1
        rows.append(join_cells(width, height, *row))
        rows.append(space_row)
    width *= 32
    im = join_rows(width, height, rows)
    display_bitmap(im, width, height * len(rows))
