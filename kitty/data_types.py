#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Tuple, Dict, Union

from numpy import zeros, dtype
from PyQt5.QtGui import QColor

color_type = dtype([('type', 'u1'), ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])


class Line:

    __slots__ = 'char fg bg bold italic reverse strikethrough decoration decoration_fg'.split()
    continued = False

    def __init__(self, sz: int):
        self.char = zeros(sz, 'U1')
        self.fg = zeros(sz, color_type)
        self.bg = zeros(sz, color_type)
        self.bold = zeros(sz, bool)
        self.italic = zeros(sz, bool)
        self.reverse = zeros(sz, bool)
        self.strikethrough = zeros(sz, bool)
        self.decoration = zeros(sz, 'u1')
        self.decoration_fg = zeros(sz, color_type)


def as_color(entry: Tuple[int, int, int, int], color_table: Dict[int, QColor]) -> Union[QColor, None]:
    t, r, g, b = entry
    if t == 1:
        return color_table.get(r)
    if t == 2:
        return QColor(r, g, b)
