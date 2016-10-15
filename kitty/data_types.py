#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import array
from typing import Tuple, Dict, Union, Iterator, Sequence
from itertools import repeat

from PyQt5.QtGui import QColor

code = 'I' if array.array('I').itemsize >= 4 else 'L'


def get_zeroes(sz: int) -> Tuple[array.array]:
    if get_zeroes.current_size != sz:
        get_zeroes.current_size = sz
        get_zeroes.ans = (
            array.array('B', repeat(0, sz)),
            array.array(code, repeat(0, sz)),
        )
    return get_zeroes.ans
get_zeroes.current_size = None


class Line:

    __slots__ = 'char fg bg bold italic reverse strikethrough decoration decoration_fg width'.split()
    continued = False

    def __init__(self, sz: int):
        z1, z4 = get_zeroes(sz)
        self.char = z4[:]
        self.fg = z4[:]
        self.bg = z4[:]
        self.bold = z1[:]
        self.italic = z1[:]
        self.reverse = z1[:]
        self.strikethrough = z1[:]
        self.decoration = z1[:]
        self.decoration_fg = z4[:]
        self.width = z1[:]

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

    def __str__(self) -> str:
        return ''.join(map(ord, self.char)).rstrip('\0')

    def __repr__(self) -> str:
        return repr(str(self))


def as_color(entry: int, color_table: Dict[int, QColor]) -> Union[QColor, None]:
    t = entry & 0xff
    if t == 1:
        r = (entry >> 8) & 0xff
        return color_table.get(r)
    if t == 2:
        r = (entry >> 8) & 0xff
        g = (entry >> 16) & 0xff
        b = (entry >> 24) & 0xff
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
