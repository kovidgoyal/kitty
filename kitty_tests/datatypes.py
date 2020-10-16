#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile

from kitty.config import build_ansi_color_table, defaults
from kitty.fast_data_types import (
    REVERSE, ColorProfile, Cursor as C, HistoryBuf, LineBuf,
    parse_input_from_terminal, truncate_point_for_length, wcswidth, wcwidth
)
from kitty.rgb import to_color
from kitty.utils import is_path_in_temp_dir, sanitize_title

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

    def test_to_color(self):
        for x in 'xxx #12 #1234 rgb:a/b'.split():
            self.assertIsNone(to_color(x))

        def c(spec, r=0, g=0, b=0):
            self.ae(tuple(to_color(spec)), (r, g, b))

        c('#eee', 0xee, 0xee, 0xee)
        c('#234567', 0x23, 0x45, 0x67)
        c('#abcabcdef', 0xab, 0xab, 0xde)
        c('rgb:e/e/e', 0xee, 0xee, 0xee)
        c('rgb:23/45/67', 0x23, 0x45, 0x67)
        c('rgb:abc/abc/def', 0xab, 0xab, 0xde)
        c('red', 0xff)

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
        l0.add_combining_char(1, '\u0300')
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
        l0.add_combining_char(0, '\u0300')
        self.ae(l0[0], ' \u0300')
        l0.add_combining_char(0, '\U000e0100')
        self.ae(l0[0], ' \u0300\U000e0100')
        l0.add_combining_char(0, '\u0302')
        self.ae(l0[0], ' \u0300\u0302')
        self.ae(l0[1], '\0')
        self.ae(str(l0), ' \u0300\u0302')
        t = 'Testing with simple text'
        lb = LineBuf(2, len(t))
        l0 = lb.line(0)
        l0.set_text(t, 0, len(t), C())
        self.ae(str(l0), t)
        l0.set_text('a', 0, 1, C())
        self.assertEqual(str(l0), 'a' + t[1:])

        c = C(3, 5)
        c.bold = c.italic = c.reverse = c.strikethrough = c.dim = True
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
        q.bold = q.italic = q.reverse = q.strikethrough = c.dim = True
        q.decoration = 2
        c = C()
        c.x = 3
        l3.set_text('axyb', 1, 2, c)
        self.ae(str(l3), '012xy56789')
        l3.set_char(0, 'x', 1, q)
        self.assertEqualAttributes(l3.cursor_from(0), q)

    def test_url_at(self):
        self.set_options()

        def create(t):
            lb = create.lb = LineBuf(1, len(t))
            lf = lb.line(0)
            lf.set_text(t, 0, len(t), C())
            return lf

        l0 = create('file:///etc/test')
        self.ae(l0.url_start_at(0), 0)

        for trail in '.,]>)\\':
            lx = create("http://xyz.com" + trail)
            self.ae(lx.url_end_at(0), len(lx) - 2)
        l0 = create("ftp://abc/")
        self.ae(l0.url_end_at(0), len(l0) - 1)
        l2 = create("http://-abcd] ")
        self.ae(l2.url_end_at(0), len(l2) - 3)
        l3 = create("http://ab.de           ")
        self.ae(l3.url_start_at(4), 0)
        self.ae(l3.url_start_at(5), 0)

        def lspace_test(n, scheme='http'):
            lf = create(' ' * n + scheme + '://acme.com')
            for i in range(0, n):
                self.ae(lf.url_start_at(i), len(lf))
            for i in range(n, len(lf)):
                self.ae(lf.url_start_at(i), n)
        for i in range(7):
            for scheme in 'http https ftp file'.split():
                lspace_test(i, scheme)
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

        l4 = create(' xxxxxtekljhgdkjgd')
        self.ae(l4.url_end_at(0), 0)

        for trail in '/-&':
            l4 = create('http://a.b?q=1' + trail)
            self.ae(l4.url_end_at(1), len(l4) - 1)

        l4 = create('http://a.b.')
        self.ae(l4.url_end_at(0), len(l4) - 2)
        self.ae(l4.url_end_at(0, 0, True), len(l4) - 1)

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
        self.assertFalse(lb.dirty_lines())
        self.ae(lb2.dirty_lines(), list(range(lb2.ynum)))

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
        self.ae(lb2.dirty_lines(), [0, 1])

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

    def test_utils(self):
        def w(x):
            return wcwidth(ord(x))
        self.ae(wcswidth('a\033[2mb'), 2)
        self.ae(wcswidth('\033a\033[2mb'), 2)
        self.ae(wcswidth('a\033]8;id=moo;https://foo\033\\a'), 2)
        self.ae(wcswidth('a\033x'), 2)
        self.ae(tuple(map(w, 'a1\0コニチ ✔')), (1, 1, 0, 2, 2, 2, 1, 1))
        self.ae(wcswidth('\u2716\u2716\ufe0f\U0001f337'), 5)
        self.ae(wcswidth('\u25b6\ufe0f'), 2)
        self.ae(wcswidth('\U0001f610\ufe0e'), 1)
        self.ae(wcswidth('\U0001f1e6a'), 3)
        self.ae(wcswidth('\U0001F1E6a\U0001F1E8a'), 6)
        self.ae(wcswidth('\U0001F1E6\U0001F1E8a'), 3)
        self.ae(wcswidth('\U0001F1E6\U0001F1E8\U0001F1E6'), 4)
        # Regional indicator symbols (unicode flags) are defined as having
        # Emoji_Presentation so must have width 2
        self.ae(tuple(map(w, '\U0001f1ee\U0001f1f3')), (2, 2))
        tpl = truncate_point_for_length
        self.ae(tpl('abc', 4), 3)
        self.ae(tpl('abc', 2), 2)
        self.ae(tpl('abc', 0), 0)
        self.ae(tpl('a\U0001f337', 2), 1)
        self.ae(tpl('a\U0001f337', 3), 2)
        self.ae(tpl('a\U0001f337b', 4), 3)
        self.ae(sanitize_title('a\0\01 \t\n\f\rb'), 'a b')
        self.ae(tpl('a\x1b[31mbc', 2), 7)

        def tp(*data, leftover='', text='', csi='', apc='', ibp=False):
            text_r, csi_r, apc_r, rest = [], [], [], []
            left = ''
            in_bp = ibp

            def on_csi(x):
                nonlocal in_bp
                if x == '200~':
                    in_bp = True
                elif x == '201~':
                    in_bp = False
                csi_r.append(x)

            for d in data:
                left = parse_input_from_terminal(text_r.append, rest.append, on_csi, rest.append, rest.append, apc_r.append, left + d, in_bp)
            self.ae(left, leftover)
            self.ae(text, ' '.join(text_r))
            self.ae(csi, ' '.join(csi_r))
            self.ae(apc, ' '.join(apc_r))
            self.assertFalse(rest)

        tp('a\033[200~\033[32mxy\033[201~\033[33ma', text='a \033[32m xy a', csi='200~ 201~ 33m')
        tp('abc', text='abc')
        tp('a\033[38:5:12:32mb', text='a b', csi='38:5:12:32m')
        tp('a\033_x,;(\033\\b', text='a b', apc='x,;(')
        tp('a\033', '[', 'mb', text='a b', csi='m')
        tp('a\033[', 'mb', text='a b', csi='m')
        tp('a\033', '_', 'x\033', '\\b', text='a b', apc='x')
        tp('a\033_', 'x', '\033', '\\', 'b', text='a b', apc='x')

        for prefix in ('/tmp', tempfile.gettempdir()):
            for path in ('a.png', 'x/b.jpg', 'y/../c.jpg'):
                self.assertTrue(is_path_in_temp_dir(os.path.join(prefix, path)))
        for path in ('/home/xy/d.png', '/tmp/../home/x.jpg'):
            self.assertFalse(is_path_in_temp_dir(os.path.join(path)))

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
        hb = large_hb = HistoryBuf(3000, 5)
        c = filled_cursor()
        for i in range(3000):
            line = lb.line(1)
            t = str(i).ljust(5)
            line.set_text(t, 0, 5, c)
            hb.push(line)
        for i in range(3000):
            self.ae(str(hb.line(i)).rstrip(), str(3000 - 1 - i))

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
        self.ae(hb2.dirty_lines(), list(range(hb2.ynum)))
        hb = filled_history_buf(5, 5)
        hb2 = HistoryBuf(hb.ynum, hb.xnum * 2)
        hb.rewrap(hb2)
        hb3 = HistoryBuf(hb.ynum, hb.xnum)
        hb2.rewrap(hb3)
        for i in range(hb.ynum):
            self.ae(hb.line(i), hb3.line(i))

        hb2 = HistoryBuf(hb.ynum, hb.xnum)
        large_hb.rewrap(hb2)
        hb2 = HistoryBuf(large_hb.ynum, large_hb.xnum)
        large_hb.rewrap(hb2)

    def test_ansi_repr(self):
        lb = filled_line_buf()
        l0 = lb.line(0)
        self.ae(l0.as_ansi(), '00000')
        a = []
        lb.as_ansi(a.append)
        self.ae(a, [str(lb.line(i)) + '\n' for i in range(lb.ynum)])
        l2 = lb.line(0)
        c = C()
        c.bold = c.italic = c.reverse = c.strikethrough = c.dim = True
        c.fg = (4 << 8) | 1
        c.bg = (1 << 24) | (2 << 16) | (3 << 8) | 2
        c.decoration_fg = (5 << 8) | 1
        l2.set_text('1', 0, 1, c)
        self.ae(l2.as_ansi(), '\x1b[1;2;3;7;9;34;48:2:1:2:3;58:5:5m' '1'
                '\x1b[22;23;27;29;39;49;59m' '0000')
        lb = filled_line_buf()
        for i in range(lb.ynum):
            lb.set_continued(i, True)
        a = []
        lb.as_ansi(a.append)
        self.ae(a, [str(lb.line(i)) for i in range(lb.ynum)])
        hb = filled_history_buf(5, 5)
        a = []
        hb.as_ansi(a.append)
        self.ae(a, [str(hb.line(i)) + '\n' for i in range(hb.count - 1, -1, -1)])
