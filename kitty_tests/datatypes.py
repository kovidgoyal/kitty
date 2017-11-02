#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
from unittest import skipIf

from kitty.config import build_ansi_color_table, defaults
from kitty.fast_data_types import (
    REVERSE, ColorProfile, Cursor as C, HistoryBuf, LineBuf
)
from kitty.utils import sanitize_title, wcwidth

from . import BaseTest, filled_cursor, filled_history_buf, filled_line_buf


def create_lbuf(*lines):
    maxw = max(map(len, lines))
    ans = LineBuf(len(lines), maxw)
    prev_full_length = False
    for i, l0 in enumerate(lines):
        ans.line(i).set_text(l0, 0, len(l0), C())
        ans.set_continued(i, prev_full_length)
        prev_full_length = len(l0) == maxw
    return ans


class TestDataTypes(BaseTest):

    def test_linebuf(self):
        old = filled_line_buf(2, 3, filled_cursor())
        new = LineBuf(1, 3)
        new.copy_old(old)
        self.ae(new.line(0), old.line(1))
        new.clear()
        self.ae(str(new.line(0)), '')
        old.set_attribute(REVERSE, False)
        for y in range(old.ynum):
            for x in range(old.xnum):
                l0 = old.line(y)
                c = l0.cursor_from(x)
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
        l2 = lb.create_line_copy(2)
        lb.copy_line_to(1, l2)
        self.ae(l2, lb2.line(2))
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
        l0 = lb.line(0)
        l0.add_combining_char(1, 'a')
        l0.clear_text(1, 2)
        self.ae(str(l0), '0  00')
        self.assertEqualAttributes(l0.cursor_from(1), l0.cursor_from(0))

        lb = filled_line_buf(10, 10, filled_cursor())
        lb.clear()
        lb2 = LineBuf(lb.ynum, lb.ynum)
        for i in range(lb.ynum):
            self.ae(lb.line(i), lb2.line(i))

    def test_line(self):
        lb = LineBuf(2, 3)
        for y in range(lb.ynum):
            line = lb.line(y)
            self.ae(str(line), '')
            for x in range(lb.xnum):
                self.ae(line[x], '\0')
        with self.assertRaises(IndexError):
            lb.line(lb.ynum)
        with self.assertRaises(IndexError):
            lb.line(0)[lb.xnum]
        l0 = lb.line(0)
        l0.set_text(' ', 0, len(' '), C())
        l0.add_combining_char(0, '1')
        self.ae(l0[0], ' 1')
        l0.add_combining_char(0, '2')
        self.ae(l0[0], ' 12')
        l0.add_combining_char(0, '3')
        self.ae(l0[0], ' 13')
        self.ae(l0[1], '\0')
        self.ae(str(l0), ' 13')
        t = 'Testing with simple text'
        lb = LineBuf(2, len(t))
        l0 = lb.line(0)
        l0.set_text(t, 0, len(t), C())
        self.ae(str(l0), t)
        l0.set_text('a', 0, 1, C())
        self.assertEqual(str(l0), 'a' + t[1:])

        c = C(3, 5)
        c.bold = c.italic = c.reverse = c.strikethrough = True
        c.fg = c.bg = c.decoration_fg = 0x0101
        self.ae(c, c)
        c2, c3 = c.copy(), c.copy()
        self.ae(repr(c), repr(c2))
        self.ae(c, c2)
        c2.bold = False
        self.assertNotEqual(c, c2)
        l0.set_text(t, 0, len(t), C())
        l0.apply_cursor(c2, 3)
        self.assertEqualAttributes(c2, l0.cursor_from(3))
        l0.apply_cursor(c2, 0, len(l0))
        for i in range(len(l0)):
            self.assertEqualAttributes(c2, l0.cursor_from(i))
        l0.apply_cursor(c3, 0)
        self.assertEqualAttributes(c3, l0.cursor_from(0))
        l0.copy_char(0, l0, 1)
        self.assertEqualAttributes(c3, l0.cursor_from(1))

        t = '0123456789'
        lb = LineBuf(1, len(t))
        l3 = lb.line(0)
        l3.set_text(t, 0, len(t), C())
        self.ae(t, str(l3))
        l3.right_shift(4, 2)
        self.ae('0123454567', str(l3))
        l3.set_text(t, 0, len(t), C())
        l3.right_shift(0, 0)
        self.ae(t, str(l3))
        l3.right_shift(0, 1)
        self.ae(str(l3), '0' + t[:-1])
        l3.set_text(t, 0, len(t), C())
        l3.left_shift(0, 2)
        self.ae(str(l3), t[2:] + '89')
        l3.set_text(t, 0, len(t), C())
        l3.left_shift(7, 3)
        self.ae(str(l3), t)

        l3.set_text(t, 0, len(t), C())
        q = C()
        q.bold = q.italic = q.reverse = q.strikethrough = True
        q.decoration = 2
        c = C()
        c.x = 3
        l3.set_text('axyb', 1, 2, c)
        self.ae(str(l3), '012xy56789')
        l3.set_char(0, 'x', 1, q)
        self.assertEqualAttributes(l3.cursor_from(0), q)

    def test_url_at(self):
        def create(t):
            lb = create.lb = LineBuf(1, len(t))
            lf = lb.line(0)
            lf.set_text(t, 0, len(t), C())
            return lf

        for trail in '.,]>)\\':
            lx = create("http://xyz.com" + trail)
            self.ae(lx.url_end_at(0), len(lx) - 2)
        l0 = create("ftp://abc/")
        self.ae(l0.url_end_at(0), len(l0) - 1)
        l2 = create("http://-abcd] ")
        self.ae(l2.url_end_at(0), len(l2) - 3)

        def lspace_test(n, scheme='http'):
            lf = create(' ' * n + scheme + '://acme.com')
            for i in range(0, n):
                self.ae(lf.url_start_at(i), len(lf))
            for i in range(n, len(lf)):
                self.ae(lf.url_start_at(i), n)
        for i in range(7):
            for scheme in 'http https ftp file'.split():
                lspace_test(i)
        l3 = create('b https://testing.me a')
        for s in (0, 1, len(l3) - 1, len(l3) - 2):
            self.ae(l3.url_start_at(s), len(l3), 'failed with start at: %d' % s)
        for s in range(2, len(l3) - 2):
            self.ae(l3.url_start_at(s), 2, 'failed with start at: %d (%s)' % (s, str(l3)[s:]))

        def no_url(t):
            lf = create(t)
            for s in range(len(lf)):
                self.ae(lf.url_start_at(s), len(lf))
        no_url('https:// testing.me a')
        no_url('h ttp://acme.com')
        no_url('http: //acme.com')
        no_url('http:/ /acme.com')

    def rewrap(self, lb, lb2):
        hb = HistoryBuf(lb2.ynum, lb2.xnum)
        cy = lb.rewrap(lb2, hb)
        return hb, cy[1]

    def test_rewrap_simple(self):
        ' Same width buffers '
        lb = filled_line_buf(5, 5)
        lb2 = LineBuf(lb.ynum, lb.xnum)
        self.rewrap(lb, lb2)
        for i in range(lb.ynum):
            self.ae(lb2.line(i), lb.line(i))
        lb2 = LineBuf(8, 5)
        cy = self.rewrap(lb, lb2)[1]
        self.ae(cy, 5)
        for i in range(lb.ynum):
            self.ae(lb2.line(i), lb.line(i))
        empty = LineBuf(1, lb2.xnum)
        for i in range(lb.ynum, lb2.ynum):
            self.ae(str(lb2.line(i)), str(empty.line(0)))
        lb2 = LineBuf(3, 5)
        cy = self.rewrap(lb, lb2)[1]
        self.ae(cy, 3)
        for i in range(lb2.ynum):
            self.ae(lb2.line(i), lb.line(i + 2))

    def line_comparison(self, buf, *lines):
        for i, l0 in enumerate(lines):
            l2 = buf.line(i)
            self.ae(l0, str(l2))

    def line_comparison_rewrap(self, lb, *lines):
        lb2 = LineBuf(len(lines), max(map(len, lines)))
        self.rewrap(lb, lb2)
        self.line_comparison(lb2, *lines)
        return lb2

    def assertContinued(self, lb, *vals):
        self.ae(list(vals), [lb.is_continued(i) for i in range(len(vals))])

    def test_rewrap_wider(self):
        ' New buffer wider '
        lb = create_lbuf('0123 ', '56789')
        lb2 = self.line_comparison_rewrap(lb, '0123 5', '6789', '')
        self.assertContinued(lb2, False, True)

        lb = create_lbuf('12', 'abc')
        lb2 = self.line_comparison_rewrap(lb, '12', 'abc')
        self.assertContinued(lb2, False, False)

    def test_rewrap_narrower(self):
        ' New buffer narrower '
        lb = create_lbuf('123', 'abcde')
        lb2 = self.line_comparison_rewrap(lb, '123', 'abc', 'de')
        self.assertContinued(lb2, False, False, True)
        lb = create_lbuf('123  ', 'abcde')
        lb2 = self.line_comparison_rewrap(lb, '123', '  a', 'bcd', 'e')
        self.assertContinued(lb2, False, True, True, True)

    @skipIf('ANCIENT_WCWIDTH' in os.environ, 'wcwidth() is too old')
    def test_utils(self):
        self.ae(tuple(map(wcwidth, 'a1\0コニチ ')), (1, 1, 0, 2, 2, 2, 1))
        self.assertEqual(sanitize_title('a\0\01 \t\n\f\rb'), 'a b')

    def test_color_profile(self):
        c = ColorProfile()
        c.update_ansi_color_table(build_ansi_color_table())
        for i in range(8):
            col = getattr(defaults, 'color{}'.format(i))
            self.assertEqual(c.as_color(i << 8 | 1), (col[0], col[1], col[2]))
        self.ae(c.as_color(255 << 8 | 1), (0xee, 0xee, 0xee))

    def test_historybuf(self):
        lb = filled_line_buf()
        hb = HistoryBuf(5, 5)
        hb.push(lb.line(1))
        hb.push(lb.line(2))
        self.ae(hb.count, 2)
        self.ae(hb.line(0), lb.line(2))
        self.ae(hb.line(1), lb.line(1))
        hb = filled_history_buf()
        self.ae(str(hb.line(0)), '4' * hb.xnum)
        self.ae(str(hb.line(4)), '0' * hb.xnum)
        hb.push(lb.line(2))
        self.ae(str(hb.line(0)), '2' * hb.xnum)
        self.ae(str(hb.line(4)), '1' * hb.xnum)

        # rewrap
        hb = filled_history_buf(5, 5)
        hb2 = HistoryBuf(hb.ynum, hb.xnum)
        hb.rewrap(hb2)
        for i in range(hb.ynum):
            self.ae(hb2.line(i), hb.line(i))
        hb2 = HistoryBuf(8, 5)
        hb.rewrap(hb2)
        for i in range(hb.ynum):
            self.ae(hb2.line(i), hb.line(i))
        for i in range(hb.ynum, hb2.ynum):
            with self.assertRaises(IndexError):
                hb2.line(i)
        hb2 = HistoryBuf(3, 5)
        hb.rewrap(hb2)
        for i in range(hb2.ynum):
            self.ae(hb2.line(i), hb.line(i))
        hb = filled_history_buf(5, 5)
        hb2 = HistoryBuf(hb.ynum, hb.xnum * 2)
        hb.rewrap(hb2)
        hb3 = HistoryBuf(hb.ynum, hb.xnum)
        hb2.rewrap(hb3)
        for i in range(hb.ynum):
            self.ae(hb.line(i), hb3.line(i))

    def test_ansi_repr(self):
        lb = filled_line_buf()
        l0 = lb.line(0)
        self.ae(l0.as_ansi(), '\x1b[0m00000')
        a = []
        lb.as_ansi(a.append)
        self.ae(a, ['\x1b[0m' + str(lb.line(i)) + '\n' for i in range(lb.ynum)])
        l2 = lb.line(0)
        c = C()
        c.bold = c.italic = c.reverse = c.strikethrough = True
        c.fg = (4 << 8) | 1
        c.bg = (1 << 24) | (2 << 16) | (3 << 8) | 2
        c.decoration_fg = (5 << 8) | 1
        l2.set_text('1', 0, 1, c)
        self.ae(l2.as_ansi(), '\x1b[0m\x1b[1m\x1b[3m\x1b[7m\x1b[9m\x1b[38;5;4m\x1b[48;2;1;2;3m\x1b[58;5;5m' '1'
                '\x1b[22m\x1b[23m\x1b[27m\x1b[29m\x1b[39m\x1b[49m\x1b[59m' '0000')
        lb = filled_line_buf()
        for i in range(lb.ynum):
            lb.set_continued(i, True)
        a = []
        lb.as_ansi(a.append)
        self.ae(a, ['\x1b[0m' + str(lb.line(i)) for i in range(lb.ynum)])
        hb = filled_history_buf(5, 5)
        a = []
        hb.as_ansi(a.append)
        self.ae(a, ['\x1b[0m' + str(hb.line(i)) + '\n' for i in range(hb.count - 1, -1, -1)])
