#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import codecs

from . import BaseTest, filled_line_buf, filled_cursor

from kitty.utils import is_simple_string, wcwidth, sanitize_title
from kitty.fast_data_types import LineBuf, Cursor as C, REVERSE


class TestDataTypes(BaseTest):

    def test_linebuf(self):
        old = filled_line_buf(2, 3, filled_cursor())
        new = LineBuf(1, 3)
        new.copy_old(old)
        self.ae(new.line(0), old.line(1))
        new.clear()
        self.ae(str(new.line(0)), ' ' * new.xnum)
        old.set_attribute(REVERSE, False)
        for y in range(old.ynum):
            for x in range(old.xnum):
                l = old.line(y)
                c = l.cursor_from(x)
                self.assertFalse(c.reverse)
                self.assertTrue(c.bold)
        self.assertFalse(old.is_continued(0))
        old.set_continued(0, True)
        self.assertTrue(old.is_continued(0))
        self.assertFalse(old.is_continued(1))

        lb = filled_line_buf(5, 5, filled_cursor())
        lb2 = LineBuf(5, 5)
        lb2.copy_old(lb)
        lb.index(0, 4)
        for i in range(0, 4):
            self.ae(lb.line(i), lb2.line(i + 1))
        self.ae(lb.line(4), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.index(1, 3)
        self.ae(lb.line(0), lb2.line(0))
        self.ae(lb.line(1), lb2.line(2))
        self.ae(lb.line(2), lb2.line(3))
        self.ae(lb.line(3), lb2.line(1))
        self.ae(lb.line(4), lb2.line(4))
        self.ae(lb.create_line_copy(1), lb2.line(2))
        l = lb.create_line_copy(2)
        lb.copy_line_to(1, l)
        self.ae(l, lb2.line(2))
        lb.clear_line(0)
        self.ae(lb.line(0), LineBuf(1, lb.xnum).create_line_copy(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.reverse_index(0, 4)
        self.ae(lb.line(0), lb2.line(4))
        for i in range(1, 5):
            self.ae(lb.line(i), lb2.line(i - 1))

        lb = filled_line_buf(5, 5, filled_cursor())
        clb = filled_line_buf(5, 5, filled_cursor())
        lb2 = LineBuf(1, 5)
        lb.insert_lines(2, 1, lb.ynum - 1)
        self.ae(lb.line(0), clb.line(0))
        self.ae(lb.line(3), clb.line(1))
        self.ae(lb.line(4), clb.line(2))
        self.ae(lb.line(1), lb2.line(0))
        self.ae(lb.line(2), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.insert_lines(10, 0, lb.ynum - 1)
        for i in range(lb.ynum):
            self.ae(lb.line(i), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.insert_lines(10, 1, lb.ynum - 1)
        self.ae(lb.line(0), clb.line(0))
        for i in range(1, lb.ynum):
            self.ae(lb.line(i), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.insert_lines(1, 1, 3)
        self.ae(lb.line(0), clb.line(0))
        self.ae(lb.line(1), lb2.line(0))
        self.ae(lb.line(2), clb.line(1))
        self.ae(lb.line(3), clb.line(2))
        self.ae(lb.line(4), clb.line(4))

        lb = filled_line_buf(5, 5, filled_cursor())
        lb.delete_lines(2, 1, lb.ynum - 1)
        self.ae(lb.line(0), clb.line(0))
        self.ae(lb.line(1), clb.line(3))
        self.ae(lb.line(2), clb.line(4))
        self.ae(lb.line(3), lb2.line(0))
        self.ae(lb.line(4), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.delete_lines(10, 0, lb.ynum - 1)
        for i in range(lb.ynum):
            self.ae(lb.line(i), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.delete_lines(10, 1, lb.ynum - 1)
        self.ae(lb.line(0), clb.line(0))
        for i in range(1, lb.ynum):
            self.ae(lb.line(i), lb2.line(0))
        lb = filled_line_buf(5, 5, filled_cursor())
        lb.delete_lines(1, 1, 3)
        self.ae(lb.line(0), clb.line(0))
        self.ae(lb.line(1), clb.line(2))
        self.ae(lb.line(2), clb.line(3))
        self.ae(lb.line(3), lb2.line(0))
        self.ae(lb.line(4), clb.line(4))

        lb = filled_line_buf(5, 5, filled_cursor())
        l = lb.line(0)
        l.add_combining_char(1, 'a')
        l.clear_text(1, 2)
        self.ae(str(l), '0  00')
        self.assertEqualAttributes(l.cursor_from(1), l.cursor_from(0))

    def test_line(self):
        lb = LineBuf(2, 3)
        for y in range(lb.ynum):
            line = lb.line(y)
            self.ae(str(line), ' ' * lb.xnum)
            for x in range(lb.xnum):
                self.ae(line[x], ' ')
        with self.assertRaises(ValueError):
            lb.line(lb.ynum)
        with self.assertRaises(ValueError):
            lb.line(0)[lb.xnum]
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

    def test_rewrap(self):
        # Simple tests when xnum is unchanged
        lb = filled_line_buf(5, 5)
        lb2 = LineBuf(lb.ynum, lb.xnum)
        lb.rewrap(lb2)
        for i in range(lb.ynum):
            self.ae(lb2.line(i), lb.line(i))
        lb2 = LineBuf(3, 5)
        lb.rewrap(lb2)
        for i in range(lb2.ynum):
            self.ae(lb2.line(i), lb.line(i + 2))
        lb2 = LineBuf(8, 5)
        lb.rewrap(lb2)
        for i in range(lb.ynum):
            self.ae(lb2.line(i), lb.line(i))
        empty = LineBuf(1, lb2.xnum)
        for i in range(lb.ynum, lb2.ynum):
            self.ae(str(lb2.line(i)), str(empty.line(0)))

    def test_utils(self):
        d = codecs.getincrementaldecoder('utf-8')('strict').decode
        self.ae(tuple(map(wcwidth, 'a1\0コ')), (1, 1, 0, 2))
        for s in ('abd38453*(+\n\t\f\r !\0~[]{}()"\':;<>/?ASD`',):
            self.assertTrue(is_simple_string(s))
            self.assertTrue(is_simple_string(d(s.encode('utf-8'))))
        self.assertFalse(is_simple_string('a1コ'))
        self.assertEqual(sanitize_title('a\0\01 \t\n\f\rb'), 'a b')
