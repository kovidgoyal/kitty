#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

import random
import re
from itertools import product

from .base import BaseTest, draw_multicell, parse_bytes

NONE, LTR, RTL = (0, False, False), (1, False, False), (1, True, False)
AUTO = (1, False, True)
PRIMED_LTR, PRIMED_RTL = (0, False, True), (0, True, True)  # no record, the direction a leading mark set
LRM, RLM, ALM = '\u200e', '\u200f', '\u061c'
IA = '\x1b[8h\x1b[?2501h'
CUP = '\x1b[{};1H'.format  # 1-based row


def pb(s, data):
    parse_bytes(s, data.encode())


class TestBidi(BaseTest):
    def screen(self, cols=10, lines=5, **opts):
        return self.create_screen(cols=cols, lines=lines, options=opts)

    def records(self, s, *rows):
        return [s.test_bidi_line_record(y) for y in rows]

    def written(self, data, *rows, cols=10):
        s = self.screen(cols=cols)
        pb(s, data)
        return self.records(s, *rows)

    def modes(self, s):
        # BDSM and ?2501 as DECRQM reports them: 1 set, 2 reset
        s.callbacks.clear()
        pb(s, '\x1b[8$p\x1b[?2501$p')
        return tuple(int(m) for m in re.findall(rb';(\d)\$y', s.callbacks.wtcbuf))

    def test_stamp(self):
        # a row is stamped by the first char drawn into it in bidi mode, with the controls current then; explicit writes keep it
        s = self.screen()
        pb(s, 'a\x1b[8h' + CUP(2) + 'b\x1b[8l' + CUP(2) + 'c' + CUP(4) + 'd')
        self.ae(self.records(s, 0, 1, 3), [NONE, LTR, NONE])
        self.ae(self.written('\x1b[8ha\r\n\x1b[8lb', 0, 1), [LTR, NONE])  # the LF writes nothing to row 1
        self.ae(self.written('\x1b[8h\x1b[8l' + CUP(4) + 'c', 3), [NONE])
        self.ae(self.written('\x1b[8h \x1b[2 k', 0), [LTR])  # a written space is text
        self.ae(self.written('\x1b[8ha\r\n\x1b[2 kb', 0, 1), [LTR, RTL])
        self.ae(self.written('\x1b[8h\x1b[2 ka\x1b[1 k\x1b[?2501h' + CUP(1) + 'b', 0), [RTL])
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[3 ka', 0), [RTL])  # SCP 3 is ignored
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[ ka', 0), [LTR])
        self.ae(self.written('\x1b[8h\x1b[?2501ha', 0), [(1, False, True)])
        # mode changes leave records alone
        self.ae(self.written('\x1b[8h\x1b[?2501h\x1b[?s\x1b[?2501la\r\nb\r\x1b[K\x1b[?r', 0, 1), [LTR, NONE])
        self.ae(self.written('\x1b[8h\x1b[?1049h\x1b[8ha\r\nb\r\x1b[K\x1b[?1049l\x1b[?47h', 0, 1), [LTR, NONE])
        # an overlay line writes no record
        s = self.screen()
        pb(s, '\x1b[8h')
        s.test_draw_overlay_line('xy', 0, 2)
        self.ae(self.records(s, 2), [NONE])
        pb(s, CUP(3) + 'z')
        self.ae(self.records(s, 2), [LTR])
        # under force_ltr nothing is recorded or stored, a leading LRM is dropped, and DECRQM answers 4
        s = self.screen(force_ltr=True)
        pb(s, '\x1b[8h\x1b[?2501h\x1b[2 k\u200eabc')
        self.ae((self.records(s, 0), s.cpu_cells(0, 0)['text'], self.modes(s)), ([NONE], 'a', (4, 4)))
        # a multicell char stamps every row it covers, the row a later write lands on below it too
        s = self.screen()
        pb(s, '\x1b[8h' + CUP(2))
        draw_multicell(s, 'a', scale=2)
        self.ae(self.records(s, 0, 1, 2, 3), [NONE, LTR, LTR, NONE])
        s = self.screen(cols=2)
        draw_multicell(s, 'a', scale=2)
        pb(s, CUP(2) + '\x1b[8hX')
        self.ae(self.records(s, 0, 1, 2), [NONE, NONE, LTR])

    def test_stamp_lands_on_the_row_written(self):
        # (columns, data before CSI 8 h, data after it, the rows stamped)
        for cols, pre, data, want in (
            (5, 'abc', '\r', ()),
            (5, 'abc', '\x07', ()),
            (5, 'abc', '\r\n', ()),
            (5, 'abc', '\x1b[2 k\n', ()),
            (5, 'abc', '\u0085', ()),
            (5, 'abc', '\u0080\u009f', ()),
            (5, 'abc', '\x7f', ()),
            (5, 'abc', '\u0085d', (0,)),
            (5, 'abc', '\rdef', (0,)),
            (5, 'abcde', 'X', (1,)),
            (5, 'abcde', '\tX', (1,)),
            (5, 'abcde', '\x07X', (1,)),
            (5, 'abcd', '世', (1,)),
            (5, 'abcde', '\rX', (0,)),
            (5, 'abcde', '\x08X', (0,)),
            (5, '\x1b[?7labcde', 'X', (0,)),
            (5, 'abcde', '\x08世', (1,)),  # BS and HT leave the column at the last one
            (5, 'abc', '\t世', (1,)),
            (9, 'abcdefgh\r', '\t世', (1,)),
            (5, 'abcde', '́', (0,)),  # zero width joins the last cell
            (5, 'abcde', '\u200b', (0,)),
            (5, 'abc\r', '́', ()),  # zero width at the line start is dropped
            (5, 'abc\r', '\u200b', ()),
            (1, 'a\r', '世', ()),  # wider than the line
            (5, 'abc', '世', (0,)),
            (5, 'abc\r\nxyz\r', '\x08', ()),
            (5, 'abc\r\nxyz\r', '\x08Q', (0,)),
            (5, '\r\nxyz' + CUP(1), '\n', ()),
            (5, '\r\nxyz' + CUP(1) + 'abcde', '\t', ()),
            (5, '\x1b(U', '\x01', (0,)),  # the charset maps a control to a glyph
            (10, '\x1b)U', '\x0e\x01', (0,)),
            (10, '\x1b)U', '\x01', ()),
            (5, 'abc\U0001f44d', '\U0001f3fd', (0,)),
            (5, 'abc\U0001f1fa', '\U0001f1f8', (0,)),
            (5, 'abcdef\r', '́', (0,)),
            (5, 'abcdef\r', '\u200b', (0,)),
            (5, 'abcd☺', '\ufe0f', (1,)),  # the widened char moves to the next row, the row it left is not written
            (10, 'a' + '́' * 23, '́', ()),  # a combining char the cell has no room for
        ):
            with self.subTest(pre=pre, data=data):
                s = self.screen(cols=cols)
                pb(s, pre + '\x1b[8h' + data)
                self.ae(tuple(y for y in range(s.lines) if s.test_bidi_line_record(y)[0]), want)

    def test_writes_are_recorded_while_mode_is_on_or_a_record_is_held(self):
        s = self.screen()
        self.assertFalse(s.test_writes_are_recorded())
        pb(s, '\x1b[8h\x1b[8l')
        self.assertFalse(s.test_writes_are_recorded())
        pb(s, '\x1b[8h')
        self.assertTrue(s.test_writes_are_recorded())
        s = self.screen()
        pb(s, '\x1b[8ha\x1b[8l')
        self.assertTrue(s.test_writes_are_recorded())

    def test_controls_mark_nothing_dirty(self):
        s = self.screen()
        pb(s, '\x1b[8ha\r\nb\r\x1b[K')
        s.reset_dirty()
        dirty = s.linebuf.dirty_lines()
        for combo in product(('\x1b[8h', '\x1b[8l', '\x1b[0 k', '\x1b[1 k', '\x1b[2 k', '\x1b[?2501h', '\x1b[?2501l'), repeat=3):
            pb(s, ''.join(combo))
            self.ae(s.linebuf.dirty_lines(), dirty, combo)
        self.ae(self.records(s, 1), [NONE])

    def test_controls_lifetime(self):
        # the alternate screen starts with every control reset, and the main screen's come back on leaving it
        s = self.screen()
        pb(s, '\x1b[8h\x1b[?2501h\x1b[2 k\x1b[?1049h')
        self.ae(self.modes(s), (2, 2))
        pb(s, '\x1b[8ha')
        self.ae((self.modes(s), self.records(s, 0)), ((1, 2), [LTR]))
        pb(s, '\x1b[?1049l' + CUP(2) + 'b')
        self.ae((self.modes(s), self.records(s, 1)), ((1, 1), [(1, True, True)]))
        pb(s, '\x1b[?1049h\x1b[8h\x1b[8l\x1b[?1049l' + CUP(3) + 'c')
        self.ae(self.records(s, 2), [(1, True, True)])
        s = self.screen()
        pb(s, '\x1b[8h\x1b[?2501h\x1b[?1049h\x1b[?47h\x1b[?1047h\x1b[8h\x1b[?47l')  # nested switches stash once
        self.ae(self.modes(s), (1, 1))
        pb(s, '\x1b[?1047h\x1b[?1049h\x1b[?1049l')
        self.ae(self.modes(s), (1, 1))
        # RIS and DECSTR reset them on both screens
        for reset, in_alt in product(('\x1bc', '\x1b[!p'), (False, True)):
            with self.subTest(reset=reset, in_alt=in_alt):
                s = self.screen()
                pb(s, '\x1b[8h\x1b[?2501h\x1b[2 k\x1b[?1049h\x1b[8h\x1b[2 k' + ('' if in_alt else '\x1b[?1049l') + reset)
                pb(s, '\x1b[?1049l\x1b[?1049h\x1b[?1049l')
                self.ae(self.modes(s), (2, 2))
                pb(s, '\x1b[8h' + CUP(5) + 'x')
                self.ae(self.records(s, 4), [LTR])
        # XTSAVE and XTRESTORE keep one terminal-global copy of the modes, DECSC and DECRC none
        s = self.screen()
        pb(s, '\x1b[8h\x1b[?2501h\x1b[?s\x1b[8l\x1b[?2501l\x1b[?r')
        self.ae(self.modes(s), (1, 1))
        pb(s, '\x1b[?2501s\x1b[?2501l\x1b[?2501r')
        self.ae(self.modes(s), (1, 1))
        pb(s, '\x1b[2 k\x1b7\x1b[8l\x1b[?2501l\x1b[1 k\x1b8')
        self.ae(self.modes(s), (2, 2))
        pb(s, '\x1b[8h\x1b[?2501h\x1b[?s\x1b[?1049h')
        self.ae(self.modes(s), (2, 2))
        pb(s, '\x1b[?r')
        self.ae(self.modes(s), (1, 1))
        # the bare XTSAVE and XTRESTORE carry the SCP direction with the modes, a single mode's do not, RIS forgets it
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[?s\x1b[1 k\x1b[?r' + CUP(2) + 'a', 1), [RTL])
        self.ae(self.written('\x1b[8h\x1b[1 k\x1b[?s\x1b[2 k\x1b[?r' + CUP(2) + 'a', 1), [LTR])
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[?2501s\x1b[1 k\x1b[?2501r' + CUP(2) + 'a', 1), [LTR])
        self.ae(self.written('\x1b[8h\x1b[1 k\x1b[?2501s\x1b[2 k\x1b[?2501r' + CUP(2) + 'a', 1), [RTL])
        self.ae(self.written('\x1b[2 k\x1b[?s\x1bc\x1b[2 k\x1b[?r\x1b[8h' + CUP(2) + 'a', 1), [LTR])

    def test_record_lifetime(self):
        # after an erase or edit a row keeps its record if and only if a cell still holds text, and the next write to a row
        # without one records the controls current then
        rtl_then_ltr = '\x1b[8h\x1b[2 ka\x1b[1 k' + CUP(1)
        self.ae(self.written('\x1b[8hאבג\x1b[8l\r\x1b[2Kדהו\r\nדהו', 0, 1), [NONE, NONE])
        self.ae(self.written(rtl_then_ltr + '\x1b[2K', 0), [NONE])
        self.ae(self.written(rtl_then_ltr + '\x1b[2Kb', 0), [LTR])
        self.ae(self.written(rtl_then_ltr + '\x1b[2Jb', 0), [LTR])
        self.ae(self.written(rtl_then_ltr + '\x1b[Lb', 0, 1), [LTR, RTL])
        self.ae(self.written(rtl_then_ltr + '\x1b[M', 0), [NONE])  # DL pulls a fresh line up
        self.ae(self.written('\x1b[8h\x1b[2 ka\r\x1b[K\x1b[8l', 0), [NONE])
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[4Gab\x1b[4G\x1b[K\x1b[1 k\x1b[1Gc', 0), [LTR])
        for x, op in (('1', '2K'), ('4', 'K'), ('7', '1K'), ('4', '?K'), ('1', '10X'), ('3', '8X'), ('1', '10P'), ('4', '2P'), ('1', '10@'), ('4', '7@')):
            self.ae(self.written(f'\x1b[8h\x1b[2 k\x1b[4Gab\x1b[{x}G\x1b[{op}', 0), [NONE], op)
        for x, op in (('5', 'K'), ('4', '1K'), ('5', '?K'), ('1', '2X'), ('1', '2P'), ('1', '2@'), ('5', 'J'), ('5', '1J'), ('1', '1@')):
            self.ae(self.written(f'\x1b[8h\x1b[2 k\x1b[4Gabc\x1b[8l\x1b[{x}G\x1b[{op}', 0), [RTL], op)
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[3Gabc\x1b[8G\x1b[1J', 0), [NONE])  # ED 1 leaving the row blank
        self.ae(self.written('\x1b[8h\x1b[2 k\x1b[9Gab\x1b[9G\x1b[2@', 0), [NONE])  # ICH pushing all text off
        # DECSTR keeps records, a resize keeps them with the rows, rewrapped or not
        s = self.screen()
        pb(s, '\x1b[8ha\r\nx\r\x1b[K\x1b[?1049h\x1b[8hb\r\ny\r\x1b[K\x1b[!p')
        self.ae(self.records(s, 0, 1), [LTR, NONE])
        pb(s, '\x1b[?1049l')
        self.ae(self.records(s, 0, 1), [LTR, NONE])
        for lines, cols in ((5, 6), (8, 10)):
            s = self.screen()
            pb(s, '\x1b[8h\x1b[2 kabc\r\n')
            s.resize(lines, cols)
            self.ae(self.records(s, 0), [RTL], (lines, cols))

    def marked(self, *data, split=False, **kw):
        # the data after IA, each item a draw call of its own when split
        s = self.screen(**kw)
        pb(s, IA)
        if split:
            for d in data:
                pb(s, d)
        else:
            pb(s, ''.join(data))
        return s

    def test_leading_mark_sets_record(self):
        # LRM or RLM drawn with no previous cell fixes the direction of a row the controls leave to its text; the mark is dropped
        for split in (False, True):
            for mark, want, primed in ((LRM, LTR, PRIMED_LTR), (RLM, RTL, PRIMED_RTL)):
                for text in ('abc', 'אבג', ''):
                    with self.subTest(split=split, mark=mark, text=text):
                        s = self.marked(mark, text, split=split)
                        self.ae((self.records(s, 0), s.cpu_cells(0, 0)['text']), ([want if text else primed], text[:1]))
            with self.subTest(split=split):
                self.ae(self.records(self.marked(ALM, 'abc', split=split), 0), [AUTO])
                self.ae(self.records(self.marked(RLM, '\x1b[31m', 'abc', split=split), 0), [RTL])
                self.ae(self.records(self.marked('abc\r', RLM, split=split), 0), [RTL])  # over existing text
                self.ae(self.records(self.marked('abc\r', RLM, '\x1b[2CX', split=split), 0), [RTL])
                self.ae(self.records(self.marked(RLM, '\tx', split=split), 0), [RTL])
                self.ae(self.records(self.marked(CUP(3), RLM, split=split), 0, 2), [NONE, PRIMED_RTL])
                self.ae(self.records(self.marked(CUP(3), RLM, 'x', split=split), 0, 2), [NONE, RTL])

    def test_leading_mark_needs_auto(self):
        for data, want in (('\x1b[8h' + RLM + 'abc', LTR), ('\x1b[8h\x1b[2 k' + LRM + 'abc', RTL), ('\x1b[8h\x1b[1 k' + RLM + '12 34', LTR)):
            self.ae(self.written(data, 0), [want], data)
        s = self.screen()
        pb(s, '\x1b[8habc\x1b[?2501h\r' + RLM)  # the controls of the draw call decide, not the row's record
        self.ae(self.records(s, 0), [RTL])
        for data in ('\x1b[8h' + RLM, '\x1b[8h\x1b[2 k' + LRM, '\x1b[?2501h' + RLM):  # nor on a blank row
            self.ae(self.written(data, 0), [NONE], data)

    def test_leading_mark_not_at_line_start(self):
        for data in ('ab' + RLM + 'c', 'abc\x1b[1;3H' + RLM, '\x1b[1;3H' + RLM + 'x'):
            self.ae(self.records(self.marked(data), 0), [AUTO], data)
        s = self.marked('abcdefghijkl')  # a continuation row has a previous cell, the mark joins it
        pb(s, CUP(2) + RLM)
        self.ae(self.records(s, 0, 1), [AUTO, AUTO])
        for ch in ('\u200b', '\u200c', '\u200d', '\u2066', '\u2067', '\u2068', '\u2069', '\u202a', '\u202b'):
            self.ae(self.records(self.marked(ch + 'abc'), 0), [AUTO], ch)
        s = self.marked('\x1b]66;w=1;' + RLM + '\x07abc')  # an OSC 66 cell keeps its mark as text
        self.ae((self.records(s, 0), s.cpu_cells(0, 0)['text']), ([AUTO], RLM))

    def test_leading_mark_other_modes(self):
        s = self.marked('abc\x1b[8l\r' + RLM + 'x')  # explicit mode drops the mark as upstream does
        self.ae(self.records(s, 0), [AUTO])
        s = self.screen(force_ltr=True)
        pb(s, IA + RLM + 'abc')
        self.ae((self.records(s, 0), s.cpu_cells(0, 0)['text']), ([NONE], 'a'))
        # the cells are those written without bidi mode
        for data, text in (('abc\r' + RLM, 'abc'), ('abc\r' + RLM + '\x1b[2CX', 'abX'), (RLM + '\tx', '\tx'), (RLM, ''), (RLM + 'hello world', 'hello world')):
            for pre in ('', '\x1b[8h', IA):
                s = self.screen(cols=12)
                pb(s, pre + data)
                self.ae(str(s.line(0)), text, (pre, data))

    def test_leading_isolates_dropped(self):
        # in bidi mode an isolate with no previous cell is dropped, as without it
        for data in ('\u2066a', '\u206712 34\u2069', '\u2068x\u2069', '\u2069y', '\u2067\u2069ls -la', 'abc\r\u2067x', 'ab\r\u2066\u2069'):
            for pre in ('\x1b[8h', IA):
                texts = []
                for modes in ('', pre):
                    s = self.screen()
                    pb(s, modes + data)
                    s.start_selection(0, 0)
                    s.update_selection(9, 0, True)
                    texts.append(([s.cpu_cells(0, x)['text'] for x in range(10)], s.cursor.x, str(s.line(0)), s.text_for_selection(False, False)))
                self.ae(*texts, (pre, data))

    def test_leading_mark_last_one_wins(self):
        for data, want in (
            (RLM + 'a\r' + LRM + 'b', LTR),
            (LRM + 'a\r' + RLM, RTL),
            (LRM + RLM + 'a', RTL),
            (LRM + RLM + 'a\r' + LRM + 'b', LTR),
        ):
            self.ae(self.records(self.marked(data), 0), [want], data)

    def test_leading_mark_redraw(self):
        # a redraw with the same bytes gives the same cells and record
        for line in (RLM + 'שלום', LRM + '~ $ ls', LRM + RLM + '中 a'):
            first = self.marked(line, cols=12)
            want = ([first.cpu_cells(0, x)['text'] for x in range(12)], self.records(first, 0), first.cursor.x)
            for n in (1, 2):
                s = self.marked(line + ('\r' + line + '\x1b[K') * n, cols=12)
                self.ae(([s.cpu_cells(0, x)['text'] for x in range(12)], self.records(s, 0), s.cursor.x), want, (line, n))

    def test_leading_mark_record_lifetime(self):
        # the record a mark sets ends as any record does: when an erase leaves the row blank
        for op, want in (('\x1b[K', RTL), ('\x1b[1K', RTL), ('\x1b[2K', NONE), ('\x1b[2J', NONE), ('\x1b[M', NONE), ('\x1bc', NONE)):
            s = self.marked(RLM + 'abc')
            pb(s, '\x1b[1;2H' + op)
            self.ae(self.records(s, 0), [want], op)
        s = self.marked(RLM)  # the direction a mark sets on a blank row is not a record: an erase keeps it
        pb(s, '\x1b[2K')
        self.ae(self.records(s, 0), [PRIMED_RTL])
        s = self.marked(RLM + 'שלום\rhello\x1b[K')  # a row rewritten without the mark keeps its direction
        self.ae(self.records(s, 0), [RTL])
        s = self.marked(CUP(5) + RLM + 'abc\n')  # scrolls with its row
        self.ae(self.records(s, 3, 4), [RTL, NONE])
        s = self.marked(RLM + 'abc\r\n')
        s.resize(5, 6)
        self.ae(self.records(s, 0), [RTL])

    def test_leading_mark_on_a_blank_row(self):
        # On a row with no record a mark sets none, only the direction its first text written in bidi mode takes. Text
        # written with bidi mode off drops it.
        self.ae([self.records(self.marked(mark), 0) for mark in (LRM, RLM)], [[PRIMED_LTR], [PRIMED_RTL]])
        self.ae([self.written('abc' + IA + '\r' + RLM + data, 0) for data in ('', '\x1b[9Gx')], [[PRIMED_RTL], [RTL]])
        for data, want in (
            ((RLM, '\x1b[8l', 'abc'), NONE),
            ((RLM, '\x1b[8l', '\r', IA, 'abc'), RTL),
            ((RLM, 'abc'), RTL),
            ((RLM, '\x1b[31m', 'abc'), RTL),
            ((RLM, LRM, 'abc'), LTR),
            ((RLM, '\x1b[8l', IA, 'abc'), RTL),
            ((RLM, '\x1b[8l', 'abc', IA, '\rx'), AUTO),
            ((RLM, '\x1b[?2501l', 'abc'), RTL),
            ((RLM, '\x1b[2Kabc'), RTL),
        ):
            self.ae(self.records(self.marked(*data, split=True), 0), [want], data)

    def test_leading_mark_on_a_blank_row_lifetime(self):
        # the direction moves with its row and ends when text is stored on the row or its attributes are cleared, not when an
        # erase inside the row leaves it blank
        self.ae(self.records(self.marked(CUP(5), RLM, '\n'), 3, 4), [PRIMED_RTL, NONE])
        self.ae(self.records(self.marked(CUP(2), RLM, CUP(1), '\x1b[L'), 1, 2), [NONE, PRIMED_RTL])
        self.ae(self.records(self.marked(CUP(2), RLM, CUP(1), '\x1b[M'), 0, 1), [PRIMED_RTL, NONE])
        self.ae(self.records(self.marked(CUP(2), RLM, CUP(1), '\x1b[Mabc'), 0), [RTL])
        # ED 0 clears the cursor row as EL 0 does, keeping its attributes
        for op in ('\x1b[K', '\x1b[2K', '\x1b[J', '\x1b[3X', '\x1b[3@', '\x1b[3P', '\x1b[2J', '\x1bc'):
            kept = op not in ('\x1b[2J', '\x1bc')
            s = self.marked(RLM, op)
            self.ae(self.records(s, 0), [PRIMED_RTL if kept else NONE], op)
            pb(s, IA + 'abc')
            self.ae(self.records(s, 0), [RTL if kept else AUTO], op)
        # it ends where text is stored with bidi mode off, not where the cursor moves onto the row or a line feed ends the text
        self.ae(self.records(self.marked(RLM, '\x1b[8l\r\x1b[8habc'), 0), [RTL])
        self.ae(self.records(self.marked(CUP(2), RLM, CUP(1), '\x1b[8lxyz\n\x1b[8h', 'abc'), 1), [RTL])
        self.ae(self.records(self.marked(CUP(2), RLM, CUP(1), '\x1b[8lxyz\nabc\x1b[8h\r', 'abc'), 1), [AUTO])
        # text written in bidi mode takes it, and a mark on a row holding a record sets the record's direction, which goes
        # with the record: the next text on the blank row records the controls current then
        self.ae(self.records(self.marked('abc\r', RLM, '\x1b[2K', 'xyz'), 0), [AUTO])
        # a mark on a row whose text was written with bidi mode off is noted, and outlives an erase of that text
        self.ae(self.written('abc' + IA + '\r' + RLM + '\x1b[2Kxyz', 0), [RTL])

    def test_leading_mark_on_a_blank_row_resize(self):
        # a resize keeps the direction a leading mark set with its row, holding text or not. The rewrap starts afresh the blank
        # rows after the last text and the cursor, as it keeps only a blank cursor row at the line start.
        for cols in (5, 20):
            for data, kept in (
                ((CUP(2), RLM), True),
                ((CUP(2), RLM, CUP(4)), True),
                ((CUP(2), RLM, CUP(4), 'xyz'), True),
                ((CUP(2), RLM, '\x1b[5G'), False),
                ((CUP(2), RLM, CUP(1)), False),
            ):
                s = self.marked(*data)
                s.resize(5, cols)
                self.ae(self.records(s, 1), [PRIMED_RTL if kept else NONE], (cols, data))
                pb(s, CUP(2) + 'abc')
                self.ae(self.records(s, 1), [RTL if kept else AUTO], (cols, data))
            s = self.screen()
            pb(s, 'abc' + IA + '\r' + RLM)
            s.resize(5, cols)
            self.ae(self.records(s, 0), [PRIMED_RTL], cols)

    def test_leading_mark_on_the_alternate_screen(self):
        s = self.marked('\x1b[?1049h' + RLM)  # the alternate screen starts with the modes reset
        self.ae(self.records(s, 0), [NONE])
        s = self.screen()
        pb(s, '\x1b[?1049h' + IA + RLM)
        self.ae(self.records(s, 0), [PRIMED_RTL])
        pb(s, '\x1b[?1049l')
        self.ae(self.records(s, 0), [NONE])
        pb(s, '\x1b[?1049h' + IA + 'abc')
        self.ae(self.records(s, 0), [AUTO])
        # a main row keeps its direction over a visit to the alternate screen
        s = self.marked(RLM, '\x1b[?1049h' + IA + LRM + 'x\x1b[?1049l', 'abc', split=True)
        self.ae(self.records(s, 0), [RTL])

    def test_erase_to_marks_only_clears_record(self):
        # An erase that leaves nothing but a leading mark's column leaves the row blank, so the record goes as it does for the
        # same stream without the mark, and text written once the mode is off is not reordered.
        for controls in ('', '\x1b[?2501h\x1b[2 k'):
            screens = []
            for mark in (LRM, ''):
                s = self.screen()
                pb(s, '\x1b[8h' + controls + mark + '\x1b[1;3Ha\x1b[1;2H\x1b[K')
                self.ae(self.records(s, 0), [NONE], f'{controls!r} mark {mark!r}')
                pb(s, '\x1b[8l\rאב')
                screens.append(s)
            marked, plain = screens
            self.ae((str(marked.line(0)), marked.cpu_cells(0, 0)['text']), (str(plain.line(0)), plain.cpu_cells(0, 0)['text']))

    def test_writes_to_rows_left_without_text(self):
        # A row left holding no text has no record: text written to it later records the controls current then, also when the
        # removed text is part of a scaled or wide char removed through another of its rows, or is in the history
        cup = '\x1b[{};{}H'.format
        s2, s3, vs16, prompt = '\x1b]66;s=2;א\x07', '\x1b]66;s=3;א\x07', '️', '\x1b]133;A\x07'
        w1, s7w2 = '\x1b]66;w=1;א\x07', '\x1b]66;s=7:w=2;א\x07'
        in_history = cup(2, 1) + s2 + cup(3, 1) + '\n\n'  # on three lines the char's top row goes into the history

        def emptied(lines, text, primed, op, rows, pre='', cols=10):
            # text written in bidi mode right to left, or with it off on the rows a mark primed, then op leaves rows without
            # text, which text written with bidi mode off leaves without a record and text written in bidi mode records
            for mark, on in product((False, True), (False, True)):
                s = self.screen(cols=cols, lines=lines)
                if mark:
                    pb(s, pre + IA + ''.join(CUP(y + 1) + RLM for y in primed) + '\x1b[8l\x1b[H' + text)
                else:
                    pb(s, pre + '\x1b[8h\x1b[2 k' + text + '\x1b[8l')
                op(s) if callable(op) else pb(s, op)
                self.assertFalse([y for y in rows if has_text(s, y)], (pre, text, op, mark))
                pb(s, ('\x1b[r\x1b[8h\x1b[1 k\x1b[?2501l' if on else '\x1b[r\x1b[8l') + ''.join(CUP(y + 1) + 'x' for y in rows))
                self.ae(self.records(s, *rows), [LTR if on else NONE] * len(rows), (pre, text, op, mark, on))

        def erase_command_and_pull(s):
            # the lower row of the char is the erased command's prompt line, its top row stays in the history
            s.erase_last_command()
            pb(s, '\x1b[+T')

        for case in (
            (5, s2, (0,), cup(2, 1) + '\x1b[2K', (0,)),
            (5, s2, (0,), cup(2, 1) + '\x1b[K', (0,)),
            (5, s2, (0,), cup(2, 1) + '\x1b[X', (0,)),
            (5, s2, (0,), cup(2, 1) + '\x1b[P', (0,)),
            (5, s2, (0,), cup(2, 1) + '\x1b[@', (0,)),
            (5, s3, (0,), cup(2, 1) + '\x1b[J', (0,)),
            (5, s3, (2,), cup(2, 1) + '\x1b[1J', (2,)),
            (5, s2, (0,), cup(2, 1) + '\x1b[M', (0,)),
            (5, cup(2, 1) + s2, (2,), cup(1, 1) + '\x1b[2M', (0,)),
            (5, s2, (0, 1), cup(2, 1) + '\x1b[L', (0, 2)),
            (5, cup(2, 1) + s2, (2,), '\x1b[1;2r\x1b[L\x1b[r', (2,)),
            (5, cup(3, 1) + s2, (2, 3), '\x1b[1;3r' + cup(3, 1) + '\n\x1b[r', (1, 3)),
            (5, cup(3, 1) + s2, (2, 3), '\x1b[1;3r\x1b[S\x1b[r', (1, 3)),
            (5, cup(2, 1) + s2, (1, 2), '\x1b[3;5r' + cup(3, 1) + '\x1bM\x1b[r', (1, 3)),
            (5, cup(2, 1) + s2, (1, 2), '\x1b[3;5r\x1b[T\x1b[r', (1, 3)),
            (3, in_history, (1,), cup(1, 1) + '\x1b[2K\x1b[+T', (0,)),
            (3, in_history, (1,), '\x1b[2J\x1b[+T', (0,)),
            (3, in_history, (2,), lambda s: s.clear_scrollback(), (0,)),
            (3, prompt + '$ p1\r\n' + s2 + cup(3, 3) + prompt + '\n\n', (1, 2), lambda s: s.erase_last_command(), (0,)),
            (3, prompt + '$ p0\r\n' + s2 + cup(3, 3) + prompt + '$ p1\r\n\r\n\r\n' + prompt, (1,), erase_command_and_pull, (0,)),
            (5, s2, (1,), cup(1, 1) + 'z', (1,)),
            (5, s2, (1,), cup(1, 1) + '中', (1,)),
            (5, s2, (1,), cup(1, 1) + '\x1b]66;w=1;z\x07', (1,)),
            (5, 'y' + s2, (1,), cup(1, 1) + 'y\x1b[b', (1,)),
            (5, cup(1, 2) + s2, (1,), cup(1, 1) + '☺' + vs16, (1,)),
            (5, cup(2, 1) + s2, (2,), cup(1, 1) + '\x1b]66;s=2;zz\x07', (2,)),
            # a wide char does not fit in the last column, it wraps or is discarded
            (5, cup(1, 10) + w1, (0,), cup(1, 10) + '中', (0,)),
            # the region scrolls up for a char that does not fit above its bottom margin, the rows below it are not written
            (5, cup(3, 1) + s2, (2, 3), '\x1b[1;3r' + cup(3, 1) + '\x1b]66;s=2;zz\x07\x1b[r', (3,)),
            (5, cup(3, 1) + s2, (2, 3), '\x1b[1;3r' + cup(3, 1) + '\x1b]66;s=3;z\x07\x1b[r', (3,)),
        ):
            emptied(*case)
        # a resize drops a char too wide for the new width, and moves rows left without text into the history
        emptied(9, cup(2, 3) + s7w2, range(1, 8), lambda s: s.resize(9, 11), range(1, 8), cols=16)
        emptied(9, s7w2 + cup(8, 1) + 'x' * 32, range(7), lambda s: (s.resize(9, 11), pb(s, '\x1b[+T')), (0,), cols=16)
        # a rewrap that leaves the first row of a line blank, widening back joins the text and the record of the next row to it
        s = self.screen()
        pb(s, '\x1b[8h\x1b[2 k' + cup(1, 10) + 'ab\x1b[8l')
        s.resize(5, 5)
        self.ae(self.records(s, 0, 1, 2), [NONE, RTL, RTL])
        s.resize(5, 10)
        self.ae(self.records(s, 0, 1), [RTL, NONE])
        # the alternate screen resizes without rewrapping, removing the chars split at its new edges
        emptied(5, cup(1, 9) + '中', (0,), lambda s: s.resize(5, 9), (0,), pre='\x1b[?1049h')
        emptied(5, cup(4, 1) + s2, (3,), lambda s: s.resize(4, 10), (3,), pre='\x1b[?1049h')
        # a widened char moved onto a row, OSC 66, CHT and DECALN on a row whose record was left without text
        stale = '\x1b[8h\x1b[2 k' + CUP(2) + 'אבג' + CUP(2) + '\x1b[2K'
        for data, rows, want in (
            ('\x1b[8l\x1b[1;10H☺' + vs16, (1,), [NONE]),
            ('\x1b[1 k\x1b[1;10H☺' + vs16, (1,), [LTR]),
            ('\x1b[1 k\x1b[H\x1b]66;s=2;ab\x07', (0, 1), [LTR, LTR]),
            ('\x1b[1 k' + CUP(2) + '\x1b[I', (1,), [NONE]),
            ('\x1b[H\x1b[2 kabc\x1b#8', (0, 1, 2), [NONE, NONE, NONE]),  # DECALN clears the attributes of every row
        ):
            s = self.screen()
            pb(s, stale + data)
            self.assertTrue(all(has_text(s, y) for y in rows), data)
            self.ae(self.records(s, *rows), want, data)
        # a char written over the only char of a row leaves it holding text, with its record
        for data, rows, want in (
            ('\x1b[2 k' + s2 + '\x1b[8l' + cup(1, 1) + 'z', (0, 1), [RTL, NONE]),
            ('中\x1b[8l' + cup(1, 1) + 'z', (0,), [LTR]),
            (s2 + '\x1b[8l' + cup(1, 1) + '\x1b]66;s=2;zz\x07', (0, 1), [LTR, LTR]),
            (cup(2, 1) + s2 + '\x1b[8l' + cup(1, 1) + '\x1b]66;s=2;zz\x07', (0, 1, 2), [NONE, LTR, NONE]),
            (cup(2, 1) + s2 + '\x1b[8l' + cup(1, 1) + '\x1b]66;s=3;zz\x07', (0, 1, 2), [NONE, LTR, LTR]),
            # the row the char is written to scrolls up with the cursor
            (cup(3, 1) + s2 + '\x1b[8l\x1b[1;3r' + cup(3, 1) + '\x1b]66;s=2;zz\x07\x1b[r', (1, 2, 3), [LTR, NONE, NONE]),
            # below the region, written where it is or moved up
            (cup(4, 1) + s2 + '\x1b[8l\x1b[1;2r' + cup(4, 1) + '\x1b]66;s=2;zz\x07\x1b[r', (3, 4), [LTR, LTR]),
            (cup(5, 1) + w1 + '\x1b[8l\x1b[1;2r' + cup(5, 1) + '\x1b]66;s=2;z\x07\x1b[r', (3, 4), [NONE, LTR]),
            # at the end of a line without autowrap
            (cup(1, 9) + s2 + '\x1b[8l\x1b[?7l' + cup(1, 10) + '\x1b]66;s=2;z\x07', (0, 1), [LTR, LTR]),
            (cup(1, 9) + w1 + '\x1b[8l' + cup(1, 9) + 'z', (0,), [LTR]),
            ('\x1b[2 k' + cup(1, 10) + w1 + '\x1b[8l' + cup(1, 10) + 'z', (0,), [RTL]),
            (cup(1, 9) + w1 + '\x1b[8l' + cup(1, 9) + '中', (0,), [LTR]),
            (cup(1, 10) + 'a\x1b[8l' + cup(1, 10) + 'z', (0,), [LTR]),
        ):
            self.ae(self.written('\x1b[8h' + data, *rows), want, data)
        # on a one-column screen a widened narrow char has no room and goes, as a wide char does, leaving the row without text
        self.ae(self.written('\x1b[8h☺' + vs16, 0, cols=1), [NONE])
        self.ae(self.written('\x1b[8h' + w1 + '\x1b[8l\x1b[H中', 0, cols=1), [NONE])
        # a mark on a row holding no text gives it no record
        self.ae(self.written(IA + RLM + '\x1b[?2501l\x1b[8l', 0), [PRIMED_RTL])
        # a char written again after a mark keeps the direction the mark set
        self.ae(self.written(IA + RLM + '中\r' + RLM + '中', 0), [RTL])
        self.ae(self.written(IA + RLM + s2 + '\r' + RLM + s2, 0, 1), [RTL, AUTO])

    def test_record_on_the_row_holding_the_widened_char(self):
        # a char widened by a later code point that moves past a scaled char, scrolling a region, records the row it lands on
        s = self.screen(cols=8, lines=4)
        pb(s, '\x1b[8h\x1b[2;2H\x1b]66;s=3;aא\x07\x1b[3;4r\x1b[3;1Hกำ')
        y = next(y for y in range(s.lines) if s.cpu_cells(y, 0)['text'] == 'กำ')
        self.ae([s.test_bidi_line_record(r) for r in range(s.lines)], [LTR if r == y else NONE for r in range(s.lines)])

    def test_writes_to_rows_without_text(self):
        # Seeded random streams of operations that remove, move and write text, with no leading mark, whose direction on a row
        # without text is kept until text comes. After each operation one writer writes to a row whose cells hold no text, and
        # the row then has the record the same write gives on a fresh screen. DECALN clears the attributes of every row. Text that
        # comes back from the kept columns of a horizontally scrolling region has no record.
        ops = (
            *('\x1b[{y};{x}H', '\x1b[{y}H', 'a', 'אב', '中', 'z ', 'b\x1b[2b', '\t', '\r', '\n', '\x1bM'),
            *(f'\x1b]66;{t}\x07' for t in ('s=2;א', 's=2;ab', 's=3;א', 's=4;z', 'w=1;z', 'w=2;中')),
            '\x1b[{y};99H\x1b]66;w=1;z\x07',
            '\x1b[{y};99H☺️',
            '☺️',
            *('\x1b[0K', '\x1b[1K', '\x1b[2K', '\x1b[{n}X', '\x1b[{y};{x}H\x1b[{n}@', '\x1b[{y};{x}H\x1b[{n}P'),
            *('\x1b[0J', '\x1b[1J', '\x1b[2J', '\x1b[3J', '\x1b[{n}L', '\x1b[{n}M', '\x1b[{n}S', '\x1b[{n}T', '\x1b[+T'),
            '\x1b[{top};{bottom}r',
            '\x1b[r',
            *('\x1b[8h', '\x1b[8l', IA, '\x1b[?2501l', '\x1b[2 k', '\x1b[1 k', '\x1b[ k'),
            *('\x1b[?1049h', '\x1b[?1049l', '\x1b]133;A\x07', 'resize', 'clear_scrollback', 'erase_last_command'),
            *('define region', 'scroll region', 'scroll region', 'remove region'),
        )
        modes = ('\x1b[8l', *(f'\x1b[8h{scp}{auto}' for scp in ('\x1b[2 k', '\x1b[1 k') for auto in ('\x1b[?2501h', '\x1b[?2501l')))

        def region(rng, s, o):
            # a vertical region using the scrollback, full width with kept rows, narrow, or a horizontal one; scrolled by whole
            # cells or fractions, either way
            rid = rng.choice((1, 2))
            if o == 'scroll region':
                return ('smooth_scroll', rid, rng.choice((-45, -25, -20, -13, -10, -5, -3, 3, 5, 10, 13, 20, 25, 45)))
            if o == 'remove region':
                return ('smooth_scroll_remove', rid)
            shape = rng.choice(('history', 'kept rows', 'narrow', 'horizontal', 'horizontal full'))
            top = 0 if shape == 'history' else rng.randrange(s.lines)
            bottom = rng.randrange(top + 1, s.lines + 1)
            left = rng.randrange(s.columns - 1) if shape in ('narrow', 'horizontal') else 0
            right = rng.randrange(left + 1, s.columns + 1) if shape in ('narrow', 'horizontal') else s.columns
            horizontal = shape.startswith('horizontal')
            capacity = rng.randrange(1, min(right - left if horizontal else bottom - top, 3) + 1)
            return ('smooth_scroll_define', rid, left, top, right, bottom, capacity, shape == 'kept rows', horizontal)

        def writer(rng, s, y):
            # data writing to row y, which stays where it is
            x = rng.randrange(s.columns - 1) + 1
            kind = rng.choice(('text', 'osc66', 'widened', 'cht', 'decaln', 'kept columns') if y else ('text', 'osc66', 'cht', 'decaln', 'kept columns'))
            if kind == 'kept columns':
                # text written to the row, moved wholly into the two kept columns of a horizontally scrolling region and back
                text = f'\x1b[{y + 1};1H' + rng.choice(('ab', 'אב', '中'))
                moves = ('smooth_scroll_remove', 1), ('smooth_scroll_remove', 2), ('smooth_scroll_define', 3, 0, y, s.columns, y + 1, 2, False, True)
                return kind, (text, *moves, ('smooth_scroll', 3, 20), ('smooth_scroll', 3, -20), ('smooth_scroll_remove', 3))
            if kind == 'text':
                text = rng.choice(('a', 'אב', '中', 'z '))
                return kind, f'\x1b[{y + 1};{min(x, s.columns + 1 - len(text) - (text == "中"))}H{text}'
            if kind == 'osc66':
                return kind, f'\x1b[{y + 1};{x}H\x1b]66;w=1;z\x07'
            if kind == 'widened':
                return kind, f'\x1b[{y};{s.columns}H☺️'
            if kind == 'cht':
                return kind, f'\x1b[{y + 1};1H\x1b[I'
            return 'decaln', '\x1b#8'

        for seed in range(250):
            rng = random.Random(seed)
            s = self.create_screen(cols=8, lines=5, scrollback=5, options={})
            self._screens_to_verify_styles.remove(s)
            done = []
            for _ in range(25):
                o = rng.choice(ops)
                if o == 'resize':
                    o = ('resize', rng.choice((4, 5, 6)), rng.choice((3, 7, 8, 9)))
                elif o in ('clear_scrollback', 'erase_last_command'):
                    o = (o,)
                elif o.endswith(' region'):
                    o = region(rng, s, o)
                else:
                    top = rng.randrange(1, 3)
                    o = o.format(y=rng.randrange(1, 7), x=rng.randrange(1, 10), n=rng.randrange(1, 4), top=top, bottom=rng.randrange(top + 1, 6))
                done.append(o)
                getattr(s, o[0])(*o[1:]) if isinstance(o, tuple) else pb(s, o)
                blank = [y for y in range(s.lines) if not has_text(s, y)]
                if not blank:
                    continue
                y, mode = rng.choice(blank), rng.choice(modes)
                kind, data = writer(rng, s, y)
                done.append((mode, data))
                if kind == 'kept columns':
                    # the text that comes back holds none of the settings it was written with
                    pb(s, '\x1b[r' + mode + data[0])
                    for o in data[1:]:
                        getattr(s, o[0])(*o[1:])
                    self.ae((has_text(s, y), s.test_bidi_line_record(y)), (True, NONE), f'seed {seed}, {kind} to row {y} after {done!r}')
                    continue
                pb(s, '\x1b[r' + mode + data)
                fresh = self.create_screen(cols=s.columns, lines=s.lines, scrollback=5, options={})
                self._screens_to_verify_styles.remove(fresh)
                pb(fresh, mode + data)
                want = {r: fresh.test_bidi_line_record(r) for r in (range(s.lines) if kind == 'decaln' else (y,))}
                self.ae({r: s.test_bidi_line_record(r) for r in want}, want, f'seed {seed}, {kind} to row {y} after {done!r}')


def has_text(s, y):
    return any(c['text'] or c['mcd'] is not None for c in s.cpu_cells(y))
