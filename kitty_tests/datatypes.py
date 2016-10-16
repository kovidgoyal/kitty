#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest, set_text_in_line

from kitty.data_types import Line


class TestDataTypes(BaseTest):

    def test_line_ops(self):
        t = 'Testing with simple text'
        l = Line(len(t))
        set_text_in_line(l, t)
        self.ae(str(l), t)
        self.ae(str(l.copy()), t)
        l.continued = False
        l2 = l.copy()
        self.assertFalse(l2.continued)
        self.ae(l, l2)
        l2.char[1] = 23
        self.assertNotEqual(l, l2)
