#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import tempfile

from kitty.fast_data_types import DECAWM, DECCOLM, DECOM, IRM, SCROLL_LINE, VT_PARSER_BUFFER_SIZE, Color, ColorProfile, Cursor
from kitty.marks import marker_from_function, marker_from_regex, marker_from_text
from kitty.window import pagerhist

from .base import BaseTest, draw_multicell, parse_bytes


class TestScreen(BaseTest):
    def test_wide_character_after_scaled_text_collision(self) -> None:
        for lines in (2, 4):
            with self.subTest(lines=lines):
                s = self.create_screen(cols=4, lines=lines)
                s.cursor_position(1, 2)
                draw_multicell(s, 'X', scale=2)
                lower_row = str(s.line(1))
                s.cursor_position(2, 1)
                s.draw('界')
                row = min(2, lines - 1)
                self.ae((s.cursor.x, s.cursor.y), (2, row))
                self.ae(str(s.line(row)), '界')
                if lines == 4:
                    self.ae(str(s.line(1)), lower_row)
        # grapheme clusters must not be split by the cursor move
        for text in ('\U0001f1fa\U0001f1f8', '\U0001f468‍\U0001f469'):
            with self.subTest(text=text):
                s = self.create_screen(cols=4, lines=4)
                s.cursor_position(1, 2)
                draw_multicell(s, 'X', scale=2)
                s.cursor_position(2, 1)
                s.draw(text)
                self.ae((s.cursor.x, s.cursor.y), (2, 2))
                self.ae(s.cpu_cells(2, 0)['text'], text)
        s = self.create_screen(cols=4, lines=4)
        s.cursor_position(1, 4)
        s.draw('\U0001f468‍\U0001f469')
        self.ae((s.cursor.x, s.cursor.y), (2, 1))
        self.ae(s.cpu_cells(1, 0)['text'], '\U0001f468‍\U0001f469')

    def test_wide_collision_at_scroll_margin(self) -> None:
        for alternate in (False, True):
            with self.subTest(alternate=alternate):
                s = self.create_screen(cols=4, lines=6)
                if alternate:
                    s.toggle_alt_screen()
                s.draw('top')
                s.cursor_position(6, 1)
                s.draw('last')
                parse_bytes(s, b'\x1b[2;4r')
                s.cursor_position(3, 2)
                draw_multicell(s, 'X', scale=2)
                s.cursor_position(4, 1)
                s.select_graphic_rendition(31)
                s.draw('界\u0301a')
                self.ae((s.cursor.x, s.cursor.y), (3, 3))
                self.ae(str(s.line(3)), '界\u0301a')
                self.ae(str(s.line(0)), 'top')
                self.ae(str(s.line(5)), 'last')
                for x in (0, 1, 2):
                    self.ae(s.line(3).cursor_from(x).fg, (1 << 8) | 1)

    def test_draw_fast(self):
        s = self.create_screen()

        # Test in line-wrap, non-insert mode
        s.draw('a' * 5)
        self.ae(str(s.line(0)), 'a' * 5)
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        s.draw('b' * 7)
        self.assertTrue(s.linebuf.is_continued(1))
        self.assertTrue(s.linebuf.is_continued(2))
        self.ae(str(s.line(0)), 'a' * 5)
        self.ae(str(s.line(1)), 'b' * 5)
        self.ae(str(s.line(2)), 'b' * 2)
        self.ae(s.cursor.x, 2), self.ae(s.cursor.y, 2)
        s.draw('c' * 15)
        self.ae(str(s.line(0)), 'b' * 5)
        self.ae(str(s.line(1)), 'bbccc')

        # Now test without line-wrap
        s.reset(), s.reset_dirty()
        s.reset_mode(DECAWM)
        s.draw('0123456789')
        self.ae(str(s.line(0)), '01239')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        s.draw('ab')
        self.ae(str(s.line(0)), '0123b')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)

        # Now test in insert mode
        s.reset(), s.reset_dirty()
        s.set_mode(IRM)
        s.draw('12345' * 5)
        s.cursor_move(5)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 4)
        s.reset_dirty()
        s.draw('ab')
        self.ae(str(s.line(4)), 'ab123')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))

    def test_draw_batched_ascii_run(self):
        # The batched fast path for runs of printable ASCII in draw_text_loop
        # must behave identically to drawing char by char

        # a run crossing multiple line wraps
        s = self.create_screen()
        s.draw('abcdefghijkl')
        self.ae(str(s.line(0)), 'abcde')
        self.ae(str(s.line(1)), 'fghij')
        self.ae(str(s.line(2)), 'kl')
        self.assertTrue(s.linebuf.is_continued(1))
        self.assertTrue(s.linebuf.is_continued(2))
        self.ae((s.cursor.x, s.cursor.y), (2, 2))

        # without line-wrap the run must stop at the right margin and
        # overwrite the last column
        s = self.create_screen()
        s.reset_mode(DECAWM)
        s.draw('abcdefgh')
        self.ae(str(s.line(0)), 'abcdh')
        self.ae((s.cursor.x, s.cursor.y), (5, 0))

        # insert mode must bypass the batch and insert per char
        s = self.create_screen()
        s.draw('12345')
        s.cursor_position(1, 1)
        s.set_mode(IRM)
        s.draw('abc')
        self.ae(str(s.line(0)), 'abc12')
        self.ae((s.cursor.x, s.cursor.y), (3, 0))

        # charset translation must still be applied to every char of a run
        s = self.create_screen()
        parse_bytes(s, b'\x1b(0qqq\x1b(B')
        self.ae(str(s.line(0)), '─' * 3)

        # overwriting the first cell of a wide char nukes the whole wide char
        s = self.create_screen()
        s.draw('ニチ')
        s.cursor_position(1, 1)
        s.draw('ab')
        self.ae(str(s.line(0)), 'abチ')
        # overwriting the second cell of a wide char replaces it with spaces
        s = self.create_screen()
        s.draw('ニチ')
        s.cursor_position(1, 2)
        s.draw('a')
        self.ae(str(s.line(0)), ' aチ')

        # a run drawn over a multiline multicell char must be handled by the
        # scalar path
        s = self.create_screen()
        draw_multicell(s, 'X', scale=2)
        before_line1 = str(s.line(1))
        s.cursor_position(1, 1)
        s.draw('abc')
        self.ae(str(s.line(0)), 'abc')
        self.ae(str(s.line(1)), before_line1)
        # drawing on a lower row of a multiline char moves the cursor past it
        s = self.create_screen()
        draw_multicell(s, 'X', scale=2)
        s.cursor_position(2, 1)
        s.draw('ab')
        self.ae(str(s.line(0)), 'X')
        self.ae((s.cursor.x, s.cursor.y), (4, 1))

        # REP must repeat the last char of a batched run
        s = self.create_screen()
        s.draw('abc')
        parse_bytes(s, b'\x1b[2b')
        self.ae(str(s.line(0)), 'abccc')

        # a combining char following a run attaches to the run's last char,
        # also when the run ends exactly at the right margin
        s = self.create_screen()
        s.draw('ab́cd')
        self.ae(str(s.line(0)), 'ab́cd')
        self.ae((s.cursor.x, s.cursor.y), (4, 0))
        s = self.create_screen()
        s.draw('abcdé')
        self.ae(str(s.line(0)), 'abcdé')
        self.ae((s.cursor.x, s.cursor.y), (5, 0))

        # a wide ZWJ emoji following a run
        s = self.create_screen()
        s.draw('ab\U0001f468‍\U0001f466')
        self.ae(str(s.line(0)), 'ab\U0001f468‍\U0001f466')
        self.ae((s.cursor.x, s.cursor.y), (4, 0))

        # the active hyperlink must be applied to all cells of a run
        s = self.create_screen()
        parse_bytes(s, '\x1b]8;;http://x.com\x1b\\'.encode('utf-8'))
        s.draw('abc')
        parse_bytes(s, '\x1b]8;;\x1b\\'.encode('utf-8'))
        s.draw('d')
        self.ae(s.line(0).hyperlink_ids(), (1, 1, 1, 0, 0))

        # SGR attributes must be applied to all cells of a run
        s = self.create_screen()
        parse_bytes(s, b'\x1b[31mabc\x1b[39md')
        self.ae(s.line(0).as_ansi(), '\x1b[31mabc\x1b[39md')

        # drawing over a selection must clear it
        s = self.create_screen()
        s.draw('hello')
        s.start_selection(0, 0)
        s.update_selection(4, 0)
        self.ae(''.join(s.text_for_selection()), 'hello')
        s.cursor_position(1, 1)
        s.draw('bye')
        self.ae(s.text_for_selection(), ())
        # also when the run wraps onto the selected line
        s = self.create_screen()
        s.draw('hello')
        s.carriage_return(), s.linefeed()
        s.draw('world')
        s.start_selection(0, 1)
        s.update_selection(4, 1)
        self.ae(''.join(s.text_for_selection()), 'world')
        s.cursor_position(1, 1)
        s.draw('a' * (s.columns + 1))
        self.ae(s.text_for_selection(), ())

        # scrolling must keep an existing selection anchored to its content
        s = self.create_screen()
        for i in range(s.lines):
            if i:
                s.carriage_return(), s.linefeed()
            s.draw(str(i) * s.columns)
        s.start_selection(0, 0)
        s.update_selection(4, 0)
        self.ae(''.join(s.text_for_selection()), '00000')
        s.linefeed()
        self.ae(''.join(s.text_for_selection()), '00000')

        # tabs at various offsets, exercising the memoized tab text lookup
        s = self.create_screen(cols=32)
        s.draw('a\tbc\td\te')
        self.ae((s.cursor.x, s.cursor.y), (25, 0))
        self.ae(s.line(0).as_ansi(), 'a\tbc\td\te')
        # a tab spanning more columns than the memo covers
        s = self.create_screen(cols=40)
        parse_bytes(s, b'\x1b[3g')  # clear all tab stops
        s.draw('a\tb')
        self.ae((s.cursor.x, s.cursor.y), (40, 0))
        self.ae(s.line(0).as_ansi(), 'a\tb')
        # spaces immediately after a tab stop must not be swallowed (issue #10609)
        s = self.create_screen(cols=20)
        s.draw('x\t y')
        s.carriage_return(), s.linefeed()
        s.draw('x\t\t  z')
        self.ae(s.line(0).as_ansi(), 'x\t y')
        self.ae(str(s.line(0)), 'x\t y')
        self.ae(s.line(1).as_ansi(), 'x\t\t  z')
        self.ae(str(s.line(1)), 'x\t\t  z')

    def test_draw_char(self):
        # Test in line-wrap, non-insert mode
        s = self.create_screen()
        s.draw('ココx')
        self.ae(str(s.line(0)), 'ココx')
        self.ae(tuple(map(s.line(0).width, range(5))), (2, 0, 2, 0, 1))
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        s.draw('ニチハ')
        self.ae(str(s.line(0)), 'ココx')
        self.ae(str(s.line(1)), 'ニチ')
        self.ae(str(s.line(2)), 'ハ')
        self.ae(s.cursor.x, 2), self.ae(s.cursor.y, 2)
        s.draw('Ƶ̧\u0308')
        self.ae(str(s.line(2)), 'ハƵ̧\u0308')
        self.ae(s.cursor.x, 3), self.ae(s.cursor.y, 2)
        s.draw('xy'), s.draw('\u0306')
        self.ae(str(s.line(2)), 'ハƵ̧\u0308xy\u0306')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 2)
        s.draw('c' * 15)
        self.ae(str(s.line(0)), 'ニチ')
        s.reset()
        qt = 'a' * s.columns + '\u0306'
        s.draw(qt)
        self.ae(str(s.line(0)), qt)
        s.reset()
        s.draw(qt[:-1]), s.draw(qt[-1])
        self.ae(str(s.line(0)), qt)
        s.reset()
        s.draw(qt[:-1]), s.linefeed(), s.carriage_return(), s.draw(qt[-1])
        self.ae(str(s.line(0)), qt[:-1])

        # Now test without line-wrap
        s.reset(), s.reset_dirty()
        s.reset_mode(DECAWM)
        s.draw('0\u030612345\u03066789\u0306')
        self.ae(str(s.line(0)), '0\u03061239\u0306')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        s.draw('ab\u0306')
        self.ae(str(s.line(0)), '0\u0306123b\u0306')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)

        # Now test in insert mode
        s.reset(), s.reset_dirty()
        text = '1\u03062345'
        s.set_mode(IRM)
        s.draw(text * 5)
        self.ae(str(s.line(0)), text)
        s.cursor_move(5)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 4)
        s.reset_dirty()
        s.draw('a\u0306b')
        self.ae(str(s.line(4)), 'a\u0306b1\u030623')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))

        # Test drawing of tabs
        s = self.create_screen(cols=32)
        txt = 'a\tb'
        s.draw(txt)
        ln = s.line(0)
        self.ae(txt, ln.as_ansi())

    def test_rep(self):
        s = self.create_screen()
        s.draw('a')
        parse_bytes(s, b'\x1b[b')
        self.ae(str(s.line(0)), 'aa')
        parse_bytes(s, b'\x1b[3b')
        self.ae(str(s.line(0)), 'a' * 5)
        s.draw(' ')
        parse_bytes(s, b'\x1b[3b')
        self.ae(str(s.line(1)), ' ' * 4)

    def test_scroll_huge_count(self):
        # CSI Ps S (Scroll Up) with a huge count must not busy-loop for
        # billions of iterations. Scrolling up by more than the number of
        # lines blanks the region, so the result is identical to scrolling
        # by the screen height. Regression test for a hang on e.g. CSI
        # 2147483647 S.
        s = self.create_screen()
        for i in range(s.lines):
            s.draw(str(i))
            if i + 1 < s.lines:
                parse_bytes(s, b'\r\n')
        parse_bytes(s, b'\x1b[2147483647S')  # INT_MAX scroll up
        for i in range(s.lines):
            self.ae(str(s.line(i)).strip(), '')

    def test_fractional_scroll(self):
        s = self.create_screen(cols=5, lines=5, scrollback=10, cell_height=20, options={'pixel_scroll': True})
        for i in range(15):
            s.draw(str(i))
            parse_bytes(s, b'\r\n')
        self.assertGreaterEqual(s.historybuf.count, 4)
        s.fractional_scroll(-0.75)
        s.fractional_scroll(-0.75)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (1, 10))
        s.fractional_scroll(0.5)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (1, 0))
        s.scroll_to_absolute(0.0)
        total = 0
        for i in range(4):
            s.fractional_scroll(-0.75)
            total += 15
            self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (total // 20, total % 20))
        for i in range(4):
            s.fractional_scroll(0.75)
            total -= 15
            self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (total // 20, total % 20))
        self.ae(total, 0)
        s.scroll_to_absolute(5.0)
        self.assertFalse(s.fractional_scroll(float('nan')))
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (5, 0))
        s.scroll_to_absolute(float('nan'))
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (5, 0))
        self.assertRaises(OverflowError, s.fractional_scroll, 10**400)
        self.assertRaises(OverflowError, s.scroll_to_absolute, 10**400)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (5, 0))
        self.assertTrue(s.fractional_scroll(float('-inf')))
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (s.historybuf.count, 0))
        self.assertTrue(s.fractional_scroll(float('inf')))
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (0, 0))
        s.scroll_to_absolute(-3.5)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (0, 0))
        s.scroll_to_absolute(float('inf'))
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (s.historybuf.count, 0))

        # Pausing rendering must not change the pixel scrolled geometry,
        # otherwise programs using synchronized output cause jitter when the
        # user is pixel scrolled into the scrollback, see #10794
        s.scroll_to_absolute(2.5)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (2, 10))
        s.start_selection(0, 0)
        s.update_selection(2, 1)
        before = s.current_selections()
        self.ae(len(before), (s.lines + 1) * s.columns)
        self.assertTrue(s.pause_rendering(True, 5000))
        self.ae(s.current_selections(), before)
        self.assertTrue(s.pause_rendering(False))
        self.ae(s.current_selections(), before)

    def test_emoji_skin_tone_modifiers(self):
        s = self.create_screen()
        q = chr(0x1F469) + chr(0x1F3FD)
        s.draw(q)
        self.ae(str(s.line(0)), q)
        self.ae(s.cursor.x, 2)

    def test_regional_indicators(self):
        s = self.create_screen()
        flag = '\U0001f1ee\U0001f1f3'
        s.draw(flag)
        self.ae(str(s.line(0)), flag)
        self.ae(s.cursor.x, 2)
        s = self.create_screen()
        s.draw('a'), s.draw(flag[0]), s.draw('b')
        self.ae(str(s.line(0)), 'a' + flag[0] + 'b')
        self.ae(s.cursor.x, 4)

    def test_zwj(self):
        s = self.create_screen(cols=20)
        q = '\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466'
        s.draw(q)
        self.ae(q, str(s.line(0)))
        self.ae(s.cursor.x, 2)
        for x in '\u200b\u200c\u200d':
            s.reset()
            q = f'X{x}Y'
            s.draw(q)
            self.ae(q, str(s.line(0)))
            self.ae(s.cursor.x, 2)

    def test_unicode_in_range_buffer_growth(self):
        # Enough combining chars to force the text buffer to grow past its initial capacity
        s = self.create_screen(cols=300, lines=2)
        q = 300 * ('e' + 23 * '\u0301')  # 23 is the max number of combining chars per cell
        s.draw(q)
        self.ae(q, str(s.line(0)))
        s.start_selection(0, 0)
        s.update_selection(299, 0)
        self.ae(q, ''.join(s.text_for_selection()))

    def test_char_manipulation(self):
        s = self.create_screen()

        def init():
            s.reset(), s.reset_dirty()
            s.draw('abcde')
            s.cursor.bold = True
            s.cursor_move(4)
            s.reset_dirty()
            self.ae(s.cursor.x, 1)

        init()
        s.insert_characters(2)
        self.ae(str(s.line(0)), 'a  bc')
        self.assertTrue(s.line(0).cursor_from(1).bold)
        s.cursor_move(1)
        s.insert_characters(20)
        self.ae(str(s.line(0)), '')
        s.draw('xココ')
        s.cursor_move(5)
        s.reset_dirty()
        s.insert_characters(1)
        self.ae(str(s.line(0)), ' xコ')
        c = Cursor()
        c.italic = True
        s.line(0).apply_cursor(c, 0, 5)
        self.ae(s.line(0).width(2), 2)
        self.assertTrue(s.line(0).cursor_from(2).italic)
        self.assertFalse(s.line(0).cursor_from(2).bold)

        init()
        s.delete_characters(2)
        self.ae(str(s.line(0)), 'ade')
        self.assertTrue(s.line(0).cursor_from(4).bold)
        self.assertFalse(s.line(0).cursor_from(2).bold)
        s = self.create_screen()
        s.set_margins(1, 2)
        s.cursor.y = 3
        s.draw('abcde')
        s.cursor.x = 0
        s.delete_characters(2)
        self.ae('cde', str(s.line(s.cursor.y)))

        init()
        s.erase_characters(2)
        self.ae(str(s.line(0)), 'a  de')
        self.assertTrue(s.line(0).cursor_from(1).bold)
        self.assertFalse(s.line(0).cursor_from(4).bold)
        s.erase_characters(20)
        self.ae(str(s.line(0)), 'a')

        init()
        s.erase_in_line()
        self.ae(str(s.line(0)), 'a')
        self.assertTrue(s.line(0).cursor_from(1).bold)
        self.assertFalse(s.line(0).cursor_from(0).bold)
        init()
        s.erase_in_line(1)
        self.ae(str(s.line(0)), '  cde')
        init()
        s.erase_in_line(2)
        self.ae(str(s.line(0)), '')
        init()
        s.erase_in_line(2, True)
        self.ae((False, False, False, False, False), tuple(map(lambda i: s.line(0).cursor_from(i).bold, range(5))))

    def test_erase_in_screen(self):
        s = self.create_screen()

        def init():
            s.reset()
            s.draw('12345' * 5)
            s.reset_dirty()
            s.cursor.x, s.cursor.y = 2, 1
            s.cursor.bold = True
            self.ae(continuations(s), (True, True, True, True, False))

        def all_lines(s):
            return tuple(str(s.line(i)) for i in range(s.lines))

        def continuations(s):
            return tuple(s.line(i).last_char_has_wrapped_flag() for i in range(s.lines))

        init()
        s.erase_in_display(0)
        self.ae(all_lines(s), ('12345', '12', '', '', ''))
        self.ae(continuations(s), (True, False, False, False, False))

        init()
        s.erase_in_display(1)
        self.ae(all_lines(s), ('', '   45', '12345', '12345', '12345'))
        self.ae(continuations(s), (False, True, True, True, False))

        init()
        s.erase_in_display(2)
        self.ae(all_lines(s), ('', '', '', '', ''))
        self.assertTrue(s.line(0).cursor_from(1).bold)
        self.ae(continuations(s), (False, False, False, False, False))

        init()
        s.erase_in_display(2, True)
        self.ae(all_lines(s), ('', '', '', '', ''))
        self.ae(continuations(s), (False, False, False, False, False))
        self.assertFalse(s.line(0).cursor_from(1).bold)

    def test_cursor_movement(self):
        s = self.create_screen()
        s.draw('12345' * 5)
        s.reset_dirty()
        s.cursor_up(2)
        self.ae((s.cursor.x, s.cursor.y), (4, 2))
        s.cursor_up1()
        self.ae((s.cursor.x, s.cursor.y), (0, 1))
        s.cursor_forward(3)
        self.ae((s.cursor.x, s.cursor.y), (3, 1))
        s.cursor_move()
        self.ae((s.cursor.x, s.cursor.y), (2, 1))
        s.cursor_down()
        self.ae((s.cursor.x, s.cursor.y), (2, 2))
        s.cursor_down1(5)
        self.ae((s.cursor.x, s.cursor.y), (0, 4))

        s = self.create_screen()
        s.draw('12345' * 5)
        s.index()
        self.ae(str(s.line(4)), '')
        for i in range(4):
            self.ae(str(s.line(i)), '12345')
        s.draw('12345' * 5)
        s.cursor_up(5)
        s.reverse_index()
        self.ae(str(s.line(0)), '')
        for i in range(1, 5):
            self.ae(str(s.line(i)), '12345')

    def test_backspace_wide_characters(self):
        s = self.create_screen()
        s.draw('⛅')
        self.ae(s.cursor.x, 2)
        s.backspace()
        s.draw(' ')
        s.backspace()
        self.ae(s.cursor.x, 1)

    def test_resize(self):
        from kitty.window import as_text

        def at():
            return as_text(s, add_history=True)

        def ac():
            return s.line(s.cursor.y)[s.cursor.x]

        # test that a wrapped line split by the history buffer is re-stitched
        s = self.create_screen(cols=4, lines=4, scrollback=4)
        text = ''
        for i in range(s.lines + 1):
            if i == 2:
                text += 'abcd'
            else:
                text += str(i + 1) * s.columns
        s.draw(text)
        self.assertTrue(s.historybuf.endswith_wrap())
        s.cursor.x, s.cursor.y = 1, 1
        self.ae(ac(), 'b')
        s.resize(s.lines, s.columns + 2)
        self.assertTrue(s.historybuf.endswith_wrap())
        self.ae(str(s.historybuf), '111122')
        self.ae(at(), text + '\n')
        self.ae((s.cursor.x, s.cursor.y), (3, 0))
        self.ae(ac(), 'b')
        s = self.create_screen(cols=4, lines=4, scrollback=4)
        s.draw('1111222'), s.linefeed(), s.carriage_return()
        s.draw('333344445555')
        s.resize(s.lines, s.columns + 2)
        self.ae(str(s.historybuf), '111122')
        self.ae(str(s.line(0)), '2')
        self.ae(at(), '1111222\n333344445555\n')
        s = self.create_screen(cols=4, lines=4, scrollback=4)
        s.draw('1111😸2'), s.linefeed(), s.carriage_return()
        s.index(), s.index()
        s.resize(s.lines, s.columns + 1)
        self.ae(str(s.historybuf), '1111')
        self.assertTrue(s.historybuf.endswith_wrap())
        self.ae(at(), '1111😸2\n\n\n')
        s = self.create_screen(cols=4, lines=4, scrollback=4)
        s.draw(text)
        s.cursor.x, s.cursor.y = 1, 1
        self.ae(ac(), 'b')
        s.resize(s.lines, s.columns * 2)
        self.ae(ac(), 'b')
        self.ae(str(s.historybuf), '11112222')
        self.ae(at(), text + '\n\n')
        self.ae((s.cursor.x, s.cursor.y), (1, 0))

        # test that trailing blank line is preserved on resize
        s = self.create_screen(cols=5, lines=5, scrollback=15)
        for i in range(3):
            s.draw(f'oo{i}'), s.index(), s.carriage_return()
        s.draw('$ pp'), s.index(), s.carriage_return()
        s.resize(s.lines, 2)
        self.assertFalse(str(s.line(s.cursor.y)))
        self.assertFalse(s.cursor.x)
        # test that only happens when last line is not continued
        s = self.create_screen(cols=5, lines=5, scrollback=15)
        for i in range(3):
            s.draw(f'oo{i}'), s.index(), s.carriage_return()
        s.draw('p' * (s.columns + 2)), s.carriage_return()
        s.resize(s.lines, 2)
        self.assertTrue(str(s.line(s.cursor.y)))
        s = self.create_screen(cols=5, lines=5, scrollback=15)
        s.draw('12345'), s.carriage_return(), s.index()
        s.resize(s.lines, s.columns - 1)
        self.ae(('1234', '5', ''), tuple(str(s.line(i)) for i in range(s.cursor.y + 1)))

        s = self.create_screen(scrollback=6)
        s.draw(''.join([str(i) * s.columns for i in range(s.lines)]))
        s.resize(3, 10)
        self.ae(str(s.line(0)), '0' * 5 + '1' * 5)
        self.ae(str(s.line(1)), '2' * 5 + '3' * 5)
        self.ae(str(s.line(2)), '4' * 5)
        s.resize(5, 1)
        self.ae(str(s.line(0)), '4')
        self.ae(str(s.historybuf), '3\n3\n3\n3\n3\n2')
        s = self.create_screen(scrollback=20)
        s.draw(''.join(str(i) * s.columns for i in range(s.lines * 2)))
        self.ae(str(s.linebuf), '55555\n66666\n77777\n88888\n99999')
        before = at()
        s.resize(5, 2)
        self.ae(before, at())
        self.ae(str(s.linebuf), '88\n88\n89\n99\n99')
        s = self.create_screen()
        s.draw('a' * s.columns)
        s.carriage_return(), s.linefeed()
        s.draw('bb')
        s.resize(s.lines, s.columns - 2)
        self.ae(str(s.linebuf), 'aaa\naa\nbb\n\n')
        s.cursor.y = s.cursor.x = 0
        s.draw('x' * len(str(s.line(0))))
        s.carriage_return(), s.linefeed()
        s.draw('x' * len(str(s.line(1))))
        s.resize(s.lines, s.columns + 4)
        self.ae(str(s.linebuf), 'xxx\nxx\nbb\n\n')
        s = self.create_screen()
        c = s.callbacks
        parse_bytes(s, b'\x1b[?2048$p')  # ]
        self.ae(c.wtcbuf, b'\x1b[?2048;2$y')  # ]
        c.clear()
        parse_bytes(s, b'\x1b[?2048h\x1b[?2048$p')  # ]]
        self.ae(c.wtcbuf, b'\x1b[?2048;1$y')  # ]
        self.ae(c.num_of_resize_events, 1)
        parse_bytes(s, b'\x1b[?2048h')  # ]
        self.ae(c.num_of_resize_events, 2)

    def test_visibility_reports(self):
        s = self.create_screen()
        c = s.callbacks
        parse_bytes(s, b'\x1b[?2033$p')  # ]
        self.ae(c.wtcbuf, b'\x1b[?2033;2$y')  # ]
        c.clear()
        parse_bytes(s, b'\x1b[?998n')  # ]
        self.ae(c.wtcbuf, b'\x1b[?999;1n')  # ]
        c.clear()
        parse_bytes(s, b'\x1b[?2033h\x1b[?2033$p')  # ]]
        self.ae(c.wtcbuf, b'\x1b[?999;1n\x1b[?2033;1$y')  # ]]
        c.clear()
        parse_bytes(s, b'\x1b[?2033h')  # ]
        self.ae(c.wtcbuf, b'\x1b[?999;1n')  # ]
        c.clear()
        parse_bytes(s, b'\x1b[?2033l\x1b[?2033$p')  # ]]
        self.ae(c.wtcbuf, b'\x1b[?2033;2$y')  # ]

    def test_cursor_position_report_origin_mode(self):
        s = self.create_screen(cols=10, lines=10)

        def report(private=''):
            s.callbacks.clear()
            parse_bytes(s, f'\x1b[{private}6n'.encode())  # ]
            return s.callbacks.wtcbuf.decode()

        for top in (1, 3):
            for origin in (False, True):
                parse_bytes(s, f'\x1b[{top};8r\x1b[?6{"h" if origin else "l"}'.encode())  # ]]
                for row in (1, 4):
                    parse_bytes(s, f'\x1b[{row};5H'.encode())  # ]
                    for private in ('', '?'):
                        with self.subTest(top=top, origin=origin, row=row, private=private):
                            self.ae(report(private), f'\x1b[{private}{row};5R')  # ]
        # cursor addressing is clamped to the bottom margin in origin mode
        parse_bytes(s, b'\x1b[3;8r\x1b[?6h\x1b[99;5H')  # ]]]
        self.ae(report(), '\x1b[6;5R')  # ]
        # pending wrap at the bottom margin stays on the same row
        parse_bytes(s, b'\x1b[6;10Hx')  # ]
        self.ae(report(), '\x1b[6;10R')  # ]
        # pending wrap inside the region moves to the start of the next row
        parse_bytes(s, b'\x1b[2;10Hx')  # ]
        self.ae(report(), '\x1b[3;1R')  # ]
        # pending wrap at the bottom of the screen outside the region
        parse_bytes(s, b'\x1b[?6l\x1b[10;10Hx')  # ]]
        self.ae(report(), '\x1b[10;10R')  # ]

    def test_da1(self):
        s = self.create_screen()
        parse_bytes(s, b'\x1b[c\x1b[0c')  # ]]
        self.ae(s.callbacks.da1, ['?62;52;c', '?62;52;c'])  # ]]
        s.callbacks.clear()
        self.create_screen(options={'clipboard_control': 'read-clipboard'})
        parse_bytes(s, b'\x1b[c')  # ]]
        self.ae(s.callbacks.da1, ['?62;c'])  # ]]

    def test_cursor_after_resize(self):

        def draw(text, end_line=True):
            s.draw(text)
            if end_line:
                s.linefeed(), s.carriage_return()

        s = self.create_screen()
        draw('123'), draw('123')
        y_before = s.cursor.y
        s.resize(s.lines, s.columns - 1)
        self.ae(y_before, s.cursor.y)

        s = self.create_screen(cols=5, lines=8)
        draw('one')
        draw('two three four five |||', end_line=False)
        s.resize(s.lines + 2, s.columns + 2)
        y = s.cursor.y
        self.assertIn('|', str(s.line(y)))

        s = self.create_screen()
        draw('a')
        x_before = s.cursor.x
        s.resize(s.lines - 1, s.columns)
        self.ae(x_before, s.cursor.x)

        s = self.create_screen()
        s.draw('abc')
        b = s.cursor.x
        s.resize(7, s.columns)
        self.assertEqual(s.cursor.x, b)
        s.cursor.x = 0
        s.resize(5, s.columns)
        self.assertEqual(s.cursor.x, 0)

    def test_scrollback_fill_after_resize(self):
        def prepare_screen(content=()):
            ans = self.create_screen(options={'scrollback_fill_enlarged_window': True})
            for line in content:
                ans.draw(line)
                ans.linefeed()
                ans.carriage_return()
            return ans

        def assert_lines(*lines):
            return self.ae(lines, tuple(str(s.line(i)) for i in range(s.lines)))

        # test the reverse scroll function
        s = prepare_screen(map(str, range(6)))
        assert_lines('2', '3', '4', '5', '')
        s.reverse_scroll(2, True)
        assert_lines('0', '1', '2', '3', '4')

        # Height increased, width unchanged → pull down lines to fill new space at the top
        s = prepare_screen(map(str, range(6)))
        assert_lines('2', '3', '4', '5', '')
        dist_from_bottom = s.lines - s.cursor.y
        s.resize(7, s.columns)
        assert_lines('0', '1', '2', '3', '4', '5', '')
        self.ae(dist_from_bottom, s.lines - s.cursor.y)

        # Height increased, width increased → rewrap, pull down
        s = prepare_screen(['0', '1', '2', '3' * 15])
        assert_lines('2', '33333', '33333', '33333', '')
        s.resize(7, 12)
        assert_lines('0', '1', '2', '333333333333', '333', '', '')

        # Height increased, width decreased → rewrap, pull down if possible
        s = prepare_screen(['0', '1', '2', '3' * 5])
        assert_lines('0', '1', '2', '33333', '')
        s.resize(6, 4)
        assert_lines('0', '1', '2', '3333', '3', '')

        # Height unchanged, width increased → rewrap, pull down if possible
        s = prepare_screen(['0', '1', '2', '3' * 15])
        assert_lines('2', '33333', '33333', '33333', '')
        s.resize(s.lines, 12)
        assert_lines('1', '2', '333333333333', '333', '')

        # Height decreased, width increased → rewrap, pull down if possible
        s = prepare_screen(['0', '1', '2', '3' * 15])
        assert_lines('2', '33333', '33333', '33333', '')
        s.resize(4, 12)
        assert_lines('2', '333333333333', '333', '')

        # Height increased with large continued text
        s = self.create_screen(options={'scrollback_fill_enlarged_window': True})
        s.draw(('x' * (s.columns * s.lines * 2)) + 'abcde')
        s.carriage_return(), s.linefeed()
        s.draw('>')
        assert_lines('xxxxx', 'xxxxx', 'xxxxx', 'abcde', '>')
        s.resize(s.lines + 2, s.columns)
        assert_lines('xxxxx', 'xxxxx', 'xxxxx', 'xxxxx', 'xxxxx', 'abcde', '>')

    def test_height_resize_reuses_history(self):
        import random

        from kitty.fast_data_types import test_set_history_reuse

        def ops_for(seed, cols):
            rng = random.Random(seed)
            chars = 'abc 日😀' if seed % 2 else 'abcdef '
            ops = []
            for i in range(rng.randint(20, 80)):
                r = rng.random()
                if r < 0.35:
                    ops.append(('draw', ''.join(rng.choice(chars) for _ in range(rng.randint(0, (3 if seed % 3 else 1) * cols)))))
                elif r < 0.45:
                    ops.append(('bytes', f'\x1b[4{rng.randint(1, 7)}m{rng.choice("xyz")}\x1b[K\x1b[m'.encode()))
                elif r < 0.5:
                    if seed % 4 == 0:
                        ops.append(('mc', rng.choice('AB日'), rng.randint(2, 3)))
                elif r < 0.55:
                    ops.append(('bytes', rng.choice((b'\x1b]133;A\x07', b'\x1b]133;A;k=s\x07', b'\x1b]133;C\x07'))))
                elif r < 0.6:
                    ops.append(('bytes', b'\x1b7'))
                elif r < 0.65:
                    ops.append(('bytes', f'\x1b[{rng.randint(1, 3)}C'.encode()))
                else:
                    ops.append(('nl',))
            if rng.random() < 0.5:
                ops.append(('draw', 'x' * rng.randint(0, cols)))
            return ops

        def build(ops, cols, lines, scrollback, options):
            s = self.create_screen(cols=cols, lines=lines, scrollback=scrollback, options=options)
            for op in ops:
                if op[0] == 'draw':
                    s.draw(op[1])
                elif op[0] == 'bytes':
                    parse_bytes(s, op[1])
                elif op[0] == 'mc':
                    draw_multicell(s, op[1], scale=op[2])
                else:
                    s.carriage_return(), s.linefeed()
            return s

        def compare(a, b, msg):
            self.ae((a.lines, a.columns, a.cursor.x, a.cursor.y), (b.lines, b.columns, b.cursor.x, b.cursor.y), msg)
            self.ae(a.historybuf.count, b.historybuf.count, msg)
            for i in range(a.historybuf.count):
                self.assertTrue(a.historybuf.line(i) == b.historybuf.line(i), f'{msg} history line {i}')
                self.ae(a.historybuf.line(i).as_ansi(), b.historybuf.line(i).as_ansi(), f'{msg} history line {i}')
                self.ae(a.historybuf.is_continued(i), b.historybuf.is_continued(i), f'{msg} history line {i}')
            for i in range(a.lines):
                self.assertTrue(a.linebuf.line(i) == b.linebuf.line(i), f'{msg} line {i}')
                self.ae(a.linebuf.line(i).as_ansi(), b.linebuf.line(i).as_ansi(), f'{msg} line {i}')
                self.ae(a.linebuf.is_continued(i), b.linebuf.is_continued(i), f'{msg} line {i}')
            self.ae(a.linebuf.dirty_lines(), b.linebuf.dirty_lines(), msg)
            self.ae(a.historybuf.pagerhist_as_text(), b.historybuf.pagerhist_as_text(), msg)
            parse_bytes(a, b'\x1b8'), parse_bytes(b, b'\x1b8')
            self.ae((a.cursor.x, a.cursor.y), (b.cursor.x, b.cursor.y), f'{msg} saved cursor')

        try:
            for seed in range(300):
                rng = random.Random(seed)
                cols, lines = rng.randint(3, 12), rng.randint(2, 8)
                scrollback = rng.choice((4, 8, 30, 200))
                options = {
                    'scrollback_fill_enlarged_window': rng.random() < 0.5,
                    'scrollback_pager_history_size': rng.choice((0, 1024)),
                }
                ops = ops_for(seed, cols)
                heights = [rng.randint(1, 12) for _ in range(4)]
                test_set_history_reuse(True)
                a = build(ops, cols, lines, scrollback, options)
                test_set_history_reuse(False)
                b = build(ops, cols, lines, scrollback, options)
                for h in heights:
                    msg = f'seed={seed} height={h}'
                    test_set_history_reuse(True)
                    a.resize(h, cols)
                    test_set_history_reuse(False)
                    b.resize(h, cols)
                    compare(a, b, msg)
        finally:
            test_set_history_reuse(True)

    def test_tab_stops(self):
        # Taken from vttest/main.c
        s = self.create_screen(cols=80, lines=2)
        s.cursor_position(1, 1)
        s.clear_tab_stop(3)
        for col in range(1, s.columns - 1, 3):
            s.cursor_forward(3)
            s.set_tab_stop()
        s.cursor_position(1, 4)
        for col in range(4, s.columns - 1, 6):
            s.clear_tab_stop(0)
            s.cursor_forward(6)
        s.cursor_position(1, 7)
        s.clear_tab_stop(2)
        s.cursor_position(1, 1)
        for col in range(1, s.columns - 1, 6):
            s.tab()
            s.draw('*')
        s.cursor_position(2, 2)
        self.ae(str(s.line(0)), '\t*' * 13)
        s = self.create_screen(cols=4, lines=2)
        s.draw('aaaX\tbbbb')
        self.ae(str(s.line(0)) + str(s.line(1)), 'aaaXbbbb')
        # DECST8C: reset tab stops to every 8 columns
        s = self.create_screen(cols=20, lines=2)
        s.clear_tab_stop(3)
        s.reset_tab_stops()
        s.cursor_position(1, 1)
        s.tab()
        self.ae(s.cursor.x, 8)
        s.tab()
        self.ae(s.cursor.x, 16)
        # Verify the DECST8C escape sequence
        s = self.create_screen(cols=20, lines=2)
        s.clear_tab_stop(3)
        parse_bytes(s, b'\x1b[?5W')
        s.cursor_position(1, 1)
        s.tab()
        self.ae(s.cursor.x, 8)

        # Custom tab stops survive a window resize
        s = self.create_screen(cols=20, lines=2)
        s.clear_tab_stop(3)  # clear all
        s.cursor_position(1, 5)
        s.set_tab_stop()  # stop at column index 4
        s.cursor_position(1, 13)
        s.set_tab_stop()  # stop at column index 12
        # Grow: existing stops preserved, new columns get default every-8 stops
        s.resize(s.lines, 30)
        s.cursor_position(1, 1)
        s.tab()
        self.ae(s.cursor.x, 4)
        s.tab()
        self.ae(s.cursor.x, 12)
        s.tab()
        self.ae(s.cursor.x, 24)  # default stop in newly added columns
        # Shrink: stops within new width are preserved
        s.resize(s.lines, 15)
        s.cursor_position(1, 1)
        s.tab()
        self.ae(s.cursor.x, 4)
        s.tab()
        self.ae(s.cursor.x, 12)
        # Resize on alt screen also preserves alt-screen tab stops
        s = self.create_screen(cols=20, lines=2)
        parse_bytes(s, b'\x1b[?1049h')  # switch to alt screen ]
        s.clear_tab_stop(3)
        s.cursor_position(1, 5)
        s.set_tab_stop()
        s.resize(s.lines, 30)
        s.cursor_position(1, 1)
        s.tab()
        self.ae(s.cursor.x, 4)

    def test_backspace(self):
        s = self.create_screen()
        q = 'a' * s.columns

        def backspace(use_bs=True):
            if use_bs:  # this is how the kernel implements backspace
                s.draw('\x08 \x08')
            else:
                s.cursor_move(1)
                s.draw(' ')
                s.cursor_move(1)

        for use_bs in (True, False):
            s.reset()
            s.draw(q)
            s.draw('b')
            backspace(use_bs)
            self.ae(str(s.line(0)), q)
            self.ae(str(s.line(1)), ' ')
            self.ae(s.cursor.x, 0)
            backspace(use_bs)
            self.ae(str(s.line(0)), q[:-1] + ' ')
            self.ae(str(s.line(1)), ' ')
        # Test that CUB does not move cursor onto previous line
        s.reset()
        s.draw('a' * s.columns + 'b')
        self.ae((s.cursor.x, s.cursor.y), (1, 1))
        parse_bytes(s, b'\x1b[100D')
        self.ae((s.cursor.x, s.cursor.y), (0, 1))

    def test_margins(self):
        # Taken from vttest/main.c
        s = self.create_screen(cols=80, lines=24)

        def nl():
            s.carriage_return(), s.linefeed()

        for deccolm in (False, True):
            if deccolm:
                s.resize(24, 132)
                s.set_mode(DECCOLM)
            else:
                s.reset_mode(DECCOLM)
            region = s.lines - 6
            s.set_margins(3, region + 3)
            s.set_mode(DECOM)
            for i in range(26):
                ch = chr(ord('A') + i)
                which = i % 4
                if which == 0:
                    s.cursor_position(region + 1, 1), s.draw(ch)
                    s.cursor_position(region + 1, s.columns), s.draw(ch.lower())
                    nl()
                elif which == 1:
                    # Simple wrapping
                    s.cursor_position(region, s.columns), s.draw(chr(ord('A') + i - 1).lower() + ch)
                    # Backspace at right margin
                    s.cursor_position(region + 1, s.columns), s.draw(ch), s.backspace(), s.draw(ch.lower())
                    nl()
                elif which == 2:
                    # Tab to right margin
                    s.cursor_position(region + 1, s.columns), s.draw(ch), s.backspace(), s.backspace(), s.tab(), s.tab(), s.draw(ch.lower())
                    s.cursor_position(region + 1, 2), s.backspace(), s.draw(ch), nl()
                else:
                    s.cursor_position(region + 1, 1), nl()
                    s.cursor_position(region, 1), s.draw(ch)
                    s.cursor_position(region, s.columns), s.draw(ch.lower())
            for ln in range(2, region + 2):
                c = chr(ord('I') + ln - 2)
                before = '\t' if ln % 4 == 0 else ' '
                self.ae(c + ' ' * (s.columns - 3) + before + c.lower(), str(s.line(ln)))
            s.reset_mode(DECOM)
        # Test that moving cursor outside the margins works as expected
        s = self.create_screen(10, 10)
        s.set_margins(4, 6)
        s.cursor_position(0, 0)
        self.ae(s.cursor.y, 0)
        nl()
        self.ae(s.cursor.y, 1)
        s.cursor.y = s.lines - 1
        self.ae(s.cursor.y, 9)
        s.reverse_index()
        self.ae(s.cursor.y, 8)

    def test_sgr(self):
        s = self.create_screen()
        s.select_graphic_rendition(0, 1, 5, 37, 42)
        s.draw('a')
        c = s.line(0).cursor_from(0)
        self.assertTrue(c.bold)
        self.assertTrue(c.blink)
        self.ae(c.bg, (2 << 8) | 1)
        self.ae('\x1b[22;1;5;37;42ma', s.line(0).as_ansi())
        s.cursor_position(2, 1)
        s.select_graphic_rendition(0, 35)
        s.draw('b')
        c = s.line(1).cursor_from(0)
        self.ae(c.fg, (5 << 8) | 1)
        self.ae(c.bg, 0)
        s.cursor_position(2, 2)
        s.select_graphic_rendition(38, 2, 99, 1, 2, 3)
        s.draw('c')
        c = s.line(1).cursor_from(1)
        self.ae(c.fg, (1 << 24) | (2 << 16) | (3 << 8) | 2)

    def test_cursor_hidden(self):
        s = self.create_screen()
        s.toggle_alt_screen()
        s.cursor_visible = False
        s.toggle_alt_screen()
        self.assertFalse(s.cursor_visible)

    def test_dirty_lines(self):
        s = self.create_screen()
        self.assertFalse(s.linebuf.dirty_lines())
        s.draw('a' * (s.columns * 2))
        self.ae(s.linebuf.dirty_lines(), [0, 1])
        self.assertFalse(s.historybuf.dirty_lines())
        while not s.historybuf.count:
            s.draw('a' * (s.columns * 2))
        self.ae(s.historybuf.dirty_lines(), list(range(s.historybuf.count)))
        self.ae(s.linebuf.dirty_lines(), list(range(s.lines)))
        s.cursor.x, s.cursor.y = 0, 1
        s.insert_lines(2)
        self.ae(s.linebuf.dirty_lines(), [0, 3, 4])
        s.draw('a' * (s.columns * s.lines))
        self.ae(s.linebuf.dirty_lines(), list(range(s.lines)))
        s.cursor.x, s.cursor.y = 0, 1
        s.delete_lines(2)
        self.ae(s.linebuf.dirty_lines(), [0, 1, 2])

        s = self.create_screen()
        self.assertFalse(s.linebuf.dirty_lines())
        s.erase_in_line(0, False)
        self.ae(s.linebuf.dirty_lines(), [0])
        s.index(), s.index()
        s.erase_in_display(0, False)
        self.ae(s.linebuf.dirty_lines(), [0, 2, 3, 4])

        s = self.create_screen()
        self.assertFalse(s.linebuf.dirty_lines())
        s.insert_characters(2)
        self.ae(s.linebuf.dirty_lines(), [0])
        s.cursor.y = 1
        s.delete_characters(2)
        self.ae(s.linebuf.dirty_lines(), [0, 1])
        s.cursor.y = 2
        s.erase_characters(2)
        self.ae(s.linebuf.dirty_lines(), [0, 1, 2])

    def test_selection_as_text(self):
        s = self.create_screen()
        for i in range(2 * s.lines):
            if i != 0:
                s.carriage_return(), s.linefeed()
            s.draw(str(i) * s.columns)
        s.start_selection(0, 0)
        s.update_selection(4, 4)

        def ts(*args):
            return ''.join(s.text_for_selection(*args))

        expected = ''.join(('55555', '\n66666', '\n77777', '\n88888', '\n99999'))
        self.ae(ts(), expected)
        self.ae(ts(True), expected)
        s.scroll(2, True)
        self.ae(ts(), expected)
        self.ae(ts(True), expected)
        s.reset()
        s.draw('ab   cd')
        s.start_selection(0, 0)
        s.update_selection(1, 3)
        self.ae(ts(), ''.join(('ab   ', 'cd')))
        # soft-wrapped lines preserve trailing spaces (issue #9834)
        self.ae(ts(False, True), 'ab   cd')
        s.reset()
        s.draw('ab        cd')
        s.start_selection(0, 0)
        s.update_selection(3, 4)
        self.ae(s.text_for_selection(), ('ab   ', '     ', 'cd'))
        # soft-wrapped lines preserve trailing spaces (issue #9834)
        self.ae(s.text_for_selection(False, True), ('ab   ', '     ', 'cd'))
        s.reset()
        s.draw('a')
        s.select_graphic_rendition(32)
        s.draw('b')
        s.select_graphic_rendition(39)
        s.draw('c  xy')
        s.start_selection(0, 0)
        s.update_selection(1, 3)
        self.ae(s.text_for_selection(), ('abc  ', 'xy'))
        self.ae(s.text_for_selection(True), ('a\x1b[32mb\x1b[39mc  ', 'xy', '\x1b[m'))
        # soft-wrapped lines preserve trailing spaces in ANSI mode too (issue #9834)
        self.ae(s.text_for_selection(True, True), ('a\x1b[32mb\x1b[39mc  ', 'xy', '\x1b[m'))
        # ]]]]]]]]]]]]]]]]]]]]
        s.reset()
        s.draw('a'), s.carriage_return(), s.linefeed(), s.linefeed(), s.draw('b')
        s.start_selection(0, 0)
        s.update_selection(4, 4)
        self.ae(''.join(s.text_for_selection()), 'a\n\nb')
        self.ae(''.join(s.text_for_selection(True)), 'a\n\nb')
        # Trailing spaces on soft-wrapped lines must be preserved when strip_trailing_whitespace
        # is set: a space at the line-wrap boundary is word-separator content, not padding
        # (regression test for issue #9834)
        s.reset()
        s.draw('1234 5')  # "1234 " soft-wraps at col 4; space must survive stripping
        s.start_selection(0, 0)
        s.update_selection(4, 4)
        self.ae(s.text_for_selection(), ('1234 ', '5'))
        self.ae(s.text_for_selection(False, True), ('1234 ', '5'))
        self.ae(s.text_for_selection(True, True), ('1234 ', '5', ''))

    def test_scrollback_anchored_against_new_output(self):
        # When scrolled back, lines added to the scrollback must not move the
        # viewport. The anchoring must be applied immediately, not deferred to
        # the next render, so that synchronized update snapshots and relative
        # scrolls made before the next render see the correct position.

        def screen(scrollback=50):
            s = self.create_screen(cols=10, lines=3, scrollback=scrollback, cell_height=20, options={'pixel_scroll': True})
            for i in range(40):
                parse_bytes(s, f'row{i:03d}\r\n'.encode())
            s.update_only_line_graphics_data()
            return s

        def visible(s):
            return tuple(str(s.visual_line(y)) for y in range(s.lines))

        # Consecutive synchronized updates before a render
        for position in (10, 10.5):
            with self.subTest(position=position):
                s = screen()
                s.scroll_to_absolute(position)
                before = visible(s), s.scrolled_by, s.pixel_scroll_offset_y
                parse_bytes(s, b'\x1b[?2026hnext\r\n\x1b[?2026l\x1b[?2026hmore\r\n')
                self.ae(visible(s), before[0])
                self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (before[1] + 2, before[2]))
                self.assertTrue(s.pause_rendering(False, 0))
                s.update_only_line_graphics_data()
                self.ae(visible(s), before[0])
                self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (before[1] + 2, before[2]))

        # Relative scrolling with output received since the last render
        for scroll in ('line', 'pixels'):
            with self.subTest(scroll=scroll):
                s = screen()
                s.scroll_to_absolute(10)
                top = str(s.visual_line(0))
                parse_bytes(s, b'a\r\nb\r\nc\r\n')
                self.ae(str(s.visual_line(0)), top)
                if scroll == 'line':
                    s.scroll(SCROLL_LINE, True)
                else:
                    s.fractional_scroll(-1)
                s.update_only_line_graphics_data()
                self.ae(str(s.visual_line(1)), top)

        # The pixel offset must be cleared when pinned at the top of a full scrollback
        s = screen(scrollback=5)
        s.scroll_to_absolute(s.historybuf.count - 0.5)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (s.historybuf.count - 1, 10))
        parse_bytes(s, b'a\r\nb\r\n')
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (s.historybuf.count, 0))

        # Lines removed from the scrollback by reverse scrolling must not move the viewport
        for position in (10, 'top'):
            with self.subTest(reverse_scroll=position):
                s = screen()
                s.scroll_to_absolute(s.historybuf.count if position == 'top' else position)
                before = visible(s)
                parse_bytes(s, b'\x1b[3+T')
                self.assertLessEqual(s.scrolled_by, s.historybuf.count)
                self.ae(visible(s), before)

        # A smooth scroll animation must follow the anchoring, not jump back to
        # positions computed from where it started
        from types import SimpleNamespace

        from kitty.window import ScrollAnimation, Window

        s = screen()
        s.scroll_to_absolute(10)
        a = ScrollAnimation()
        a.start_scrolled_by = a.last_scrolled_by = s.scrolled_by
        a.total = -1
        w = SimpleNamespace(screen=s, scroll_animation=a)
        top = str(s.visual_line(0))
        Window.scroll_animation_to(w, a.start_scrolled_by - a.total * 0.5)  # type: ignore[arg-type]
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (10, 10))
        parse_bytes(s, b'a\r\nb\r\nc\r\n')
        Window.scroll_animation_to(w, a.start_scrolled_by - a.total)  # type: ignore[arg-type]
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (14, 0))
        self.ae(str(s.visual_line(1)), top)

        # A hard reset clears the scrollback, so it must also reset the scroll position
        s = screen()
        s.scroll_to_absolute(10.5)
        s.reset()
        self.ae((s.historybuf.count, s.scrolled_by, s.pixel_scroll_offset_y), (0, 0, 0))

        # Rewrapping on resize can shrink the scrollback below the scroll position
        s = self.create_screen(cols=5, lines=3, scrollback=50, cell_height=20, options={'pixel_scroll': True})
        for i in range(20):
            parse_bytes(s, f'wrapped{i:02d}\r\n'.encode())
        s.scroll_to_absolute(s.historybuf.count - 0.5)
        self.assertGreater(s.pixel_scroll_offset_y, 0)
        s.resize(3, 10)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (s.historybuf.count, 0))
        self.ae(str(s.visual_line(0)), 'wrapped00')

        # A sub-line scroll offset at the bottom keeps following new output
        s = screen()
        s.scroll_to_absolute(0.5)
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (0, 10))
        parse_bytes(s, b'a\r\nb\r\n')
        s.update_only_line_graphics_data()
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (0, 10))
        self.ae(str(s.visual_line(1)), 'b')

    def test_apply_selection_with_paused_rendering_and_scrollback(self):
        # Regression test: in 0.46.2 the paused-rendering branch of
        # apply_selection passed the (possibly negative) loop variable y
        # directly to linebuf_init_line, which interprets it as an unsigned
        # index_type and reads ~4GB out of bounds in line_attrs[idx]. The fix
        # translates to paused_y = y + scrolled_by and guards paused_y < 0.
        # Real-world trigger: a TUI sending DCS =1s (DEC synchronized output)
        # while the user has scrolled back and has an active scrollback
        # selection.
        s = self.create_screen(cols=10, lines=3, scrollback=50)
        for i in range(40):
            s.draw(f'row{i:03d}')
            s.carriage_return()
            s.linefeed()
        s.scroll(20, True)
        self.assertGreater(s.scrolled_by, 0)
        # Selection that crosses the top of the visible area into scrollback,
        # so the inner loop iterates with negative y.
        s.start_selection(0, 0)
        s.update_selection(2, 1)
        self.assertTrue(s.has_selection())
        before = s.current_selections()
        self.assertTrue(s.pause_rendering(True, 5000))
        # Must not crash and must return the same render buffer as before pausing
        result = s.current_selections()
        self.ae(result, before)
        # The visible portion of the selection must have at least one byte
        # marked (set_mask = 1 for plain selections).
        self.assertIn(1, result)

    def test_rendered_scroll_state_with_paused_rendering(self):
        # While rendering is paused, everything drawn over the frozen text
        # (images, cursor, scrollbar) must use the scroll state captured at
        # pause time, not the live one, which output can change during the pause.
        def screen(pixel_scroll=False):
            s = self.create_screen(cols=10, lines=3, scrollback=50, cell_height=20, options={'pixel_scroll': pixel_scroll})
            for i in range(40):
                parse_bytes(s, f'row{i:03d}\r\n'.encode())
            return s

        def live(s):
            return s.scrolled_by, s.pixel_scroll_offset_y, s.historybuf.count

        # Not paused: the rendered state is the live state
        s = screen()
        self.ae(s.rendered_scroll_state(), live(s))
        s.scroll(5, True)
        self.ae(s.rendered_scroll_state(), live(s))

        # Output arriving while scrolled back moves the live view to keep it anchored
        s = screen()
        s.scroll(5, True)
        captured = live(s)
        parse_bytes(s, b'\x1b[?2026h')
        for i in range(4):
            parse_bytes(s, f'new{i}\r\n'.encode())
        self.ae(s.scrolled_by, 9)
        self.ae(s.rendered_scroll_state(), captured)
        parse_bytes(s, b'\x1b[?2026l')
        self.ae(s.rendered_scroll_state(), live(s))
        self.ae(s.scrolled_by, 9)

        # Filling from the scrollback can bring the live view to the bottom
        # while the frozen frame still shows the scrollback
        s = screen()
        s.scroll(1, True)
        captured = live(s)
        parse_bytes(s, b'\x1b[?2026h\x1b[+T')
        self.ae((s.scrolled_by, s.historybuf.count), (0, captured[2] - 1))
        self.ae(s.rendered_scroll_state(), captured)
        self.assertTrue(s.pause_rendering(False))
        self.ae(s.rendered_scroll_state(), live(s))

        # Clearing the scrollback while at the bottom does not end the pause
        s = screen()
        captured = live(s)
        self.assertGreater(captured[2], 0)
        parse_bytes(s, b'\x1b[?2026h\x1b[3J')
        self.ae(s.historybuf.count, 0)
        self.ae(s.rendered_scroll_state(), captured)

        # Scrolling the view ends the pause, so the rendered state follows it
        s = screen()
        parse_bytes(s, b'\x1b[?2026h')
        s.scroll(3, True)
        self.ae(s.rendered_scroll_state(), live(s))
        self.ae(s.scrolled_by, 3)

        # Pausing at the bottom, with output that scrolls the screen
        s = screen()
        captured = live(s)
        parse_bytes(s, b'\x1b[?2026h')
        for i in range(4):
            parse_bytes(s, f'new{i}\r\n'.encode())
        self.ae(s.scrolled_by, 0)
        self.ae(s.rendered_scroll_state(), captured)

        # The pixel scroll offset is captured with the scroll position
        s = screen(pixel_scroll=True)
        s.scroll_to_absolute(10.5)
        captured = live(s)
        self.ae(captured[:2], (10, 10))
        parse_bytes(s, b'\x1b[?2026h')
        for i in range(3):
            parse_bytes(s, f'new{i}\r\n'.encode())
        self.ae((s.scrolled_by, s.pixel_scroll_offset_y), (13, 10))
        self.ae(s.rendered_scroll_state(), captured)
        self.assertTrue(s.pause_rendering(False))
        self.ae(s.rendered_scroll_state(), live(s))

        # Without pixel scroll the rendered pixel offset is always zero
        s = screen()
        s.scroll(4, True)
        parse_bytes(s, b'\x1b[?2026h')
        self.ae(s.rendered_scroll_state(), (4, 0, s.historybuf.count))

    def test_selection_uses_rendered_scroll_state(self):
        # A selection rendered during a pause must match the frozen frame even
        # though output has moved the live view
        s = self.create_screen(cols=10, lines=3, scrollback=50)
        for i in range(40):
            parse_bytes(s, f'row{i:03d}\r\n'.encode())
        s.scroll(5, True)
        s.start_selection(0, 0)
        s.update_selection(2, 1)
        before = s.current_selections()
        parse_bytes(s, b'\x1b[?2026h')
        for i in range(3):
            parse_bytes(s, f'new{i}\r\n'.encode())
        self.ae(s.scrolled_by, 8)
        self.ae(s.current_selections(), before)
        parse_bytes(s, b'\x1b[?2026l')
        after = s.current_selections()
        self.assertFalse(s.is_selection_dirty())
        self.ae(after, before)

    def test_scrollbar_geometry(self):
        def screen(pixel_scroll=False, scrollback=50):
            s = self.create_screen(cols=10, lines=3, scrollback=scrollback, cell_height=20, options={'pixel_scroll': pixel_scroll})
            for i in range(40):
                parse_bytes(s, f'row{i:03d}\r\n'.encode())
            return s

        def expected(scrolled_by, pixel_offset, count, lines=3, cell_height=20):
            return (scrolled_by + pixel_offset / cell_height) / max(1, count), lines / (lines + count)

        def check(s, scrolled_by, pixel_offset, count, msg=''):
            actual = s.scrollbar_geometry()
            exp = expected(scrolled_by, pixel_offset, count)
            for a, e in zip(actual, exp):
                self.assertAlmostEqual(a, e, places=5, msg=msg)

        # No scrollback
        s = self.create_screen(cols=10, lines=3, scrollback=50)
        self.ae(s.scrollbar_geometry(), (0, 1))

        # Live geometry at the bottom, scrolled back and at the top
        s = screen()
        count = s.historybuf.count
        self.ae(count, 38)
        check(s, 0, 0, count, 'bottom')
        s.scroll(5, True)
        check(s, 5, 0, count, 'scrolled')
        s.scroll(count, True)
        check(s, count, 0, count, 'top')
        self.assertAlmostEqual(s.scrollbar_geometry()[0], 1, places=5)

        # The pixel scroll offset contributes a fraction of a line
        s = screen(pixel_scroll=True)
        s.scroll_to_absolute(10.5)
        check(s, 10, 10, s.historybuf.count, 'pixel scroll')

        # Output arriving during a pause does not move the handle
        for pixel_scroll in (False, True):
            with self.subTest(pixel_scroll=pixel_scroll):
                s = screen(pixel_scroll=pixel_scroll)
                s.scroll_to_absolute(5.5 if pixel_scroll else 5)
                before = s.scrollbar_geometry()
                parse_bytes(s, b'\x1b[?2026h')
                for i in range(6):
                    parse_bytes(s, f'new{i}\r\n'.encode())
                self.assertGreater(s.scrolled_by, 5)
                self.ae(s.scrollbar_geometry(), before)
                parse_bytes(s, b'\x1b[?2026l')
                check(s, s.scrolled_by, s.pixel_scroll_offset_y if pixel_scroll else 0, s.historybuf.count, 'after pause')
                self.assertNotEqual(s.scrollbar_geometry(), before)

        # Full scrollback: the view stops being anchored once it reaches the top
        s = screen(scrollback=20)
        s.scroll(15, True)
        before = s.scrollbar_geometry()
        parse_bytes(s, b'\x1b[?2026h')
        for i in range(10):
            parse_bytes(s, f'new{i}\r\n'.encode())
        self.ae(s.scrollbar_geometry(), before)

        # Changes to the scrollback size during a pause
        s = screen()
        s.scroll(1, True)
        before = s.scrollbar_geometry()
        parse_bytes(s, b'\x1b[?2026h\x1b[+T')
        self.ae(s.scrolled_by, 0)
        self.ae(s.scrollbar_geometry(), before)
        s = screen()
        before = s.scrollbar_geometry()
        parse_bytes(s, b'\x1b[?2026h\x1b[3J')
        self.ae(s.historybuf.count, 0)
        self.ae(s.scrollbar_geometry(), before)
        parse_bytes(s, b'\x1b[?2026l')
        self.ae(s.scrollbar_geometry(), (0, 1))

    def test_scrollbar_visibility(self):
        def screen(policy, history=True):
            s = self.create_screen(cols=10, lines=3, scrollback=50, options={'scrollbar': policy})
            for i in range(40 if history else 1):
                parse_bytes(s, f'row{i:03d}\r\n'.encode())
            return s

        def visibility(s):
            return s.has_scrollbar(False), s.has_scrollbar(True)

        # (not scrolled, scrolled) -> (not hovering, hovering)
        policies = {
            'never': ((False, False), (False, False)),
            'always': ((True, True), (True, True)),
            'scrolled': ((False, False), (True, True)),
            'hovered': ((False, True), (False, True)),
            'scrolled-and-hovered': ((False, False), (False, True)),
            'scrolled-or-hovered': ((False, True), (True, True)),
        }
        for policy, (at_bottom, scrolled) in policies.items():
            with self.subTest(policy=policy):
                s = screen(policy)
                self.ae(visibility(s), at_bottom)
                s.scroll(3, True)
                self.ae(visibility(s), scrolled)
                # No scrollback or the alternate screen: never a scrollbar
                self.ae(visibility(screen(policy, history=False)), (False, False))
                s = screen(policy)
                parse_bytes(s, b'\x1b[?1049h')
                self.ae(visibility(s), (False, False))

        # Filling from the scrollback during a pause brings the live view to
        # the bottom, but the frozen frame is still scrolled back
        s = screen('scrolled')
        s.scroll(1, True)
        self.assertTrue(s.has_scrollbar(False))
        parse_bytes(s, b'\x1b[?2026h\x1b[+T')
        self.ae(s.scrolled_by, 0)
        self.assertTrue(s.has_scrollbar(False))
        parse_bytes(s, b'\x1b[?2026l')
        self.assertFalse(s.has_scrollbar(False))

        # Clearing the scrollback during a pause
        s = screen('always')
        parse_bytes(s, b'\x1b[?2026h\x1b[3J')
        self.ae(s.historybuf.count, 0)
        self.assertTrue(s.has_scrollbar(False))
        parse_bytes(s, b'\x1b[?2026l')
        self.assertFalse(s.has_scrollbar(False))

        # Switching screens during a pause
        s = screen('always')
        parse_bytes(s, b'\x1b[?2026h\x1b[?1049h')
        self.assertTrue(s.has_scrollbar(False))
        parse_bytes(s, b'\x1b[?2026l')
        self.assertFalse(s.has_scrollbar(False))
        parse_bytes(s, b'\x1b[?2026h\x1b[?1049l')
        self.assertFalse(s.has_scrollbar(False))
        parse_bytes(s, b'\x1b[?2026l')
        self.assertTrue(s.has_scrollbar(False))

    def test_selection_not_dirty_after_render(self):
        # Regression test for https://github.com/kovidgoyal/kitty/issues/10714
        # selections were considered dirty on every frame when scrolled back,
        # causing continuous re-rendering
        s = self.create_screen(cols=10, lines=3, scrollback=50)
        for i in range(40):
            s.draw(f'row{i:03d}')
            s.carriage_return()
            s.linefeed()

        def check(msg):
            s.current_selections()
            self.assertFalse(s.is_selection_dirty(), msg)

        s.start_selection(0, 0)
        s.update_selection(2, 1)
        check('not scrolled')
        for amt in (1, 2, 5, 20):
            s.scroll(amt, True)
            self.assertTrue(s.is_selection_dirty())
            check(f'scrolled by {s.scrolled_by}')
        s.clear_selection()
        s.start_selection(0, 0)
        s.update_selection(2, 1)
        check('selection in scrollback')
        s.scroll(20, False)
        self.assertTrue(s.is_selection_dirty())
        check('selection above visible area')
        s.update_selection(3, 1)
        self.assertTrue(s.is_selection_dirty())
        check('updated selection above visible area')

    def test_soft_hyphen(self):
        s = self.create_screen()
        s.draw('a\u00adb')
        self.ae(s.cursor.x, 2)
        s.start_selection(0, 0)
        s.update_selection(2, 0)
        self.ae(s.text_for_selection(), ('a\u00adb',))

    def test_variation_selectors(self):
        s = self.create_screen(cols=3)
        q = '*\ufe0f'
        s.draw(q * (s.columns + 1))
        self.ae(str(s.line(0)), q * (s.columns // 2))
        s = self.create_screen(cols=8)

        def widths(text, *widths):
            s.reset()
            s.draw(text)

            def w(x):
                c = s.cpu_cells(0, x)
                return (c['mcd'] or {'width': 1})['width']

            actual = tuple(w(x) for x in range(len(widths)))
            self.ae(widths, actual)

        widths('\u4e00\u4e00\u26ab\ufe0e', 2, 2, 2, 2, 1)

        s = self.create_screen()

        def tt(text_to_draw):
            s.reset()
            s.draw(text_to_draw)
            self.ae(str(s.line(0)), text_to_draw)

        tt('abc\U0001f44d\ufe0ed')

        def t(*a):
            s.reset()
            for i in range(0, len(a), 2):
                char, x = a[i], a[i + 1]
                s.draw(char)
                self.ae(s.cursor.x, x, f'after char: {char!r}')

        # already wide + VS15
        t('\U0001f610', 2, '\ufe0e', 1, '\ufe0e', 1)
        t('\U0001f610\ufe0e', 1, '\ufe0e', 1)
        # narrow + VS16
        t('\u25b6', 1, '\ufe0f', 2)
        t('\u25b6\ufe0f', 2)
        # wide + VS16
        t('\u26d4\ufe0f', 2, '\ufe0f', 2)
        t('\u26d4', 2, '\ufe0f', 2)
        # narrow + VS15
        t('\u25b6', 1, '\ufe0e', 1)
        t('\u25b6\ufe0e', 1)
        # narrow + VS16 + VS15
        t('\u25b6', 1, '\ufe0f', 2, '\ufe0e', 2)
        # wide + VS15 + VS16
        t('\U0001f610', 2, '\ufe0e', 1, '\ufe0f', 1)
        # large numbers of combining chars
        s.reset()
        s.draw('\N{HEAVY EXCLAMATION MARK SYMBOL}' + 4500 * '\N{VARIATION SELECTOR-16}')

    def test_explicit_width_is_not_changed_by_combining_chars(self):
        # A width set explicitly via the text sizing protocol wins over the implicit
        # re-sizing done by the variation selectors and Thai/Lao SARA AM
        def mcd(text, width, follow):
            s = self.create_screen(cols=8)
            draw_multicell(s, text, width=width)
            before = s.cpu_cells(0, 0)['mcd']
            self.ae(before['width'], width)
            self.assertFalse(before['natural_width'])
            s.draw(follow)
            return s, s.cpu_cells(0, 0)['mcd']

        # VS15 must not narrow an explicitly widened cell
        s, c = mcd('\u25b6', 2, '\ufe0e')
        self.ae(c['width'], 2)
        self.ae(s.cursor.x, 2)
        # VS16 must not widen an explicitly narrowed cell
        s, c = mcd('\u26d4', 1, '\ufe0f')
        self.ae(c['width'], 1)
        self.ae(s.cursor.x, 1)
        # SARA AM must not widen an explicitly narrowed cell
        s, c = mcd('\u0e08', 1, '\u0e33')
        self.ae(c['width'], 1)
        self.ae(s.cursor.x, 1)

        # and the natural width cases still re-size, so the tests above are meaningful
        s = self.create_screen(cols=8)
        s.draw('\U0001f610')
        self.ae(s.cursor.x, 2)
        self.assertTrue(s.cpu_cells(0, 0)['mcd']['natural_width'])
        s.draw('\ufe0e')
        self.ae(s.cursor.x, 1)
        self.ae(s.cpu_cells(0, 0)['mcd']['width'], 1)
        s = self.create_screen(cols=8)
        s.draw('\u26d4')
        self.ae(s.cursor.x, 2)
        s.draw('\u0e08\u0e33')
        self.ae(s.cursor.x, 4)

    def test_spacing_mark_widens_narrow_cell(self):
        # Thai SARA AM and Lao AM are SpacingMarks with width 1 that widen the cell they combine into
        s = self.create_screen(cols=5)
        s.draw('จำ')
        self.ae(s.cursor.x, 2)
        self.assertTrue(str(s.line(0)).startswith('จำ'))
        c = s.cpu_cells(0, 0)
        self.assertTrue(c['mcd'])
        self.ae(c['mcd']['width'], 2)
        self.ae(c['x'], 0)
        self.ae(s.cpu_cells(0, 1)['x'], 1)
        s.reset()
        s.draw('จ')
        self.ae(s.cursor.x, 1)
        s.draw('ำ')
        self.ae(s.cursor.x, 2)
        s.reset()
        s.draw('จำำ')
        self.ae(s.cursor.x, 2)
        s.reset()
        s.draw('ກຳ')
        self.ae(s.cursor.x, 2)
        s.reset()
        s.draw('กิ')
        self.ae(s.cursor.x, 1)
        # widened char on the last column wraps onto the next line
        s = self.create_screen(cols=2)
        s.draw('aจำ')
        self.ae((s.cursor.x, s.cursor.y), (2, 1))
        self.ae(str(s.line(0)), 'a')
        self.ae(str(s.line(1)), 'จำ')

    def test_writing_with_cursor_on_trailer_of_wide_character(self):
        s = self.create_screen()

        def r(x, pos, expected):
            s.reset()
            s.draw('😸')
            self.ae(s.cursor.x, 2)
            s.cursor.x = 1
            s.draw(x)
            self.ae(s.cursor.x, pos)
            self.ae(str(s.line(0)), expected)

        r('a', 2, ' a')
        r('😸', 3, ' 😸')
        r('\u0304', 1, '😸\u0304')
        r('\r', 0, '😸')

    def test_serialize(self):
        from kitty.window import as_text

        sgr0 = '\x1b[m'  # ]
        s = self.create_screen()
        parse_bytes(s, b'\x1b[1;91m')  # ]
        s.draw('X')
        parse_bytes(s, b'\x1b[0m\x1b[2m')  # ]]
        s.draw('Y')
        self.ae(as_text(s, True), f'{sgr0}\x1b[22;1;91mX\x1b[22;2;39mY\n\n\n\n')  # ]]

        s.reset()
        s.draw('ab' * s.columns)
        s.carriage_return(), s.linefeed()
        s.draw('c')

        self.ae(as_text(s), 'ababababab\nc\n\n')
        self.ae(as_text(s, True), f'{sgr0}ababa{sgr0}babab\n{sgr0}c\n\n')

        s = self.create_screen(cols=2, lines=2, scrollback=2)
        for i in range(1, 7):
            s.select_graphic_rendition(30 + i)
            s.draw(f'{i}' * s.columns)
        self.ae(as_text(s, True, True), f'{sgr0}\x1b[31m11{sgr0}\x1b[32m22{sgr0}\x1b[33m33{sgr0}\x1b[34m44{sgr0}{sgr0}\x1b[35m55{sgr0}\x1b[36m66')
        # ]]]]]]]]]]]]]]]]]]]]]

        def hl(url='', id=''):
            return '\x1b]8;{};{}\x1b\\'.format(f'id={id}' if id else '', url or '')

        def set_link(url=None, id=None):
            parse_bytes(s, hl(url, id).encode('utf-8'))

        s = self.create_screen()
        set_link('moo')
        s.draw('X')
        set_link()
        self.ae(as_text(s, True), f'{sgr0}{hl("moo")}X{hl()}\n\n\n\n')
        s.reset()
        set_link('moo')
        s.draw('X' * s.columns)
        set_link()
        self.ae(as_text(s, True), f'{sgr0}{hl("moo")}XXXXX\n{sgr0}{hl()}\n\n\n')

        s.reset()
        s.draw('a')
        set_link('moo', 'foo')
        s.draw('bcdef')
        self.ae(as_text(s, True), f'{sgr0}a{hl("moo", "foo")}bcde{sgr0}f{hl()}\n\n\n')
        set_link()
        s.draw('gh')
        self.ae(as_text(s, True), f'{sgr0}a{hl("moo", "foo")}bcde{sgr0}f{hl()}gh\n\n\n')
        s.reset()
        s.draw('a')
        set_link('moo')
        s.draw('bcdef')
        self.ae(as_text(s, True), f'{sgr0}a{hl("moo")}bcde{sgr0}f{hl()}\n\n\n')

    def test_wrapping_serialization(self):
        from kitty.window import as_text

        s = self.create_screen(cols=2, lines=2, scrollback=2, options={'scrollback_pager_history_size': 128})
        s.draw('ū̀abbccddeefū̀')
        self.ae(as_text(s, add_history=True), 'ū̀abbccddeefū̀')
        self.assertNotIn('\n', as_text(s, add_history=True, as_ansi=True))

        s = self.create_screen(cols=2, lines=2, scrollback=2, options={'scrollback_pager_history_size': 128})
        s.draw('1'), s.carriage_return(), s.linefeed()
        s.draw('2'), s.carriage_return(), s.linefeed()
        s.draw('3'), s.carriage_return(), s.linefeed()
        s.draw('4'), s.carriage_return(), s.linefeed()
        s.draw('5'), s.carriage_return(), s.linefeed()
        s.draw('6'), s.carriage_return(), s.linefeed()
        s.draw('7')
        self.ae(as_text(s, add_history=True), '1\n2\n3\n4\n5\n6\n7')

        s = self.create_screen(cols=2, lines=2, scrollback=2, options={'scrollback_pager_history_size': 128})
        s.draw('aabb')
        s.cursor.y = 0
        s.carriage_return(), s.linefeed()
        self.ae(as_text(s, add_history=True), 'aabb')

        s = self.create_screen(cols=2, lines=2, scrollback=2, options={'scrollback_pager_history_size': 128})
        s.draw('a'), s.carriage_return(), s.linefeed()
        s.cursor.y = 0
        s.draw('aabb')
        self.ae(as_text(s), 'aabb')
        s = self.create_screen(cols=2, lines=2, scrollback=2, options={'scrollback_pager_history_size': 128})
        s.draw('a😀')
        self.ae(as_text(s), 'a😀')

    def test_pagerhist(self):
        hsz = 8
        s = self.create_screen(cols=2, lines=2, scrollback=2, options={'scrollback_pager_history_size': hsz})

        def contents():
            return s.historybuf.pagerhist_as_text()

        def line(i):
            q.append('\x1b[m' + f'{i}' * s.columns + '\r')

        def w(x):
            s.historybuf.pagerhist_write(x)

        def test():
            expected = ''.join(q)
            maxlen = hsz
            extra = len(expected) - maxlen
            if extra > 0:
                expected = expected[extra:]
            got = contents()
            self.ae(got, expected)

        q = []
        for i in range(4):
            s.draw(f'{i}' * s.columns)
        self.ae(contents(), '')
        s.draw('4' * s.columns), line(0), test()
        s.draw('5' * s.columns), line(1), test()
        s.draw('6' * s.columns), line(2), test()
        s.draw('7' * s.columns), line(3), test()
        s.draw('8' * s.columns), line(4), test()
        s.draw('9' * s.columns), line(5), test()

        s = self.create_screen(options={'scrollback_pager_history_size': 2048})
        text = '\x1b[msoft\r\x1b[mbreak\nnext😼cat'
        w(text)
        self.ae(contents(), text)
        s.historybuf.pagerhist_rewrap(2)
        self.ae(contents(), '\x1b[mso\rft\x1b[m\rbr\rea\rk\nne\rxt\r😼\rca\rt')

        s = self.create_screen(options={'scrollback_pager_history_size': 8})
        w('😼')
        self.ae(contents(), '😼')
        w('abcd')
        self.ae(contents(), '😼abcd')
        w('e')
        self.ae(contents(), 'abcde')

    def test_user_marking(self):

        def cells(*a, y=0, mark=3):
            return [(x, y, mark) for x in a]

        s = self.create_screen()
        s.draw('abaa')
        s.carriage_return(), s.linefeed()
        s.draw('xyxyx')
        s.set_marker(marker_from_regex('a', 3))
        self.ae(s.marked_cells(), cells(0, 2, 3))
        s.set_marker()
        self.ae(s.marked_cells(), [])

        def mark_x(text):
            col = 0
            for i, c in enumerate(text):
                if c == 'x':
                    col += 1
                    yield i, i, col

        s.set_marker(marker_from_function(mark_x))
        self.ae(s.marked_cells(), [(0, 1, 1), (2, 1, 2), (4, 1, 3)])
        s = self.create_screen(lines=5, scrollback=10)
        for i in range(15):
            s.draw(str(i))
            if i != 14:
                s.carriage_return(), s.linefeed()
        s.set_marker(marker_from_regex(r'\d+', 3))
        for i in range(10):
            self.assertTrue(s.scroll_to_next_mark())
            self.ae(s.scrolled_by, i + 1)
        self.ae(s.scrolled_by, 10)
        for i in range(10):
            self.assertTrue(s.scroll_to_next_mark(0, False))
            self.ae(s.scrolled_by, 10 - i - 1)
        self.ae(s.scrolled_by, 0)

        s = self.create_screen()
        s.draw('🐈ab')
        s.set_marker(marker_from_regex('🐈', 3))
        self.ae(s.marked_cells(), cells(0, 1))
        s.set_marker(marker_from_regex('🐈a', 3))
        self.ae(s.marked_cells(), cells(0, 1, 2))
        s.set_marker(marker_from_regex('a', 3))
        self.ae(s.marked_cells(), cells(2))
        s = self.create_screen(cols=20)
        s.tab()
        s.draw('ab')
        s.set_marker(marker_from_regex('a', 3))
        self.ae(s.marked_cells(), cells(8))
        s.set_marker(marker_from_regex('\t', 3))
        self.ae(s.marked_cells(), cells(*range(8)))
        s = self.create_screen()
        s.cursor.x = 2
        s.draw('x')
        s.cursor.x += 1
        s.draw('x')
        s.set_marker(marker_from_function(mark_x))
        self.ae(s.marked_cells(), [(2, 0, 1), (4, 0, 2)])
        # Test CJK/wide characters not at position 0 (issue #9705)
        s = self.create_screen(cols=20)
        s.draw('テスト世界')
        s.set_marker(marker_from_regex('テ', 3))
        self.ae(s.marked_cells(), cells(0, 1))
        s.set_marker(marker_from_regex('世', 3))
        self.ae(s.marked_cells(), cells(6, 7))
        s.set_marker(marker_from_text('世界', 3))
        self.ae(s.marked_cells(), cells(6, 7, 8, 9))
        s = self.create_screen(cols=20)
        s.draw('ABテCD世EF')
        s.set_marker(marker_from_regex('テ', 3))
        self.ae(s.marked_cells(), cells(2, 3))
        s.set_marker(marker_from_regex('世', 3))
        self.ae(s.marked_cells(), cells(6, 7))

    def test_hyperlinks(self):
        s = self.create_screen()
        self.ae(s.line(0).hyperlink_ids(), tuple(0 for x in range(s.columns)))

        def set_link(url=None, id=None):
            parse_bytes(s, '\x1b]8;id={};{}\x1b\\'.format(id or '', url or '').encode('utf-8'))

        set_link('wide-chars', 'XX')
        self.ae(s.line(0).hyperlink_ids(), tuple(0 for x in range(s.columns)))
        s.draw('状')
        self.ae(s.line(0).hyperlink_ids(), (1, 1) + tuple(0 for x in range(s.columns - 2)))
        set_link()

        s = self.create_screen()
        set_link('url-a', 'a')
        self.ae(s.line(0).hyperlink_ids(), tuple(0 for x in range(s.columns)))
        s.draw('a')
        self.ae(s.line(0).hyperlink_ids(), (1,) + tuple(0 for x in range(s.columns - 1)))
        s.draw('bc')
        self.ae(s.line(0).hyperlink_ids(), (1, 1, 1, 0, 0))
        set_link()
        s.draw('d')
        self.ae(s.line(0).hyperlink_ids(), (1, 1, 1, 0, 0))
        set_link('url-a', 'a')
        s.draw('efg')
        self.ae(s.line(0).hyperlink_ids(), (1, 1, 1, 0, 1))
        self.ae(s.line(1).hyperlink_ids(), (1, 1, 0, 0, 0))
        set_link('url-b')
        s.draw('hij')
        self.ae(s.line(1).hyperlink_ids(), (1, 1, 2, 2, 2))
        set_link()
        self.ae({('a:url-a', 1), (':url-b', 2)}, s.hyperlinks_as_set())
        s.garbage_collect_hyperlink_pool()
        self.ae({('a:url-a', 1), (':url-b', 2)}, s.hyperlinks_as_set())
        for i in range(s.lines + 2):
            s.linefeed()
        s.garbage_collect_hyperlink_pool()
        self.ae({('a:url-a', 1), (':url-b', 2)}, s.hyperlinks_as_set())
        for i in range(s.lines * 2):
            s.linefeed()
        s.garbage_collect_hyperlink_pool()
        self.assertFalse(s.hyperlinks_as_set())
        set_link('url-a', 'x')
        s.draw('a')
        set_link('url-a', 'y')
        s.draw('a')
        set_link()
        self.ae({('x:url-a', 1), ('y:url-a', 2)}, s.hyperlinks_as_set())

        s = self.create_screen()
        set_link('u' * 2048)
        s.draw('a')
        self.ae({(':' + 'u' * 2045, 1)}, s.hyperlinks_as_set())
        s = self.create_screen()
        set_link('u' * 2048, 'i' * 300)
        s.draw('a')
        self.ae({('i' * 256 + ':' + 'u' * (2045 - 256), 1)}, s.hyperlinks_as_set())

        s = self.create_screen()
        set_link('1'), s.draw('1')
        set_link('2'), s.draw('2')
        set_link('3'), s.draw('3')
        s.cursor.x = 1
        set_link(), s.draw('X')
        self.ae(s.line(0).hyperlink_ids(), (1, 0, 3, 0, 0))
        self.ae({(':1', 1), (':2', 2), (':3', 3)}, s.hyperlinks_as_set())
        s.garbage_collect_hyperlink_pool()
        self.ae({(':1', 1), (':3', 2)}, s.hyperlinks_as_set())
        set_link('3'), s.draw('3')
        self.ae({(':1', 1), (':3', 2)}, s.hyperlinks_as_set())
        set_link('4'), s.draw('4')
        self.ae({(':1', 1), (':3', 2), (':4', 3)}, s.hyperlinks_as_set())

        s = self.create_screen()
        set_link('1'), s.draw('1')
        set_link('2'), s.draw('2')
        set_link('1'), s.draw('1')
        self.ae({(':2', 2), (':1', 1)}, s.hyperlinks_as_set())

        s = self.create_screen()
        set_link('1'), s.draw('12'), set_link(), s.draw('X'), set_link('1'), s.draw('3')
        s.carriage_return(), s.linefeed()
        s.draw('abc')
        s.carriage_return(), s.linefeed()
        set_link(), s.draw('Z ')
        set_link('1'), s.draw('xyz')
        s.carriage_return(), s.linefeed()
        set_link('2'), s.draw('Z Z')
        self.assertIsNone(s.current_url_text())
        self.assertIsNone(s.hyperlink_at(0, 4))
        self.assertIsNone(s.current_url_text())
        self.ae(s.hyperlink_at(0, 0), '1')
        self.ae(s.current_url_text(), '123abcxyz')
        self.ae('1', s.hyperlink_at(3, 2))
        self.ae(s.current_url_text(), '123abcxyz')
        self.ae('2', s.hyperlink_at(1, 3))
        self.ae(s.current_url_text(), 'Z Z')

    def test_automatic_hyperlink_collection(self) -> None:
        s = self.create_screen()
        for i in range(1, 2 * 8192 + 3):
            url = f'https://example.test/{i}'
            parse_bytes(s, f'\r\x1b]8;;{url}\x1b\\L\x1b]8;;\x1b\\'.encode())
            self.ae(s.hyperlink_at(0, 0), url)
        self.assertLess(len(s.hyperlinks_as_set()), 8192)

    def test_text_cache_garbage_collection(self):
        # unique multi-codepoint cell texts, single width base + combining mark
        def unique_text(i):
            return chr(0x100 + i // 0x70) + chr(0x300 + i % 0x70)

        s = self.create_screen()
        base = s.text_cache_count()
        for i in range(10):
            s.draw(unique_text(i))
        self.ae(s.text_cache_count(), base + 10)
        before = tuple(str(s.line(y)) for y in range(s.lines))
        s.garbage_collect_text_cache()
        # all entries are still referenced by cells, so all survive
        self.ae(s.text_cache_count(), base + 10)
        self.ae(before, tuple(str(s.line(y)) for y in range(s.lines)))

        # scroll all multi-codepoint cells out of the screen and the history
        # buffer, then intern one more entry, which gets a high index
        for i in range(s.lines * 3):
            s.linefeed()
        s.carriage_return()
        s.draw(unique_text(10))
        s.garbage_collect_text_cache()
        # only the surviving entry remains and its index was remapped
        # without changing the cell's text
        self.ae(s.text_cache_count(), base + 1)
        self.ae(str(s.line(s.cursor.y)).rstrip(), unique_text(10))

        # the periodic GC keeps the cache bounded when unique cell texts
        # are continuously created and scrolled out, as in the DoS scenario
        s = self.create_screen()
        num = 3 * 8192 + 100
        for i in range(num):
            s.draw(unique_text(i))
        self.assertLess(s.text_cache_count(), 8192 + 2 * s.lines * s.columns)
        self.ae(str(s.line(s.cursor.y)).rstrip()[-2:], unique_text(num - 1))

    def test_bottom_margin(self):
        s = self.create_screen(cols=80, lines=6, scrollback=4)
        s.set_margins(0, 5)
        for i in range(8):
            s.draw(str(i))
            s.linefeed()
            s.carriage_return()

        self.ae(str(s.linebuf), '4\n5\n6\n7\n\n')
        self.ae(str(s.historybuf), '3\n2\n1\n0')

    def test_top_margin(self):
        s = self.create_screen(cols=80, lines=6, scrollback=4)
        s.set_margins(2, 6)
        for i in range(8):
            s.draw(str(i))
            s.linefeed()
            s.carriage_return()

        self.ae(str(s.linebuf), '0\n4\n5\n6\n7\n')
        self.ae(str(s.historybuf), '')

    def test_top_and_bottom_margin(self):
        s = self.create_screen(cols=80, lines=6, scrollback=4)
        s.set_margins(2, 5)
        for i in range(8):
            s.draw(str(i))
            s.linefeed()
            s.carriage_return()

        self.ae(str(s.linebuf), '0\n5\n6\n7\n\n')
        self.ae(str(s.historybuf), '')

    def test_osc_52(self):
        s = self.create_screen()
        c = s.callbacks

        def send(what: str):
            return parse_bytes(s, f'\033]52;p;{what}\a'.encode('ascii'))

        def t(q, *expected):
            c.clear()
            send(q)
            del q
            t.ex = list(expected)
            del expected
            try:
                self.ae(tuple(map(len, c.cc_buf)), tuple(map(len, t.ex)))
                self.ae(c.cc_buf, t.ex)
            finally:
                del t.ex

        t('XYZ', ('p;XYZ', False))
        t('a' * VT_PARSER_BUFFER_SIZE, ('p;' + 'a' * (VT_PARSER_BUFFER_SIZE - 8), True), (';' + 'a' * 8, False))
        t('', ('p;', False))
        t('!', ('p;!', False))

    def test_key_encoding_flags_stack(self):
        s = self.create_screen()
        c = s.callbacks

        def w(code, p1='', p2=''):
            p = f'{p1}'
            if p2:
                p += f';{p2}'
            return parse_bytes(s, f'\033[{code}{p}u'.encode('ascii'))

        def ac(flags):
            parse_bytes(s, b'\033[?u')
            self.ae(c.wtcbuf, f'\033[?{flags}u'.encode('ascii'))
            c.clear()

        ac(0)
        w('=', 0b1001)
        ac(0b1001)
        w('=', 0b0011, 2)
        ac(0b1011)
        w('=', 0b0110, 3)
        ac(0b1001)
        s.reset()
        ac(0)

        w('>', 0b0011)
        ac(0b0011)
        w('=', 0b1111)
        ac(0b1111)
        w('>', 0b10)
        ac(0b10)
        w('<')
        ac(0b1111)
        for i in range(10):
            w('<')
            ac(0)
        s.reset()

        for i in range(1, 16):
            w('>', i)
        ac(15)
        w('<'), ac(14), w('<'), ac(13)

    def test_color_stack(self):
        s = self.create_screen()
        c = s.callbacks

        def w(code):
            return parse_bytes(s, ('\033[' + code).encode('ascii'))

        def ac(idx, count):
            self.ae(c.wtcbuf, f'\033[{idx};{count}#Q'.encode('ascii'))
            c.clear()

        # ]]]]]]]]]]]]]]]]}}}}}}}}}}}}}}}}))))))))))))))))))))))

        w('#R')
        ac(0, 0)

        w('#P')
        w('#R')
        ac(0, 1)
        w('10#P')
        w('#R')
        ac(0, 1)
        w('#Q')
        w('#R')
        ac(0, 0)
        for i in range(20):
            w('#P')
        w('#R')
        ac(9, 10)

    def test_detect_url(self):
        detect_url(self)
        detect_url(self, scale=2)

    def test_detect_url_regex(self):
        file_ref = r'[[:alnum:]_./-]+\.[[:alnum:]]+:[0-9]+'

        def screen(*patterns, cols=30, lines=5, scrollback=5):
            return self.create_screen(cols=cols, lines=lines, scrollback=scrollback, options={'detect_url_regex': {p: p for p in patterns}})

        def ae(s, expected, x, y=0):
            s.detect_url(x, y)
            self.ae(expected, ''.join(s.text_for_marked_url()))

        s = screen(file_ref)
        s.draw('see src/foo.py:42 here')
        for x in range(4, 17):
            ae(s, 'src/foo.py:42', x)
        for x in (0, 3, 17, 20, 25):
            ae(s, '', x)
        ae(s, '', 5, 1)

        # multiple expressions, the first one to match under the mouse wins
        s = screen(r'[0-9]+', r'JIRA-[0-9]+', r'[A-Z]+-[0-9]+')
        s.draw('fix ABC-12 and JIRA-7')
        ae(s, 'ABC-12', 5)
        ae(s, 'JIRA-7', 16)
        ae(s, '12', 9)

        # normal URLs take precedence
        s = screen(file_ref)
        s.draw('http://moo.com/x.py:1')
        ae(s, 'http://moo.com/x.py:1', 16)

        # wide characters before the match must not shift columns
        s = screen(file_ref)
        s.draw('世界 foo.py:1 x')
        ae(s, '', 4)
        ae(s, 'foo.py:1', 5)
        ae(s, 'foo.py:1', 12)
        ae(s, '', 13)

        # matches in soft wrapped lines
        s = screen(file_ref, cols=10)
        s.draw('xx aaaa/bbbb/cccc.py:12 yy')
        for x, y in ((3, 0), (9, 0), (0, 1), (9, 1), (2, 2)):
            ae(s, 'aaaa/bbbb/cccc.py:12', x, y)
        ae(s, '', 4, 2)
        # a wide character wrapped onto the next line leaves an empty cell
        s = screen('abcd世x', cols=5)
        s.draw('abcd世x')
        ae(s, 'abcd世x', 0)
        ae(s, 'abcd世x', 2, 1)
        # the number of wrapped lines scanned is limited
        s = screen('a+', cols=5, lines=12)
        s.draw('a' * 50)
        ae(s, 'a' * 20, 0)
        ae(s, 'a' * 35, 0, 5)
        ae(s, 'a' * 20, 0, 9)
        # hard line breaks are not joined
        s = screen('a+', cols=5)
        s.draw('aaaaa'), s.carriage_return(), s.linefeed(), s.draw('aa')
        ae(s, 'aaaaa', 0)
        ae(s, 'aa', 0, 1)

        # matches in the scrollback when scrolled
        s = screen(file_ref, lines=3)
        s.draw('see src/foo.py:42')
        for i in range(4):
            s.carriage_return(), s.linefeed(), s.draw(f'line {i}')
        s.scroll(2, True)
        ae(s, 'src/foo.py:42', 6)
        ae(s, '', 0, 1)

        # invalid expressions are ignored, with an error logged to stderr by C code
        with tempfile.TemporaryFile() as f:
            orig_stderr = os.dup(2)
            os.dup2(f.fileno(), 2)
            try:
                s = screen('(', 'foo')
            finally:
                os.dup2(orig_stderr, 2)
                os.close(orig_stderr)
            f.seek(0)
            self.assertIn(b'Ignoring invalid detect_url_regex: (', f.read())
        s.draw('a foo')
        ae(s, 'foo', 2)

    def test_scroll_to_prompt_with_short_scrollback(self):
        for lines_before_prompt in (0, 1):
            with self.subTest(lines_before_prompt=lines_before_prompt):
                s = self.create_screen(cols=12, lines=4, scrollback=10)
                if lines_before_prompt:
                    parse_bytes(s, b'\x1b]133;C\x07older\r\n')
                parse_bytes(s, b'\x1b]133;A\x07$ a\r\n')
                parse_bytes(s, b'\x1b]133;C\x07a0\r\n\r\n\r\n')
                parse_bytes(s, b'\x1b]133;A\x07$ live')
                self.ae(s.historybuf.count, lines_before_prompt + 1)

                self.assertTrue(s.scroll_to_prompt(-1, 3))
                self.ae(s.scrolled_by, s.historybuf.count)
                s.scroll_to_absolute(0)

                output = []
                s.cmd_output(2, output.append)
                self.ae(''.join(output).rstrip(), 'a0')
                self.assertTrue(s.scroll_to_prompt(0))
                self.ae(s.scrolled_by, s.historybuf.count)
                self.ae(str(s.visual_line(lines_before_prompt)), '$ a')

    def test_scroll_to_prompt_offset_tracks_target_command(self):
        # With a scroll offset the top of the viewport is in the output of the
        # command above the target, which must not be used as the last visited prompt
        def create():
            s = self.create_screen(cols=12, lines=5, scrollback=50)
            for i in range(4):
                parse_bytes(s, f'\x1b]133;A\x07$ c{i}\r\n'.encode())
                parse_bytes(s, f'\x1b]133;C\x07o{i}a\r\no{i}b\r\no{i}c\r\no{i}d\r\n'.encode())
            parse_bytes(s, b'\x1b]133;A\x07$ live')
            return s

        def last_visited_output(s):
            output = []
            s.cmd_output(2, output.append)
            return ''.join(output).split()

        expected = ['o3a', 'o3b', 'o3c', 'o3d']
        for offset in range(5):
            with self.subTest(offset=offset):
                s = create()
                self.assertTrue(s.scroll_to_prompt(-1, offset))
                self.ae(s.scrolled_by, offset + 1)
                self.ae(str(s.visual_line(offset)), '$ c3')
                self.ae(last_visited_output(s), expected)
                s.scroll_to_absolute(0)
                self.assertTrue(s.scroll_to_prompt(0))
                self.ae(s.scrolled_by, offset + 1)
                self.ae(str(s.visual_line(offset)), '$ c3')

        # Jumping forward with an offset records the prompt jumped to
        s = create()
        self.assertTrue(s.scroll_to_prompt(-2, 0))
        self.assertTrue(s.scroll_to_prompt(1, 2))
        self.ae(str(s.visual_line(2)), '$ c3')
        self.ae(last_visited_output(s), expected)

    def test_prompt_marking(self):
        # ]]]]]]]]]]]]]]]]}}}}}}}}}}}}}}}}))))))))))))))))))))))

        def mark_prompt():
            parse_bytes(s, b'\033]133;A\007')

        def mark_output():
            parse_bytes(s, b'\033]133;C\007')

        def draw_prompt(x):
            mark_prompt(), s.draw(f'$ {x}'), s.carriage_return(), s.index()

        def draw_output(n, x='', m=True):
            if m:
                mark_output()
            for i in range(n):
                s.draw(f'{i}{x}'), s.index(), s.carriage_return()

        from kitty.window import as_text

        def at():
            return as_text(s, add_history=True)

        s = self.create_screen(cols=5, lines=5, scrollback=15)
        draw_output(3, 'oo')
        draw_prompt('pp')
        mark_output()
        s.toggle_alt_screen()
        s.resize(s.lines, 2)
        s.toggle_alt_screen()
        self.assertFalse(str(s.line(s.cursor.y)))

        s = self.create_screen(scrollback=10)
        draw_output(1, 'start')
        for i in range(4):
            draw_prompt(str(i) + 'ab')
            draw_output(1, 'ut')
        self.ae(s.scrolled_by, 0)
        self.ae(str(s.visual_line(0)), '$ 2ab')
        self.assertFalse(s.scroll_to_prompt(-3))
        self.assertTrue(s.scroll_to_prompt())
        self.ae(str(s.visual_line(0)), '$ 1ab')
        self.assertTrue(s.scroll_to_prompt())
        self.ae(str(s.visual_line(0)), '$ 0ab')
        self.assertFalse(s.scroll_to_prompt())
        self.assertFalse(s.scroll_to_prompt(4))
        self.assertTrue(s.scroll_to_prompt(1))
        self.ae(str(s.visual_line(0)), '$ 1ab')
        self.assertTrue(s.scroll_to_prompt(1))
        self.ae(str(s.visual_line(0)), '$ 2ab')
        self.assertFalse(s.scroll_to_prompt(1))
        # wrap prompts
        s.resize(s.lines + 1, s.columns - 2)
        self.ae(s.scrolled_by, 0)
        self.ae(str(s.visual_line(0)), 'ab')
        self.assertFalse(s.scroll_to_prompt(-4))
        self.assertTrue(s.scroll_to_prompt())
        self.ae(str(s.visual_line(0)), '$ 2')
        self.assertTrue(s.scroll_to_prompt())
        self.ae(str(s.visual_line(0)), '$ 1')
        self.assertTrue(s.scroll_to_prompt())
        self.ae(str(s.visual_line(0)), '$ 0')
        self.assertFalse(s.scroll_to_prompt())
        self.assertFalse(s.scroll_to_prompt(4))
        self.assertTrue(s.scroll_to_prompt(1))
        self.ae(str(s.visual_line(0)), '$ 1')
        self.assertTrue(s.scroll_to_prompt(1))
        self.ae(str(s.visual_line(0)), '$ 2')
        self.assertTrue(s.scroll_to_prompt(1))
        self.ae(str(s.visual_line(0)), 'ab')
        self.assertFalse(s.scroll_to_prompt(1))

        s = self.create_screen()
        mark_prompt(), s.draw('$ 0')
        s.carriage_return(), s.index()
        mark_prompt(), s.draw('$ 1')
        for i in range(s.lines):
            s.carriage_return(), s.index()
            s.draw(str(i))
        self.assertTrue(s.scroll_to_prompt())
        self.ae(str(s.visual_line(0)), '$ 1')

        def lco(as_ansi=False, which=0):
            a = []
            if s.cmd_output(which, a.append, as_ansi):
                pht = pagerhist(s, as_ansi=as_ansi, upto_output_start=True)
                if pht:
                    a.insert(0, pht)
            return ''.join(a)

        def fco():
            a = []
            s.cmd_output(1, a.append)
            return ''.join(a)

        def lvco():
            a = []
            s.cmd_output(2, a.append)
            return ''.join(a)

        s = self.create_screen(cols=5, lines=5, scrollback=15)
        draw_prompt('P' * s.columns)
        draw_output(s.lines + 1, 'a')  # ensure prompt is in scrollback
        draw_prompt('Q' * s.columns)
        draw_output(s.lines + 1, 'b')  # ensure prompt is in scrollback
        draw_prompt('R' * s.columns)
        self.ae(lco(), '0b\n1b\n2b\n3b\n4b\n5b')

        s = self.create_screen()
        s.draw('abcd'), s.index(), s.carriage_return()
        s.draw('12'), s.index(), s.carriage_return()
        self.ae(fco(), '')
        self.ae(lco(), 'abcd\n12\n')
        s = self.create_screen()
        mark_prompt(), s.draw('$ 0')
        s.carriage_return(), s.index()
        mark_output()
        s.draw('abcd'), s.index(), s.carriage_return()
        s.draw('12'), s.index(), s.carriage_return()
        mark_prompt(), s.draw('$ 1')
        self.ae(fco(), 'abcd\n12')
        self.ae(lco(), 'abcd\n12')
        self.ae(lco(as_ansi=True), '\x1b[m\x1b]133;C\x1b\\abcd\n\x1b[m12')  # ]]]

        s = self.create_screen(cols=5, lines=5, scrollback=15)
        draw_output(1, 'start', False)
        draw_prompt('0'), draw_output(3)
        draw_prompt('1')
        draw_prompt('2'), draw_output(2, 'x')

        # last cmd output
        # test: find upwards
        self.ae(s.scrolled_by, 0)
        self.ae(lco(), '0x\n1x\n')
        # get output after scroll up
        s.scroll_to_prompt()
        self.ae(s.scrolled_by, 4)
        self.ae(str(s.visual_line(0)), '$ 0')
        self.ae(lco(), '0x\n1x\n')

        # first cmd output on screen
        # test: find around
        self.ae(fco(), '0\n1\n2')
        s.scroll(2, False)
        self.ae(s.scrolled_by, 2)
        self.ae(str(s.visual_line(0)), '1')
        self.ae(fco(), '0x\n1x\n')
        # test: find downwards
        s.scroll(2, False)
        self.ae(str(s.visual_line(0)), '$ 1')
        self.ae(fco(), '0x\n1x\n')
        # test: obscure prompt in scrollback
        s.resize(3, 5)
        self.ae(str(s.visual_line(0)), '0x')
        # without succeeding prompt
        self.ae(fco(), '0x\n1x\n')
        s.resize(4, 5)
        draw_prompt('3')
        # with succeeding prompt
        self.ae(fco(), '0x\n1x')

        # resize
        # get last cmd output with continued output mark
        draw_output(1, 'long_line'), draw_output(2, 'l', False)
        s.resize(4, 5)
        s.scroll_to_prompt(-4)
        self.ae(str(s.visual_line(0)), '$ 0')
        self.ae(lco(), '0long_line\n0l\n1l\n')

        # last visited cmd output
        self.ae(lvco(), '0\n1\n2')
        s.scroll_to_prompt(1)
        self.ae(lvco(), '0x\n1x')
        # test: obscure prompt
        s.scroll(2, False)
        s.set_last_visited_prompt()
        self.ae(lvco(), '0x\n1x')
        # test: prompts without output
        s.scroll(s.scrolled_by, False)
        s.resize(5, s.columns + 5)
        draw_prompt('4')
        s.set_last_visited_prompt(2)
        self.ae(lvco(), '')
        draw_prompt('wrapcmd')
        self.ae(lvco(), '')
        draw_output(1, 'wrapout'), draw_output(1, 'y', False)
        s.set_last_visited_prompt(0)
        self.ae(lvco(), '0wrapout\n0y\n')
        # wrap long prompt with long output
        s.resize(5, s.columns - 5)
        # test: set last visited to previous empty prompt
        s.scroll_to_prompt(-2)
        self.ae(str(s.visual_line(0)), '$ 4')
        self.ae(lvco(), '0wrapout\n0y\n')
        draw_prompt('end')
        # new output must not move the scrolled back viewport
        self.ae(str(s.visual_line(0)), '$ 4')
        s.scroll_to_prompt(1)
        s.scroll_to_prompt(-1)
        self.ae(str(s.visual_line(0)), '$ 4')
        self.ae(lvco(), '0wrapout\n0y')
        s.scroll_to_prompt(1)
        self.ae(lvco(), '0wrapout\n0y')
        # test: set last visited to continued line of long prompt
        s.set_last_visited_prompt(1)
        self.ae(lvco(), '0wrapout\n0y')
        # test: set last visited to continued line of output
        s.set_last_visited_prompt(3)
        self.ae(lvco(), '0wrapout\n0y')

        # test: losing markers past scrollback
        s = self.create_screen(lines=10, scrollback=0)
        draw_prompt('a' * (s.columns * 3))
        draw_output(1, 'v' * (s.columns * 2)), draw_output(1, 'w', False)
        draw_prompt('b')
        draw_output(1, 'x')
        # remove prompt start above, set last visited to within prompt
        s.clear_scrollback()
        s.set_last_visited_prompt(0)
        self.ae(lvco(), '0vvvvvvvvvv\n0w')
        # remove output start above, set last visited to within output
        draw_output(3, 'y', False), draw_output(1, 'z', False)
        s.clear_scrollback()
        s.set_last_visited_prompt(0)
        self.ae(lvco(), 'vvvvvv\n0w')
        draw_output(1, 'end', False)
        s.clear_scrollback()
        s.set_last_visited_prompt(0)
        self.ae(lvco(), 'v\n0w')
        # clear last visited line without setting new one
        draw_output(1, 'end', False)
        s.clear_scrollback()
        self.ae(lvco(), '')

        # test that post rewrap prompt lines have correct attributes
        s = self.create_screen(cols=5, lines=5, scrollback=15)
        draw_prompt('P' * (s.columns - 2))
        draw_output(s.lines + 1, 'a')  # ensure prompt is in scrollback
        draw_prompt('Q' * (s.columns - 2))
        self.ae(str(s.visual_line(0)), '3a')
        s.scroll_to_prompt()
        self.ae(str(s.visual_line(0)), '$ PPP')
        s.scroll_to_prompt(1)
        self.ae(str(s.visual_line(0)), '3a')
        s.resize(s.lines, s.columns - 2)
        s.scroll_to_prompt()
        self.ae(str(s.visual_line(0)), '$ P')

        # last command output without line break
        s = self.create_screen(cols=10, lines=3)
        draw_prompt('p1')
        mark_output(), s.draw('running')
        self.ae(lco(), 'running')
        s.index(), s.carriage_return()
        self.ae(lco(), 'running\n')

        # last command output from pager history
        s = self.create_screen()
        draw_prompt('p1')
        draw_output(30)
        self.ae(tuple(map(int, lco().split())), tuple(range(0, 30)))

        # last non empty command output
        s = self.create_screen()
        draw_prompt('a'), draw_output(2, 'a')
        draw_prompt('b'), mark_output()
        self.ae(lco(), '')
        self.ae(lco(which=3), '0a\n1a')
        s.draw('running'), s.index(), s.carriage_return()
        self.ae(lco(which=3), 'running\n')
        s = self.create_screen()
        draw_prompt('p1')
        draw_output(30)
        self.ae(tuple(map(int, lco(which=3).split())), tuple(range(0, 30)))
        s = self.create_screen()
        draw_prompt('p1')
        draw_output(2, 'a')
        draw_prompt('p1')
        draw_prompt('p1')
        self.ae(lco(which=3), '0a\n1a')

        # erase last command
        s = self.create_screen(cols=10, lines=10, scrollback=15)
        s.draw('before\r\n')
        draw_prompt('p1'), draw_output(2), mark_prompt(), s.draw('partial')
        self.ae('before\n$ p1\n0\n1\npartial', at().rstrip())
        self.ae(lco(), '0\n1')
        x = s.cursor.x
        s.erase_last_command()
        self.ae('before\npartial', at().rstrip())
        self.ae((x, 1), (s.cursor.x, s.cursor.y))
        s.reset()
        s.draw('before\r\n')
        draw_prompt('p1'), draw_output(2), mark_prompt(), s.draw('partial')
        x = s.cursor.x
        s.erase_last_command()
        self.ae('before\npartial', at().rstrip())
        for scroll in (8, 9, 10):
            s.reset()
            s.draw('before'), s.carriage_return(), s.linefeed()
            draw_prompt('p1'), draw_output(scroll), mark_prompt(), s.draw('partial')
            s.erase_last_command()
            self.ae('before\npartial', at().rstrip())
        s.reset()
        draw_multicell(s, 'A', scale=2), s.draw('a'), draw_multicell(s, 'B', scale=2), s.draw('b\r\n')
        draw_prompt('p1'), draw_output(9), mark_prompt(), s.draw('partial')
        s.erase_last_command()
        self.ae(at().rstrip(), '  a  b\npartial')

        # the most recent command is erased even when it produced no output (an
        # empty Enter, a comment, cd, ...): such commands emit no OSC 133;C and
        # must not be skipped in favour of an older command-with-output.
        s = self.create_screen(cols=10, lines=12, scrollback=30)
        s.draw('before\r\n')
        draw_prompt('p1'), draw_output(2), draw_prompt('# note'), mark_prompt(), s.draw('partial')
        s.erase_last_command()
        self.ae('before\n$ p1\n0\n1\npartial', at().rstrip())  # the output-less command goes first
        s.erase_last_command()
        self.ae('before\npartial', at().rstrip())  # then the command with output
        # consecutive output-less commands are removed newest-first, one per call
        s.reset()
        s.draw('before\r\n')
        draw_prompt('p1'), draw_output(1), draw_prompt('e1'), draw_prompt('e2'), mark_prompt(), s.draw('partial')
        s.erase_last_command()
        self.ae('before\n$ p1\n0\n$ e1\npartial', at().rstrip())
        s.erase_last_command()
        self.ae('before\n$ p1\n0\npartial', at().rstrip())
        s.erase_last_command()
        self.ae('before\npartial', at().rstrip())
        # multi-line live prompt: the command region is erased with no residual
        s.reset()
        s.draw('before\r\n')
        draw_prompt('p1'), draw_output(9), mark_prompt(), s.draw('l1'), s.carriage_return(), s.index(), s.draw('partial')
        s.erase_last_command()
        self.ae('before\nl1\npartial', at().rstrip())

        # erasing while scrolled back must work and keep the viewport anchored
        # on the same content when the erased lines are below it
        s = self.create_screen(cols=10, lines=5, scrollback=50)
        for i in range(20):
            s.draw(f'h{i}\r\n')
        draw_prompt('p1'), draw_output(8), mark_prompt(), s.draw('partial')
        s.scroll(12, True)
        before = tuple(str(s.visual_line(y)) for y in range(s.lines))
        self.ae(before[0], 'h13')
        self.assertTrue(s.erase_last_command())
        self.ae(tuple(str(s.visual_line(y)) for y in range(s.lines)), before)
        self.ae(at().rstrip(), '\n'.join(f'h{i}' for i in range(20)) + '\npartial')
        # when the erased lines include the top of the viewport, go to the bottom
        s.reset()
        for i in range(20):
            s.draw(f'h{i}\r\n')
        draw_prompt('p1'), draw_output(8), mark_prompt(), s.draw('partial')
        s.scroll(3, True)
        self.assertTrue(s.erase_last_command())
        self.ae(s.scrolled_by, 0)
        self.ae(str(s.visual_line(s.cursor.y)), 'partial')

        # the last visited prompt must move with the lines that remain after
        # erasing, both above the erased region (in the scrollback) and below it
        def erase_with_last_visited(which):
            nonlocal s
            s = self.create_screen(cols=10, lines=5, scrollback=50)
            # filler so that a stale last visited position is still within the scrollback
            for i in range(20):
                s.draw(f'h{i}\r\n')
            draw_prompt('p0'), draw_output(2, 'a')
            draw_prompt('p1'), draw_output(8)
            mark_prompt(), s.draw('$ live'), s.carriage_return(), s.index()
            mark_output(), s.draw('r0')
            if which == 'below':
                self.ae(s.cursor.y, 4)
                s.set_last_visited_prompt(3)
            else:
                self.assertTrue(s.scroll_to_prompt(-2 if which == 'above' else -1))
                s.scroll(s.scrolled_by, False)
            self.assertTrue(s.erase_last_command())
            return lvco()

        def visible():
            return tuple(str(s.visual_line(y)) for y in range(s.lines))

        self.ae(erase_with_last_visited('above'), '0a\n1a')
        s.scroll(1, True)
        self.assertTrue(s.scroll_to_prompt(0))
        self.ae(visible()[0], '$ p0')
        self.ae(erase_with_last_visited('erased'), '')
        self.assertFalse(s.scroll_to_prompt(0))
        self.ae(erase_with_last_visited('below').rstrip(), 'r0')
        s.scroll(10, True)
        self.assertTrue(s.scroll_to_prompt(0))
        self.ae(visible()[3], '$ live')  # the row it was visited at

    def test_last_visited_prompt_tracking(self):
        # The last visited prompt is stored as a single content row and must
        # stay on the same content as lines move, whatever the scroll offset
        # it was visited at.
        s = None

        def new_screen(lines=6, scrollback=20):
            nonlocal s
            s = self.create_screen(cols=10, lines=lines, scrollback=scrollback)

        def mark_prompt():
            parse_bytes(s, b'\x1b]133;A\a')

        def cmd(name, num_output_lines=1):
            mark_prompt(), s.draw(f'$ {name}\r\n')
            parse_bytes(s, b'\x1b]133;C\a')
            for i in range(num_output_lines):
                s.draw(f'{name}{i}\r\n')

        def lvco():
            ans = []
            s.cmd_output(2, ans.append)
            return ''.join(ans).rstrip()

        def visible():
            return tuple(str(s.visual_line(y)) for y in range(s.lines))

        def assert_visited(prompt, at_row, output=None):
            if output is not None:
                self.ae(lvco(), output)
            # jump from both ends of the scrollback so the jump always has to
            # compute the position rather than happen to already be there
            for start in (0, s.historybuf.count):
                s.scroll_to_absolute(start)
                s.scroll_to_prompt(0)
                self.ae(visible()[at_row], prompt, f'jumping from scrolled_by={start}')
            s.scroll_to_absolute(0)

        def assert_unset():
            self.ae(lvco(), '')
            for start in (0, s.historybuf.count):
                s.scroll_to_absolute(start)
                self.assertFalse(s.scroll_to_prompt(0))
                self.ae(s.scrolled_by, start)
            s.scroll_to_absolute(0)

        def visit(prompt):
            # visit the prompt at the first viewport position it is shown at
            for sb in range(s.historybuf.count + 1):
                s.scroll_to_absolute(sb)
                for y, text in enumerate(visible()):
                    if text == prompt:
                        self.assertTrue(s.set_last_visited_prompt(y))
                        s.scroll_to_absolute(0)
                        return sb, y
            raise AssertionError(f'{prompt} not found')

        def set_region_and_scroll(top, bottom, csi):
            # top and bottom are one based, as in DECSTBM
            parse_bytes(s, f'\x1b[{top};{bottom}r\x1b[{csi}'.encode())
            parse_bytes(s, b'\x1b[r')

        # Erasing a command can leave less scrollback than the scroll offset
        # the prompt was visited at. The prompt must still be reachable, shown
        # as close to the row it was visited at as the scrollback allows.
        for remaining_history in (0, 1, 2, 5):
            for scrolled_by in (0, 2):
                with self.subTest(remaining_history=remaining_history, scrolled_by=scrolled_by):
                    new_screen(lines=10)
                    for i in range(remaining_history):
                        s.draw(f'h{i}\r\n')
                    cmd('old', 7)
                    cmd('live', 1)  # the live prompt, with the cursor below it
                    s.draw('\r\n\r\n')
                    self.ae(s.historybuf.count, remaining_history + 3)
                    s.scroll_to_absolute(scrolled_by)
                    preferred_y = 5 + scrolled_by
                    self.ae(str(s.visual_line(preferred_y)), '$ live')
                    self.assertTrue(s.set_last_visited_prompt(preferred_y))
                    s.scroll_to_absolute(0)
                    self.assertTrue(s.erase_last_command())
                    self.ae(s.historybuf.count, remaining_history)
                    self.ae(visible()[0], '$ live')
                    self.ae(lvco(), 'live0')
                    expected_scrolled_by = min(preferred_y, remaining_history)
                    for start in sorted({0, remaining_history}):
                        s.scroll_to_absolute(start)
                        s.scroll_to_prompt(0)
                        self.ae(s.scrolled_by, expected_scrolled_by)
                        self.ae(str(s.visual_line(expected_scrolled_by)), '$ live')

        # Erasing a command keeps prompts in the scrollback above it on the
        # same content, even though fewer lines are left in the scrollback
        new_screen(lines=5)
        cmd('a', 3), cmd('b', 6), cmd('live', 0)
        self.ae(s.historybuf.count, 8)
        sb, y = visit('$ a')
        self.assertTrue(s.erase_last_command())
        self.ae(s.historybuf.count, 4)
        assert_visited('$ a', y, 'a0\na1\na2')

        # Scrolling a region with a bottom margin adds the lines scrolled off
        # its top to the scrollback but must not move lines below the region
        new_screen()
        cmd('a', 0), cmd('b', 0), s.draw('x\r\ny\r\n'), mark_prompt(), s.draw('$ c')
        self.ae(visible()[:5], ('$ a', '$ b', 'x', 'y', '$ c'))
        self.assertTrue(s.set_last_visited_prompt(4))
        set_region_and_scroll(1, 4, '2S')
        self.ae(s.historybuf.count, 2)
        self.ae(visible()[:5], ('x', 'y', '', '', '$ c'))
        assert_visited('$ c', 4)
        self.assertTrue(s.set_last_visited_prompt(0))  # x
        set_region_and_scroll(1, 4, '1S')
        assert_visited('x', 0)
        self.ae(s.historybuf.count, 3)

        # Scrolling a region with a top margin discards the line scrolled off
        # the top of the region, moves the lines in the region up and leaves
        # lines above the region alone
        for visited, expected in ((0, ('$ a', 0)), (1, None), (3, ('$ c', 2))):
            with self.subTest(top_margin_visited=visited):
                new_screen(lines=5)
                cmd('a', 0), cmd('b', 0), s.draw('x\r\n'), cmd('c', 0)
                self.ae(visible()[:4], ('$ a', '$ b', 'x', '$ c'))
                self.assertTrue(s.set_last_visited_prompt(visited))
                set_region_and_scroll(2, 5, '1S')
                self.ae(s.historybuf.count, 0)
                self.ae(visible()[:3], ('$ a', 'x', '$ c'))
                if expected is None:
                    assert_unset()
                else:
                    assert_visited(*expected)

        # Reverse index moves the screen lines down and discards the bottom
        # line, without touching the scrollback
        new_screen(lines=4)
        cmd('a', 0), cmd('b', 0), cmd('c', 0), cmd('d', 0), cmd('e', 0), s.draw('z')
        self.ae(s.historybuf.count, 2)
        self.ae(visible(), ('$ c', '$ d', '$ e', 'z'))
        self.ae(visit('$ a'), (2, 0))
        s.cursor_position(1, 1), s.reverse_index()
        self.ae(visible(), ('', '$ c', '$ d', '$ e'))
        assert_visited('$ a', 0)
        self.assertTrue(s.set_last_visited_prompt(1))  # $ c
        s.reverse_index()
        assert_visited('$ c', 2)
        self.assertTrue(s.set_last_visited_prompt(3))  # $ d, now on the bottom line
        s.reverse_index()
        assert_unset()

        # Reverse scrolling that pulls lines back from the scrollback moves
        # everything in the scrollback and on screen down
        new_screen(lines=4)
        cmd('a', 0), cmd('b', 0), cmd('c', 0), cmd('d', 0), cmd('e', 0), s.draw('z')
        self.ae(visit('$ a'), (2, 0))
        s.reverse_scroll(1, True)
        self.ae(s.historybuf.count, 1)
        self.ae(visible(), ('$ b', '$ c', '$ d', '$ e'))
        assert_visited('$ a', 0)
        s.reverse_scroll(1, True)
        self.ae(s.historybuf.count, 0)
        self.ae(visible()[0], '$ a')
        assert_visited('$ a', 0)

        # With a top margin the scrollback does not adjoin the scroll region,
        # so reverse scrolling must insert blank lines and leave the lines
        # above the region and the scrollback alone
        new_screen(lines=4)
        cmd('a', 0), cmd('b', 0), cmd('c', 0), cmd('d', 0), cmd('e', 0), s.draw('z')
        self.assertTrue(s.set_last_visited_prompt(0))  # $ c
        parse_bytes(s, b'\x1b[2;4r\x1b[1+T\x1b[r')
        self.ae(s.historybuf.count, 2)
        self.ae(visible(), ('$ c', '', '$ d', '$ e'))
        assert_visited('$ c', 0)
        self.assertTrue(s.set_last_visited_prompt(2))  # $ d
        parse_bytes(s, b'\x1b[2;4r\x1b[1+T\x1b[r')
        self.ae(visible(), ('$ c', '', '', '$ d'))
        assert_visited('$ d', 3)

        # A prompt that falls off the end of the scrollback is forgotten, even
        # though the scrollback still has as many lines as before
        new_screen(lines=3, scrollback=2)
        cmd('a', 0)
        i = 0
        while s.historybuf.count < s.historybuf.ynum:  # fill the scrollback with $ a as its oldest line
            s.draw(f'f{i}\r\n')
            i += 1
        self.ae(str(s.historybuf.line(s.historybuf.count - 1)), '$ a')
        self.ae(visit('$ a'), (s.historybuf.count, 0))
        assert_visited('$ a', 0)
        s.draw('last\r\n')
        self.ae(s.historybuf.count, s.historybuf.ynum)
        assert_unset()

        # In a full scrollback, prompts that are not the oldest line stay on
        # their content as old lines are dropped
        new_screen(lines=3, scrollback=2)
        s.draw('f\r\n'), cmd('a', 0)
        while s.historybuf.count < s.historybuf.ynum:
            s.draw('f\r\n')
        self.ae(str(s.historybuf.line(s.historybuf.count - 2)), '$ a')
        self.ae(visit('$ a'), (s.historybuf.count - 1, 0))
        s.draw('last\r\n')
        self.ae(str(s.historybuf.line(s.historybuf.count - 1)), '$ a')
        assert_visited('$ a', 0)
        s.draw('last\r\n')
        assert_unset()

        # Inserting and deleting lines moves the lines below the cursor in the
        # scroll region, discarding lines pushed off its bottom
        def five_prompts(lines=6):
            new_screen(lines=lines)
            for x in 'abcde':
                cmd(x, 0)
            self.ae(visible()[:5], ('$ a', '$ b', '$ c', '$ d', '$ e'))

        five_prompts()
        self.assertTrue(s.set_last_visited_prompt(3))  # $ d
        parse_bytes(s, b'\x1b[2H\x1b[L')  # insert a line at row 1
        self.ae(visible()[:6], ('$ a', '', '$ b', '$ c', '$ d', '$ e'))
        assert_visited('$ d', 4)
        parse_bytes(s, b'\x1b[2H\x1b[2M')  # delete rows 1 and 2
        self.ae(visible()[:4], ('$ a', '$ c', '$ d', '$ e'))
        assert_visited('$ d', 2)
        self.assertTrue(s.set_last_visited_prompt(0))  # above the cursor
        parse_bytes(s, b'\x1b[2H\x1b[3L')
        assert_visited('$ a', 0)
        five_prompts()
        self.assertTrue(s.set_last_visited_prompt(3))
        parse_bytes(s, b'\x1b[2H\x1b[3M')  # deletes the visited line
        assert_unset()
        five_prompts()
        self.assertTrue(s.set_last_visited_prompt(3))
        parse_bytes(s, b'\x1b[2H\x1b[2L')  # pushes the visited line off the bottom of the screen
        self.ae(visible()[5], '$ d')
        parse_bytes(s, b'\x1b[2H\x1b[L')
        assert_unset()
        five_prompts()
        self.assertTrue(s.set_last_visited_prompt(4))  # $ e, below the scroll region
        parse_bytes(s, b'\x1b[1;4r\x1b[2H\x1b[2L\x1b[r')
        self.ae(visible()[:5], ('$ a', '', '', '$ b', '$ e'))
        assert_visited('$ e', 4)
        self.assertTrue(s.set_last_visited_prompt(3))  # $ b, at the bottom of the scroll region
        parse_bytes(s, b'\x1b[1;4r\x1b[2H\x1b[L\x1b[r')
        assert_unset()
        # inserting a huge number of lines must not overflow
        five_prompts()
        self.assertTrue(s.set_last_visited_prompt(3))
        parse_bytes(s, b'\x1b[2H\x1b[4294967295L')
        assert_unset()

        # A hard reset forgets the last visited prompt
        five_prompts()
        self.assertTrue(s.set_last_visited_prompt(1))
        s.reset()
        cmd('x', 0), cmd('y', 0)
        assert_unset()

        # Erasing a command when the live prompt has itself scrolled into the
        # scrollback: lines above the erased command move down, the lines of the
        # live prompt in the scrollback stay where they are
        def long_live_prompt():
            new_screen(lines=5)
            cmd('a', 1), cmd('b', 2)
            mark_prompt(), s.draw('$ l0')
            for i in range(1, 7):
                s.draw(f'\r\nl{i}')
            self.ae(s.historybuf.count, 7)
            self.ae(str(s.historybuf.line(1)), '$ l0')

        long_live_prompt()
        self.ae(visit('$ a'), (7, 0))
        self.assertTrue(s.erase_last_command())
        self.ae(s.historybuf.count, 4)
        self.ae(lvco(), 'a0')
        assert_visited('$ a', 0)
        long_live_prompt()
        self.ae(visit('$ l0'), (2, 0))
        self.assertTrue(s.erase_last_command())
        assert_visited('$ l0', 0)
        self.ae(s.scrolled_by, 0)
        long_live_prompt()
        visit('$ b')
        self.assertTrue(s.erase_last_command())
        assert_unset()

        # Clearing the scrollback forgets a prompt that was in it
        new_screen(lines=3)
        cmd('a', 1), cmd('b', 1)
        self.assertTrue(s.historybuf.count)
        visit('$ a')
        s.clear_scrollback()
        assert_unset()

        # Output arriving while scrolled back keeps the visited prompt on the
        # same content and jumping back shows it at the row it was visited at
        new_screen(lines=5, scrollback=50)
        cmd('a', 2), cmd('b', 2), cmd('c', 2)
        sb, y = visit('$ b')
        for i in range(7):
            s.draw(f'n{i}\r\n')
        self.ae(lvco(), 'b0\nb1')
        self.assertTrue(s.scroll_to_prompt(0))
        self.ae((s.scrolled_by, str(s.visual_line(y))), (sb + 7, '$ b'))

    def test_erase_last_command_with_live_prompt_in_scrollback(self):
        # A long live prompt, such as a multi-line command being typed, can
        # scroll its own first lines into the scrollback. Erasing the last
        # command must then delete lines from the middle of the scrollback,
        # leaving the live prompt intact.
        from kitty.window import as_text

        def new_screen():
            return self.create_screen(cols=10, lines=5, scrollback=30)

        def mark_prompt():
            parse_bytes(s, b'\x1b]133;A\a')

        def mark_output():
            parse_bytes(s, b'\x1b]133;C\a')

        def at():
            return as_text(s, add_history=True)

        def visible():
            return tuple(str(s.visual_line(y)) for y in range(s.lines))

        def assert_no_multicell_fragments():
            # every part of a multicell char must be adjoined by the parts of
            # the same char above and below it, in the scrollback and on screen
            for y in range(-s.historybuf.count, s.lines):
                for x in range(s.columns):
                    c = s.cpu_cells(y, x)
                    if c['mcd'] is None:
                        continue
                    scale = c['mcd']['scale']
                    for dy, expected_y in ((-1, c['y'] - 1), (1, c['y'] + 1)):
                        if 0 <= expected_y < scale:
                            other = s.cpu_cells(y + dy, x)
                            msg = f'multicell part at {x=} {y=} is missing its part at y={y + dy}'
                            self.assertIsNotNone(other['mcd'], msg)
                            self.ae((other['x'], other['y'], other['mcd']['scale']), (c['x'], expected_y, scale), msg)

        def live_prompt(num_lines=7, x=0):
            # x is the column at which every line of the prompt is drawn
            mark_prompt()
            for i in range(num_lines):
                if i:
                    s.draw('\r\n')
                if x:
                    parse_bytes(s, f'\x1b[{x + 1}G'.encode())
                s.draw(f'$ l{i}' if i == 0 else f'l{i}')

        live = '\n'.join(['$ l0'] + [f'l{i}' for i in range(1, 7)])
        for num_live_lines_in_history in (1, 2, 3):
            with self.subTest(num_live_lines_in_history=num_live_lines_in_history):
                s = new_screen()
                s.draw('before\r\n')
                mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\no1\r\n')
                live_prompt(s.lines + num_live_lines_in_history)
                live_text = '\n'.join(['$ l0'] + [f'l{i}' for i in range(1, s.lines + num_live_lines_in_history)])
                self.ae(at(), 'before\n$ p1\no0\no1\n' + live_text)
                self.ae(s.historybuf.count, 4 + num_live_lines_in_history)
                cursor = s.cursor.x, s.cursor.y
                screen_before = visible()
                self.assertTrue(s.erase_last_command())
                self.ae(at(), 'before\n' + live_text)
                self.ae(s.historybuf.count, 1 + num_live_lines_in_history)
                self.ae((s.cursor.x, s.cursor.y), cursor)
                self.ae(visible(), screen_before)
                self.assertTrue(s.erase_last_command() is False)  # nothing left to erase
                self.ae(at(), 'before\n' + live_text)

        with self.subTest('live prompt starting at the top of the screen'):
            # the erased lines are all in the scrollback, none of the live prompt is
            s = new_screen()
            s.draw('before\r\n')
            mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\no1\r\n')
            live_prompt(s.lines)
            self.ae(str(s.visual_line(0)), '$ l0')
            self.assertTrue(s.erase_last_command())
            self.ae(at(), 'before\n' + '\n'.join(['$ l0'] + [f'l{i}' for i in range(1, s.lines)]))

        # A scrolled back viewport stays on the same content: lines above the
        # erased command move down, lines below it do not move, and the viewport
        # goes to the bottom if its top line was erased
        def setup():
            nonlocal s
            s = new_screen()
            for i in range(6):
                s.draw(f'h{i}\r\n')
            mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\no1\r\n')
            live_prompt()
            self.ae(s.historybuf.count, 11)
            self.ae(str(s.historybuf.line(4)), '$ p1')

        for scrolled_by, expected_scrolled_by in ((11, 8), (7, 4), (6, 3), (5, 0), (3, 0), (2, 2), (1, 1)):
            with self.subTest(scrolled_by=scrolled_by):
                setup()
                s.scroll_to_absolute(scrolled_by)
                before = visible()
                self.assertTrue(s.erase_last_command())
                self.ae(s.scrolled_by, expected_scrolled_by)
                if expected_scrolled_by:
                    self.ae(visible()[0], before[0])
                else:
                    self.ae(visible()[-1], 'l6')
                self.ae(at(), '\n'.join(f'h{i}' for i in range(6)) + '\n' + live)

        def indented_live(num_lines=7, x=3):
            return '\n'.join(' ' * x + ('$ l0' if i == 0 else f'l{i}') for i in range(num_lines))

        with self.subTest('multicell chars cut at both edges'):
            s = new_screen()
            s.draw('before\r\n')
            draw_multicell(s, 'A', scale=2), s.draw('a\r\n')
            mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\n')
            draw_multicell(s, 'B', scale=2), s.draw('\r\n')
            live_prompt(x=3)
            self.assertIn('A', at())
            self.assertTrue(s.erase_last_command())
            self.ae(at(), 'before\n  a\n' + indented_live())
            assert_no_multicell_fragments()
        # including large chars that run through the live prompt lines in the
        # scrollback onto the screen, from the erased lines or from above them
        for scale, num_live_lines_in_history in ((3, 1), (4, 1), (4, 2), (3, 0)):
            for from_above in (False, True):
                with self.subTest(scale=scale, num_live_lines_in_history=num_live_lines_in_history, from_above=from_above):
                    s = new_screen()
                    s.draw('before\r\n')
                    if from_above:  # a char starting above the erased lines, running through them
                        draw_multicell(s, 'C', scale=scale), s.draw('\r\n')
                        mark_prompt(), parse_bytes(s, f'\x1b[{scale + 1}G'.encode()), s.draw('$ p1\r\n')
                    else:
                        mark_prompt(), s.draw('$ p1\r\n'), mark_output()
                        draw_multicell(s, 'C', scale=scale), s.draw('\r\n')
                    live_prompt(s.lines + num_live_lines_in_history, x=scale)
                    # the char reaches the screen
                    reaches_screen = num_live_lines_in_history + (2 if from_above else 1) < scale
                    self.ae(s.cpu_cells(0, 0)['mcd'] is not None, reaches_screen)
                    assert_no_multicell_fragments()
                    self.assertTrue(s.erase_last_command())
                    # a char from above the erased lines leaves its now blank top line
                    self.ae(at(), 'before\n' + ('\n' if from_above else '') + indented_live(s.lines + num_live_lines_in_history, scale))
                    assert_no_multicell_fragments()

        # multicell chars that are not cut by the deletion must survive it
        with self.subTest('wide char at the top of the screen'):
            # no live prompt lines are left in the scrollback, so the screen
            # starts right below the deleted lines
            s = new_screen()
            s.draw('before\r\n')
            mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\no1\r\n')
            mark_prompt(), s.draw('\U0001f600$ l0')
            for i in range(1, s.lines):
                s.draw(f'\r\nl{i}')
            self.ae(str(s.visual_line(0)), '\U0001f600$ l0')
            self.ae(s.historybuf.count, 4)
            self.assertTrue(s.erase_last_command())
            self.ae(s.historybuf.count, 1)
            self.ae(str(s.visual_line(0)), '\U0001f600$ l0')
            self.ae((s.cpu_cells(0, 0)['mcd'] is not None, s.cpu_cells(0, 1)['mcd'] is not None), (True, True))
            assert_no_multicell_fragments()
        for num_live_lines_in_history in (1, 2):
            with self.subTest('scaled char in the live prompt running onto the screen', num_live_lines_in_history=num_live_lines_in_history):
                # a char in the live prompt whose top is in the scrollback and
                # whose bottom is on screen is not cut by the deletion
                scale = num_live_lines_in_history + 1
                s = new_screen()
                s.draw('before\r\n')
                mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\n')
                mark_prompt(), draw_multicell(s, 'D', scale=scale), s.draw('$ l0')
                for i in range(1, s.lines + num_live_lines_in_history):
                    s.draw('\r\n'), parse_bytes(s, f'\x1b[{scale + 1}G'.encode()), s.draw(f'l{i}')
                self.ae(s.historybuf.count, 3 + num_live_lines_in_history)
                self.ae(s.cpu_cells(0, 0)['y'], scale - 1)  # the bottom of D is on screen
                self.assertTrue(s.erase_last_command())
                self.ae(s.historybuf.count, 1 + num_live_lines_in_history)
                for y in range(-num_live_lines_in_history, 1):
                    c = s.cpu_cells(y, 0)
                    self.assertIsNotNone(c['mcd'], f'{y=}')
                    self.ae((c['y'], c['mcd']['scale']), (y + num_live_lines_in_history, scale))
                self.ae(str(s.historybuf.line(num_live_lines_in_history - 1)), 'D$ l0')
                assert_no_multicell_fragments()

        # a wrapped line above the erased command no longer wraps into the live prompt
        with self.subTest('wrapped line above, live prompt in the scrollback'):
            s = new_screen()
            s.draw('x' * (s.columns + 3))  # wraps into the line the erased prompt is on
            mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\n')
            live_prompt()
            self.ae(at(), 'x' * (s.columns + 3) + '$ p1\no0\n' + live)
            self.assertTrue(s.erase_last_command())
            self.ae(at(), 'x' * s.columns + '\n' + live)
        # also when the erased lines are partly or wholly on screen
        for num_before in (0, 4):
            with self.subTest(num_before=num_before):
                s = new_screen()
                s.draw('h\r\n' * num_before)
                s.draw('x' * (s.columns + 3))
                mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\no1\r\no2\r\no3\r\n')
                live_prompt(1)
                self.ae(s.historybuf.count, 2 + num_before)  # the erased lines start in the scrollback
                self.assertTrue(s.erase_last_command())
                self.ae(at().rstrip(), 'h\n' * num_before + 'x' * s.columns + '\n$ l0')

        # a selection is cleared when lines are deleted from the scrollback
        # rather than going stale and selecting whatever moved into its rows
        with self.subTest('selection'):
            setup()
            s.scroll_to_absolute(6)
            s.start_selection(0, 0), s.update_selection(1, 0)
            self.ae(''.join(s.text_for_selection()), 'h5')
            self.assertTrue(s.erase_last_command())
            self.ae(s.text_for_selection(), ())

        # a full scrollback ring that has wrapped around
        for extra in range(0, 12):
            with self.subTest(full_ring_extra_lines=extra):
                s = self.create_screen(cols=10, lines=5, scrollback=5)
                ynum = s.historybuf.ynum
                for i in range(ynum + extra):
                    s.draw(f'h{i}\r\n')
                mark_prompt(), s.draw('$ p1\r\n'), mark_output(), s.draw('o0\r\no1\r\n')
                live_prompt()
                self.ae(s.historybuf.count, ynum)
                expected = at().replace('$ p1\no0\no1\n', '')
                self.assertTrue(s.erase_last_command())
                self.ae(at(), expected)
                self.ae(s.historybuf.count, ynum - 3)
                # adding lines afterwards keeps the ring consistent
                s.draw('\r\nl7\r\nl8\r\nl9\r\nl10')
                self.ae(at(), expected + '\nl7\nl8\nl9\nl10')

    def test_command_and_alternate_screen_state(self):
        # Used by custom shaders
        s = self.create_screen()
        self.assertFalse(s.command_running)
        self.ae((s.command_started_at, s.command_finished_at), (0, 0))
        parse_bytes(s, b'\033]133;A\007')  # a prompt with no running command finishes nothing
        self.ae(s.command_finished_at, 0)
        parse_bytes(s, b'\033]133;C\007')
        self.assertTrue(s.command_running)
        started = s.command_started_at
        self.assertGreater(started, 0)
        self.ae(s.command_finished_at, 0)
        parse_bytes(s, b'\033]133;A;k=s\007')  # a secondary prompt does not finish the command
        self.assertTrue(s.command_running)
        parse_bytes(s, b'\033]133;D;0\007')
        self.assertFalse(s.command_running)
        finished = s.command_finished_at
        self.assertGreaterEqual(finished, started)
        parse_bytes(s, b'\033]133;A\007')  # the prompt after D does not finish it again
        self.ae(s.command_finished_at, finished)
        parse_bytes(s, b'\033]133;C\007')
        self.assertTrue(s.command_running)
        parse_bytes(s, b'\033]133;A\007')  # a shell that does not send D
        self.assertFalse(s.command_running)
        self.assertGreaterEqual(s.command_finished_at, s.command_started_at)

        self.ae((s.alternate_screen_entered_at, s.alternate_screen_exited_at), (0, 0))
        parse_bytes(s, b'\033[?1049h')
        self.assertTrue(s.is_using_alternate_linebuf())
        entered = s.alternate_screen_entered_at
        self.assertGreater(entered, 0)
        self.ae(s.alternate_screen_exited_at, 0)
        parse_bytes(s, b'\033[?1049h')  # already on the alternate screen
        self.ae(s.alternate_screen_entered_at, entered)
        parse_bytes(s, b'\033[?1049l')
        self.assertFalse(s.is_using_alternate_linebuf())
        self.assertGreaterEqual(s.alternate_screen_exited_at, entered)

    def test_pointer_shapes(self):
        from kitty.window import set_pointer_shape

        s = self.create_screen()
        c = s.callbacks
        response = ''

        def cb(data):
            nonlocal response
            response = set_pointer_shape(s, str(data, 'utf-8'))

        c.set_pointer_shape = cb

        def send(a):
            nonlocal response
            response = ''
            parse_bytes(s, f'\x1b]22;{a}\x1b\\'.encode())
            return response

        self.ae(send('?__current__'), '0')
        self.ae(send('?__default__,__grabbed__,default,ne-resize,crosshair,XXX'), 'text,default,1,1,1,0')

        def t(q, e=None):
            self.ae(send(q), '')
            self.ae(send('?__current__'), e)

        t('default', 'default')
        s.reset()
        self.ae(send('?__current__'), '0')
        t('=crosshair', 'crosshair')
        t('<', '0')
        t('=crosshair', 'crosshair')
        t('', '0')
        t('>help', 'help')
        t('>wait', 'wait')
        t('<', 'help')
        t('<', '0')
        t('default,help', 'help')
        t('<', '0')
        t('>default,help', 'help')
        t('<', 'default')
        t('<', '0')
        t('=left_ptr', 'default')
        t('=fleur', 'move')

        names = 'alias cell copy crosshair help move wait text pointer progress zoom-in zoom-out e-resize n-resize s-resize w-resize'.split()
        for which_screen in (0, 1):
            s.reset()
            if which_screen:
                s.toggle_alt_screen()
            for n in names:
                s.change_pointer_shape('>', n)
            for n in reversed(names):
                self.ae(send('?__current__'), n)
                s.change_pointer_shape('<', '')
            self.ae(send('?__current__'), '0')
            for n in names + ['ne-resize']:
                s.change_pointer_shape('>', n)
            for n in reversed(names[1:] + ['ne-resize']):
                self.ae(send('?__current__'), n)
                s.change_pointer_shape('<', '')
            self.ae(send('?__current__'), '0')
            if which_screen:
                s.toggle_alt_screen()

    def test_decoration_sgr_round_trip(self):
        for code, extra, expected in (
            (1, '', '4'),
            (2, '', '4:2'),
            (3, '', '4:3'),
            (4, '', '4:4'),
            (5, '', '4:5'),
            (4, ';3;31', '3;31;4:4'),
            (5, ';3;31', '3;31;4:5'),
        ):
            s = self.create_screen(cols=5, lines=2)
            parse_bytes(s, f'\x1b[4:{code}{extra}mx'.encode())
            ansi = s.line(0).as_ansi()
            self.ae(ansi, f'\x1b[{expected}mx')
            s2 = self.create_screen(cols=5, lines=2)
            parse_bytes(s2, ansi.encode())
            self.ae(s2.line(0).as_ansi(), ansi)

    def test_dump_lines_continued(self):
        s = self.create_screen(cols=5, lines=3, scrollback=5)
        s.draw('abcdefgh')
        s.carriage_return(), s.linefeed()
        s.draw('xy')
        for which_screen in (0, 1):
            accum = []
            s.dump_lines_with_attrs(accum.append, which_screen)
            lines = re.sub(r'\x1b\[[\d;]*m', '', ''.join(accum)).splitlines()
            rows = [x for x in lines if re.match(r'-?\d+: ', x)]
            if which_screen == 0:
                self.ae(len(rows), 3)
                self.assertIn('continued', rows[1])
            for i, row in enumerate(rows):
                self.assertEqual('continued' in row, which_screen == 0 and i == 1, row)

    def test_live_mark_colors(self):
        from kitty.fast_data_types import COLOR_LAYER_GLOBAL, MARK_MASK, patch_color_profiles

        opts = self.set_options({'palette_generate': 'fixed'})
        profiles = tuple(ColorProfile(opts) for _ in range(3))
        marks = range(1, MARK_MASK + 1)
        channels = ('foreground', 'background')

        def configured():
            return [[int(getattr(opts, f'mark{m}_{ch}')) for ch in channels] for m in marks]

        def ae(cp, expected):
            self.ae([list(pair) for pair in cp.test_mark_colors()], expected)

        for cp in profiles:
            ae(cp, configured())
        # Patch all marks in the first two profiles, the third must be unaffected
        for base in (0x123400, 0x567800):
            spec = {f'mark{m}_{ch}': base + 2 * m + j for m in marks for j, ch in enumerate(channels)}
            patch_color_profiles(spec, None, profiles[:2], COLOR_LAYER_GLOBAL)
            expected = [[spec[f'mark{m}_{ch}'] for ch in channels] for m in marks]
            for cp in profiles[:2]:
                ae(cp, expected)
            ae(profiles[2], configured())
        # Patching a single channel of a single mark must not affect the others
        for i, m in enumerate(marks):
            for j, ch in enumerate(channels):
                expected[i][j] = 0xABCD00 + 2 * i + j
                patch_color_profiles({f'mark{m}_{ch}': expected[i][j]}, None, profiles[:1], COLOR_LAYER_GLOBAL)
                ae(profiles[0], expected)
        for reset in (False, True):
            profiles[0].reload_from_opts(opts, reset_overriden_colors=reset)
            ae(profiles[0], configured())

    def test_mark_color_layers(self):
        from kitty.fast_data_types import COLOR_LAYER_GLOBAL, COLOR_LAYER_OVERRIDE, COLOR_LAYER_SESSION, COLOR_LAYER_WINDOW, patch_color_profiles

        opts = self.set_options({'palette_generate': 'fixed'})
        s = self.create_screen()
        cp = s.color_profile
        cp.reload_from_opts(opts)
        configured = cp.test_mark_colors()

        def theme(bg, layer=COLOR_LAYER_GLOBAL, clear=False, profile=cp):
            patch_color_profiles({'mark1_background': bg}, None, (profile,), layer, clear)

        def check(bg, profile=cp):
            # only the background of mark1 is ever changed
            self.ae(profile.test_mark_colors(), ((configured[0][0], bg),) + configured[1:])

        theme(1)
        check(1)
        self.assertNotIn('mark1_background', cp.as_dict())
        # colors set by the program survive changes to the configured colors
        theme(2, COLOR_LAYER_OVERRIDE)
        theme(3)
        check(2)
        # and are restored by popping the color stack and removed by a full reset
        parse_bytes(s, b'\x1b[#P')
        theme(4, COLOR_LAYER_OVERRIDE)
        check(4)
        parse_bytes(s, b'\x1b[#Q')
        check(2)
        parse_bytes(s, b'\x1bc')
        check(3)
        # window layer colors survive changes to the global layer and full reset
        theme(5, COLOR_LAYER_WINDOW)
        theme(6)
        check(5)
        self.ae(cp.as_dict()['mark1_background'], 5)
        self.assertNotIn('mark1_foreground', cp.as_dict())
        theme(7, COLOR_LAYER_OVERRIDE)
        parse_bytes(s, b'\x1bc')
        check(5)
        # session layer colors are above the window layer
        theme(8, COLOR_LAYER_SESSION)
        check(8)
        cp.reset_layer(COLOR_LAYER_SESSION)
        check(5)
        # reloading from opts keeps the window layer, and program colors unless reset
        theme(9, COLOR_LAYER_OVERRIDE)
        cp.reload_from_opts(opts, reset_overriden_colors=False)
        check(9)
        cp.reload_from_opts(opts)
        check(5)
        # copying colors copies all layers
        theme(10, COLOR_LAYER_OVERRIDE)
        s2 = self.create_screen()
        s2.copy_colors_from(s)
        check(10, s2.color_profile)
        parse_bytes(s2, b'\x1bc')
        check(5, s2.color_profile)
        parse_bytes(s, b'\x1bc')
        cp.reset_layer(COLOR_LAYER_WINDOW)
        check(configured[0][1])
        # changing the global layer and clearing upper layers replaces colors
        # from all layers above it, like set-colors --configured
        theme(11, COLOR_LAYER_WINDOW)
        theme(12, COLOR_LAYER_SESSION)
        theme(13, COLOR_LAYER_OVERRIDE)
        theme(14, clear=True)
        check(14)
        cp.reset_layer(COLOR_LAYER_SESSION)
        cp.reset_layer(COLOR_LAYER_WINDOW)
        check(14)
        self.assertNotIn('mark1_background', cp.as_dict())

    def test_color_profile(self):
        from kitty.fast_data_types import COLOR_LAYER_WINDOW, NULL_COLOR_VALUE, patch_color_profiles

        self.ae(NULL_COLOR_VALUE, 0xFFFFFFFF)
        opts = self.set_options({'palette_generate': 'fixed'})
        c = ColorProfile(opts)
        for i in range(8):
            col = getattr(opts, f'color{i}')
            self.ae(c.as_color(i << 8 | 1), col)
        for i in range(16, 256):
            self.assertIsNone(getattr(opts, f'color{i}'))
        self.ae(c.as_color(255 << 8 | 1), Color(0xEE, 0xEE, 0xEE))
        s = self.create_screen()
        s.color_profile.reload_from_opts(opts)

        def q(send, expected=None):
            s.callbacks.clear()
            parse_bytes(s, b'\x1b]21;' + ';'.join(f'{k}={v}' for k, v in send.items()).encode() + b'\a')
            self.ae(s.callbacks.color_control_responses, [expected] if expected else [])

        # Unknown fields must be reported with their name base64 encoded, not echoed back
        # verbatim, to prevent using this escape code to emit arbitrary printable ASCII text
        q(
            {k: '?' for k in 'background foreground 213 unknown'.split()},
            {'background': opts.background, 'foreground': opts.foreground, '213': Color(255, 135, 255), 'unknown': ['unknown']},
        )
        q(
            {'arbitrary text!': '?', ' 5 ': '?', 'transparent_background_colorX': '?'},
            {'unknown': ['arbitrary text!', ' 5 ', 'transparent_background_colorX']},
        )
        q({'background': 'aquamarine'})
        q(
            {'background': '?', 'selection_background': '?'},
            {'background': Color.parse_color('Aquamarine'), 'selection_background': s.color_profile.highlight_bg},
        )
        q({'selection_background': ''})
        self.assertIsNone(s.color_profile.highlight_bg)
        q({'selection_background': '?'}, {'selection_background': ''})
        self.assertTrue(s.color_profile.palette_color_is_generated(213))
        opts = self.set_options({'palette_generate': 'semantic'})
        q({'213': ''})
        q({'213': '?'}, {'213': Color(216, 125, 215)})
        self.assertTrue(s.color_profile.palette_color_is_generated(213))
        s.color_profile.reload_from_opts(opts)
        q({'transparent_background_color9': '?'}, {'unknown': ['transparent_background_color9']})
        q({'transparent_background_color2': '?'}, {'transparent_background_color2': ''})
        q({'transparent_background_color2': 'red@0.5'})
        q({'transparent_background_color2': '?'}, {'transparent_background_color2': (Color(255, 0, 0), 126)})
        q({'transparent_background_color2': '#ffffff@-1'})
        q({'transparent_background_color2': '?'}, {'transparent_background_color2': (Color(255, 255, 255), 255)})
        opts.color114 = Color(1, 1, 4)
        s.color_profile.reload_from_opts(opts)
        self.assertTrue(s.color_profile.palette_color_is_generated(213))
        self.assertFalse(s.color_profile.palette_color_is_generated(114))
        q({'213': '?'}, {'213': Color(216, 125, 215)})
        patch_color_profiles({'background': Color(255, 255, 255), 'foreground': Color(0, 0, 0)}, (), (s.color_profile,), True)
        self.assertTrue(s.color_profile.palette_color_is_generated(213))
        self.assertFalse(s.color_profile.palette_color_is_generated(114))
        # the generated colors are re-generated from the new configured colors
        opts.background, opts.foreground = Color(255, 255, 255), Color(0, 0, 0)
        q({'213': '?'}, {'213': ColorProfile(opts).as_color(213 << 8 | 1)})
        # as_dict() uses the same names as kitty.conf
        patch_color_profiles({'cursor_text_color': 0x123456, 'cursor': 0xABCDEF}, None, (s.color_profile,), COLOR_LAYER_WINDOW)
        d = s.color_profile.as_dict()
        self.ae((d['cursor_text_color'], d['cursor']), (0x123456, 0xABCDEF))
        self.assertNotIn('cursor_text', d)

    def test_color_layers(self):
        from kitty.fast_data_types import COLOR_LAYER_GLOBAL, COLOR_LAYER_OVERRIDE, COLOR_LAYER_WINDOW, patch_color_profiles

        opts = self.set_options({'palette_generate': 'fixed'})
        s = self.create_screen()
        cp = s.color_profile
        cp.reload_from_opts(opts)
        red, green, blue, white, black = Color(255, 0, 0), Color(0, 255, 0), Color(0, 0, 255), Color(255, 255, 255), Color(0, 0, 0)
        dark = {'background': int(black), 'foreground': int(white), 'color1': int(Color(1, 1, 1)), 'color2': int(Color(2, 2, 2))}
        light = {'background': int(white), 'foreground': int(black), 'color1': int(Color(11, 11, 11)), 'color2': int(Color(12, 12, 12))}

        def pal(i):
            return cp.as_color(i << 8 | 1)

        def osc21(**kw):
            parse_bytes(s, b'\x1b]21;' + ';'.join(f'{k}={v}' for k, v in kw.items()).encode() + b'\a')

        def theme(spec, layer=COLOR_LAYER_GLOBAL, clear=False, tbc=None):
            patch_color_profiles(spec, tbc, (cp,), layer, clear)

        def check(bg, fg, c1, c2):
            self.ae((cp.default_bg, cp.default_fg, pal(1), pal(2)), (bg, fg, c1, c2))

        theme(dark)
        check(black, white, Color(1, 1, 1), Color(2, 2, 2))
        # colors set by the program survive changes to the configured colors
        osc21(background='#ff0000', **{'1': '#00ff00'})
        theme(light)
        check(red, black, green, Color(12, 12, 12))
        # and are reset to the new configured colors
        parse_bytes(s, b'\x1b]21;background;1\a')
        check(white, black, Color(11, 11, 11), Color(12, 12, 12))

        # the color stack restores the current configured colors for colors
        # not set by the program
        theme(dark)
        osc21(**{'2': '#0000ff'})
        parse_bytes(s, b'\x1b[#P')
        osc21(background='#ff0000', foreground='#00ff00', **{'1': '#ff0000', '2': '#00ff00'})
        theme(light)
        check(red, green, red, green)
        parse_bytes(s, b'\x1b[#Q')
        check(white, black, Color(11, 11, 11), blue)
        cp.reset_color(2)
        check(white, black, Color(11, 11, 11), Color(12, 12, 12))

        # window layer colors survive changes to the global layer and are reset to
        theme({'background': int(blue), 'color2': int(red)}, COLOR_LAYER_WINDOW)
        check(blue, black, Color(11, 11, 11), red)
        self.ae(cp.as_dict()['background'], int(blue))
        self.assertNotIn('foreground', cp.as_dict())
        theme(dark)
        check(blue, white, Color(1, 1, 1), red)
        osc21(background='#00ff00', **{'2': '#00ff00'})
        check(green, white, Color(1, 1, 1), green)
        parse_bytes(s, b'\x1b]21;background;2\a')
        check(blue, white, Color(1, 1, 1), red)
        osc21(background='#00ff00', **{'2': '#00ff00'})
        parse_bytes(s, b'\x1bc')  # full reset
        check(blue, white, Color(1, 1, 1), red)
        # window layer survives reloading the global layer from opts
        osc21(background='#00ff00')
        cp.reload_from_opts(opts)
        check(blue, opts.foreground, opts.color1, red)
        theme(dark)
        # copying colors copies all layers
        s2 = self.create_screen()
        s2.copy_colors_from(s)
        theme(light)
        patch_color_profiles(light, None, (s2.color_profile,), COLOR_LAYER_GLOBAL)
        self.ae((s2.color_profile.default_bg, s2.color_profile.default_fg, s2.color_profile.as_color(2 << 8 | 1)), (blue, black, red))

        # changing the global layer and clearing upper layers replaces colors
        # from the window layer and the program, like set-colors --configured
        osc21(foreground='#ff0000', **{'1': '#ff0000'})
        check(blue, red, red, red)
        theme({'foreground': int(green), 'color1': int(green)}, clear=True)
        check(blue, green, green, red)
        theme({'background': int(white), 'color2': int(white)}, clear=True)
        check(white, green, green, white)
        self.assertNotIn('background', cp.as_dict())
        # the override layer is like set-colors without --configured
        theme({'background': int(red), 'color2': int(red)}, COLOR_LAYER_OVERRIDE)
        theme(dark)
        check(red, white, Color(1, 1, 1), red)

        # transparent background colors
        theme(dark, tbc=((Color(1, 2, 3), 0.5),))
        self.ae(cp.get_transparent_background_color(0), Color(1, 2, 3, 127))
        osc21(transparent_background_color1='#ff0000@0.5')
        theme(light, tbc=((Color(3, 2, 1), 0.5),))
        self.ae(cp.get_transparent_background_color(0), Color(255, 0, 0, 127))
        theme({}, COLOR_LAYER_WINDOW, tbc=((Color(4, 4, 4), 1.0),))
        parse_bytes(s, b'\x1b]21;transparent_background_color1\a')
        self.ae(cp.get_transparent_background_color(0), Color(4, 4, 4, 255))
        theme(dark, tbc=((Color(1, 2, 3), 0.5),))
        self.ae(cp.get_transparent_background_color(0), Color(4, 4, 4, 255))
        theme({}, tbc=((Color(1, 2, 3), 0.5),), clear=True)
        self.ae(cp.get_transparent_background_color(0), Color(1, 2, 3, 127))

        # generated palette colors
        opts = self.set_options({'palette_generate': 'semantic'})
        cp.reload_from_opts(opts)
        theme(dark)

        def generated(spec, idx=213):
            o = self.set_options({'palette_generate': 'semantic', **{k: Color(v >> 16, (v >> 8) & 0xFF, v & 0xFF) for k, v in spec.items()}})
            return ColorProfile(o).as_color(idx << 8 | 1)

        self.assertTrue(cp.palette_color_is_generated(213))
        self.ae(pal(213), generated(dark))
        osc21(**{'100': '#ff0000'})
        theme(light)
        self.ae(pal(213), generated(light))
        self.ae(pal(100), red)
        self.assertTrue(cp.palette_color_is_generated(213))
        # generated from the window layer colors
        theme({'background': int(blue)}, COLOR_LAYER_WINDOW)
        self.ae(pal(213), generated({**light, 'background': int(blue)}))

    def test_session_color_schemes(self):
        from kitty.colors import SessionColorSchemes, parse_color_scheme_variants
        from kitty.fast_data_types import COLOR_LAYER_GLOBAL, COLOR_LAYER_SESSION, COLOR_LAYER_WINDOW, patch_color_profiles

        opts = self.set_options({'palette_generate': 'fixed'})
        s = self.create_screen()
        cp = s.color_profile
        cp.reload_from_opts(opts)
        red, green, blue, white, black = Color(255, 0, 0), Color(0, 255, 0), Color(0, 0, 255), Color(255, 255, 255), Color(0, 0, 0)
        patch_color_profiles({'background': int(black), 'foreground': int(white), 'color1': 1}, None, (cp,), COLOR_LAYER_GLOBAL)

        # validation of untrusted data
        for bad in (
            [],
            {'dusk': {}},
            {'dark': []},
            {'dark': {'background_image': 1}},
            {'dark': {'url_color': 1}},
            {'dark': {'background': None}},
            {'dark': {'color1': None}},
            {'dark': {'color1': -1}},
            {'dark': {'color1': 0x1000000}},
            {'dark': {'color1': True}},
            {'dark': {'color1': '#ff0000'}},
        ):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_color_scheme_variants(bad)
        variants = parse_color_scheme_variants(
            {
                'dark': {'background': int(blue), 'color1': int(red), 'color16': None, 'cursor': None},
                'light': {'background': int(white), 'foreground': int(black), 'color1': int(green)},
            }
        )

        def pal(i):
            return cp.as_color(i << 8 | 1)

        def check(bg, fg, c1):
            self.ae((cp.default_bg, cp.default_fg, pal(1)), (bg, fg, c1))

        scs = SessionColorSchemes()
        self.assertFalse(scs)
        parse_bytes(s, b'\x1b[#P')  # the ssh kitten pushes colors first
        scs.add(cp.color_stack_depth(), variants)
        scs.apply(cp, 'dark')
        check(blue, white, red)
        self.assertIsNone(cp.cursor_color)
        self.assertTrue(cp.palette_color_is_generated(16))
        self.ae(cp.as_dict()['background'], int(blue))
        scs.apply(cp, 'light')
        check(white, black, green)
        # no variant for the system color scheme uses the configured colors
        scs.apply(cp, 'no_preference')
        check(black, white, Color(0, 0, 1))
        self.assertNotIn('background', cp.as_dict())

        # the session layer is above the window layer, below program colors and
        # is not affected by changes to the global layer
        scs.apply(cp, 'dark')
        patch_color_profiles({'background': int(green), 'foreground': int(green)}, None, (cp,), COLOR_LAYER_WINDOW)
        check(blue, green, red)
        parse_bytes(s, b'\x1b]21;background=#ffffff\a')
        self.ae(cp.default_bg, white)
        parse_bytes(s, b'\x1b]21;background\a')  # resets to the session color
        self.ae(cp.default_bg, blue)
        patch_color_profiles({'background': int(white), 'color1': int(white)}, None, (cp,), COLOR_LAYER_GLOBAL)
        check(blue, green, red)

        # a nested session, such as ssh from the remote host, replaces the colors
        # till it ends
        parse_bytes(s, b'\x1b[#P')
        scs.add(cp.color_stack_depth(), parse_color_scheme_variants({'dark': {'background': int(red)}}))
        scs.apply(cp, 'dark')
        check(red, green, Color(255, 255, 255))
        # programs pushing and popping colors in the session do not end it
        parse_bytes(s, b'\x1b[#P\x1b]21;background=#00ff00\a')
        self.ae(cp.default_bg, green)
        parse_bytes(s, b'\x1b[#Q')
        self.assertFalse(scs.color_stack_popped(cp.color_stack_depth()))
        self.ae(cp.default_bg, red)
        parse_bytes(s, b'\x1b[#Q')
        self.assertTrue(scs.color_stack_popped(cp.color_stack_depth()))
        scs.apply(cp, 'dark')
        check(blue, green, red)
        parse_bytes(s, b'\x1b[#Q')
        self.assertTrue(scs.color_stack_popped(cp.color_stack_depth()))
        self.assertFalse(scs)
        scs.apply(cp, 'dark')
        check(green, green, white)

        # copying colors, as for launch --copy-colors
        parse_bytes(s, b'\x1b[#P')
        scs.add(cp.color_stack_depth(), variants)
        scs.apply(cp, 'light')
        s2 = self.create_screen()
        s2.copy_colors_from(s)
        scs2 = SessionColorSchemes()
        scs2.copy_from(scs)
        self.ae(s2.color_profile.default_bg, white)
        self.assertFalse(scs2.color_stack_popped(s2.color_profile.color_stack_depth()))
        scs2.apply(s2.color_profile, 'dark')
        self.ae(s2.color_profile.default_bg, blue)

        # a full reset clears the color stack and the session
        parse_bytes(s, b'\x1bc')
        self.ae(cp.color_stack_depth(), 0)
        self.assertTrue(scs.clear())
        scs.apply(cp, 'light')
        check(green, green, white)
        cp.reset_layer(COLOR_LAYER_WINDOW)
        check(white, white, white)
        with self.assertRaises(ValueError):
            cp.reset_layer(COLOR_LAYER_GLOBAL)
        patch_color_profiles({'background': int(red)}, None, (cp,), COLOR_LAYER_SESSION)
        self.ae(cp.default_bg, red)
        cp.reset_layer(COLOR_LAYER_SESSION)
        self.ae(cp.default_bg, white)

    def test_multi_cursors(self):
        s = self.create_screen()
        c = s.callbacks

        # Test detection
        def ec(payload=''):
            return f'\x1b[>{payload} q'.encode()  # ]

        parse_bytes(s, ec())
        self.ae(c.wtcbuf, ec('1;2;3;29;30;40;100;101'))

        def current() -> dict[int, tuple[int, int]]:
            ans = {}
            c.clear()
            parse_bytes(s, ec('100'))
            for entry in c.wtcbuf[6:-2].decode().split(';'):
                if entry:
                    which, _, y, x = map(int, entry.split(':'))
                    ans.setdefault(which, set()).add((x - 1, y - 1))
            return ans

        self.ae({}, current())

        def a(which: int, *positions: tuple[int, int], region=None) -> dict[int, tuple[int, int]]:
            if positions:
                buf = [f'\x1b[>{which};']  # ]
                buf.extend(f'2:{y + 1}:{x + 1};' for x, y in positions)
                parse_bytes(s, ''.join(buf).encode() + b' q')
            if region:
                if region is True:
                    parse_bytes(s, ec(f'{which};4'))
                else:
                    left, top, right, bottom = region
                    parse_bytes(s, ec(f'{which};4:{top + 1}:{left + 1}:{bottom + 1}:{right + 1}'))
            return current()

        self.ae(a(1, region=True), {1: {(x, y) for x in range(s.columns) for y in range(s.lines)}})
        self.ae(a(0, region=True), {})
        self.ae(a(29, region=(1, 2, 2, 3)), {29: {(1, 2), (2, 2), (1, 3), (2, 3)}})
        self.ae(a(2, (1, 2), (1, 3)), {29: {(2, 3), (2, 2)}, 2: {(1, 2), (1, 3)}})
        self.ae(a(0, (1, 2), (2, 3)), {29: {(2, 2)}, 2: {(1, 3)}})
        self.ae(a(0, region=True), {})
        s.cursor.x, s.cursor.y = 1, 2
        parse_bytes(s, ec('3;0'))
        self.ae(current(), {3: {(1, 2)}})
        parse_bytes(s, ec('3;2:3'))
        self.ae(current(), {3: {(1, 2)}})
        parse_bytes(s, ec('0;4:3:1:4'))
        self.ae(current(), {})

        def sc(op, r=0, g=0, b=0, slot=40):
            parse_bytes(s, ec(f'{slot};{op}:{r}:{g}:{b}'))
            c.clear()
            parse_bytes(s, ec('101'))
            for x in c.wtcbuf[3:-2].decode().split(';')[1:]:
                parts = x.split(':')
                if int(parts[0]) == slot:
                    if op < 2:
                        self.ae(op, int(parts[1]))
                    elif op == 2:
                        self.ae((op, r, g, b), tuple(map(int, parts[1:])))
                    else:
                        self.ae((op, r), tuple(map(int, parts[1:])))
                    break

        for slot in (40, 30):
            sc(0, slot=slot)
            sc(1, slot=slot)
            sc(2, 1, 2, 3, slot=slot)
            sc(5, 13, slot=slot)

    def test_activity_tracking(self):
        s = self.create_screen()
        calls = []
        s.callbacks.on_activity_since_last_focus = lambda: calls.append(1) or False
        s.focus_changed(False)
        s.track_activity = False
        parse_bytes(s, b'\x1b[31ma\x1b[mb')
        self.ae(len(calls), 0)
        s.track_activity = True
        parse_bytes(s, b'\x1b[31ma\x1b[mb')
        self.ae(len(calls), 2)

    def test_soft_reset(self):
        SOFT_RESET = b'\x1b[!p'  # DECSTR sequence

        # Screen content is preserved (unlike hard reset)
        s = self.create_screen()
        s.draw('hello')
        parse_bytes(s, SOFT_RESET)
        self.ae(str(s.line(0)), 'hello')

        # Hard reset clears screen content; soft reset does not
        s = self.create_screen()
        s.draw('hello')
        s.reset()
        self.ae(str(s.line(0)), '')

        # Cursor SGR attributes are cleared
        s = self.create_screen()
        s.select_graphic_rendition(1)  # bold
        s.select_graphic_rendition(31)  # red fg
        self.assertTrue(s.cursor.bold)
        self.assertNotEqual(s.cursor.fg, 0)
        parse_bytes(s, SOFT_RESET)
        self.assertFalse(s.cursor.bold)
        self.ae(s.cursor.fg, 0)

        # Cursor position is preserved
        s = self.create_screen()
        s.cursor_position(3, 4)
        self.ae((s.cursor.y, s.cursor.x), (2, 3))
        parse_bytes(s, SOFT_RESET)
        self.ae((s.cursor.y, s.cursor.x), (2, 3))

        # Insert mode (IRM) is cleared
        s = self.create_screen()
        s.draw('abcde')
        s.set_mode(IRM)
        parse_bytes(s, SOFT_RESET)
        # without IRM, drawing overwrites
        s.cursor.x = 0
        s.draw('X')
        self.ae(str(s.line(0)), 'Xbcde')

        # Alternate screen is NOT exited on soft reset
        s = self.create_screen()
        parse_bytes(s, b'\x1b[?1049h')  # enter alternate screen
        self.assertFalse(s.is_main_linebuf())
        parse_bytes(s, SOFT_RESET)
        self.assertFalse(s.is_main_linebuf())
        s.reset()
        self.assertTrue(s.is_main_linebuf())

    def test_ime_preedit_styling(self):
        # Pre-edit text is marked with italics and a dashed underline in the
        # highlight color, rather than reverse video.
        s = self.create_screen(cols=10, lines=3)
        s.draw('xy')
        before = s.line(0).cursor_from(0)
        s.test_draw_overlay_line('ab', 0, 0)
        line = s.line(0)
        for x in (0, 1):
            c = line.cursor_from(x)
            self.assertTrue(c.italic, f'pre-edit cell {x} is not italic')
            self.assertFalse(c.reverse, f'pre-edit cell {x} is in reverse video')
            self.ae(c.decoration, 5, f'pre-edit cell {x} is not dashed-underlined')
            # decoration_fg is packed as (rgb << 8) | type, type 2 being RGB
            self.ae(c.decoration_fg & 0xFF, 2)
            self.ae(c.decoration_fg >> 8, 0xFFFACD)  # default selection_background

        # the styling is applied to the overlay's own cursor and must be
        # restored, not leaked into the screen's cursor
        self.assertFalse(s.cursor.italic)
        self.ae(s.cursor.decoration, before.decoration)
        self.ae(s.cursor.decoration_fg, before.decoration_fg)

    def test_ime_preedit_cursor(self):
        # The cursor is placed where the IME says it is inside the pre-edit
        # text (in code points), so that one can see which character is being
        # edited when moving inside the pre-edit text, as with Chewing. See :iss:`10807`
        s = self.create_screen(cols=20, lines=3)
        self.ae(s.test_draw_overlay_line('新酷音', 2, 0), 8)  # no cursor information: after the text
        self.ae(s.test_draw_overlay_line('新酷音', 2, 0, 0), 2)
        self.ae(s.test_draw_overlay_line('新酷音', 2, 0, 1), 4)
        self.ae(s.test_draw_overlay_line('新酷音', 2, 0, 2), 6)
        self.ae(s.test_draw_overlay_line('新酷音', 2, 0, 3), 8)
        self.ae(s.test_draw_overlay_line('a新b', 0, 1, 2), 3)
        self.ae(s.test_draw_overlay_line('ab', 0, 1, 99), 2)  # out of range: after the text

        # The cursor position must be correct as soon as the pre-edit text is
        # updated, as it is collected for rendering before the overlay is drawn
        s = self.create_screen(cols=20, lines=3)
        s.draw('ab')
        self.ae(s.test_update_overlay_text('官大為'), 8)
        for cursor, x in ((0, 2), (1, 4), (2, 6), (3, 8), (1, 4)):
            self.ae(s.test_update_overlay_text('官大為', cursor), x)
        self.ae(s.test_update_overlay_text('官大ㄨㄟ', 2), 6)
        # pre-edit text that does not fit after the cursor is shifted left
        s.cursor.x = 16
        self.ae(s.test_update_overlay_text('官大為', 1), 16)
        # pre-edit text wider than the screen is right aligned and clipped on the left
        s = self.create_screen(cols=6, lines=3)
        self.ae(s.test_update_overlay_text('官大為好和', 4), 4)
        self.ae(s.test_update_overlay_text('官大為好和', 2), 0)
        self.ae(s.test_update_overlay_text('官大為好和', 0), 0)
        self.ae(s.test_update_overlay_text('官大為好和'), 6)

    def test_ime_overlay_line_start(self):
        # The IME is anchored at the start of the pre-edit text as drawn,
        # which is shifted left when it would otherwise not fit on the line
        s = self.create_screen(cols=10, lines=3)
        s.test_draw_overlay_line('ab', 3, 0)
        self.ae(s.overlay_line_start(), 3)
        self.ae(str(s.line(0)), '   ab')
        s.test_draw_overlay_line('abcd', 8, 1)
        self.ae(s.overlay_line_start(), 6)
        self.ae(str(s.line(1)), '      abcd')
        s.test_draw_overlay_line('abcdefghijkl', 8, 2)
        self.ae(s.overlay_line_start(), 0)
        self.ae(str(s.line(2)), 'cdefghijkl')

    def test_ime_text_around_cursor(self):
        # The text macOS input methods read to decide things like whether a
        # space is needed between Latin and CJK text. See :iss:`10492`.
        s = self.create_screen(cols=8, lines=3)
        self.ae(s.ime_text_around_cursor(), ('', ''))

        s.draw('abcd')
        self.ae(s.ime_text_around_cursor(), ('abcd', ''))
        s.cursor.x = 2
        self.ae(s.ime_text_around_cursor(), ('ab', 'cd'))
        s.cursor.x = 0
        self.ae(s.ime_text_around_cursor(), ('', 'abcd'))
        # trailing unwritten cells are trimmed, but written blanks are not
        s.cursor.x = 4
        s.draw('  ')
        s.cursor.x = 4
        self.ae(s.ime_text_around_cursor(), ('abcd', '  '))

        # a cursor sitting past the last cell, with the wrap still deferred
        s = self.create_screen(cols=4, lines=3)
        s.draw('abcd')
        self.ae(s.cursor.x, 4)
        self.ae(s.ime_text_around_cursor(), ('abcd', ''))

        # wide characters occupy two cells but contribute one character
        s = self.create_screen(cols=8, lines=3)
        s.draw('你好ab')
        self.ae(s.ime_text_around_cursor(), ('你好ab', ''))
        s.cursor.x = 4
        self.ae(s.ime_text_around_cursor(), ('你好', 'ab'))
        s.cursor.x = 2
        self.ae(s.ime_text_around_cursor(), ('你', '好ab'))

        # the unit is the logical line, not the row: without this an input
        # method sees nothing before a cursor at the start of a wrapped row
        s = self.create_screen(cols=4, lines=3)
        s.draw('abcdefg')
        self.ae((s.cursor.x, s.cursor.y), (3, 1))
        self.ae(s.ime_text_around_cursor(), ('abcdefg', ''))
        s.cursor.x, s.cursor.y = 0, 1
        self.ae(s.ime_text_around_cursor(), ('abcd', 'efg'))
        s.cursor.x, s.cursor.y = 2, 0
        self.ae(s.ime_text_around_cursor(), ('ab', 'cdefg'))

        # a hard line break ends the logical line
        s = self.create_screen(cols=4, lines=3)
        s.draw('ab')
        s.carriage_return(), s.linefeed()
        s.draw('cd')
        s.cursor.x = 1
        self.ae(s.ime_text_around_cursor(), ('c', 'd'))

    def test_cwd_change_notification(self):
        from kitty.window import Watchers, Window

        s = self.create_screen()
        c = s.callbacks
        parse_bytes(s, b'\x1b]7;file://host/a/b\x1b\\')
        self.ae(c.cwd_changes, [b'file://host/a/b'])
        self.ae(s.last_reported_cwd, b'file://host/a/b')
        # repeating the same directory does not report a change
        parse_bytes(s, b'\x1b]7;file://host/a/b\x07')
        self.ae(c.cwd_changes, [b'file://host/a/b'])
        parse_bytes(s, b'\x1b]7;file://host/a/c\x07')
        self.ae(c.cwd_changes, [b'file://host/a/b', b'file://host/a/c'])
        # OSC 6 is ignored
        parse_bytes(s, b'\x1b]6;file://host/x\x07')
        self.ae(c.cwd_changes, [b'file://host/a/b', b'file://host/a/c'])
        # after a reset the next report is a change
        s.reset()
        parse_bytes(s, b'\x1b]7;file://host/a/c\x07')
        self.ae(c.cwd_changes, [b'file://host/a/b', b'file://host/a/c', b'file://host/a/c'])

        delivered = []

        class FakeWindow:
            def __init__(self):
                self.watchers = Watchers()
                self.watchers.on_cwd_change.append(lambda boss, window, data: None)

            def call_watchers(self, which, data):
                delivered.append(data)

        w = FakeWindow()
        Window.on_cwd_change(w, b'file://myhost/some%20dir/x')
        Window.on_cwd_change(w, b'kitty-shell-cwd://otherhost/a b')
        Window.on_cwd_change(w, b'file:///no/host')
        Window.on_cwd_change(w, b'file://h/bad\xff')
        self.ae(
            delivered,
            [
                {'cwd': '/some dir/x', 'host': 'myhost'},
                {'cwd': '/a b', 'host': 'otherhost'},
                {'cwd': '/no/host', 'host': ''},
                {'cwd': '/bad�', 'host': 'h'},
            ],
        )
        del delivered[:]
        w.watchers.on_cwd_change.clear()
        Window.on_cwd_change(w, b'file://myhost/y')
        self.ae(delivered, [])


def detect_url(self, scale=1):
    s = self.create_screen(cols=30 * scale)

    def ae(expected, x=3, y=0):
        s.detect_url(x * scale, y * scale)
        url = ''.join(s.text_for_marked_url())
        self.assertEqual(expected, url)

    def t(url, x=0, y=0, before='', after='', expected=''):
        s.reset()
        s.cursor.x = x
        s.cursor.y = y
        text = before + url + after
        if scale == 1:
            s.draw(text)
        else:
            draw_multicell(s, text, scale=scale)
        ae(expected or url, x=x + 1 + len(before), y=y)

    t('http://moo.com')
    t('http://moo.com/something?else=+&what-')
    t('http://moo.com#fragme')
    for st, e in '() {} [] <>'.split():
        t('http://moo.com', before=st, after=e)
    for trailer in ')-=':
        t('http://moo.com' + trailer)
    for trailer in '{}([<>':  # )]>
        t('http://moo.com', after=trailer)
    if scale == 1:
        t('http://moo.com', x=s.columns - 9)
    t('https://wraps-by-one-char.com', before='[', after=']')
    t('http://[::1]:8080')
    t('https://wr[aps-by-one-ch]ar.com')
    t('http://[::1]:8080/x', after='[')  # ]
    t('http://[::1]:8080/x]y34', expected='http://[::1]:8080/x')
    t('https://wraps-by-one-char.com[]/x', after='[')  # ]
    t('https://t.me/#1_*_*_*_*')
