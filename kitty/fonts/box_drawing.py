#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import math
from functools import partial as p

from kitty.utils import get_logical_dpi


def thickness(level=1, horizontal=True):
    dpi = get_logical_dpi()[0 if horizontal else 1]
    pts = (1, 1, 2, 4)[level]
    return int(math.ceil(pts * dpi / 72.0))


def half_hline(buf, width, height, level=1, which='left'):
    sz = thickness(level=level, horizontal=True)
    start = height // 2 - sz // 2
    for y in range(start, start + sz):
        offset = y * width
        for x in (range(0, width // 2) if which == 'left' else range(width // 2, width)):
            buf[offset + x] = 255


def half_vline(buf, width, height, level=1, which='top'):
    sz = thickness(level=level, horizontal=False)
    start = width // 2 - sz // 2
    for x in range(start, start + sz):
        for y in (range(0, height // 2) if which == 'top' else range(height // 2, height)):
            buf[x + y * width] = 255


def get_holes(sz, hole_sz, num):
    if num == 1:
        pts = [sz // 2]
    elif num == 2:
        pts = (sz // 3, 2 * (sz // 3))
    elif num == 3:
        pts = (sz // 4, sz // 2, 3 * (sz // 4))
    holes = []
    for c in pts:
        holes.append(tuple(range(c - hole_sz // 2, c - hole_sz // 2 + hole_sz)))
    return holes


def add_hholes(buf, width, height, level=1, num=1, hole_sz=3):
    line_sz = thickness(level=level, horizontal=True)
    hole_sz = thickness(level=hole_sz, horizontal=False)
    start = height // 2 - line_sz // 2
    holes = get_holes(width, hole_sz, num)
    for y in range(start, start + line_sz):
        offset = y * width
        for hole in holes:
            for x in hole:
                buf[offset + x] = 0


def add_vholes(buf, width, height, level=1, num=1, hole_sz=3):
    line_sz = thickness(level=level, horizontal=False)
    hole_sz = thickness(level=hole_sz, horizontal=True)
    start = width // 2 - line_sz // 2
    holes = get_holes(height, hole_sz, num)
    for x in range(start, start + line_sz):
        for hole in holes:
            for y in hole:
                buf[x + width * y] = 0


def hline(*a, level=1):
    half_hline(*a, level=level)
    half_hline(*a, level=level, which='right')


def vline(*a, level=1):
    half_vline(*a, level=level)
    half_vline(*a, level=level, which='bottom')


def hholes(*a, level=2, num=1):
    hline(*a, level=level)
    add_hholes(*a, level=level, num=num)


def vholes(*a, level=1, num=1):
    vline(*a, level=level)
    add_vholes(*a, level=level, num=num)


def corner(*a, hlevel=1, vlevel=1, which=None):
    wh = 'right' if which in '┌└' else 'left'
    half_hline(*a, level=hlevel, which=wh)
    wv = 'top' if which in '└┘' else 'bottom'
    half_vline(*a, level=vlevel, which=wv)


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
    '┌': [p(corner, '┌')],
}

for start in '┌┐└┘':
    for i, (hlevel, vlevel) in enumerate(((1, 1), (3, 2), (2, 3), (3, 3))):
        box_chars[chr(ord(start) + i)] = [p(corner, which=start, hlevel=hlevel, vlevel=vlevel)]

is_renderable_box_char = box_chars.__contains__


def render_box_char(ch, buf, width, height):
    for func in box_chars[ch]:
        func(buf, width, height)
    return buf
