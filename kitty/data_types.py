#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import array
from typing import Tuple, Dict, Union, Iterator, Sequence
from itertools import repeat

from pyte.graphics import FG_BG_256
from .config import fg_color_table, bg_color_table

code = 'I' if array.array('I').itemsize >= 4 else 'L'
lcode = 'L' if array.array('L').itemsize >= 8 else 'Q'


def get_zeroes(sz: int) -> Tuple[array.array]:
    if get_zeroes.current_size != sz:
        get_zeroes.current_size = sz
        get_zeroes.ans = (
            array.array(lcode, repeat(0, sz)),
            array.array(code, repeat(0, sz)),
            array.array(code, repeat(32, sz)),
        )
    return get_zeroes.ans
get_zeroes.current_size = None


class Cursor:

    __slots__ = ("x", "y", 'shape', 'blink', "hidden", 'fg', 'bg', 'bold', 'italic', 'reverse', 'strikethrough', 'decoration', 'decoration_fg',)

    def __init__(self, x: int=0, y: int=0):
        self.x = x
        self.y = y
        self.hidden = False
        self.shape = None
        self.blink = None
        self.reset_display_attrs()

    def reset_display_attrs(self):
        self.fg = self.bg = self.decoration_fg = 0
        self.bold = self.italic = self.reverse = self.strikethrough = False
        self.decoration = 0

    def copy(self):
        ans = Cursor(self.x, self.y)
        ans.hidden = self.hidden
        ans.fg, ans.bg, ans.decoration_fg = self.fg, self.bg, self.decoration_fg
        ans.bold, ans.italic, ans.reverse, ans.strikethrough = self.bold, self.italic, self.reverse, self.strikethrough
        ans.decoration = self.decoration
        return ans

    def __eq__(self, other):
        if not isinstance(other, Cursor):
            return False
        for x in self.__slots__:
            if getattr(self, x) != getattr(other, x):
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return self.__class__.__name__ + '({})'.format(', '.join(
            '{}={}'.format(x, getattr(self, x)) for x in self.__slots__))

    def colors(self):
        return as_color(self.fg, fg_color_table()), as_color(self.bg, bg_color_table()), as_color(self.decoration_fg, fg_color_table())

CHAR_MASK = 0xFFFFFF
ATTRS_SHIFT = 24
WIDTH_MASK = 0xFF
DECORATION_SHIFT = 2
BOLD_SHIFT, ITALIC_SHIFT, REVERSE_SHIFT, STRIKE_SHIFT = range(DECORATION_SHIFT + 2, DECORATION_SHIFT + 6)
DECORATION_MASK = 1 << DECORATION_SHIFT
BOLD_MASK = 1 << BOLD_SHIFT
ITALIC_MASK = 1 << ITALIC_SHIFT
REVERSE_MASK = 1 << REVERSE_SHIFT
STRIKE_MASK = 1 << STRIKE_SHIFT
COL_MASK = 0xFFFFFFFF
COL_SHIFT = 32
HAS_BG_MASK = 0xFF << COL_SHIFT


class Line:

    __slots__ = 'char color decoration_fg continued combining_chars'.split()

    def __init__(self, sz: int, other=None):
        if other is None:
            z8, z4, spaces = get_zeroes(sz)
            self.char = spaces[:]
            self.color = z8[:]
            self.decoration_fg = z4[:]
            self.continued = False
            self.combining_chars = {}
        else:
            self.char = other.char[:]
            self.color = other.color[:]
            self.decoration_fg = other.decoration_fg[:]
            self.continued = other.continued
            self.combining_chars = other.combining_chars.copy()

    # Read API {{{

    def __eq__(self, other):
        if not isinstance(other, Line):
            return False
        for x in self.__slots__:
            if getattr(self, x) != getattr(other, x):
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __len__(self):
        return len(self.char)

    def copy(self):
        return Line(len(self.char), self)

    def cursor_to_attrs(self, c: Cursor) -> int:
        return ((c.decoration & 0b11) << DECORATION_SHIFT) | ((c.bold & 0b1) << BOLD_SHIFT) | \
            ((c.italic & 0b1) << ITALIC_SHIFT) | ((c.reverse & 0b1) << REVERSE_SHIFT) | ((c.strikethrough & 0b1) << STRIKE_SHIFT)

    def cursor_from(self, x: int, ypos: int=0) -> Cursor:
        c = Cursor(x, ypos)
        c.decoration_fg = self.decoration_fg[x]
        col = self.color[x]
        c.fg = col & COL_MASK
        c.bg = col >> COL_SHIFT
        attrs = self.char[x] >> ATTRS_SHIFT
        c.decoration = (attrs >> DECORATION_SHIFT) & 0b11
        c.bold = bool((attrs >> BOLD_SHIFT) & 0b1)
        c.italic = bool((attrs >> ITALIC_SHIFT) & 0b1)
        c.reverse = bool((attrs >> REVERSE_SHIFT) & 0b1)
        c.strikethrough = bool((attrs >> STRIKE_SHIFT) & 0b1)
        return c

    def basic_cell_data(self, pos: int):
        c = self.char[pos]
        cols = self.color[pos]
        return c & CHAR_MASK, c >> ATTRS_SHIFT, cols

    def __iter__(self):
        for i in range(len(self)):
            yield self.text_at(i)

    def __str__(self) -> str:
        return ''.join(self)

    def __repr__(self) -> str:
        return repr(str(self))

    def width(self, i):
        return (self.char[i] >> ATTRS_SHIFT) & 0b11

    def text_at(self, i):
        ch = self.char[i] & CHAR_MASK
        if ch:
            ans = chr(ch)
            cc = self.combining_chars.get(i)
            if cc is not None:
                ans += cc
            return ans
        return ''
    # }}}

    # Write API {{{

    def copy_char(self, src: int, to, dest: int) -> None:
        to.char[dest] = self.char[src]
        to.color[dest] = self.color[src]
        to.decoration_fg[dest] = self.decoration_fg[src]
        to.combining_chars.pop(dest, None)
        cc = self.combining_chars.get(src)
        if cc is not None:
            to.combining_chars[dest] = cc

    def set_text(self, text: str, offset_in_text: int, sz: int, cursor: Cursor) -> None:
        ' Set the specified text in this line, with attributes taken from the cursor '
        attrs = self.cursor_to_attrs(cursor) | 1
        fg, bg, dfg = cursor.fg, cursor.bg, cursor.decoration_fg
        col = (fg & COL_MASK) | ((bg & COL_MASK) << COL_SHIFT)
        dx = cursor.x
        for cpos in range(offset_in_text, offset_in_text + sz):
            ch = ord(text[cpos]) & CHAR_MASK
            self.char[dx] = ch | (attrs << ATTRS_SHIFT)
            self.color[dx], self.decoration_fg[dx] = col, dfg
            dx += 1
        if self.combining_chars:
            for i in range(cursor.x, cursor.x + sz):
                self.combining_chars.pop(i, None)

    def clear_text(self, start, num, clear_char=' '):
        ' Clear the text in the specified range, preserving existing attributes '
        ch = ord(clear_char) & CHAR_MASK
        for i in range(start, min(len(self), start + num)):
            self.char[i] = (self.char[i] & ~CHAR_MASK) | ch

    def copy_slice(self, src, dest, num):
        if self.combining_chars:
            scc = self.combining_chars.copy()
            for i in range(num):
                cc = scc.get(src + i)
                if cc is None:
                    self.combining_chars.pop(dest + i, None)
                else:
                    self.combining_chars[dest + i] = cc
        src, dest = slice(src, src + num), slice(dest, dest + num)
        for a in (self.char, self.color, self.decoration_fg):
            a[dest] = a[src]

    def right_shift(self, at: int, num: int) -> None:
        src_start, dest_start = at, at + num
        ls = len(self)
        dnum = min(ls - dest_start, ls)
        if dnum:
            self.copy_slice(src_start, dest_start, dnum)
            # Check if a wide character was split at the right edge
            w = (self.char[-1] >> ATTRS_SHIFT) & 0b11
            if w != 1:
                self.char[-1] = (w << ATTRS_SHIFT) | ord(' ')

    def left_shift(self, at: int, num: int) -> None:
        src_start, dest_start = at + num, at
        ls = len(self)
        snum = min(ls - src_start, ls)
        if snum:
            self.copy_slice(src_start, dest_start, snum)

    def apply_cursor_fast(self, ch, col, dfg, at, num):
        for i in range(at, min(len(self), at + num)):
            self.color[i], self.decoration_fg[i], self.char[i] = col, dfg, ch

    def apply_cursor(self, c: Cursor, at: int=0, num: int=1, clear_char=False, char=' ') -> None:
        col = ((c.bg & COL_MASK) << COL_SHIFT) | (c.fg & COL_MASK)
        dfg = c.decoration_fg
        s, e = at, min(len(self), at + num)
        chara, color, dfga = self.char, self.color, self.decoration_fg
        cattrs = self.cursor_to_attrs(c)
        if clear_char:
            ch = (ord(char) & CHAR_MASK) | ((cattrs | 1) << ATTRS_SHIFT)
            for i in range(s, e):
                chara[i] = ch
                color[i] = col
                dfga[i] = dfg
            if self.combining_chars:
                if e - s >= len(self):
                    self.combining_chars.clear()
                else:
                    for i in range(s, e):
                        self.combining_chars.pop(i, None)
        else:
            for i in range(s, e):
                color[i] = col
                dfga[i] = dfg
                sc = chara[i]
                sattrs = sc >> ATTRS_SHIFT
                w = sattrs & WIDTH_MASK
                attrs = w | cattrs
                chara[i] = (sc & CHAR_MASK) | (attrs << ATTRS_SHIFT)

    def set_char(self, i: int, ch: str, width: int=1, cursor: Cursor=None) -> None:
        if cursor is None:
            c = self.char[i]
            a = (c >> ATTRS_SHIFT) & ~WIDTH_MASK
        else:
            a = self.cursor_to_attrs(cursor)
            col = (cursor.fg & COL_MASK) | ((cursor.bg & COL_MASK) << COL_SHIFT)
            self.color[i], self.decoration_fg[i] = col, cursor.decoration_fg
        a |= width & WIDTH_MASK
        self.char[i] = (a << ATTRS_SHIFT) | (ord(ch) & CHAR_MASK)
        self.combining_chars.pop(i, None)

    def add_combining_char(self, i: int, ch: str):
        # TODO: Handle the case when i is the second cell of a double-width char
        self.combining_chars[i] = self.combining_chars.get(i, '') + ch

    def set_bold(self, i, val):
        c = self.char[i]
        a = c >> ATTRS_SHIFT
        a = (a & ~BOLD_MASK) | ((val & 0b1) << BOLD_SHIFT)
        self.char[i] = (a << ATTRS_SHIFT) | (c & CHAR_MASK)

    def set_italic(self, i, val):
        c = self.char[i]
        a = c >> ATTRS_SHIFT
        a = (a & ~ITALIC_MASK) | ((val & 0b1) << ITALIC_SHIFT)
        self.char[i] = (a << ATTRS_SHIFT) | (c & CHAR_MASK)

    def set_reverse(self, i, val):
        c = self.char[i]
        a = c >> ATTRS_SHIFT
        a = (a & ~REVERSE_MASK) | ((val & 0b1) << REVERSE_SHIFT)
        self.char[i] = (a << ATTRS_SHIFT) | (c & CHAR_MASK)

    def set_strikethrough(self, i, val):
        c = self.char[i]
        a = c >> ATTRS_SHIFT
        a = (a & ~STRIKE_MASK) | ((val & 0b1) << STRIKE_SHIFT)
        self.char[i] = (a << ATTRS_SHIFT) | (c & CHAR_MASK)

    def set_decoration(self, i, val):
        c = self.char[i]
        a = c >> ATTRS_SHIFT
        a = (a & ~DECORATION_MASK) | ((val & 0b11) << DECORATION_SHIFT)
        self.char[i] = (a << ATTRS_SHIFT) | (c & CHAR_MASK)
    # }}}


def as_color(entry: int, color_table: Dict[int, Tuple[int]]) -> Union[Tuple[int], None]:
    t = entry & 0xff
    if t == 1:
        r = (entry >> 8) & 0xff
        return color_table.get(r)
    if t == 2:
        r = (entry >> 8) & 0xff
        return FG_BG_256[r]
    if t == 3:
        r = (entry >> 8) & 0xff
        g = (entry >> 16) & 0xff
        b = (entry >> 24) & 0xff
        return r, g, b


def copy_char(src: Line, dest: Line, src_pos: int, dest_pos: int) -> None:
    for i in range(src.width(src_pos)):
        src.copy_char(src_pos + i, dest, dest_pos + i)


def rewrap_lines(lines: Sequence[Line], width: int) -> Iterator[Line]:
    if lines:
        current_line, current_dest_pos = Line(width), 0
        src_limit = len(lines[0]) - 1
        for i, src in enumerate(lines):
            current_src_pos = 0
            while current_src_pos <= src_limit:
                cw = src.width(current_src_pos)
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
