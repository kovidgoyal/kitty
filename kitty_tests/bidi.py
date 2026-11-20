#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

import random
import re
from itertools import product

from kitty.fast_data_types import EXTEND_LINE, EXTEND_WORD
from kitty.marks import marker_from_regex

from .base import BaseTest, draw_multicell, parse_bytes
from .graphics import put_helpers

NONE, LTR, RTL = (0, False, False), (1, False, False), (1, True, False)
CUP = '\x1b[{};1H'.format  # 1-based row
LRM, RLM = '\u200e', '\u200f'
LRI, RLI, FSI, PDI = '\u2066', '\u2067', '\u2068', '\u2069'


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
            (5, 'abcd☺', '\ufe0f', (0, 1)),  # the widened char moves to the next row
            (10, 'a' + '́' * 23, '́', ()),  # a combining char the cell has no room for
        ):
            with self.subTest(pre=pre, data=data):
                s = self.screen(cols=cols)
                pb(s, pre + '\x1b[8h' + data)
                self.ae(tuple(y for y in range(s.lines) if s.test_bidi_line_record(y)[0]), want)

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

    def cell_texts(self, s, y=0, n=4):
        return [s.cpu_cells(y, x)['text'] for x in range(n)]

    def mark_screen(self, data, cols=10, lines=5, bdsm=True):
        s = self.screen(cols=cols, lines=lines)
        pb(s, ('\x1b[8h' if bdsm else '') + data)
        return s

    def test_leading_mark(self):
        # In bidi mode an LRM or RLM drawn with no previous cell goes in the text of the cell under the cursor, and the cursor
        # does not move. Until a char is drawn or text is erased, inserted, deleted or scrolled, a char drawn there with no
        # previous cell is stored after them and more marks are added to them; after that both replace them. A tab recorded over
        # them replaces them.
        for data, cells, x in (
            ('abc\r' + RLM, [RLM + 'a', 'b', 'c', ''], 0),
            ('abc\r' + RLM + 'xyz', [RLM + 'x', 'y', 'z', ''], 3),
            (RLM + 'a\rb', ['b', '', '', ''], 1),
            ('abc\r' + RLM + '\x1b[2CX', [RLM + 'a', 'b', 'X', ''], 3),
            (RLM + '\tx', ['\t\x07', ' ', ' ', ' '], 9),
            (LRM + RLM + 'a\r' + LRM + 'b', [LRM + 'b', '', '', ''], 1),
            (LRM + 'a\r' + RLM + LRM + '\x1b[2C\rb', [RLM + LRM + 'b', '', '', ''], 1),
            (RLM + '\x1b[2C' + LRM + '\rb', [RLM + 'b', '', '', ''], 1),  # the LRM is dropped on an empty cell
            (RLM + '中x', [RLM + '中', '', 'x', ''], 3),
            ('中x\r' + RLM + 'y', [RLM + 'y', '', 'x', ''], 1),
            ('ab' + RLM + 'c', ['a', 'b' + RLM, 'c', ''], 3),
            (RLM + 'é', [RLM + 'é', '', '', ''], 1),
            # VS16 and SARA AM widen the cell, as without the controls
            (LRM + '✖\ufe0fx', [LRM + '✖\ufe0f', '', 'x', ''], 3),
            (LRM + 'กำx', [LRM + 'กำ', '', 'x', ''], 3),
            # in insert mode the cell moves right with its controls, as any cell content does
            (LRM + 'abc\r\x1b[4hX', ['X', LRM + 'a', 'b', 'c'], 1),
            (LRM + 'abc\r\x1b[4h中', ['中', '', LRM + 'a', 'b'], 2),
            # and so does ICH
            ('abc\r' + LRM + '\r\x1b[@', ['', LRM + 'a', 'b', 'c'], 0),
            ('\r' + LRM + 'abc\r\x1b[2@', ['', '', LRM + 'a', 'b'], 0),
            ('\r' + LRM + '\x1b[@', ['', LRM, '', ''], 0),
            ('\x1b]66;w=2;a\x07bc\r' + LRM + '\r\x1b[@', ['', LRM + 'a', '', 'b'], 0),
            ('abc\r' + LRM + '\x1b[C\x1b[@', [LRM + 'a', '', 'b', 'c'], 1),
            # an OSC 66 char written into the cell replaces it, controls included
            (LRM + '\x1b]66;w=1;Z\x07', ['Z', '', '', ''], 1),
        ):
            with self.subTest(data=data):
                s = self.mark_screen(data)
                self.ae((self.cell_texts(s), s.cursor.x), (cells, x))
        # over an OSC 66 char, or a wide char, insert mode erases it, as without bidi mode
        for data in (
            '\x1b]66;n=1:d=2;a\x07bc\r' + LRM + '\x1b[4hX',
            '\x1b]66;w=1;中\x07bc\r' + LRM + '\x1b[4hX',
            '\x1b]66;w=1;ab\x07bc\r' + LRM + '\x1b[4hX',
            '\x1b]66;;a\x07bc\r' + LRM + '\x1b[4hX',
            LRM + '中x\r\x1b[4hX',
        ):
            with self.subTest(data=data):
                s, off = self.mark_screen(data), self.mark_screen(data, bdsm=False)
                self.ae((self.cell_texts(s), s.cursor.x), (self.cell_texts(off), off.cursor.x))
        # the OSC 66 char that ICH shifts keeps its shape
        self.ae(self.mark_screen('\x1b]66;n=1:d=2;a\x07\r' + LRM + '\r\x1b[@').cpu_cells(0, 1)['mcd']['subscale_d'], 2)
        # a plain cell holding controls stays a plain cell
        self.assertIsNone(self.mark_screen('abc\r' + RLM).cpu_cells(0, 0)['mcd'])
        # copied text holds the controls
        self.ae(str(self.mark_screen('abc\r' + RLM).line(0)), RLM + 'abc')
        # a marks-only cell is blank: the tab is recorded over it, as without bidi mode
        self.ae(str(self.mark_screen(RLM + '\tx').line(0)), '\tx')
        # over a multiline char the mark goes into all its cells, which a char drawn there replaces
        s = self.mark_screen('\x1b]66;s=2;a\x07' + CUP(1) + RLM, cols=4, lines=3)
        self.ae(s.cpu_cells(0, 0)['text'], RLM + 'a')
        pb(s, 'q')
        self.ae((self.cell_texts(s, 0, 3), self.cell_texts(s, 1, 3), s.cpu_cells(1, 0)['mcd']), ([RLM + 'q', '', ''], ['', '', ''], None))
        # and records every row it is written to, also for a char drawn before bidi mode
        s = self.mark_screen('\x1b]66;s=2;a\x07\x1b[8h\r' + RLM, cols=4, lines=3, bdsm=False)
        self.ae((s.cpu_cells(0, 0)['text'], self.records(s, 0, 1)), (RLM + 'a', [LTR, LTR]))

    def test_leading_mark_dropped(self):
        # on the lower row of a multiline char no cell can take the mark
        s = self.mark_screen('\x1b]66;s=2;a\x07' + CUP(2) + RLM, cols=4, lines=3)
        self.ae((self.cell_texts(s, 0, 3), self.cell_texts(s, 1, 3)), (['a', '', ''], ['', '', '']))
        # a cell keeps room for one code point after its marks
        marks = (LRM + RLM) * 12
        self.ae(self.cell_texts(self.mark_screen(marks), n=2), [marks[:23], ''])
        self.ae(self.cell_texts(self.mark_screen(marks + 'a'), n=2), [marks[:23] + 'a', ''])
        # a cell holding a char takes marks up to its last code point
        self.ae(self.cell_texts(self.mark_screen('a\r' + marks), n=2), [marks[:23] + 'a', ''])
        # a tab cell takes no mark: it is dropped, as without bidi mode
        for data in ('\tX\r' + RLM + '\t', '\x1b[3g\x1b[1;15H\x1bH\r\t\r' + LRM + '\x1b[1;15Hls'):
            with self.subTest(data=data):
                texts = []
                for bdsm in (True, False):
                    s = self.mark_screen(data, cols=20, bdsm=bdsm)
                    text, ansi = [], []
                    s.as_text(text.append, False)
                    s.as_text(ansi.append, True)
                    s.start_selection(0, 0)
                    s.update_selection(19, 0, True)
                    texts.append((str(s.line(0)), ''.join(text), ''.join(ansi), s.text_for_selection(False, False)))
                self.assertIn('\t', texts[1][0])
                self.ae(texts[0], texts[1])

    def test_leading_mark_redraw(self):
        # a line redrawn from its start, as a shell redraws its prompt, holds the cells it held when first drawn
        for line in (RLM + 'שלום', LRM + '~ $ ls', LRM + RLM + '中 a'):
            for pre in ('', '\x1b[?2501h'):
                with self.subTest(line=line, pre=pre):
                    first = self.mark_screen(pre + line, cols=12)
                    for redraws in (1, 2):
                        s = self.mark_screen(pre + line + ('\r' + line + '\x1b[K') * redraws, cols=12)
                        self.ae((s.cpu_cells(0), s.cursor.x), (first.cpu_cells(0), first.cursor.x))
        # a row rewritten from its start without the mark loses it
        s = self.mark_screen('\x1b[?2501h' + RLM + 'שלום\rhello\x1b[K')
        self.ae((str(s.line(0)), s.cpu_cells(0, 0)['text']), ('hello', 'h'))

    def test_leading_mark_pending_ends(self):
        # the marks stop being pending when a char is drawn or text is erased, inserted, deleted or scrolled, after which a char
        # drawn there replaces the marks of its cell, also those of a row moved there
        stale = CUP(2) + LRM + 'a'
        for data, y in (
            (stale + CUP(1) + RLM + '\x1b[S' + CUP(1), 0),
            (stale + CUP(1) + RLM + CUP(5) + '\n' + CUP(1), 0),
            (stale + CUP(1) + RLM + CUP(5) + '\x1bD' + CUP(1), 0),
            (stale + CUP(1) + RLM + '\x1b[M' + CUP(1), 0),
            (CUP(1) + LRM + 'a' + CUP(2) + RLM + '\x1b[T' + CUP(2), 1),
            (CUP(1) + LRM + 'a' + CUP(2) + RLM + CUP(1) + '\x1bM' + CUP(2), 1),
            (CUP(1) + LRM + 'a' + CUP(2) + RLM + CUP(1) + '\x1b[L' + CUP(2), 1),
            ('abc\r' + RLM + '\x1b[3G\x1b[@\r', 0),
            ('abc\r' + RLM + '\x1b[3G\x1b[P\r', 0),
            ('abc\r' + RLM + '\x1b[3G\x1b[X\r', 0),
            ('abc\r' + RLM + '\x1b[3G\x1b[K\r', 0),
            ('abc\r' + RLM + '\x1b[3G\x1b[J\r', 0),
            ('abc\r' + RLM + '\x1b[?1049h\x1b[?1049l\r', 0),
            ('abc\r' + RLM + '\x1b[!p\x1b[8h\r', 0),
            ('abc\r' + RLM + '\x1b[8l\x1b[8h\r', 0),
            ('abc\r' + RLM + CUP(3) + '\x1b]66;w=1;Z\x07' + CUP(1), 0),
            ('abc\r' + RLM + CUP(3) + 'x' + CUP(1), 0),
        ):
            with self.subTest(data=data):
                s = self.mark_screen(data)
                pb(s, 'b')
                self.ae(s.cpu_cells(y, 0)['text'], 'b')
        s = self.mark_screen('abcdefgh\r' + RLM)
        s.resize(5, 6)
        pb(s, '\x1b[Hb')
        self.ae(s.cpu_cells(0, 0)['text'], 'b')
        s = self.mark_screen('abc\r' + RLM)
        self.set_options({'force_ltr': True})
        pb(s, CUP(3) + 'x')
        self.set_options({})
        pb(s, CUP(1) + 'b')
        self.ae(s.cpu_cells(0, 0)['text'], 'b')

    def test_leading_isolates_dropped(self):
        # in bidi mode an isolate with no previous cell is dropped, as without it
        for data in (LRI + 'a', RLI + '12 34' + PDI, FSI + 'x' + PDI, PDI + 'y', RLI + PDI + 'ls -la', 'abc\r' + RLI + 'x', 'ab\r' + LRI + PDI):
            with self.subTest(data=data):
                texts = []
                for bdsm in (True, False):
                    s = self.mark_screen(data, bdsm=bdsm)
                    s.start_selection(0, 0)
                    s.update_selection(9, 0, True)
                    texts.append((self.cell_texts(s, n=10), s.cursor.x, str(s.line(0)), s.text_for_selection(False, False)))
                self.ae(*texts)

    def test_leading_mark_takes_no_combining_char(self):
        # a combining or zero width char written after a cursor move next to a cell holding only marks is dropped, as next to an
        # empty cell
        for mark in ('\u0301', '\u0301\u0302', '\u200d', '\ufe0f', LRM):
            with self.subTest(mark=ascii(mark)):
                self.ae(self.cell_texts(self.mark_screen(RLM + '\x1b[C' + mark)), [RLM, '', '', ''])
                self.ae(self.cell_texts(self.mark_screen(RLM + '\x1b[C' + mark, bdsm=False)), ['', '', '', ''])

    def test_leading_mark_pending_random(self):
        # A model of the rule: marks written at column 0 are pending until a char is drawn, text is erased, inserted, deleted or
        # scrolled, the screen is resized or switched, or bidi mode is turned off. A tab recorded over them replaces them.
        # Marks written there replace the marks of the cell unless they follow pending ones. After each char drawn there, marks
        # kept imply the model's pending row, and the model's pending row implies marks kept unless an op that clears broadly ran
        # since. With the marks stripped every cell equals the same stream drawn without bidi mode.
        marks = (LRM, RLM)
        broad_kinds = frozenset('su sd el ed ech ich dch il dl resize'.split())
        kinds = 'mark mark prompt prompt text text cr cup cup ind ri su sd lf el ed ech irm ich dch il dl stbm resize alt decstr bdsm auto scp tab cht'.split()
        counts = dict.fromkeys('replaced appended kept overwritten moved'.split(), 0)
        stops = {'marker': 0}

        def lead(text):
            return text[: len(text) - len(text.lstrip(LRM + RLM))]

        def run(seed, num_ops):
            rng = random.Random(seed)
            a, b = self.screen(cols=6, lines=4), self.screen(cols=6, lines=4)
            pb(a, '\x1b[8h')
            m = {'bdsm': True, 'stash': False, 'irm': False, 'pending': None, 'broad': False}

            def both(data):
                pb(a, data)
                pb(b, data)

            def at_col0():
                y = a.cursor.y
                return m['bdsm'] and a.cursor.x == 0 and not (y and a.line(y - 1).last_char_has_wrapped_flag())

            def touch(rows):
                p = m['pending']
                if p and p[0] == a.is_using_alternate_linebuf() and p[1] in rows:
                    m['pending'] = None

            def mark(ctx):
                both('\r')
                new = ''.join(rng.choices(marks, k=rng.randrange(1, 3)))
                if not at_col0():
                    # stored after the char that wrapped, or dropped
                    m['broad'] = True
                    both(new)
                    return
                y = a.cursor.y
                here, before = (a.is_using_alternate_linebuf(), y), lead(a.cpu_cells(y, 0)['text'])
                if a.cpu_cells(y, 0)['text'].lstrip(LRM + RLM).startswith('\t'):
                    # a tab cell takes no mark
                    both(new)
                    self.ae(lead(a.cpu_cells(y, 0)['text']), '', ctx)
                    return
                both(new)
                if m['pending'] != here or not m['broad']:
                    appended = m['pending'] == here
                    expected = before + new if appended else new
                    if len(expected) < 20:
                        if appended or before:
                            counts['appended' if appended else 'replaced'] += 1
                        self.ae(lead(a.cpu_cells(y, 0)['text']), expected, ctx)
                m['pending'], m['broad'] = here, False

            def text(ctx):
                if rng.random() < 0.5:
                    both('\r')
                chars = rng.choices('abc xyאבג中文', k=rng.randrange(1, 9))
                data = ''.join(c + ('\u0301' if c.isalpha() and rng.random() < 0.15 else '') for c in chars)
                first = 2 if data[1:2] == '\u0301' else 1
                y, col0 = a.cursor.y, at_col0()
                # insert mode erases a wide char under the cursor, marks included, as without bidi mode
                wide = col0 and a.cpu_cells(y, 0)['mcd']
                had_marks = col0 and bool(lead(a.cpu_cells(y, 0)['text']))
                both(data[:first])
                if col0:
                    pending = m['pending'] == (a.is_using_alternate_linebuf(), y)
                    must_keep = pending and not m['broad']
                    cell0 = a.cpu_cells(y, 0)['text']
                    if m['irm']:
                        self.assertFalse(cell0.startswith(marks), ctx)
                        if must_keep and not wide:
                            counts['moved'] += 1
                            self.assertTrue(a.cpu_cells(y, a.cursor.x)['text'].startswith(marks), ctx)
                    elif cell0.startswith(marks):
                        counts['kept'] += 1
                        self.assertTrue(pending, ctx)
                    else:
                        counts['overwritten'] += had_marks
                        self.assertFalse(must_keep, ctx)
                both(data[first:])
                m['pending'] = None

            for i in range(num_ops):
                kind = rng.choice(kinds)
                ctx = f'seed {seed}, op {i} ({kind})'
                y, mt, mb = a.cursor.y, a.margin_top, a.margin_bottom
                if kind in broad_kinds or kind in ('ind', 'lf') and y == mb or kind == 'ri' and y == mt:
                    m['broad'] = True
                if kind in ('mark', 'prompt'):
                    mark(ctx)
                if kind in ('text', 'prompt'):
                    text(ctx)
                elif kind == 'bdsm':
                    m['bdsm'] = rng.random() < 0.6
                    pb(a, '\x1b[8h' if m['bdsm'] else '\x1b[8l')
                    if not m['bdsm']:
                        m['pending'] = None
                elif kind == 'alt':
                    to_alt = rng.random() < 0.5
                    if to_alt != a.is_using_alternate_linebuf():
                        m['pending'] = None
                        if to_alt:
                            m['stash'], m['bdsm'] = m['bdsm'], False
                        else:
                            m['bdsm'] = m['stash']
                    both('\x1b[?1049h' if to_alt else '\x1b[?1049l')
                elif kind == 'decstr':
                    m.update(bdsm=False, stash=False, irm=False, pending=None)
                    both('\x1b[!p')
                elif kind == 'resize':
                    lines, cols = rng.choice(((4, 6), (3, 6), (4, 7), (5, 5)))
                    a.resize(lines, cols)
                    b.resize(lines, cols)
                    m['pending'] = None
                elif kind == 'irm':
                    m['irm'] = rng.random() < 0.5
                    both('\x1b[4h' if m['irm'] else '\x1b[4l')
                elif kind != 'mark':
                    n = rng.randrange(3)
                    data = {
                        'cr': '\r',
                        'cup': f'\x1b[{rng.randrange(1, 6)};{1 if rng.random() < 0.5 else rng.randrange(1, 8)}H',
                        'ind': '\x1bD',
                        'lf': '\n',
                        'ri': '\x1bM',
                        'su': '\x1b[S',
                        'sd': '\x1b[T',
                        'el': f'\x1b[{n}K',
                        'ed': f'\x1b[{n}J',
                        'ech': '\x1b[X',
                        'ich': '\x1b[@',
                        'dch': '\x1b[P',
                        'il': '\x1b[L',
                        'dl': '\x1b[M',
                        'stbm': '\x1b[2;3r\x1b[?6h' if rng.random() < 0.5 else '\x1b[r\x1b[?6l',
                        'auto': rng.choice(('\x1b[?2501h', '\x1b[?2501l')),
                        'scp': rng.choice(('\x1b[1 k', '\x1b[2 k', '\x1b[ k')),
                        'tab': '\t',
                        'cht': '\x1b[I',
                    }[kind]
                    region = range(mt, mb + 1)
                    if kind in ('ind', 'lf') and y == mb or kind == 'ri' and y == mt or kind in ('su', 'sd'):
                        touch(region)
                    elif kind in ('il', 'dl') and y in region:
                        touch(range(y, mb + 1))
                    elif kind in ('el', 'ech', 'ich', 'dch'):
                        touch((y,))
                    elif kind == 'ed':
                        touch((range(y, a.lines), range(y + 1), range(a.lines))[n])
                    at_pending = at_col0() and m['pending'] == (a.is_using_alternate_linebuf(), y)
                    both(data)
                    if kind in ('tab', 'cht') and at_pending and a.cpu_cells(y, 0)['text'].startswith('\t'):
                        m['pending'] = None
                rows_a = [[dict(c, text=c['text'].lstrip(LRM + RLM)) for c in a.cpu_cells(r)] for r in range(a.lines)]
                rows_b = [list(b.cpu_cells(r)) for r in range(b.lines)]
                # a rewrap can leave the reservation marker '<' of a blank output start row, which bidi mode does not put
                # before a marks-only cell 0: the screens then differ from here on
                if kind == 'resize' and rows_a != rows_b and any('<' in c['text'] for row in rows_b for c in row):
                    stops['marker'] += 1
                    return
                for r in range(a.lines):
                    self.ae([dict(c, text=c['text'].lstrip(LRM + RLM)) for c in a.cpu_cells(r)], list(b.cpu_cells(r)), f'{ctx}, row {r}')
                self.ae((a.cursor.x, a.cursor.y), (b.cursor.x, b.cursor.y), ctx)

        for seed in range(300):
            run(seed, 60)
        self.assertLess(stops['marker'], 3, stops)
        self.assertGreater(min(counts.values()), 10, counts)

    def test_marks_only_is_blank(self):
        # A cell holding only LRM and RLM is blank wherever cells and rows are read, so with the marks stripped everything equals
        # the same stream drawn without bidi mode.
        bdsm = '\x1b[8h'

        def texts(s):
            out = []
            for as_ansi in (False, True):
                for f in (s.as_text, s.as_text_non_visual):
                    lines = []
                    f(lines.append, as_ansi, False)
                    out.append(''.join(lines))
            return out

        def selections(s):
            return [s.text_for_selection(a, b) for a, b in product((False, True), repeat=2)]

        def observe(s, probe):
            cells = [[dict(c, text=c['text'].lstrip(LRM + RLM)) for c in s.cpu_cells(r)] for r in range(s.lines)]
            return {
                'cells': cells,
                'wrapped': [s.line(r).last_char_has_wrapped_flag() for r in range(s.lines)],
                'cursor': (s.cursor.x, s.cursor.y),
                'history': s.historybuf.count,
                'probe': probe(s) if probe else None,
                'text': texts(s),
            }

        def differential(data, op=None, probe=None, cols=6, lines=4, prefix='', size=None, **opts):
            a, b = (self.create_screen(cols=cols, lines=lines, options=opts, **(size or {})) for _ in range(2))
            pb(a, prefix + data)
            pb(b, data.replace(bdsm, ''))
            if op:
                op(a), op(b)
            oa, ob = observe(a, probe), observe(b, probe)
            for key in oa:
                self.ae(oa[key], ob[key], key)

        def resize(lines, cols):
            return lambda s: s.resize(lines, cols)

        def erase_to_history(s):
            pb(s, '\x1b[22J')

        def line_selection(y):
            def probe(s):
                s.start_selection(0, y, False, EXTEND_LINE)
                s.update_selection(0, y, True)
                return selections(s)

            return probe

        def drag(rectangle):
            def probe(s):
                s.start_selection(2, 0, rectangle)
                s.update_selection(0, 1, rectangle)
                return selections(s)

            return probe

        def last_output(s):
            out = []
            return s.cmd_output(3, out.append), ''.join(out)

        def to_bottom(s):
            s.scroll_prompt_to_bottom()
            return texts(s), (s.cursor.x, s.cursor.y), s.historybuf.count

        def marked(s):
            s.set_marker(marker_from_regex('foo', 1))
            return s.marked_cells()

        # the wide char wraps past the marks cell insert mode pushed to the last column, and the row under it is replaced
        wrapped_marks = RLM + '\x1b[4habcde中f\x1b[L' + 'x\x1b[4l'
        marked_x = {LRM + RLM + '\x1b[Cfoo': (1, 2, 3), LRM + RLM + '\x1b[3@\rab\x1b[7Gfoo': (6, 7, 8)}
        below_ice = RLM + '\x1b[3@\rab'
        resize_cases = {
            'resize drops the marks row below content': (bdsm + 'ab\r\n\r\n' + RLM + CUP(2), resize(2, 5)),
            'rewrap a trailing marks cell': (bdsm + RLM + '\x1b[4habc\x1b[4l', resize(4, 3)),
            'rewrap a marks cell at the last column': (bdsm + RLM + '\x1b[4habcde\x1b[4l', resize(4, 3)),
            'taller, a marks cell ends a wrapped row': (bdsm + wrapped_marks, resize(5, 6)),
            'taller, the wrapped row is in history': (bdsm + '1\r\n2\r\n3\r\n4\r\n' + wrapped_marks, resize(5, 6)),
            'narrower, a marks cell ends a wrapped row': (bdsm + wrapped_marks, resize(4, 5)),
        }
        for prefix in ('', '\x1b[?2501h\x1b[2 k'):
            for name, (data, op) in resize_cases.items():
                with self.subTest(case=name, prefix=prefix):
                    differential(data, op, prefix=prefix)
        cases = {
            'ED 22 moves only the content to history': (bdsm + 'ab\r\n\r\n' + RLM, erase_to_history, None),
            'as_text with a trailing marks cell': (bdsm + below_ice, None, None),
            'as_text with a marks row': (bdsm + 'ab\r\n\r\n' + RLM, None, None),
            'marks cell between characters': (bdsm + RLM + '\x1b[3@\rab\x1b[6Gx', None, None),
            'line selection over a row ending in a marks cell': (bdsm + below_ice, None, line_selection(0)),
            'line selection over a marks row': (bdsm + 'ab\r\n\r\n' + RLM, None, line_selection(2)),
            'drag ending on a marks cell': (bdsm + 'abcd\r\n' + RLM + '\x1b[Cfoo', None, drag(False)),
            'rectangle over column 0 ending on a marks cell': (bdsm + 'abcd\r\n' + RLM + '\x1b[Cfoo', None, drag(True)),
            'last non-empty output made of marks rows': (
                bdsm + '\x1b]133;A\x07$ \r\n\x1b]133;C\x07' + RLM + '\r\n' + RLM + '\r\n\x1b]133;A\x07$ ',
                None,
                last_output,
            ),
            'scroll prompt to bottom over marks rows': (
                bdsm + 'a\r\nb\r\nc\r\nd\r\ne\r\nf' + CUP(3) + '\x1b[2K' + RLM + CUP(4) + '\x1b[2K' + RLM + CUP(2),
                None,
                to_bottom,
            ),
        }
        for name, (data, op, probe) in cases.items():
            with self.subTest(case=name):
                differential(data, op, probe)
        tab_cases = {
            'tab over a marks cell': bdsm + RLM + '\tx',
            'tab span over a marks cell ICH pushed': bdsm + RLM + '\x1b[3@\rab\tx',
            'tab span over a marks cell insert mode pushed': bdsm + RLM + '\x1b[4hab\x1b[4l\tx',
            'CHT over a marks cell': bdsm + RLM + '\x1b[Ix',
            'a mark after the tab is dropped': bdsm + RLM + '\t\r' + RLM + 'x',
            'tab over marks before a space': bdsm + RLM + ' \r\tx',
        }
        for prefix in ('', '\x1b[?2501h\x1b[2 k'):
            for name, data in tab_cases.items():
                with self.subTest(case=name, prefix=prefix):
                    differential(data, None, None, prefix=prefix)
        # marks before a char are not blank: no tab is recorded, and the marks stay in the copied text
        with self.subTest(case='tab over marks before a char keeps them'):
            a, b = self.mark_screen('abc\r' + RLM + '\tx'), self.mark_screen('abc\r' + RLM + '\tx', bdsm=False)
            self.ae(self.cell_texts(a, n=6)[0], RLM + 'a')
            self.ae([c.lstrip(LRM + RLM) for c in self.cell_texts(a, n=6)], self.cell_texts(b, n=6))
            self.ae((a.cursor.x, a.cursor.y), (b.cursor.x, b.cursor.y))
        # CHT is not drawn text, so overwriting the marks must dirty the row for the renderer
        s = self.mark_screen(RLM)
        s.update_only_line_graphics_data()
        self.ae(s.linebuf.dirty_lines(), [])
        pb(s, '\x1b[I')
        self.ae(s.linebuf.dirty_lines(), [0])

        # the lines a resize drops are counted from the content, which images placed above a marks-only row must not be moved for
        def image_rects(s):
            layers = s.grman.update_layers(0, -1, -1, 2 / s.columns, 2 / s.lines, s.columns, s.lines, 10, 20)
            return [r['dest_rect'] for r in layers]

        image = '\x1b_Ga=T,f=24,i=1,s=1,v=1,c=1,r=1,C=1;eHh4\x1b\\'
        for screen_switch in ('', '\x1b[?1049h'):
            with self.subTest(case='image above a marks row', alternate=bool(screen_switch)):
                data = screen_switch + bdsm + 'ab' + CUP(2) + image + CUP(4) + RLM + CUP(1)
                differential(data, resize(2, 6), image_rects, size={'cell_width': 10, 'cell_height': 20})
        # a URL continues from a wrapped row whose last cell is marks-only, over the row the wide char wrapped to
        pattern = 'http://[a-z.]+'

        def url(s):
            s.detect_url(1, 0)
            return s.current_url_text(), ''.join(s.text_for_marked_url())

        with self.subTest(case='url'):
            data = bdsm + RLM + '\x1b[4hhttp:中\x1b[4l' + CUP(2) + '\x1b[2K//a.co'
            differential(data, probe=url, detect_url_regex={pattern: pattern})
        # marks-only cells do not shift marker highlights
        for data in (LRM + RLM + '\x1b[Cfoo', LRM + RLM + '\x1b[3@\rab\x1b[7Gfoo'):
            with self.subTest(case='marker', data=data):
                a, b = self.screen(cols=12), self.screen(cols=12)
                pb(a, bdsm + data)
                pb(b, data)
                self.ae(marked(a), marked(b))
                self.ae(marked(b), [(x, 0, 1) for x in marked_x[data]])
        # an OSC 66 cell holding only marks is explicit text, kept as without bidi mode
        for w in (2, 3):
            multi = f'\x1b]66;w={w};{LRM}{RLM}\x07'
            with self.subTest(case='multicell marks resize', w=w):
                differential(bdsm + multi + '\r', resize(4, 6))
                s = self.screen(cols=6)
                pb(s, bdsm + multi + '\r')
                s.resize(4, 6)
                out = []
                s.as_text(out.append, False, False)
                text = ''.join(out)
                self.assertIn(LRM + RLM, text)
                self.assertNotIn('<', text)
            with self.subTest(case='multicell marks marker', w=w):
                s = self.screen(cols=12)
                pb(s, bdsm + multi + 'foo')
                self.ae(marked(s), [(x, 0, 1) for x in range(w, w + 3)])
            with self.subTest(case='multicell marks ansi copy', w=w):
                s = self.screen(cols=12)
                pb(s, bdsm + multi)
                out = []
                s.as_text(out.append, True, False)
                self.assertIn(f'\x1b]66;w={w};{LRM}{RLM}', ''.join(out))
        # a mark stored on its own is text when bidi mode never recorded it
        s = self.screen()
        pb(s, '\x1b]66;w=1;' + LRM + '\x07')
        out = []
        s.as_text(out.append, False, False)
        self.ae(''.join(out).rstrip('\n'), LRM)

    def test_leading_mark_without_bidi_mode(self):
        # as without bidi support: the mark is dropped
        for data, text in (('abc\r' + RLM, 'abc'), ('abc\r' + RLM + '\x1b[2CX', 'abX'), (RLM + '\tx', '\tx'), (RLM, ''), (RLM + 'hello world', 'hello world')):
            with self.subTest(data=data):
                self.ae(str(self.mark_screen(data, cols=12, bdsm=False).line(0)), text)
        # ICH in column 0 only shifts the cell, marks in its text included
        s = self.mark_screen('\x1b]66;w=1;' + LRM + 'a\x07bc\r\x1b[@', bdsm=False)
        self.ae(self.cell_texts(s), ['', LRM + 'a', 'b', 'c'])
        # a cell written in bidi mode is overwritten as any cell is
        self.ae(self.cell_texts(self.mark_screen(RLM + 'a\x1b[8l\rb'), n=2), ['b', ''])

    def test_leading_mark_word_selection(self):
        def word(s):
            s.start_selection(2, 0, False, EXTEND_WORD)
            s.update_selection(2, 0, True)
            return s.text_for_selection(False, False)

        self.ae(word(self.mark_screen(RLM + 'hello world', cols=20)), (RLM + 'hello',))
        # without bidi mode an OSC 66 cell whose text starts with a mark is read as it is
        self.ae(word(self.mark_screen('\x1b]66;w=1;' + RLM + 'h\x07ello world', cols=20, bdsm=False)), ('ello',))

    def test_leading_mark_marker(self):
        for bdsm, data in ((True, RLM + 'foo bar foo'), (True, RLM + LRM + 'foo bar foo'), (False, 'foo bar foo')):
            with self.subTest(data=data):
                s = self.mark_screen(data, cols=20, bdsm=bdsm)
                s.set_marker(marker_from_regex('foo', 1))
                self.ae(s.marked_cells(), [(x, 0, 1) for x in (0, 1, 2, 8, 9, 10)])
        # a cell holding only controls
        s = self.mark_screen(RLM + '\x1b[Cfoo', cols=20)
        s.set_marker(marker_from_regex('foo', 1))
        self.ae(s.marked_cells(), [(x, 0, 1) for x in (1, 2, 3)])

    def test_leading_mark_image_placeholder(self):
        def refs(marks):
            s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, 10, 20)
            put_image(s, 20, 20, num_cols=4, num_lines=2, unicode_placeholder=1, id=42)
            pb(s, '\x1b[8h' + marks + '\x1b[38;5;42m\U0010eeee\u0305\u0305\U0010eeee\u0305\u030d')
            s.update_only_line_graphics_data()
            return [(r['src_rect'], r['dest_rect']) for r in layers(s)]

        # the placeholder after the controls in the first cell starts the image there
        expected = refs('')
        self.ae(len(expected), 1)
        for marks in (LRM, RLM + LRM):
            with self.subTest(marks=marks):
                self.ae(refs(marks), expected)

    def test_leading_mark_url_across_newline(self):
        url = 'http://moo.com/abcdef'
        for opener, second, expected in (('', 'ghij x', url + 'ghij'), ('(', ')x', url)):
            for bdsm in (False, True):
                for mark in ('', RLM):
                    with self.subTest(opener=opener, bdsm=bdsm, mark=mark):
                        s = self.screen(cols=len(opener + url), lines=3)
                        pb(s, ('\x1b[8h' if bdsm else '') + opener + url + '\r\n' + mark + second)
                        s.detect_url(len(opener) + 3, 0)
                        self.ae(s.current_url_text(), expected)

    def test_leading_mark_url_regex(self):
        for pattern in ('[[:alnum:]_./-]+\\.[[:alnum:]]+:[0-9]+', '^[[:alnum:]_./-]+\\.[[:alnum:]]+:[0-9]+'):
            for mark in ('', RLM):
                with self.subTest(pattern=pattern, mark=mark):
                    s = self.screen(cols=30, lines=3, detect_url_regex={pattern: pattern})
                    pb(s, '\x1b[8h' + mark + 'src/foo.py:42 here')
                    s.detect_url(3, 0)
                    self.ae(s.current_url_text(), 'src/foo.py:42')
