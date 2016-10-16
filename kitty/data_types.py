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
            array.array(code, repeat(32, sz)),
        )
    return get_zeroes.ans
get_zeroes.current_size = None


class Cursor:

    __slots__ = ("x", "y", "hidden", 'fg', 'bg', 'bold', 'italic', 'reverse', 'strikethrough', 'decoration', 'decoration_fg')

    def __init__(self, x: int=0, y: int=0):
        self.x = x
        self.y = y
        self.hidden = False
        self.fg = self.bg = self.decoration_fg = 0
        self.bold = self.italic = self.reverse = self.strikethrough = False
        self.decoration = 0

    def copy(self):
        ans = Cursor(self.x, self.y)
        ans.hidden = self.hidden
        ans.fg, ans.bg, ans.decoration_fg = self.fg, self.bg, self.decoration_fg
        ans.bold, ans.italic, ans.reverse, ans.strikethrough = self.bold, self.italic, self.reverse, self.strikethrough
        return ans


class Line:

    __slots__ = 'char fg bg bold italic reverse strikethrough decoration decoration_fg width continued'.split()

    def __init__(self, sz: int, other=None):
        if other is None:
            z1, z4, spaces = get_zeroes(sz)
            self.char = spaces[:]
            self.fg = z4[:]
            self.bg = z4[:]
            self.bold = z1[:]
            self.italic = z1[:]
            self.reverse = z1[:]
            self.strikethrough = z1[:]
            self.decoration = z1[:]
            self.decoration_fg = z4[:]
            self.width = z1[:]
            self.continued = False
        else:
            self.char = other.char[:]
            self.fg = other.fg[:]
            self.bg = other.bg[:]
            self.bold = other.bold[:]
            self.italic = other.italic[:]
            self.reverse = other.reverse[:]
            self.strikethrough = other.strikethrough[:]
            self.decoration = other.decoration[:]
            self.decoration_fg = other.decoration_fg[:]
            self.width = other.width[:]
            self.continued = other.continued

    def __eq__(self, other):
        if not isinstance(other, Line):
            return False
        for x in self.__slots__:
            if getattr(self, x) != getattr(other, x):
                return False
        return self.continued == other.continued

    def __ne__(self, other):
        return not self.__eq__(other)

    def __len__(self):
        return len(self.char)

    def copy(self):
        return Line(len(self.char), self)

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

    def apply_cursor(self, c: Cursor, at: int=0, num: int=1, clear_char=False, char=' ') -> None:
        if num < 2:
            self.fg[at] = c.fg
            self.bg[at] = c.bg
            self.bold[at] = c.bold
            self.italic[at] = c.italic
            self.reverse[at] = c.reverse
            self.strikethrough[at] = c.strikethrough
            self.decoration[at] = c.decoration
            self.decoration_fg[at] = c.decoration_fg
            if clear_char:
                self.width[at], self.char[at] = 1, ord(char)
        else:
            num = min(len(self) - at, num)
            at = slice(at, at + num)
            self.fg[at] = repeat(c.fg, num)
            self.bg[at] = repeat(c.bg, num)
            self.bold[at] = repeat(c.bold, num)
            self.italic[at] = repeat(c.italic, num)
            self.reverse[at] = repeat(c.reverse, num)
            self.strikethrough[at] = repeat(c.strikethrough, num)
            self.decoration[at] = repeat(c.decoration, num)
            self.decoration_fg[at] = repeat(c.decoration_fg, num)
            if clear_char:
                self.width[at], self.char[at] = repeat(1, num), repeat(ord(char), num)

    def copy_slice(self, src, dest, num):
        src, dest = slice(src, src + num), slice(dest, dest + num)
        for a in (self.char, self.fg, self.bg, self.bold, self.italic, self.reverse, self.strikethrough, self.decoration, self.decoration_fg, self.width):
            a[dest] = a[src]

    def right_shift(self, at: int, num: int) -> None:
        src_start, dest_start = at, at + num
        ls = len(self)
        dnum = min(ls - dest_start, ls)
        if dnum:
            self.copy_slice(src_start, dest_start, dnum)

    def left_shift(self, at: int, num: int) -> None:
        src_start, dest_start = at + num, at
        ls = len(self)
        snum = min(ls - src_start, ls)
        if snum:
            self.copy_slice(src_start, dest_start, snum)

    def __str__(self) -> str:
        return ''.join(map(chr, filter(None, self.char)))

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
