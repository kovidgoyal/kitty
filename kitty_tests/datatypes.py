#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest, set_text_in_line

from kitty.data_types import Line, Cursor


class TestDataTypes(BaseTest):

    def test_line_ops(self):
        t = 'Testing with simple text'
        l = Line(len(t))
        set_text_in_line(l, t)
        self.ae(l, l)
        self.ae(str(l), t)
        self.ae(str(l.copy()), t)
        l.continued = False
        l2 = l.copy()
        self.assertFalse(l2.continued)
        self.ae(l, l2)
        l2.char[1] = 23
        self.assertNotEqual(l, l2)

        c = Cursor(3, 5)
        c.hidden = True
        c.bold = c.italic = c.reverse = c.strikethrough = True
        c.fg = c.bg = c.decoration_fg = 0x0101
        self.ae(c, c)
        c2 = c.copy()
        self.ae(c, c.copy())
        c2.bold = c2.hidden = False
        self.assertNotEqual(c, c2)
        l.apply_cursor(c2, 3)
        self.ae(c2, l.cursor_from(3, ypos=c2.y))
        l.apply_cursor(c2, 0, len(l))
        for i in range(len(l)):
            self.ae(c2, l.cursor_from(i, ypos=c2.y))
