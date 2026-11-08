#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import random

from kitty.fast_data_types import Cursor

from .base import BaseTest, draw_multicell, parse_bytes

RED_BOLD = b'\x1b[1;31m'
TRUECOLOR_BG = b'\x1b[4:3;48;2;1;2;3m'
RESET = b'\x1b[m'


class TestStyles(BaseTest):
    def assert_styles_consistent(self, s, msg=''):
        mismatches = s.test_verify_styles()
        if mismatches:
            self.fail(f'{msg} Cell style mismatches: {mismatches}')

    def test_style_interning(self):
        s = self.create_screen(cols=10, lines=3)
        self.ae(s.style_table_info()['count'], 1)
        self.ae(s.style_table_info()['max_count'], 1 << 18)
        s.draw('ab')
        self.ae(s.cell_style_idx(0, 0), 0)
        parse_bytes(s, RED_BOLD)
        s.draw('cd')
        red = s.cell_style_idx(0, 2)
        self.assertNotEqual(red, 0)
        self.ae(s.cell_style_idx(0, 3), red)
        parse_bytes(s, TRUECOLOR_BG)
        s.draw('e')
        tc = s.cell_style_idx(0, 4)
        self.assertNotIn(tc, (0, red))
        parse_bytes(s, RESET + RED_BOLD)
        s.draw('f')
        self.ae(s.cell_style_idx(0, 5), red, 'the same style must be interned to the same index')
        parse_bytes(s, RESET)
        s.draw('g')
        self.ae(s.cell_style_idx(0, 6), 0)
        self.ae(s.style_table_info()['count'], 3)
        # Changing the cursor via the Python API must be picked up
        s.cursor.bold = True
        s.draw('h')
        self.assertNotIn(s.cell_style_idx(0, 7), (0, red, tc))
        s.cursor.bold = False
        s.draw('i')
        self.ae(s.cell_style_idx(0, 8), 0)

    def test_style_of_erased_cells(self):
        s = self.create_screen(cols=6, lines=4)
        s.draw('abcdef' * 4)
        parse_bytes(s, b'\x1b[44m')
        s.cursor_position(2, 1)
        s.erase_in_line(0)
        blue = s.cell_style_idx(1, 0)
        self.assertNotEqual(blue, 0)
        self.ae({s.cell_style_idx(1, x) for x in range(s.columns)}, {blue})
        s.cursor_position(3, 2)
        s.erase_characters(2)
        self.ae(s.cell_style_idx(2, 1), blue)
        self.ae(s.cell_style_idx(2, 2), blue)
        self.ae(s.cell_style_idx(2, 0), 0)
        s.insert_characters(1)
        self.ae(s.cell_style_idx(2, 1), blue)
        s.delete_characters(1)
        self.ae(s.cell_style_idx(2, s.columns - 1), blue)
        s.erase_in_display(2)
        self.ae({s.cell_style_idx(y, x) for y in range(s.lines) for x in range(s.columns)}, {blue})
        self.assert_styles_consistent(s)

    def test_style_of_widened_cell(self):
        s = self.create_screen(cols=6, lines=2)
        parse_bytes(s, RED_BOLD)
        s.draw('❤')  # a narrow char that becomes wide with VS16
        parse_bytes(s, RESET)
        s.draw('️')
        self.ae(s.cell_style_idx(0, 0), s.cell_style_idx(0, 1))
        self.assertNotEqual(s.cell_style_idx(0, 0), 0)
        self.assert_styles_consistent(s)

    def test_style_after_resize(self):
        for cols, lines in ((4, 3), (12, 8), (9, 2), (3, 6)):
            with self.subTest(cols=cols, lines=lines):
                s = self.create_screen(cols=8, lines=4, scrollback=10)
                for i, prefix in enumerate((RED_BOLD, TRUECOLOR_BG, b'\x1b[44m', RESET)):
                    parse_bytes(s, prefix)
                    s.draw(f'{i}ab日cde')
                    s.carriage_return(), s.linefeed()
                parse_bytes(s, b'\x1b[45m')
                s.erase_in_line(0)
                s.resize(lines, cols)
                self.assert_styles_consistent(s)

    def test_style_with_deccara(self):
        s = self.create_screen(cols=6, lines=3)
        s.draw('abcdef' * 3)
        parse_bytes(s, b'\x1b[2;2;3;4;1;31$r')
        self.ae(s.cell_style_idx(0, 0), 0)
        styled = s.cell_style_idx(1, 1)
        self.assertNotEqual(styled, 0)
        self.ae(s.line(1).cursor_from(1).bold, True)
        parse_bytes(s, b'\x1b[2;2;3;4;22$r')
        self.ae(s.line(1).cursor_from(1).bold, False)
        self.assert_styles_consistent(s)

    def test_style_with_line_apis(self):
        s = self.create_screen(cols=6, lines=3)
        s.draw('abcdef')
        line = s.line(0)
        c = Cursor()
        c.bold = True
        c.fg = (2 << 8) | 1
        line.apply_cursor(c, 1, 2)
        self.ae(line.cursor_from(1).bold, True)
        self.ae(line.cursor_from(2).fg, (2 << 8) | 1)
        self.ae(line.cursor_from(3).bold, False)
        line.apply_cursor(c, 4, 1, True)
        self.ae(str(line)[4], ' ')
        self.ae(line.cursor_from(4).bold, True)
        line.set_char(0, 'x', 1, c)
        self.ae(line.cursor_from(0).bold, True)
        line.set_attribute('italic', 1)
        self.ae({line.cursor_from(x).italic for x in range(s.columns)}, {True})
        line.clear_text(0, s.columns)
        self.ae(line.cursor_from(0).bold, True, 'clear_text must preserve formatting')
        line = s.line(1)
        c.x = 0
        line.set_text('hello', 0, 5, c)
        self.ae(line.cursor_from(4).fg, (2 << 8) | 1)
        self.assert_styles_consistent(s)

    def test_style_of_multicell(self):
        s = self.create_screen(cols=8, lines=4)
        parse_bytes(s, TRUECOLOR_BG)
        draw_multicell(s, 'A', scale=2)
        draw_multicell(s, 'B', width=2)
        idx = s.cell_style_idx(0, 0)
        self.assertNotEqual(idx, 0)
        self.ae({s.cell_style_idx(y, x) for y in range(2) for x in range(2)}, {idx})
        self.ae({s.cell_style_idx(0, x) for x in range(2, 4)}, {idx})
        self.assert_styles_consistent(s)

    def all_cell_styles(self, s):
        # The style of every cell in history and on screen, by value
        ans = []
        for y in range(s.historybuf.count - 1, -1, -1):
            line = s.historybuf.line(y)
            ans.append(tuple(self.style_of(line.cursor_from(x)) for x in range(s.columns)))
        for y in range(s.lines):
            line = s.line(y)
            ans.append(tuple(self.style_of(line.cursor_from(x)) for x in range(s.columns)))
        return ans

    def style_of(self, c):
        return (c.fg, c.bg, c.decoration_fg, c.bold, c.italic, c.reverse, c.strikethrough, c.dim, c.decoration)

    def test_style_lossless_gc(self):
        s = self.create_screen(cols=6, lines=3, scrollback=4)
        for i in range(12):
            parse_bytes(s, f'\x1b[38;5;{i + 1};4{i % 8}m'.encode())
            s.draw('ab')
            if i % 3 == 2:
                s.carriage_return(), s.linefeed()

        def ansi():
            return [s.historybuf.line(y).as_ansi() for y in range(s.historybuf.count)] + [s.line(y).as_ansi() for y in range(s.lines)]

        before, ansi_before, count_before = self.all_cell_styles(s), ansi(), s.style_table_info()['count']
        s.test_gc_style_table()
        self.ae(self.all_cell_styles(s), before)
        self.ae(ansi(), ansi_before)
        self.ae(s.style_table_info()['count'], count_before, 'all styles are live so none must be freed')
        # Erase a line, freeing its styles
        parse_bytes(s, RESET)
        s.cursor_position(1, 1)
        s.erase_in_line(2)
        before = self.all_cell_styles(s)
        s.test_gc_style_table()
        self.ae(self.all_cell_styles(s), before)
        self.ae(s.style_table_info()['count'], count_before - 3)
        self.assert_styles_consistent(s)

    def test_style_gc_when_full(self):
        s = self.create_screen(cols=6, lines=2, scrollback=0)
        s.test_set_style_table_limit(6)
        for i in range(5):
            parse_bytes(s, f'\x1b[38;5;{i + 1}m'.encode())
            s.draw('x')
        self.ae(s.style_table_info()['count'], 6)
        parse_bytes(s, RESET)
        s.erase_in_line(2)
        s.cursor_position(2, 1)
        # Drawing a new style when the table is full collects garbage, freeing the erased styles
        for i in range(5):
            parse_bytes(s, f'\x1b[38;5;{i + 100}m'.encode())
            s.draw('y')
        self.ae([s.line(1).cursor_from(x).fg for x in range(5)], [((i + 100) << 8) | 1 for i in range(5)])
        self.assertGreaterEqual(s.style_table_info()['gc_count'], 1)
        self.assertFalse(s.style_table_info()['degraded'])
        self.assert_styles_consistent(s)

    def test_style_lossy_gc_of_scrollback(self):
        s = self.create_screen(cols=4, lines=2, scrollback=50)
        s.test_set_style_table_limit(32)
        colors = []
        for i in range(60):
            # Colors that are distinct but close, so that reducing their precision frees space
            r, g, b = 100 + i, 50, 200 - i
            colors.append((r << 24) | (g << 16) | (b << 8) | 2)
            parse_bytes(s, f'\x1b[38;2;{r};{g};{b}m'.encode())
            s.draw(str(i % 10))
            s.carriage_return(), s.linefeed()
        info = s.style_table_info()
        self.assertGreaterEqual(info['gc_count'], 1)
        self.assertFalse(info['degraded'])
        # The cell on screen has its exact style
        self.ae(s.line(0).cursor_from(0).fg, colors[-1])
        # Cells in the scrollback have their colors approximately
        for y in range(s.historybuf.count):
            fg = s.historybuf.line(y).cursor_from(0).fg
            expected = colors[-2 - y]
            self.ae(fg & 0xFF, 2, f'line {y}')
            for shift in (8, 16, 24):
                self.assertLessEqual(abs(((fg >> shift) & 0xFF) - ((expected >> shift) & 0xFF)), 8, f'line {y}')
        self.assert_styles_consistent(s)

    def test_style_degraded(self):
        s = self.create_screen(cols=24, lines=2, scrollback=0)
        s.test_set_style_table_limit(16)
        expected = []
        for i in range(24):
            expected.append(((i * 10) << 24) | 2)
            parse_bytes(s, f'\x1b[38;2;{i * 10};0;0m'.encode())
            s.draw('x')
        info = s.style_table_info()
        self.assertTrue(info['degraded'])
        self.assertLessEqual(info['count'], 16)
        # Styles that do not fit are replaced by the closest existing style or the default style
        for x in range(24):
            fg = s.line(0).cursor_from(x).fg
            if x < 15:
                self.ae(fg, expected[x])
            else:
                self.assertTrue(fg == 0 or abs((fg >> 24) - (expected[x] >> 24)) < 64, f'{x}: {fg:x}')
        self.assert_styles_consistent(s)

    def test_style_caches_after_gc(self):
        s = self.create_screen(cols=8, lines=3, scrollback=2)
        parse_bytes(s, b'\x1b[38;5;10m')
        s.draw('a')
        parse_bytes(s, b'\x1b7')  # DECSC saves the style
        parse_bytes(s, b'\x1b[38;5;20m')
        s.draw('b')
        parse_bytes(s, b'\x1b[38;5;30m')
        s.draw('c')
        s.erase_in_line(2)  # free the styles, so indices change on collection
        s.test_gc_style_table()
        s.cursor_position(2, 1)
        s.draw('d')
        self.ae(s.line(1).cursor_from(0).fg, (30 << 8) | 1)
        parse_bytes(s, b'\x1b8')  # DECRC
        s.draw('e')
        self.ae(s.line(0).cursor_from(1).fg, (10 << 8) | 1)
        self.assert_styles_consistent(s)

    def test_style_random_operations(self):
        ops = (
            lambda s, r: parse_bytes(s, r.choice((RED_BOLD, TRUECOLOR_BG, RESET, b'\x1b[44m', b'\x1b[7m', b'\x1b[38;5;99m'))),
            lambda s, r: s.draw(''.join(r.choice('ab日é́️︎❤😀 ') for _ in range(r.randint(1, 12)))),
            lambda s, r: (s.carriage_return(), s.linefeed()),
            lambda s, r: s.erase_in_line(r.randint(0, 2)),
            lambda s, r: s.erase_in_display(r.randint(0, 2)),
            lambda s, r: s.erase_characters(r.randint(1, 3)),
            lambda s, r: s.insert_characters(r.randint(1, 3)),
            lambda s, r: s.delete_characters(r.randint(1, 3)),
            lambda s, r: s.cursor_position(r.randint(1, 5), r.randint(1, 8)),
            lambda s, r: parse_bytes(s, f'\x1b[{r.randint(1, 3)};{r.randint(1, 4)};{r.randint(2, 5)};{r.randint(3, 8)};1;32$r'.encode()),
            lambda s, r: parse_bytes(s, r.choice((b'\x1b[4h', b'\x1b[4l', b'\x1b[2b', b'\x1b[?1049h', b'\x1b[?1049l', b'\x1b[L', b'\x1b[M'))),
            lambda s, r: draw_multicell(s, r.choice('A日'), scale=r.randint(1, 2)),
            lambda s, r: s.resize(r.randint(2, 6), r.randint(3, 10)),
            lambda s, r: s.test_gc_style_table(r.choice((0, 0, 4, 2))),
            lambda s, r: parse_bytes(s, f'\x1b[38;2;{r.randint(0, 255)};{r.randint(0, 255)};{r.randint(0, 255)}m'.encode()),
        )
        for seed in range(60):
            r = random.Random(seed)
            s = self.create_screen(cols=8, lines=5, scrollback=8)
            if seed % 2:
                s.test_set_style_table_limit(r.randint(3, 12))
            for i in range(80):
                op = r.choice(ops)
                op(s, r)
                if i % 10 == 0:
                    self.assert_styles_consistent(s, f'seed={seed} op={i}')
            self.assert_styles_consistent(s, f'seed={seed}')

    def test_style_copies_between_style_tables(self):
        from kitty.fast_data_types import HistoryBuf, LineBuf

        def styled(bold=False, fg=0):
            c = Cursor()
            c.bold = bold
            c.fg = fg
            return c

        src, dest = LineBuf(2, 4), LineBuf(2, 4)
        # Make the style indices of the two tables differ
        dest.line(0).apply_cursor(styled(fg=(5 << 8) | 1), 0, 4)
        red_bold = styled(True, (1 << 8) | 1)
        src.line(1).apply_cursor(red_bold, 0, 2)
        dest.copy_old(src)
        line = dest.line(1)
        for x in range(2):
            self.ae((line.cursor_from(x).bold, line.cursor_from(x).fg), (True, (1 << 8) | 1))
        self.ae((line.cursor_from(2).bold, line.cursor_from(2).fg), (False, 0))
        other = LineBuf(1, 4)
        other.line(0).apply_cursor(styled(fg=(6 << 8) | 1), 0, 4)
        src.copy_line_to(1, other.line(0))
        self.ae(other.line(0).cursor_from(0).fg, (1 << 8) | 1)
        src.line(1).copy_char(1, other.line(0), 3)
        self.ae(other.line(0).cursor_from(3).bold, True)
        hb = HistoryBuf(3, 4)
        hb.push(LineBuf(1, 4).line(0))
        hb.push(src.line(1))
        self.ae(hb.line(0).cursor_from(0).fg, (1 << 8) | 1)
        self.ae(hb.line(0).cursor_from(3).fg, 0)

    def test_style_table_reset_when_unused(self):
        s = self.create_screen(cols=6, lines=3, scrollback=4)
        for i in range(5):
            parse_bytes(s, f'\x1b[38;5;{i + 1}m'.encode())
            s.draw('x')
        info = s.style_table_info()
        self.ae(info['count'], 6)
        # Erasing with a style still in use on screen does not reset
        s.erase_in_display(2)
        self.ae(s.style_table_info()['count'], 6)
        parse_bytes(s, RESET)
        s.erase_in_display(2)
        info2 = s.style_table_info()
        self.ae(info2['count'], 1)
        self.assertNotEqual(info2['generation'], info['generation'])
        # Styles in the scrollback prevent a reset
        parse_bytes(s, RED_BOLD)
        s.draw('abc')
        for i in range(4):
            s.carriage_return(), s.linefeed()
        parse_bytes(s, RESET)
        s.erase_in_display(2)
        self.assertGreater(s.style_table_info()['count'], 1)
        s.erase_in_display(3)
        self.ae(s.style_table_info()['count'], 1)
        # A hard reset
        parse_bytes(s, RED_BOLD)
        s.draw('abc')
        parse_bytes(s, b'\x1bc')
        self.ae(s.style_table_info()['count'], 1)
        # Drawing after a reset works, including with the cached cursor style
        parse_bytes(s, RED_BOLD)
        s.draw('d')
        self.assertTrue(s.line(0).cursor_from(0).bold)
        self.assert_styles_consistent(s)

    def test_style_of_line_copies_after_gc(self):
        s = self.create_screen(cols=6, lines=3, scrollback=2)
        parse_bytes(s, RED_BOLD)
        s.draw('abc')
        copy = s.linebuf.create_line_copy(0)
        self.assertTrue(copy.cursor_from(0).bold)
        view = s.line(0)
        s.test_gc_style_table()
        # Views into the screen are remapped by the collection
        self.assertTrue(view.cursor_from(0).bold)
        # Copies are not, so using their formatting is an error
        for f in (lambda: copy.cursor_from(0), copy.as_ansi, lambda: copy.apply_cursor(Cursor(), 0, 1), lambda: copy.set_attribute('bold', 1)):
            self.assertRaises(ValueError, f)
        self.ae(str(copy), 'abc')  # the text is still usable
        # Copying a whole line into the copy makes its formatting valid again
        s.linebuf.copy_line_to(0, copy)
        self.assertTrue(copy.cursor_from(0).bold)
        self.assert_styles_consistent(s)
