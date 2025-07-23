#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from binascii import hexlify
from functools import partial

from kitty.fast_data_types import (
    CURSOR_BLOCK,
    VT_PARSER_BUFFER_SIZE,
    base64_decode,
    base64_encode,
    has_avx2,
    has_sse4_2,
    test_find_either_of_two_bytes,
    test_utf8_decode_to_sentinel,
)

from . import BaseTest, parse_bytes


def cnv(x):
    if isinstance(x, memoryview):
        x = str(x, 'utf-8')
    return x


class CmdDump(list):

    def __call__(self, window_id, *a):
        if a and a[0] == 'bytes':
            return
        if a and a[0] == 'error':
            a = a[1:]
        self.append(tuple(map(cnv, a)))

    def get_result(self):
        current = ''
        q = []
        for args in self:
            if args[0] == 'draw':
                current += args[1]
            else:
                if current:
                    q.append(('draw', current))
                    current = ''
                q.append(args)
        if current:
            q.append(('draw', current))
        return tuple(q)


class TestParser(BaseTest):

    def create_write_buffer(self, screen):
        return screen.test_create_write_buffer()

    def write_bytes(self, screen, write_buf, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        s = screen.test_commit_write_buffer(data, write_buf)
        return data[s:]

    def parse_written_data(self, screen, *cmds):
        cd = CmdDump()
        screen.test_parse_written_data(cd)
        cmds = tuple(('draw', x) if isinstance(x, str) else tuple(map(cnv, x)) for x in cmds)
        self.ae(cmds, cd.get_result())

    def parse_bytes_dump(self, s, x, *cmds):
        cd = CmdDump()
        if isinstance(x, str):
            x = x.encode('utf-8')
        cmds = tuple(('draw', x) if isinstance(x, str) else tuple(map(cnv, x)) for x in cmds)
        parse_bytes(s, x, cd)
        self.ae(cmds, cd.get_result())

    def test_charsets(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb(b'\xc3')
        pb(b'\xa1', ('draw', b'\xc3\xa1'.decode('utf-8')))
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('\033)0\x0e/_', ('screen_designate_charset', 1, ord('0')), ('screen_change_charset', 1), '/_')
        self.ae(str(s.line(0)), '/\xa0')
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('\033(0/_', ('screen_designate_charset', 0, ord('0')), '/_')
        self.ae(str(s.line(0)), '/\xa0')

    def test_parser_threading(self):
        s = self.create_screen()

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), 'a\x1b]2;some title'))
        b = self.create_write_buffer(s)
        self.parse_written_data(s, 'a')
        self.assertFalse(self.write_bytes(s, b, ' full\x1b\\'))
        self.parse_written_data(s, ('set_title', 'some title full'))

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), 'a\x1b]'))
        b = self.create_write_buffer(s)
        self.parse_written_data(s, 'a')
        self.assertFalse(self.write_bytes(s, b, '2;title\x1b\\'))
        self.parse_written_data(s, ('set_title', 'title'))

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), 'a\x1b'))
        b = self.create_write_buffer(s)
        self.parse_written_data(s, 'a')
        self.assertFalse(self.write_bytes(s, b, ']2;title\x1b\\'))
        self.parse_written_data(s, ('set_title', 'title'))

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), 'a\x1b]2;some title\x1b'))
        b = self.create_write_buffer(s)
        self.parse_written_data(s, 'a')
        self.assertFalse(self.write_bytes(s, b, '\\b'))
        self.parse_written_data(s, ('set_title', 'some title'), 'b')

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '1\x1b'))
        self.parse_written_data(s, '1')
        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), 'E2'))
        self.parse_written_data(s, ('screen_nel',), ('draw', '2'))

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '1\x1b[2'))
        self.parse_written_data(s, '1')
        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '3mx'))
        self.parse_written_data(s, ('select_graphic_rendition', '23'), 'x')

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '1\x1b'))
        self.parse_written_data(s, '1')
        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '[23mx'))
        self.parse_written_data(s, ('select_graphic_rendition', '23'), 'x')

        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '1\x1b['))
        self.parse_written_data(s, '1')
        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), '23mx'))
        self.parse_written_data(s, ('select_graphic_rendition', '23'), 'x')

        # test full write
        sz = VT_PARSER_BUFFER_SIZE // 3 + 7
        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), b'a' * sz))
        self.assertFalse(self.write_bytes(s, self.create_write_buffer(s), b'b' * sz))
        left = self.write_bytes(s, self.create_write_buffer(s), b'c' * sz)
        self.assertTrue(len(left), 3 * sz - VT_PARSER_BUFFER_SIZE)
        self.assertFalse(self.create_write_buffer(s))
        s.test_parse_written_data()
        b = self.create_write_buffer(s)
        self.assertTrue(b)
        self.write_bytes(s, b, b'')

    def test_base64(self):
        for src, expected in {
            'bGlnaHQgdw==': 'light w',
            'bGlnaHQgd28=': 'light wo',
            'bGlnaHQgd29y': 'light wor',
        }.items():
            self.ae(base64_decode(src.encode()), expected.encode(), f'Decoding of {src} failed')
            self.ae(base64_decode(src.replace('=', '').encode()), expected.encode(), f'Decoding of {src} failed')
            self.ae(base64_encode(expected.encode()), src.replace('=', '').encode(), f'Encoding of {expected} failed')

    def test_simple_parsing(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)

        pb('12', '12')
        self.ae(str(s.line(0)), '12')
        self.ae(s.cursor.x, 2)
        pb('3456', '3456')
        self.ae(str(s.line(0)), '12345')
        self.ae(str(s.line(1)), '6')
        pb(b'\n123\n\r45', ('screen_linefeed',), '123', ('screen_linefeed',), ('screen_carriage_return',), '45')
        self.ae(str(s.line(1)), '6')
        self.ae(str(s.line(2)), ' 123')
        self.ae(str(s.line(3)), '45')
        pb(b'\rabcde', ('screen_carriage_return',), 'abcde')
        self.ae(str(s.line(3)), 'abcde')
        pb('\rßxyz1', ('screen_carriage_return',), 'ßxyz1')
        self.ae(str(s.line(3)), 'ßxyz1')
        pb('ニチ ', 'ニチ ')
        self.ae(str(s.line(4)), 'ニチ ')
        s.reset()
        self.assertFalse(str(s.line(1)) + str(s.line(2)) + str(s.line(3)))
        c1_controls = '\x84\x85\x88\x8d\x8e\x8f\x90\x96\x97\x98\x9a\x9b\x9c\x9d\x9e\x9f'
        pb(c1_controls, c1_controls)
        self.assertFalse(str(s.line(1)) + str(s.line(2)) + str(s.line(3)))
        pb('😀'.encode()[:-1])
        pb('\x1b\x1b%a', '\ufffd', ('Unknown char after ESC: 0x1b',), ('draw', '%a'))

    def test_utf8_parsing(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb(b'"\xbf"', '"\ufffd"')
        pb(b'"\x80"', '"\ufffd"')
        pb(b'"\x80\xbf"', '"\ufffd\ufffd"')
        pb(b'"\x80\xbf\x80"', '"\ufffd\ufffd\ufffd"')
        pb(b'"\xc0 "', '"\ufffd "')
        pb(b'"\xfe"', '"\ufffd"')
        pb(b'"\xff"', '"\ufffd"')
        pb(b'"\xff\xfe"', '"\ufffd\ufffd"')
        pb(b'"\xfe\xfe\xff\xff"', '"\ufffd\ufffd\ufffd\ufffd"')
        pb(b'"\xef\xbf"', '"\ufffd"')
        pb(b'"\xe0\xa0"', '"\ufffd"')
        pb(b'"\xf0\x9f\x98"', '"\ufffd"')

    def test_utf8_simd_decode(self):
        def unsupported(which):
            return (which == 2 and not has_sse4_2) or (which == 3 and not has_avx2)

        def reset_state():
            test_utf8_decode_to_sentinel(b'', -1)

        def asbytes(x):
            if isinstance(x, str):
                x = x.encode()
            return x

        def t(*a, which=2):
            if unsupported(which):
                return

            def parse_parts(which):
                total_consumed = 0
                esc_found = False
                parts = []
                for x in a:
                    found_sentinel, x, num_consumed = test_utf8_decode_to_sentinel(asbytes(x), which)
                    total_consumed += num_consumed
                    if found_sentinel:
                        esc_found = found_sentinel
                    parts.append(x)
                return esc_found, ''.join(parts), total_consumed

            reset_state()
            actual = parse_parts(1)
            reset_state()
            expected = parse_parts(which)
            self.ae(expected, actual, msg=f'Failed for {a} with {which=}\n{expected!r} !=\n{actual!r}')
            return actual

        def double_test(x):
            for which in (2, 3):
                t(x, which=which)
            t(x*2, which=3)
            reset_state()

        # incomplete trailer at end of vector
        t("a"*10 + "😸😸" + "b"*15)

        x = double_test
        x('2:α3')
        x('2:α\x1b3')
        x('2:α3:≤4:😸|')
        x('abcd1234efgh5678')
        x('abc\x1bd1234efgh5678')
        x('abcd1234efgh5678ijklABCDmnopEFGH')

        for which in (2, 3):
            x = partial(t, which=which)
            x('abcdef', 'ghijk')
            x('2:α3', ':≤4:😸|')
            # trailing incomplete sequence
            for prefix in (b'abcd', '😸'.encode()):
                for suffix in (b'1234', '😸'.encode()):
                    x(prefix + b'\xf0\x9f', b'\x98\xb8' + suffix)
                    x(prefix + b'\xf0\x9f\x9b', b'\xb8' + suffix)
                    x(prefix + b'\xf0', b'\x9f\x98\xb8' + suffix)
                    x(prefix + b'\xc3', b'\xa4' + suffix)
                    x(prefix + b'\xe2', b'\x89\xa4' + suffix)
                    x(prefix + b'\xe2\x89', b'\xa4' + suffix)

        def test_expected(src, expected, which=2):
            if unsupported(which):
                return
            reset_state()
            _, actual, _ = t(b'filler' + asbytes(src), which=which)
            expected = 'filler' + expected
            self.ae(expected, actual, f'Failed for: {src!r} with {which=}')

        for which in (1, 2, 3):
            pb = partial(test_expected, which=which)
            pb('ニチ', 'ニチ')
            pb('\x84\x85', '\x84\x85')
            pb('\x84\x85', '\x84\x85')
            pb('\uf4df', '\uf4df')
            pb('\uffff', '\uffff')
            pb('\0', '\0')
            pb(chr(0x10ffff), chr(0x10ffff))
            # various invalid input
            pb(b'abcd\xf51234', 'abcd\ufffd1234')  # bytes > 0xf4
            pb(b'abcd\xff1234', 'abcd\ufffd1234')  # bytes > 0xf4
            pb(b'"\xbf"', '"\ufffd"')
            pb(b'"\x80"', '"\ufffd"')
            pb(b'"\x80\xbf"', '"\ufffd\ufffd"')
            pb(b'"\x80\xbf\x80"', '"\ufffd\ufffd\ufffd"')
            pb(b'"\xc0 "', '"\ufffd "')
            pb(b'"\xfe"', '"\ufffd"')
            pb(b'"\xff"', '"\ufffd"')
            pb(b'"\xff\xfe"', '"\ufffd\ufffd"')
            pb(b'"\xfe\xfe\xff\xff"', '"\ufffd\ufffd\ufffd\ufffd"')
            pb(b'"\xef\xbf"', '"\ufffd"')
            pb(b'"\xe0\xa0"', '"\ufffd"')
            pb(b'"\xf0\x9f\x98"', '"\ufffd"')
            pb(b'"\xef\x93\x94\x95"', '"\uf4d4\ufffd"')

    def test_find_either_of_two_bytes(self):
        sizes = []
        if has_sse4_2:
            sizes.append(2)
        if has_avx2:
            sizes.append(3)
        sizes.append(0)

        def test(buf, a, b, align_offset=0):
            a_, b_ = ord(a), ord(b)
            expected = test_find_either_of_two_bytes(buf, a_, b_, 1, 0)
            for sz in sizes:
                actual = test_find_either_of_two_bytes(buf, a_, b_, sz, align_offset)
                self.ae(expected, actual, f'Failed for: {buf!r} {a=} {b=} at {sz=} and {align_offset=}')

        q = 'abc'
        for off in range(32):
            test(q, '<', '>', off)
            test(q, ' ', 'b', off)
            test(q, '<', 'a', off)
            test(q, '<', 'b', off)
            test(q, 'c', '>', off)

        def tests(buf, a, b):
            for sz in (0, 16, 32, 64, 79):
                buf = (' ' * sz) + buf
                for align_offset in range(32):
                    test(buf, a, b, align_offset)
        tests("", '<', '>')
        tests("a", '\0', '\0')
        tests("a", '<', '>')
        tests("dsdfsfa", '1', 'a')
        tests("xa", 'a', 'a')
        tests("bbb", 'a', '1')
        tests("bba", 'a', '<')
        tests("baa", '>', 'a')

    def test_esc_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('12\033Da', '12', ('screen_index',), 'a')
        self.ae(str(s.line(0)), '12')
        self.ae(str(s.line(1)), '  a')
        pb('\033xa', ('Unknown char after ESC: 0x%x' % ord('x'),), 'a')
        pb('\033c123', ('screen_reset', ), '123')
        self.ae(str(s.line(0)), '123')
        pb('\033.\033a', ('Unhandled charset related escape code: 0x2e 0x1b',), 'a')

    def test_csi_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('abcde', 'abcde')
        s.cursor_move(5)
        pb('x\033[2@y', 'x', ('screen_insert_characters', 2), 'y')
        self.ae(str(s.line(0)), 'xy bc')
        pb('x\033[2;7@y', 'x', ('CSI code @ has 2 > 1 parameters',), 'y')
        pb('x\033[2;-7@y', 'x', ('CSI code @ has 2 > 1 parameters',), 'y')
        pb('x\033[-0001234567890@y', 'x', ('CSI code @ is not allowed to have negative parameter (-1234567890)',), 'y')
        pb('x\033[2-3@y', 'x', ('Invalid character in CSI: 3 (0x33), ignoring the sequence',), '@y')
        pb('x\033[@y', 'x', ('screen_insert_characters', 1), 'y')
        pb('x\033[345@y', 'x', ('screen_insert_characters', 345), 'y')
        pb('x\033[345;@y', 'x', ('screen_insert_characters', 345), 'y')
        pb('\033[H', ('screen_cursor_position', 1, 1))
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 0)
        pb('\033[4H', ('screen_cursor_position', 4, 1))
        pb('\033[4;0H', ('screen_cursor_position', 4, 0))
        pb('\033[3;2H', ('screen_cursor_position', 3, 2))
        pb('\033[3;2;H', ('screen_cursor_position', 3, 2))
        pb('\033[00000000003;0000000000000002H', ('screen_cursor_position', 3, 2))
        self.ae(s.cursor.x, 1), self.ae(s.cursor.y, 2)
        pb('\033[0001234567890H', ('screen_cursor_position', 1234567890, 1))
        pb('\033[J', ('screen_erase_in_display', 0, 0))
        pb('\033[?J', ('screen_erase_in_display', 0, 1))
        pb('\033[?2J', ('screen_erase_in_display', 2, 1))
        pb('\033[h')
        pb('\033[20;4h', ('screen_set_mode', 20, 0), ('screen_set_mode', 4, 0))
        pb('\033[?1000;1004h', ('screen_set_mode', 1000, 1), ('screen_set_mode', 1004, 1))
        pb('\033[20;4;20l', ('screen_reset_mode', 20, 0), ('screen_reset_mode', 4, 0), ('screen_reset_mode', 20, 0))
        pb('\033[=c', ('report_device_attributes', 0, 61))
        s.reset()

        def sgr(*params):
            return (('select_graphic_rendition', f'{x}') for x in params)

        pb('\033[1;2;3;4;7;9;34;44m', *sgr('1;2;3;4;7;9;34;44'))
        for attr in 'bold italic reverse strikethrough dim'.split():
            self.assertTrue(getattr(s.cursor, attr), attr)
        self.ae(s.cursor.decoration, 1)
        self.ae(s.cursor.fg, 4 << 8 | 1)
        self.ae(s.cursor.bg, 4 << 8 | 1)
        pb('\033[38;5;1;48;5;7m', ('select_graphic_rendition', '38:5:1'), ('select_graphic_rendition', '48:5:7'))
        self.ae(s.cursor.fg, 1 << 8 | 1)
        self.ae(s.cursor.bg, 7 << 8 | 1)
        pb('\033[38;2;1;2;3;48;2;7;8;9m', ('select_graphic_rendition', '38:2:1:2:3'), ('select_graphic_rendition', '48:2:7:8:9'))
        self.ae(s.cursor.fg, 1 << 24 | 2 << 16 | 3 << 8 | 2)
        self.ae(s.cursor.bg, 7 << 24 | 8 << 16 | 9 << 8 | 2)
        pb('\033[0;2m', *sgr('0;2'))
        pb('\033[;2m', *sgr('0;2'))
        pb('\033[m', *sgr('0'))
        pb('\033[1;;2m', *sgr('1;0;2'))
        pb('\033[38;5;1m', ('select_graphic_rendition', '38:5:1'))
        pb('\033[58;2;1;2;3m', ('select_graphic_rendition', '58:2:1:2:3'))
        pb('\033[38;2;1;2;3m', ('select_graphic_rendition', '38:2:1:2:3'))
        pb('\033[1001:2:1:2:3m', ('select_graphic_rendition', '1001:2:1:2:3'))
        pb('\033[38:2:1:2:3;48:5:9;58;5;7m', (
            'select_graphic_rendition', '38:2:1:2:3'), ('select_graphic_rendition', '48:5:9'), ('select_graphic_rendition', '58:5:7'))
        s.reset()
        pb('\033[1;2;3;4:5;7;9;34;44m', *sgr('1;2;3', '4:5', '7;9;34;44'))
        for attr in 'bold italic reverse strikethrough dim'.split():
            self.assertTrue(getattr(s.cursor, attr), attr)
        self.ae(s.cursor.decoration, 5)
        c = s.callbacks
        pb('\033[5n', ('report_device_status', 5, 0))
        self.ae(c.wtcbuf, b'\033[0n')
        c.clear()
        pb('\033[6n', ('report_device_status', 6, 0))
        self.ae(c.wtcbuf, b'\033[1;1R')
        pb('12345', '12345')
        c.clear()
        pb('\033[6n', ('report_device_status', 6, 0))
        self.ae(c.wtcbuf, b'\033[2;1R')
        c.clear()
        s.cursor_key_mode = True
        pb('\033[?1$p', ('report_mode_status', 1, 1))
        self.ae(c.wtcbuf, b'\033[?1;1$y')
        pb('\033[?1l', ('screen_reset_mode', 1, 1))
        self.assertFalse(s.cursor_key_mode)
        c.clear()
        pb('\033[?1$p', ('report_mode_status', 1, 1))
        self.ae(c.wtcbuf, b'\033[?1;2$y')
        pb('\033[2;4r', ('screen_set_margins', 2, 4))
        c.clear()
        pb('\033[14t', ('screen_report_size', 14))
        self.ae(c.wtcbuf, b'\033[4;100;50t')
        self.ae(s.margin_top, 1), self.ae(s.margin_bottom, 3)
        pb('\033[r', ('screen_set_margins', 0, 0))
        self.ae(s.margin_top, 0), self.ae(s.margin_bottom, 4)
        pb('\033[1 q', ('screen_set_cursor', 1, ord(' ')))
        self.assertTrue(s.cursor.blink)
        self.ae(s.cursor.shape, CURSOR_BLOCK)

        s.reset()
        pb('\033[3 @', ('Shift left escape code not implemented',))
        pb('\033[3 A', ('Shift right escape code not implemented',))
        pb('\033[3;4 S', ('Select presentation directions escape code not implemented',))
        pb('\033[1T', ('screen_reverse_scroll', 1))
        pb('\033[T', ('screen_reverse_scroll', 1))
        pb('\033[+T', ('screen_reverse_scroll_and_fill_from_scrollback', 1))

        c.clear()
        pb('\033[?2026$p', ('report_mode_status', 2026, 1))
        self.ae(c.wtcbuf, b'\x1b[?2026;2$y')
        c.clear()
        pb('\033[?2026h', ('screen_set_mode', 2026, 1))
        pb('\033[?2026$p', ('report_mode_status', 2026, 1))
        self.ae(c.wtcbuf, b'\x1b[?2026;1$y')
        pb('\033[?2026l', ('screen_reset_mode', 2026, 1))
        c.clear()
        pb('\033[?2026$p', ('report_mode_status', 2026, 1))
        self.ae(c.wtcbuf, b'\x1b[?2026;2$y')

    def test_csi_code_rep(self):
        s = self.create_screen(8)
        pb = partial(self.parse_bytes_dump, s)
        pb('\033[1b', ('screen_repeat_character', 1))
        self.ae(str(s.line(0)), '')
        pb('x\033[7b', 'x', ('screen_repeat_character', 7))
        self.ae(str(s.line(0)), 'xxxxxxxx')
        pb('\033[1;3H', ('screen_cursor_position', 1, 3))
        pb('\033[byz\033[b', ('screen_repeat_character', 1), 'yz', ('screen_repeat_character', 1))
        # repeat 'x' at 3, then 'yz' at 4-5, then repeat 'z' at 6
        self.ae(str(s.line(0)), 'xxxyzzxx')
        s.reset()
        pb(' \033[3b', ' ', ('screen_repeat_character', 3))
        self.ae(str(s.line(0)), '    ')
        s.reset()
        pb('\t\033[b', ('screen_tab',), ('screen_repeat_character', 1))
        self.ae(str(s.line(0)), '\t')
        s.reset()
        b']]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]'

    def test_osc_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        c = s.callbacks
        pb('a\033]2;x\\ryz\033\\bcde', 'a', ('set_title', 'x\\ryz'), 'bcde')
        self.ae(str(s.line(0)), 'abcde')
        self.ae(c.titlebuf, ['x\\ryz'])
        c.clear()
        pb('\033]\x07', ('set_title', ''), ('set_icon', ''))
        self.ae(c.titlebuf, ['']), self.ae(c.iconbuf, '')
        pb('1\033]ab\x072', '1', ('set_title', 'ab'), ('set_icon', 'ab'), '2')
        self.ae(c.titlebuf, ['', 'ab']), self.ae(c.iconbuf, 'ab')
        c.clear()
        pb('\033]2;;;;\x07', ('set_title', ';;;'))
        self.ae(c.titlebuf, [';;;'])
        c.clear()
        pb('\033]2;\x07', ('set_title', ''))
        self.ae(c.titlebuf, [''])
        pb('\033]110\x07', ('set_dynamic_color', 110, ''))
        self.ae(c.colorbuf, '')
        c.clear()
        pb('\033]9;\x07', ('desktop_notify', 9, ''))
        pb('\033]9;test it with a nice long string\x07', ('desktop_notify', 9, 'test it with a nice long string'))
        pb('\033]99;moo=foo;test it\x07', ('desktop_notify', 99, 'moo=foo;test it'))
        self.ae(c.notifications, [(9, ''), (9, 'test it with a nice long string'), (99, 'moo=foo;test it')])
        c.clear()
        pb('\033]8;;\x07', ('set_active_hyperlink', None, None))
        pb('\033]8moo\x07', ('Ignoring malformed OSC 8 code',))
        pb('\033]8;moo\x07', ('Ignoring malformed OSC 8 code',))
        pb('\033]8;id=xyz;\x07', ('set_active_hyperlink', 'xyz', None))
        pb('\033]8;moo:x=z:id=xyz:id=abc;http://yay;.com\x07', ('set_active_hyperlink', 'xyz', 'http://yay;.com'))
        c.clear()
        payload = '1' * 1024
        pb(f'\033]52;p;{payload}\x07', ('clipboard_control', 52, f'p;{payload}'))
        c.clear()
        pb('\033]52;p;xyz\x07', ('clipboard_control', 52, 'p;xyz'))
        c.clear()
        pb('\033]22;?__current__\x07', ('set_dynamic_color', 22, '?__current__'))

    def test_dcs_codes(self):
        s = self.create_screen()
        c = s.callbacks
        pb = partial(self.parse_bytes_dump, s)
        q = hexlify(b'kind').decode('ascii')
        pb(f'a\033P+q{q}\033\\bcde', 'a', ('screen_request_capabilities', 43, q), 'bcde')
        self.ae(str(s.line(0)), 'abcde')
        self.ae(c.wtcbuf, '1+r{}={}'.format(q, '1b5b313b3242').encode('ascii'))
        c.clear()
        pb('\033P$q q\033\\', ('screen_request_capabilities', ord('$'), ' q'))
        self.ae(c.wtcbuf, b'\033P1$r1 q\033\\')
        c.clear()
        pb('\033P$qm\033\\', ('screen_request_capabilities', ord('$'), 'm'))
        self.ae(c.wtcbuf, b'\033P1$rm\033\\')
        for sgr in '0;34;102;1;2;3;4 0;38:5:200;58:2:10:11:12'.split():
            expected = set(sgr.split(';'))
            c.clear()
            parse_bytes(s, f'\033[{sgr}m\033P$qm\033\\'.encode('ascii'))
            r = c.wtcbuf.decode('ascii').partition('r')[2].partition('m')[0]
            self.ae(expected, set(r.split(';')))
        c.clear()
        pb('\033P$qr\033\\', ('screen_request_capabilities', ord('$'), 'r'))
        self.ae(c.wtcbuf, f'\033P1$r{s.margin_top + 1};{s.margin_bottom + 1}r\033\\'.encode('ascii'))
        pb('\033P@kitty-cmd{abc\033\\', ('handle_remote_cmd', '{abc'))
        p = base64_encode('abcd').decode()
        pb(f'\033P@kitty-print|{p}\033\\', ('handle_remote_print', p))
        self.ae(['abcd'], s.callbacks.printbuf)

        c.clear()
        pb('\033[?2026$p', ('report_mode_status', 2026, 1))
        self.ae(c.wtcbuf, b'\x1b[?2026;2$y')
        pb('\033P=1s\033\\', ('screen_start_pending_mode',))
        c.clear()
        pb('\033[?2026$p', ('report_mode_status', 2026, 1))
        self.ae(c.wtcbuf, b'\x1b[?2026;1$y')
        pb('\033P=2s\033\\', ('screen_stop_pending_mode',))
        c.clear()
        pb('\033[?2026$p', ('report_mode_status', 2026, 1))
        self.ae(c.wtcbuf, b'\x1b[?2026;2$y')


    def test_oth_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('a\033_+\\+\033\\bcde', ('draw', 'a'), ('Unrecognized APC code: 0x2b',), ('draw', 'bcde'))
        pb('a\033^+\\+\033\\bcde', ('draw', 'a'), ('Unrecognized PM code: 0x2b',), ('draw', 'bcde'))
        pb('a\033X+\\+\033\\bcde', ('draw', 'a'), ('Unrecognized SOS code: 0x2b',), ('draw', 'bcde'))

    def test_graphics_command(self):
        from base64 import standard_b64encode

        def enc(x):
            return standard_b64encode(x.encode('utf-8') if isinstance(x, str) else x).decode('ascii')

        def c(**k):
            for p, v in tuple(k.items()):
                if isinstance(v, str) and p != 'payload':
                    k[p] = v.encode('ascii')
            for f in 'action delete_action transmission_type compressed'.split():
                k.setdefault(f, b'\0')
            for f in ('format more id data_sz data_offset width height x_offset y_offset data_height data_width cursor_movement'
                      ' num_cells num_lines cell_x_offset cell_y_offset z_index placement_id image_number quiet unicode_placement'
                      ' parent_id parent_placement_id offset_from_parent_x offset_from_parent_y'
            ).split():
                k.setdefault(f, 0)
            p = k.pop('payload', '')
            k[''] = p
            return ('graphics_command', k)

        def t(cmd, **kw):
            pb('\033_G{};{}\033\\'.format(cmd, enc(kw.get('payload', ''))), c(**kw))

        def e(cmd, err):
            pb(f'\033_G{cmd}\033\\', (err,))

        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        uint32_max = 2**32 - 1
        t('i=%d' % uint32_max, id=uint32_max)
        t('i=3,p=4', id=3, placement_id=4)
        e('i=%d' % (uint32_max + 1), 'Malformed GraphicsCommand control block, number is too large')
        pb('\033_Gi=12\033\\', c(id=12))
        t('a=t,t=d,s=100,z=-9', payload='X', action='t', transmission_type='d', data_width=100, z_index=-9)
        t('a=t,t=d,s=100,z=9', payload='payload', action='t', transmission_type='d', data_width=100, z_index=9)
        t('a=t,t=d,s=100,z=9,q=2', action='t', transmission_type='d', data_width=100, z_index=9, quiet=2)
        e(',s=1', 'Malformed GraphicsCommand control block, invalid key character: 0x2c')
        e('W=1', 'Malformed GraphicsCommand control block, invalid key character: 0x57')
        e('1=1', 'Malformed GraphicsCommand control block, invalid key character: 0x31')
        e('a=t,,w=2', 'Malformed GraphicsCommand control block, invalid key character: 0x2c')
        e('s', 'Malformed GraphicsCommand control block, no = after key')
        e('s=', 'Malformed GraphicsCommand control block, expecting an integer value')
        e('s==', 'Malformed GraphicsCommand control block, expecting an integer value for key: s')
        e('s=1=', 'Malformed GraphicsCommand control block, expecting a , or semi-colon after a value, found: 0x3d')

    def test_deccara(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('\033[$r', ('deccara', '0;0;0;0;0'))
        pb('\033[;;;;4:3;38:5:10;48:2:1:2:3;1$r',
           ('deccara', '0;0;0;0;4:3'), ('deccara', '0;0;0;0;38:5:10'), ('deccara', '0;0;0;0;48:2:1:2:3'), ('deccara', '0;0;0;0;1'))
        for y in range(s.lines):
            line = s.line(y)
            for x in range(s.columns):
                c = line.cursor_from(x)
                self.ae(c.bold, True)
                self.ae(c.italic, False)
                self.ae(c.decoration, 3)
                self.ae(c.fg, (10 << 8) | 1)
                self.ae(c.bg, (1 << 24 | 2 << 16 | 3 << 8 | 2))
        self.ae(s.line(0).cursor_from(0).bold, True)
        pb('\033[1;2;2;3;22;39$r', ('deccara', '1;2;2;3;22;39'))
        self.ae(s.line(0).cursor_from(0).bold, True)
        line = s.line(0)
        for x in range(1, s.columns):
            c = line.cursor_from(x)
            self.ae(c.bold, False)
            self.ae(c.fg, 0)
        line = s.line(1)
        for x in range(0, 3):
            c = line.cursor_from(x)
            self.ae(c.bold, False)
        self.ae(line.cursor_from(3).bold, True)
        pb('\033[2*x\033[3;2;4;3;34$r\033[*x', ('screen_decsace', 2), ('deccara', '3;2;4;3;34'), ('screen_decsace', 0))
        for y in range(2, 4):
            line = s.line(y)
            for x in range(s.columns):
                self.ae(line.cursor_from(x).fg, (10 << 8 | 1) if x < 1 or x > 2 else (4 << 8) | 1)
