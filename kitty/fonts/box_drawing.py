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
        for x in (range(0, width // 2) if which == 'left' else range(width // 2, width)):
            buf[y * width + x] = 255


box_chars = {
    '─': [half_hline, p(half_hline, which='right')],
    '━': [p(half_hline, level=3), p(half_hline, level=3, which='right')],
}


is_renderable_box_char = box_chars.__contains__


def render_box_char(ch, buf, width, height):
    for func in box_chars[ch]:
        func(buf, width, height)
    return buf
