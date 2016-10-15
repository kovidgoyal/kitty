#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Tuple, Dict, Union, Iterator, Sequence

from numpy import zeros, dtype
from PyQt5.QtGui import QColor

color_type = dtype([('type', 'u1'), ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])


class Line:

    __slots__ = 'char fg bg bold italic reverse strikethrough decoration decoration_fg width'.split()
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
        self.width = zeros(sz, 'u1')

    def __len__(self):
        return len(self.char)

    def copy_char(self, src: int, to, dest: int) -> None:
        to.char[dest] = self.char[src]
        to.fg[dest] = self.fg[src]
        to.bg[dest] = self.bg[src]
        to.bold[dest] = self.bold[src]
        to.italic[dest] = self.italic[src]
        to.reverse[dest] = self.reverse[src]
        to.strikethrough[dest] = self.strikethrough[src]
        to.decoration[dest] = self.decoration[src]
        to.decoration_fg[dest] = self.decoration_fg[src]
        to.width[dest] = self.width[src]

    def __repr__(self) -> str:
        return repr(''.join(self.char))


def as_color(entry: Tuple[int, int, int, int], color_table: Dict[int, QColor]) -> Union[QColor, None]:
    t, r, g, b = entry
    if t == 1:
        return color_table.get(r)
    if t == 2:
        return QColor(r, g, b)


def copy_char(src: Line, dest: Line, src_pos: int, dest_pos: int) -> None:
    for i in range(src.width[src_pos]):
        src.copy_char(src_pos + i, dest, dest_pos + i)


def rewrap_lines(lines: Sequence[Line], width: int) -> Iterator[Line]:
    if lines:
        current_line, current_dest_pos = Line(width), 0
        src_limit = len(lines[0]) - 1
        for i, src in enumerate(lines):
            current_src_pos = 0
            while current_src_pos <= src_limit:
                cw = src.width[current_src_pos]
                if cw == 0:
                    # Hard line break, start a new line
                    yield current_line
                    current_line, current_dest_pos = Line(width), 0
                    break
                if cw + current_dest_pos > width:
                    # dest line does not have enough space to hold the current source char
                    yield current_line
                    current_line, current_dest_pos = Line(width), 0
                    current_line.continued = True
                copy_char(src, current_line, current_src_pos, current_dest_pos)
                current_dest_pos += cw
                current_src_pos += cw
            else:
                hard_break = src is not lines[-1] and not lines[i + 1].continued
                if hard_break:
                    yield current_line
                    current_line, current_dest_pos = Line(width), 0
        if current_dest_pos:
            yield current_line
