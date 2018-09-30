#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from unittest import TestCase

from kitty.config import Options, defaults, merge_configs
from kitty.fast_data_types import set_options
from kitty.fast_data_types import LineBuf, Cursor, Screen, HistoryBuf


class Callbacks:

    def __init__(self):
        self.clear()

    def write(self, data):
        self.wtcbuf += data

    def title_changed(self, data):
        self.titlebuf += data

    def icon_changed(self, data):
        self.iconbuf += data

    def set_dynamic_color(self, code, data):
        self.colorbuf += data or ''

    def set_color_table_color(self, code, data):
        self.ctbuf += ''

    def request_capabilities(self, q):
        from kitty.terminfo import get_capabilities
        c = get_capabilities(q)
        self.write(c.encode('ascii'))

    def use_utf8(self, on):
        self.iutf8 = on

    def clear(self):
        self.wtcbuf = b''
        self.iconbuf = self.titlebuf = self.colorbuf = self.ctbuf = ''
        self.iutf8 = True


def filled_line_buf(ynum=5, xnum=5, cursor=Cursor()):
    ans = LineBuf(ynum, xnum)
    cursor.x = 0
    for i in range(ynum):
        t = ('{}'.format(i)) * xnum
        ans.line(i).set_text(t, 0, xnum, cursor)
    return ans


def filled_cursor():
    ans = Cursor()
    ans.bold = ans.italic = ans.reverse = ans.strikethrough = ans.dim = True
    ans.fg = 0x101
    ans.bg = 0x201
    ans.decoration_fg = 0x301
    return ans


def filled_history_buf(ynum=5, xnum=5, cursor=Cursor()):
    lb = filled_line_buf(ynum, xnum, cursor)
    ans = HistoryBuf(ynum, xnum)
    for i in range(ynum):
        ans.push(lb.line(i))
    return ans


class BaseTest(TestCase):

    ae = TestCase.assertEqual
    maxDiff = 2000

    def create_screen(self, cols=5, lines=5, scrollback=5, cell_width=10, cell_height=20, options={}):
        options = Options(merge_configs(defaults._asdict(), options))
        set_options(options)
        c = Callbacks()
        return Screen(c, lines, cols, scrollback, cell_width, cell_height, 0, c)

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2
