#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial

from kitty.fast_data_types import EXTEND_CELL, TEXT_SIZE_CODE, test_ch_and_idx, wcswidth

from . import BaseTest, parse_bytes
from . import draw_multicell as multicell


class TestMulticell(BaseTest):

    def test_multicell(self):
        test_multicell(self)


def test_multicell(self: TestMulticell) -> None:
    from kitty.tab_bar import as_rgb
    from kitty.window import as_text

    def as_ansi(add_history=False):
        return as_text(s, as_ansi=True, add_history=add_history)

    def ac(x_, y_, **assertions):  # assert cell
        cell = s.cpu_cells(y_, x_)
        msg = f'Assertion failed for cell at ({x_}, {y_})\n{cell}\n'
        failures = []
        def ae(key):
            if key not in assertions:
                return
            if key in cell:
                val = cell[key]
            else:
                mcd = cell['mcd']
                if mcd is None:
                    raise AssertionError(f'{msg}Unexpectedly not a multicell')
                val = mcd[key]
            if assertions[key] != val:
                failures.append(f'{key}: (expected) {assertions[key]!r} != {val!r}')

        self.ae(test_ch_and_idx(0), (0, 0, 0))
        self.ae(test_ch_and_idx(1), (0, 1, 1))
        self.ae(test_ch_and_idx(0x80000000), (1, 0, 0x80000000))
        self.ae(test_ch_and_idx(0x80000001), (1, 1, 0x80000001))
        self.ae(test_ch_and_idx((1, 0)), (1, 0, 0x80000000))
        self.ae(test_ch_and_idx((1, 3)), (1, 3, 0x80000003))

        ae('x')
        ae('y')
        ae('width')
        ae('scale')
        ae('subscale_n')
        ae('subscale_d')
        ae('vertical_align')
        ae('horizontal_align')
        ae('text')
        ae('natural_width')
        ae('next_char_was_wrapped')
        if failures:
            raise AssertionError(msg + '\n' + '\n'.join(failures))

        if 'cursor' in assertions:
            self.ae(assertions['cursor'], (s.cursor.x, s.cursor.y), msg)

        if 'is_multicell' in assertions:
            q = cell['mcd']
            if assertions['is_multicell']:
                if q is None:
                    raise AssertionError(f'{msg}Unexpectedly not a multicell')
            else:
                if q is not None:
                    raise AssertionError(f'{msg}Unexpectedly is a multicell')

    def count_multicells(with_text=''):
        ans = 0
        for y in range(s.lines):
            for x in range(s.columns):
                c = s.cpu_cells(y, x)
                if c['mcd'] is not None and (not with_text or c['text'] == with_text):
                    ans += 1
        return ans

    def line_text(y):
        def ct(c):
            if c['text']:
                return c['text']
            if c['mcd']:
                return '_'
            return '\0'
        return ''.join(ct(c) for c in s.cpu_cells(y))

    def assert_line(text, y=None):
        if y is None:
            y = s.cursor.y
        self.ae(text, line_text(y))

    def assert_cursor_at(x, y):
        self.ae((s.cursor.x, s.cursor.y), (x, y))

    s = self.create_screen(cols=8, lines=4)
    s.draw('飛青進服三上')
    s.resize(s.lines, 5)
    self.ae('飛青', str(s.line(0)))

    s = self.create_screen(cols=6, lines=6)

    # Test basic multicell drawing
    s.reset()
    ac(0, 0, is_multicell=False)
    multicell(s, 'a')
    ac(0, 0, is_multicell=True, width=1, scale=1, subscale_n=0, x=0, y=0, text='a', natural_width=True, cursor=(1, 0))
    ac(0, 1, is_multicell=False), ac(1, 0, is_multicell=False), ac(1, 1, is_multicell=False)
    s.draw('莊')
    ac(0, 0, is_multicell=True, width=1, scale=1, subscale_n=0, x=0, y=0, text='a', natural_width=True)
    ac(1, 0, is_multicell=True, width=2, scale=1, subscale_n=0, x=0, y=0, text='莊', natural_width=True, cursor=(3, 0))
    ac(2, 0, is_multicell=True, width=2, scale=1, subscale_n=0, x=1, y=0, text='', natural_width=True)
    for x in range(s.columns):
        ac(x, 1, is_multicell=False)
    s.cursor.x = 0
    multicell(s, 'a', width=2, scale=2, subscale_n=3)
    ac(0, 0, is_multicell=True, width=2, scale=2, subscale_n=3, x=0, y=0, text='a', natural_width=False, cursor=(4, 0))
    for x in range(1, 4):
        ac(x, 0, is_multicell=True, width=2, scale=2, subscale_n=3, x=x, y=0, text='', natural_width=False)
    for x in range(0, 4):
        ac(x, 1, is_multicell=True, width=2, scale=2, subscale_n=3, x=x, y=1, text='', natural_width=False)
    def comb(x, y):
        s.reset()
        multicell(s, 'a', scale=2)
        s.cursor.x, s.cursor.y = x, y
        s.draw('\u0301')
        assert_cursor_at(x, y)
        ac(0, 0, text='a' if y else 'a\u0301', is_multicell=True)
    for y in range(2):
        for x in range(1, 3):
            comb(x, y)
    comb(0, 1)
    s.reset()
    multicell(s, 'aüa', scale=2)
    self.ae(s.cursor.x, 6)
    s = self.create_screen(cols=7 * 7, lines=7)
    multicell(s, 'a', scale=7, width=7)
    for y in range(s.lines):
        for x in range(s.columns):
            ac(x, y, is_multicell=True, x=x, y=y)

    # Test zero width roundtripping
    for preserved in '\xad\u200b\u2060':
        s.reset()
        multicell(s, f'|{preserved}|', scale=2)
        assert_cursor_at(4, 0)
        ac(0, 0, text=f'|{preserved}')

    # Test wrapping
    s = self.create_screen(cols=6, lines=6)
    s.draw('x' * (s.columns - 1))
    multicell(s, 'a', scale=2)
    ac(s.columns - 1, 0, is_multicell=False, text='', next_char_was_wrapped=True)
    s.reset()
    multicell(s, 'a', scale=2)
    s.draw('x' * s.columns)
    ac(s.cursor.x-1, s.cursor.y, is_multicell=False, text='x', next_char_was_wrapped=False)
    ac(0, 0, is_multicell=True, text='a')
    ac(0, 1, is_multicell=True, text='', y=1)

    # Test draw with cursor in a multicell
    s.reset()
    multicell(s, '12', scale=2)
    s.draw('\rx')
    ac(0, 0, is_multicell=False, text='x')
    ac(1, 0, is_multicell=False, text='')
    ac(0, 1, is_multicell=False, text='')
    ac(1, 1, is_multicell=False, text='')
    ac(2, 0, is_multicell=True, text='2')
    s.reset()
    s.draw('莊')
    s.cursor.x -= 1
    s.draw('a'), ac(0, 0, is_multicell=False), ac(1, 0, is_multicell=False)
    s.reset()
    s.draw('莊')
    s.cursor.x = 0
    s.draw('a'), ac(0, 0, is_multicell=False), ac(1, 0, is_multicell=False)
    s.reset()
    multicell(s, 'a', width=2, scale=2, subscale_n=3, subscale_d=4)
    s.cursor.x, s.cursor.y = 1, 1
    s.draw('b')
    self.ae(8, count_multicells())
    assert_cursor_at(5, 1)
    self.assertIn('b', str(s.linebuf))
    s.reset()
    s.cursor.x = 1
    s.draw('莊')
    s.cursor.x = 0
    s.draw('莊')
    ac(2, 0, is_multicell=False, text=' ')
    s.reset()
    multicell(s, 'a', scale=2)
    s.cursor.x += 1
    multicell(s, 'b', scale=2)
    s.draw('莊')
    assert_cursor_at(2, 2)
    self.assertIn('莊', str(s.linebuf))
    s.reset()
    multicell(s, 'a', scale=2)
    s.cursor.x += 1
    multicell(s, 'b', scale=2)
    assert_cursor_at(5, 0)
    s.draw('\u2716\ufe0f')
    assert_cursor_at(2, 2)
    s.reset()
    s.draw('莊')
    s.cursor.x = 0
    s.draw('b')
    self.ae(str(s.line(0)), 'b')
    s.reset()
    s.draw('莊')
    s.cursor.x = 1
    s.draw('b')
    self.ae(str(s.line(0)), ' b')

    # Test multicell with cursor in a multicell
    def big_a(x, y=0, spaces=False, skip=False):
        s.reset()
        s.cursor.x, s.cursor.y = 1, 1
        multicell(s, 'a', scale=4)
        ac(1, 1, x=0, y=0, text='a', scale=4, width=1)
        s.cursor.x, s.cursor.y = x, y
        multicell(s, 'b', scale=2)
        if skip:
            self.ae(20, count_multicells())
            assert_cursor_at(2, 4)
            self.assertIn('a', str(s.linebuf))
        else:
            ac(x, y, text='b')
            self.ae(4, count_multicells())
            for x_ in range(1, 5):
                ac(x_, 4, text=' ' if spaces else '')
    for y in (0, 1):
        big_a(0, y), big_a(1, y), big_a(2, y, spaces=True)
    big_a(2, 2, skip=True), big_a(5, 1, skip=True)

    # Test multicell with combining and flag codepoints and default width
    def seq(text, *expected):
        s.reset()
        multicell(s, text)
        i = iter(expected)
        for x in range(s.cursor.x):
            cell = s.cpu_cells(0, x)
            if cell['x'] == 0:
                q = next(i)
                ac(x, 0, text=q, width=wcswidth(q))
    seq('ab', 'a', 'b')
    flag = '\U0001f1ee\U0001f1f3'
    seq(flag + 'CD', flag, 'C', 'D')
    seq('àn̂X', 'à', 'n̂', 'X')
    seq('\U0001f1eea', '\U0001f1ee', 'a')
    del flag, seq

    # Test insert chars with multicell (aka right shift)
    s.reset()
    s.draw('a')
    s.cursor.x = 0
    s.insert_characters(1)
    assert_line('\0a\0\0\0\0')
    s.reset()
    multicell(s, 'a', width=2)
    s.cursor.x = 0
    s.insert_characters(1)
    assert_line('\0a_\0\0\0')
    s.reset()
    multicell(s, 'a', width=2)
    s.cursor.x = 0
    s.insert_characters(2)
    assert_line('\0\0a_\0\0')
    s.reset()
    multicell(s, 'a', width=2)
    s.cursor.x = 1
    s.insert_characters(1)
    assert_line('\0\0\0\0\0\0')
    s.reset()
    s.cursor.x = 3
    multicell(s, 'a', width=2)
    s.cursor.x = 0
    s.insert_characters(1)
    assert_line('\0\0\0\0a_')
    s.reset()
    s.cursor.x = s.columns - 2
    multicell(s, 'a', width=2)
    s.cursor.x = 0
    s.insert_characters(1)
    assert_line('\0\0\0\0\0\0')
    # multiline
    s.reset()
    s.draw('a')
    multicell(s, 'b', scale=2)
    assert_line('ab_\0\0\0')
    assert_line('\0__\0\0\0', 1)
    s.cursor.x, s.cursor.y = 0, 0
    s.insert_characters(1)
    assert_line('\0a\0\0\0\0')
    assert_line('\0\0\0\0\0\0', 1)
    s.reset()
    multicell(s, 'a', scale=2)
    s.cursor.x = 3
    s.insert_characters(1)
    assert_line('a_\0\0\0\0')
    assert_line('__\0\0\0\0', 1)

    # Test delete chars with multicell (aka left shift)
    s.reset()
    s.draw(' 允许')
    s.cursor.x = 0
    s.delete_characters(1)
    for x in range(4):
        ac(x, 0, width=2)
    s.reset()
    multicell(s, 'a', width=2)
    s.cursor.x = 0
    s.delete_characters(1)
    assert_line('\0\0\0\0\0\0')
    s.reset()
    multicell(s, 'a', width=2)
    s.cursor.x = 1
    s.delete_characters(1)
    assert_line('\0\0\0\0\0\0')
    s.reset()
    s.draw('ab')
    multicell(s, 'a', width=2)
    s.cursor.x = 0
    s.delete_characters(2)
    assert_line('a_\0\0\0\0')
    s.reset()
    s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
    s.cursor.x = 0
    s.delete_characters(1)
    assert_line('b_c\0\0\0')
    s.reset()
    s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
    s.cursor.x = 0
    s.delete_characters(1)
    assert_line('b_c\0\0\0')
    s.reset(), s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
    s.cursor.x = 0
    s.delete_characters(2)
    assert_line('\0c\0\0\0\0')
    s.reset(), s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
    s.cursor.x = 1
    s.delete_characters(1)
    assert_line('a\0c\0\0\0')
    s.reset(), s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
    s.cursor.x = 2
    s.delete_characters(1)
    assert_line('a\0c\0\0\0')
    # multiline
    s.reset()
    s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    assert_line('ab_c\0\0')
    assert_line('\0__\0\0\0', 1)
    s.cursor.x, s.cursor.y = 0, 0
    s.delete_characters(1)
    assert_line('\0\0c\0\0\0')
    assert_line('\0\0\0\0\0\0', 1)
    s.reset()
    multicell(s, 'a', scale=2)
    s.cursor.x = 3
    s.delete_characters(1)
    assert_line('a_\0\0\0\0')
    assert_line('__\0\0\0\0', 1)

    # Erase characters (aka replace with null)
    s.reset()
    s.cursor.x = 1
    s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    s.cursor.x = 0
    s.erase_characters(1)
    assert_line('\0ab_c\0')
    s.erase_characters(2)
    assert_line('\0\0b_c\0')
    assert_line('\0\0__\0\0', 1)
    s.erase_characters(3)
    assert_line('\0\0\0\0c\0')
    assert_line('\0\0\0\0\0\0', 1)

    # Erase in line
    for x in (1, 2):
        s.reset()
        s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
        s.cursor.x = x
        s.erase_in_line(0)
        assert_line('a\0\0\0\0\0')
        s.reset()
        s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
        s.cursor.x = x
        s.erase_in_line(1)
        assert_line('\0\0\0c\0\0')
    s.reset()
    s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    s.erase_in_line(2)
    for y in (0, 1):
        assert_line('\0\0\0\0\0\0', y)
    s.reset()
    s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    s.cursor.y = 1
    s.erase_in_line(2)
    assert_line('a\0\0c\0\0', 0)
    assert_line('\0\0\0\0\0\0', 1)

    # Clear scrollback
    s.reset()
    s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    for i in range(s.lines):
        s.index()
    s.cursor.y = 0
    assert_line('\0__\0\0\0')
    s.clear_scrollback()
    assert_line('\0\0\0\0\0\0')

    # Erase in display
    for x in (1, 2):
        s.reset(), s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
        s.cursor.x = x
        s.erase_in_display(0)
        assert_line('a\0\0\0\0\0')
    s.reset(), s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    s.cursor.x, s.cursor.y = 2, 1
    s.erase_in_display(0)
    assert_line('a\0\0c\0\0', 0)
    assert_line('\0\0\0\0\0\0', 1)
    s.reset(), s.draw('a'), multicell(s, 'b', scale=2), s.draw('c')
    for i in range(s.lines):
        s.index()
    s.erase_in_display(22)
    assert_line('ab_c\0\0', -2)
    assert_line('\0__\0\0\0', -1)
    self.ae(s.historybuf.line(1).as_ansi(), f'a\x1b]{TEXT_SIZE_CODE};s=2;b\x07c')
    self.ae(s.historybuf.line(0).as_ansi(), ' ')

    # Insert lines
    s.reset()
    multicell(s, 'a', scale=2)
    s.cursor.x, s.cursor.y = 0, s.lines - 2
    multicell(s, 'b', scale=2)
    s.cursor.x, s.cursor.y = 0, 1
    s.insert_lines(1)
    for y in range(s.lines):
        assert_line('\0' * s.columns, y)
    s.reset()
    multicell(s, 'a', scale=2)
    s.insert_lines(2)
    assert_line('\0' * s.columns, 0)
    assert_line('a_\0\0\0\0', 2)

    # Delete lines
    s.reset()
    multicell(s, 'a', scale=2)
    s.cursor.y = 1
    multicell(s, 'b', scale=2)
    s.delete_lines(1)
    for y in range(s.lines):
        assert_line('\0' * s.columns, y)

    # ansi output
    def ta(expected):
        actual = as_ansi().rstrip()[3:]
        self.ae(expected, actual)
        s.reset()
        parse_bytes(s, actual.encode())
        actual2 = as_ansi().rstrip()[3:]
        self.ae(expected, actual2)
        s.reset()

    s.reset()
    multicell(s, 'a', width=2, scale=3, subscale_n=1, subscale_d=2, vertical_align=3, horizontal_align=3)
    ta(f'\x1b]{TEXT_SIZE_CODE};w=2:s=3:n=1:d=2:v=3:h=3;a\x07')
    s.draw('a')
    multicell(s, 'b', width=2)
    s.draw('c')
    ta(f'a\x1b]{TEXT_SIZE_CODE};w=2;b\x07c')
    multicell(s, 'a')
    s.cursor.fg = as_rgb(0xffffff)
    multicell(s, 'b')
    ta('a\x1b[38:2:255:255:255mb')
    multicell(s, 'a', scale=2)
    multicell(s, 'b', scale=2)
    ta(f'\x1b]{TEXT_SIZE_CODE};s=2;ab\x07')
    multicell(s, '😀a', scale=2)
    ta(f'\x1b]{TEXT_SIZE_CODE};s=2;😀a\x07')
    multicell(s, '😀', scale=2)
    multicell(s, 'b', width=1, scale=2)
    ta(f'\x1b]{TEXT_SIZE_CODE};s=2;😀\x07\x1b]{TEXT_SIZE_CODE};w=1:s=2;b\x07')
    multicell(s, 'a', scale=2)
    s.cursor.fg = as_rgb(0xffffff)
    multicell(s, 'b', scale=2)
    ta(f'\x1b]{TEXT_SIZE_CODE};s=2;a\x07\x1b[38:2:255:255:255m\x1b]{TEXT_SIZE_CODE};s=2;b\x07\n\x1b[m\x1b[38:2:255:255:255m')
    multicell(s, 'a', scale=3)
    multicell(s, 'b', scale=2)
    ta(f'\x1b]{TEXT_SIZE_CODE};s=3;a\x07\x1b]{TEXT_SIZE_CODE};s=2;b\x07')

    # rewrap with multicells
    s = self.create_screen(cols=6, lines=6, scrollback=20)
    o = s.lines, s.columns
    def reset():
        s.resize(*o)
        s.reset()
        s.clear_scrollback()

    def mc(x=None, y=None):
        if x is not None:
            s.cursor.x = x
        if y is not None:
            s.cursor.y = y

    reset()
    multicell(s, 'a', scale=2)
    before = as_ansi()
    s.resize(s.lines + 1, s.columns)
    self.ae(before.rstrip(), as_ansi().rstrip())

    reset()
    s.draw('a' * (s.columns - 2) + '😛' + 'bb')
    mc(4, 0)
    s.resize(s.lines, s.columns-1)
    self.ae('\x1b[maaaa\x1b[m😛bb', as_ansi().rstrip())
    assert_cursor_at(0, 1)
    reset()
    s.draw('a' * (s.columns - 2) + '😛' + 'bb')
    mc(0, 1)
    s.resize(s.lines, s.columns-2)
    assert_cursor_at(2, 1)
    self.ae('\x1b[maaaa\x1b[m😛bb', as_ansi().rstrip())
    reset()
    s.draw('a' * (s.columns - 2) + '😛' + 'bb')
    mc(5, 0)
    s.resize(s.lines, s.columns-3)
    self.ae('\x1b[maaa\x1b[ma😛\x1b[mbb', as_ansi().rstrip()) # ]]]]]]]
    assert_cursor_at(2, 1)

    def resize(lines, cols, cursorx=None, cursory=None):
        mc(cursorx, cursory)
        before = s.cursor.x, s.cursor.y
        cell = s.cpu_cells(s.cursor.y, s.cursor.x)
        cell.pop('next_char_was_wrapped')
        s.resize(lines, cols)
        ncell = s.cpu_cells(s.cursor.y, s.cursor.x)
        ncell.pop('next_char_was_wrapped')
        self.ae(cell, ncell, f'Cursor moved from: {before} to {(s.cursor.x, s.cursor.y)}')

    reset()
    multicell(s, 'a', scale=3), s.draw('b'*(s.columns-3))
    resize(s.lines, s.columns-1, 5, 0)
    self.ae(f'\x1b[m\x1b]{TEXT_SIZE_CODE};s=3;a\x07bb\x1b[mb', as_ansi().rstrip())  # ]]
    ac(0, 0, is_multicell=True)
    ac(0, 1, is_multicell=True)
    ac(3, 1, is_multicell=False, text='b')
    reset()
    s.draw('X'), multicell(s, 'a', scale=3), s.draw('12345')
    resize(s.lines, s.columns-1, 4, 0)
    self.ae(f'\x1b[mX\x1b]{TEXT_SIZE_CODE};s=3;a\x071\x1b[m23\x1b[m45', as_ansi().rstrip())  # ]]
    for y in (0, 1):
        ac(0, y, is_multicell=False), ac(1, y, is_multicell=True), ac(3, y, is_multicell=True)
    ac(0, 1, is_multicell=False, text='2'), ac(4, 1, is_multicell=False, text='3')

    reset()
    s.draw('a'*(s.columns - 2)), s.draw('😛'), s.linefeed(), s.carriage_return(), s.draw('123')
    resize(s.lines, s.columns-1, 5, 0)
    self.ae('\x1b[maaaa\x1b[m😛\n\x1b[m123', as_ansi().rstrip()) # ]]]]]]]

    reset()
    s.draw('a'*(s.columns - 1)), s.draw('😛'), s.draw('bcd')
    resize(s.lines, s.columns + 1, 0, 1)
    self.ae('\x1b[maaaaa😛\x1b[mbcd', as_ansi().rstrip()) # ]]]]]]]

    reset()
    s.draw('a'*s.columns), s.draw('😛'), s.draw('bcd')
    resize(s.lines, s.columns + 1, 0, 1)
    self.ae('\x1b[maaaaaa\x1b[m😛bcd', as_ansi().rstrip()) # ]]]]]]]
    ac(s.columns-1, 0, next_char_was_wrapped=True)
    s.resize(s.lines, s.columns + 1)
    self.ae('\x1b[maaaaaa😛\x1b[mbcd', as_ansi().rstrip()) # ]]]]]]]

    reset()
    s.draw('a'*(s.columns - 1)), multicell(s, 'X', scale=2), s.draw('bcd')
    resize(s.lines, s.columns + 1, 0, 2)
    self.ae(f'\x1b[maaaaa\x1b]{TEXT_SIZE_CODE};s=2;X\x07\x1b[mbcd', as_ansi().rstrip()) # ]]]]]]]
    for y in (0, 1):
        for x in (1, 2):
            ac(s.columns-x, y, is_multicell=True)
        for x in (0, 1):
            ac(x, y, is_multicell=False)
    reset()
    s.draw('a'*(s.columns - 1)), multicell(s, 'X', scale=2), s.draw('bcd1234!')
    s.resize(s.lines, s.columns + 2)
    self.ae(f'\x1b[maaaaa\x1b]{TEXT_SIZE_CODE};s=2;X\x07b\x1b[mcd1234\x1b[m!', as_ansi().rstrip()) # ]]]]]]]
    for y in (0, 1):
        for x in (1, 2):
            ac(s.columns-x -1, y, is_multicell=True)
        for x in (0, 1):
            ac(x, y, is_multicell=False)

    reset()
    multicell(s, 'X', scale=4), s.draw('abc')
    resize(3, 3, 5, 0)
    self.ae('\x1b[mabc', as_ansi().rstrip()) # ]]]]]]]
    reset()
    multicell(s, 'X', width=4), s.draw('abc')
    resize(3, 3, 4, 0)
    self.ae('\x1b[mabc', as_ansi().rstrip()) # ]]]]]]]
    reset()
    s.draw('1'), multicell(s, 'X', width=4), s.draw('abc')
    resize(3, 3, 5, 0)
    self.ae('\x1b[m1ab\x1b[mc', as_ansi().rstrip()) # ]]]]]]]

    reset()
    suffix = '112233445555556666667'
    multicell(s, 'X', scale=4), s.draw(suffix)
    self.ae(str(s.historybuf), 'X11')  # X is split between the buffers
    resize(6, s.columns+1, 0, 5)
    self.ae(str(s.historybuf), 'X112')
    self.ae(str(s.linebuf.line(0)), '233')
    for y in range(3):
        for x in range(4):
            ac(x, y, is_multicell=True, x=x, y=y+1)
    reset()
    multicell(s, 'X', scale=4), s.draw(suffix)
    resize(6, s.columns-1, 0, 5)
    self.ae(f'X{suffix}', as_text(s, add_history=True))
    self.ae(str(s.historybuf), '1\nX1')
    self.ae(str(s.linebuf.line(0)), '2')
    for y in range(-2, 2):
        for x in range(4):
            ac(x, y, is_multicell=True, x=x, y=y+2, text='X' if (x, y) == (0, -2) else '')

    reset()
    multicell(s, 'AB', scale=2), s.draw('11223333334444445555556666667')
    self.ae(str(s.historybuf), 'AB11')  # AB is split between the buffers
    resize(6, s.columns+1, 0, 5)
    self.ae(str(s.historybuf), 'AB112')
    self.ae(str(s.linebuf.line(0)), '233')
    for x in range(2):
        ac(x, -1, is_multicell=True, x=x, y=0, text='' if x else 'A')
        ac(x, 0, is_multicell=True, x=x, y=1, text='')
    for x in range(2, 4):
        ac(x, -1, is_multicell=True, x=x-2, y=0, text='' if x > 2 else 'B')
        ac(x, 0, is_multicell=True, x=x-2, y=1, text='')

    # selections
    s = self.create_screen(lines=5, cols=8)

    def p(x=0, y=0, in_left_half_of_cell=True):
        return (x, y, in_left_half_of_cell)

    def ss(start, end, rectangle_select=False, extend_mode=EXTEND_CELL):
        s.start_selection(start[0], start[1], rectangle_select, extend_mode, start[2])
        s.update_selection(end[0], end[1], end[2])

    def asl(*ranges, bp=1):
        actual = s.current_selections()
        def as_lists(x):
            a = []
            for y in range(s.lines):
                a.append(x[y*s.columns: (y+1)*s.columns ])
            return a

        expected = bytearray(s.lines * s.columns)
        for (y, x1, x2) in ranges:
            pos = y * s.columns
            for x in range(x1, x2 + 1):
                expected[pos + x] = bp
        for i, (e, a) in enumerate(zip(as_lists(bytes(expected)), as_lists(actual))):
            self.ae(e, a, f'Row: {i}')

    def ast(*expected, strip_trailing_whitespace=False, as_ansi=False):
        actual = s.text_for_selection(as_ansi, strip_trailing_whitespace)
        self.ae(expected, actual)

    def asa(*expected, strip_trailing_whitespace=False):
        ast(*expected, as_ansi=True, strip_trailing_whitespace=strip_trailing_whitespace)

    s.reset()
    s.draw('a'), multicell(s, 'b', width=2), s.draw('c')
    ss(p(), p(x=1, in_left_half_of_cell=False))
    asl((0, 0, 2))
    ast('ab')
    asa(f'a\x1b]{TEXT_SIZE_CODE};w=2;b\x07', '\x1b[m')
    ss(p(x=2), p(x=3, in_left_half_of_cell=False))
    asl((0, 1, 3))
    ast('bc')
    asa(f'\x1b]{TEXT_SIZE_CODE};w=2;b\x07c', '\x1b[m')

    s.reset()
    s.draw('a'), multicell(s, 'b', scale=2), s.draw('c'), multicell(s, 'd', scale=2)
    ss(p(), p(x=4, in_left_half_of_cell=False))
    asl((0, 0, 5), (1, 1, 2), (1, 4, 5))
    ast('abcd')
    asa(f'a\x1b]{TEXT_SIZE_CODE};s=2;b\x07c\x1b]{TEXT_SIZE_CODE};s=2;d\x07', '\x1b[m')
    ss(p(y=1, x=1), p(y=1, x=1, in_left_half_of_cell=False))
    asl((0, 1, 2), (1, 1, 2))
    ast('b')
    asa(f'\x1b]{TEXT_SIZE_CODE};s=2;b\x07', '\x1b[m')
    ss(p(y=1, x=0), p(y=1, x=1, in_left_half_of_cell=False))  # empty leading cell before multiline on y=1
    asl((0, 1, 2), (1, 0, 2))
    ast('b')
    asa(f'\x1b]{TEXT_SIZE_CODE};s=2;b\x07', '\x1b[m')

    s.reset()
    multicell(s, 'X', scale=2), s.draw('123456abcd')
    for x in (0, 1, 2):
        ss(p(x=x), p(x=3, y=1, in_left_half_of_cell=False))
        asl((0, 0, 7), (1, 0, 3))
        ast('X123456', 'ab')
        asa(f'\x1b]{TEXT_SIZE_CODE};s=2;X\x07123456', 'ab', '\x1b[m')
    ss(p(y=1), p(y=1, x=3, in_left_half_of_cell=False))
    asl((0, 0, 1), (1, 0, 3))
    ast('X', 'ab')
    asa(f'\x1b]{TEXT_SIZE_CODE};s=2;X\x07', 'ab', '\x1b[m')

    s = self.create_screen(lines=5, cols=24)

    s.reset()
    multicell(s, 'ab cd ef', scale=2)
    ss(p(6, 1), p(9, 0, in_left_half_of_cell=False))
    ast('cd')
    asa(f'\x1b]{TEXT_SIZE_CODE};s=2;cd\x07', '\x1b[m')

    s.reset()
    multicell(s, 'ab', scale=2), s.draw('  '), multicell(s, 'cd', scale=2), s.draw('  '), multicell(s, 'ef', scale=2)
    ss(p(6, 1), p(9, 0, in_left_half_of_cell=False))
    ast('cd')

    # Hyperlinks
    s = self.create_screen(lines=5, cols=8)
    asu = partial(asl, bp=2)
    def set_link(url=None, id=None):
        parse_bytes(s, '\x1b]8;id={};{}\x1b\\'.format(id or '', url or '').encode('utf-8'))

    s.reset()
    set_link('url-a', 'a')
    multicell(s, 'ab', scale=2)
    for y in (0, 1):
        self.ae(s.line(y).hyperlink_ids(), (1, 1, 1, 1, 0, 0, 0, 0))
    for y in (0, 1):
        for x in (0, 3):
            self.ae('url-a', s.hyperlink_at(x, y))
    asu((0, 0, 3), (1, 0, 3))
    self.ae(s.current_url_text(), 'ab')

    # URL detection
    s = self.create_screen(cols=60)

    s.reset()
    url = 'http://moo.com'
    multicell(s, url, scale=2)
    s.detect_url(0, 0)
    self.ae(s.current_url_text(), url)
    asu((0, 0, len(url)*2 - 1), (1, 0, len(url)*2 - 1))
    # More tests for URL detection are in screen.py in detect_url()
