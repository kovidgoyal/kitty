#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from unittest import TestCase

from kitty.fast_data_types import LineBuf, Cursor, Screen, HistoryBuf


class Callbacks:

    def __init__(self):
        self.clear()

    def write_to_child(self, data):
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
        self.qbuf += q

    def clear(self):
        self.wtcbuf = b''
        self.iconbuf = self.titlebuf = self.colorbuf = self.qbuf = self.ctbuf = ''


def filled_line_buf(ynum=5, xnum=5, cursor=Cursor()):
    ans = LineBuf(ynum, xnum)
    cursor.x = 0
    for i in range(ynum):
        t = ('{}'.format(i)) * xnum
        ans.line(i).set_text(t, 0, xnum, cursor)
    return ans


def filled_cursor():
    ans = Cursor()
    ans.bold = ans.italic = ans.reverse = ans.strikethrough = True
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

    def create_screen(self, cols=5, lines=5, scrollback=5):
        return Screen(Callbacks(), lines, cols, scrollback)

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2

    def assertChanges(self, s, ignore='', **expected_changes):
        actual_changes = s.consolidate_changes()
        ignore = frozenset(ignore.split())
        for k, v in actual_changes.items():
            if k not in ignore:
                if isinstance(v, dict):
                    v = {ky: tuple(vy) for ky, vy in v.items()}
                if k == 'lines':
                    v = set(v)
                if k in expected_changes:
                    self.ae(expected_changes[k], v)
                else:
                    self.assertFalse(v, 'The property {} was expected to be empty but is: {}'.format(k, v))
