#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import codecs

from . import BaseTest

from kitty.utils import is_simple_string, wcwidth, sanitize_title
from kitty.fast_data_types import LineBuf, Cursor as C


class TestDataTypes(BaseTest):

    def test_line(self):
        lb = LineBuf(2, 3)
        for y in range(2):
            line = lb.line(y)
            self.ae(str(line), ' ' * 3)
            for x in range(3):
                self.ae(line[x], ' ')
        with self.assertRaises(ValueError):
            lb.line(5)
        with self.assertRaises(ValueError):
            lb.line(0)[5]
        l = lb.line(0)
        l.add_combining_char(0, '1')
        self.ae(l[0], ' 1')
        l.add_combining_char(0, '2')
        self.ae(l[0], ' 12')
        l.add_combining_char(0, '3')
        self.ae(l[0], ' 13')
        self.ae(l[1], ' ')
        self.ae(str(l), ' 13  ')
        t = 'Testing with simple text'
        lb = LineBuf(2, len(t))
        l = lb.line(0)
        l.set_text(t, 0, len(t), C())
        self.ae(str(l), t)
        l.set_text('a', 0, 1, C())
        self.assertEqual(str(l), 'a' + t[1:])

        c = C(3, 5)
        c.bold = c.italic = c.reverse = c.strikethrough = True
        c.fg = c.bg = c.decoration_fg = 0x0101
        self.ae(c, c)
        c2, c3 = c.copy(), c.copy()
        self.ae(repr(c), repr(c2))
        self.ae(c, c2)
        c2.bold = c2.hidden = False
        self.assertNotEqual(c, c2)
        l.set_text(t, 0, len(t), C())
        l.apply_cursor(c2, 3)
        self.assertEqualAttributes(c2, l.cursor_from(3))
        l.apply_cursor(c2, 0, len(l))
        for i in range(len(l)):
            self.assertEqualAttributes(c2, l.cursor_from(i))
        l.apply_cursor(c3, 0)
        self.assertEqualAttributes(c3, l.cursor_from(0))
        l.copy_char(0, l, 1)
        self.assertEqualAttributes(c3, l.cursor_from(1))

        t = '0123456789'
        lb = LineBuf(1, len(t))
        l = lb.line(0)
        l.set_text(t, 0, len(t), C())
        self.ae(t, str(l))
        l.right_shift(4, 2)
        self.ae('0123454567', str(l))
        l.set_text(t, 0, len(t), C())
        l.right_shift(0, 0)
        self.ae(t, str(l))
        l.right_shift(0, 1)
        self.ae(str(l), '0' + t[:-1])
        l.set_text(t, 0, len(t), C())
        l.left_shift(0, 2)
        self.ae(str(l), t[2:] + '89')
        l.set_text(t, 0, len(t), C())
        l.left_shift(7, 3)
        self.ae(str(l), t)

        l.set_text(t, 0, len(t), C())
        q = C()
        q.bold = q.italic = q.reverse = q.strikethrough = True
        q.decoration = 2
        c = C()
        c.x = 3
        l.set_text('axyb', 1, 2, c)
        self.ae(str(l), '012xy56789')
        l.set_char(0, 'x', 1, q)
        self.assertEqualAttributes(l.cursor_from(0), q)

    def test_utils(self):
        d = codecs.getincrementaldecoder('utf-8')('strict').decode
        self.ae(tuple(map(wcwidth, 'a1\0コ')), (1, 1, 0, 2))
        for s in ('abd38453*(+\n\t\f\r !\0~[]{}()"\':;<>/?ASD`',):
            self.assertTrue(is_simple_string(s))
            self.assertTrue(is_simple_string(d(s.encode('utf-8'))))
        self.assertFalse(is_simple_string('a1コ'))
        self.assertEqual(sanitize_title('a\0\01 \t\n\f\rb'), 'a b')
