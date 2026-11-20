#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

import array
import os
import random
import re
import struct
import tempfile
from itertools import product

from kitty.fast_data_types import (
    CURSOR_BEAM,
    CURSOR_BLOCK,
    CURSOR_HOLLOW,
    CURSOR_UNDERLINE,
    Screen,
    create_mock_window,
    get_options,
    send_mock_mouse_event_to_window,
    sprite_idx_to_pos,
    test_render_line,
    test_set_batched_non_ascii_draw,
)
from kitty.fonts.render import setup_for_testing

from .base import BaseTest, Callbacks, draw_multicell, parse_bytes
from .fonts import testing_font_data

A = 'אבג'  # three Hebrew letters, bidi class R
MIXED = 'abc' + A
NSI = 'אב 12'  # R R WS EN EN: its map (3, 4, 2, 1, 0) is not its own inverse
LRM, RLM = '\u200e', '\u200f'
ISOLATES = '\u2066\u2067\u2068\u2069'  # LRI RLI FSI PDI
LRE, RLE, PDF, LRO, RLO = '\u202a\u202b\u202c\u202d\u202e'
AUTO, SCP_RTL, SCP_LTR = '\x1b[?2501h', '\x1b[2 k', '\x1b[1 k'
PROMPT = '\x1b]133;A\x07'  # OSC 133 prompt start, as shell integration sends it
GPU_CELL = struct.Struct('=II')  # CellGPUData in kitty/line.h: sprite_idx, style_and_mark
CELL_GPU_STYLE_SHIFT = 2
EXTRA_CURSOR = 1 << 2  # an extra cursor of shape 1 in the selection buffer
FONT_SIZE, DPI = 11.0, 96.0  # the font group the tests render with


def pb(s, data):
    parse_bytes(s, data.encode())


def frame(s):
    return s.test_update_cell_data(FONT_SIZE, DPI, DPI)


def order(s, y=0):
    # visual to logical map of screen row y in the last frame, None for a row shaped without levels
    return s.test_bidi_v2l(y + int(bool(get_options().pixel_scroll) and not s.is_using_alternate_linebuf()))


def visual(s, y=0):
    # screen row y as a new frame shows it: each char once, an empty cell as a space
    frame(s)
    cells = (s.cpu_cells(y, x) for x in order(s, y) or range(s.columns))
    return ''.join(c['text'] or ' ' for c in cells if not (c['mcd'] and (c['x'] or c['y']))).rstrip()


def orders(s):
    frame(s)
    return [order(s, y) for y in range(s.lines)]


def n0_walk_is_slow(s):
    # FriBidi before 1.0.17 walks back from the opening bracket of every pair to the previous strong char (N0)
    info = s.test_bidi_bracket_limit()[1]
    version = re.match(r'\(GNU FriBidi\) (\d+)\.(\d+)\.(\d+)', info)
    assert version is not None, info
    return tuple(map(int, version.groups())) < (1, 0, 17)


def uploaded(s, y=0):
    # (sprite_idx, style_and_mark) of each cell of screen row y in a new frame
    buf = frame(s)
    row_size = s.columns * GPU_CELL.size
    start = (y + len(buf) // row_size - s.lines) * row_size  # pixel scroll adds a leading render row
    return list(GPU_CELL.iter_unpack(buf[start : start + row_size]))


def sprites(s, y=0):
    return [c[0] for c in uploaded(s, y)]


def styles(s, y=0):
    return [c[1] >> CELL_GPU_STYLE_SHIFT for c in uploaded(s, y)]


def screen_render_rows(s):
    return s.lines + int(bool(get_options().pixel_scroll) and not s.is_using_alternate_linebuf())


def main_row(s, buf, y, start=0, end=None):
    # the cells uploaded for columns start..end of screen row y in the frame buf, in visual order
    first = (screen_render_rows(s) - s.lines + y) * s.columns
    cells = list(GPU_CELL.iter_unpack(buf[first * GPU_CELL.size : (first + s.columns) * GPU_CELL.size]))
    return cells[start:end]


def strips(s, buf, regions=None):
    # {id: rows} of the strip of each shifted region in the frame buf. The strips follow the cells of the screen, in the order of
    # the regions. A vertical region's strip is the kept row (or newest scrollback line) above it, its rows, and the kept row
    # below it; a horizontal region's has a row per row of it, between the kept columns on its left and right.
    cells = list(GPU_CELL.iter_unpack(buf))
    at, ans = screen_render_rows(s) * s.columns, {}
    for r in s.smooth_scroll_regions() if regions is None else regions:
        if not r['offset']:
            continue
        w, h = r['right'] - r['left'], r['bottom'] - r['top']
        width, height = (w + 2, h) if r['horizontal'] else (w, h + 2)
        ans[r['id']] = [cells[at + y * width : at + (y + 1) * width] for y in range(height)]
        at += width * height
    if at != len(cells):
        raise AssertionError(f'{len(cells) - at} cells of the frame are in no strip')
    return ans


def draw_coloured(s, text, first_colour=1):
    # each char gets its own 256-colour fg, so its own style index
    for i, ch in enumerate(text):
        pb(s, f'\x1b[38;5;{first_colour + i}m{ch}')
    pb(s, '\x1b[m')


def osc66_controls(text, control_as=None):
    # each bidi control of text in an OSC 66 cell of its own, the only way a cell can start with one
    return ''.join(f'\x1b]66;w=1;{control_as or ch}\x07' if ch in ISOLATES + LRE + RLE + PDF + LRO + RLO else ch for ch in text)


def apply(s, op):
    if callable(op):
        op(s)
    else:
        pb(s, op)


class TestBidiReorder(BaseTest):
    def setUp(self):
        # A monospace font with Hebrew glyphs: text narrower than its multicell, as in a proportional fallback font, is
        # aligned by its direction, which the cell comparisons with a screen without bidi mode would see
        tdir = tempfile.mkdtemp()
        self.addCleanup(self.rmtree_ignoring_errors, tdir)
        path = os.path.join(tdir, 'LiberationMono-Regular.ttf')
        with open(path, 'wb') as f:
            f.write(testing_font_data('LiberationMono-Regular.ttf'))
        self.sprite_map = self.enterContext(setup_for_testing(size=FONT_SIZE, dpi=DPI, main_face_path=path))[0]

    def screen(self, *seqs, cols=10, lines=5, scrollback=5, text='', **opts):
        s = self.create_screen(cols=cols, lines=lines, scrollback=scrollback, options=opts)
        pb(s, '\x1b[8h' + ''.join(seqs))
        s.draw(text)
        return s

    def written(self, data, *seqs, cols=10, lines=1, **opts):
        s = self.screen(*seqs, cols=cols, lines=lines, **opts)
        pb(s, data)
        return s

    def paragraph(self, *rows, **kw):
        # rows of a 5 column screen, soft-wrapped into one paragraph
        return self.screen(cols=5, text=''.join(rows), **kw)

    def split(self, s, row=1, ch='ו'):
        # overwrite the last cell of the row above linebuf row `row`, which clears its soft wrap
        s.cursor_position(row, 5)
        s.draw(ch)
        self.assertFalse(s.linebuf.is_continued(row))

    def fresh_sprites(self, text, cols=5, **opts):
        ans = sprites(self.screen(cols=cols, lines=2, text=text, **opts))
        self.assertTrue(any(ans))
        return ans

    def guessed_sprites(self, text, cols=5):
        # text shaped without levels, by a screen that never sent CSI 8 h
        s = self.create_screen(cols=cols, lines=2, options={})
        s.draw(text)
        return sprites(s)

    def bidi_and_plain(self, draw, cols=10, lines=5, scrollback=5):
        # the same cells drawn after CSI 8 h and on a screen that never sent it
        s = self.screen(cols=cols, lines=lines, scrollback=scrollback)
        plain = self.create_screen(cols=cols, lines=lines, scrollback=scrollback, options={})
        # without Hebrew glyphs each letter is the same missing-glyph box, and cells compare equal in any order
        letters = self.create_screen(cols=2, lines=1, options={})
        letters.draw('של')
        self.assertNotEqual(*self.bitmaps(letters), 'the test font has no Hebrew glyphs')
        draw(s)
        draw(plain)
        return s, plain

    def bitmaps(self, s, y=0):
        # the alpha of each cell of screen row y in a new frame, in uploaded (visual) order
        return self.pixels(uploaded(s, y))

    def pixels(self, cells):
        # the alpha of each of these uploaded cells
        ans = []
        for idx, _ in cells:
            pixels = array.array('I', self.sprite_map[sprite_idx_to_pos(idx & 0x7FFFFFFF, setup_for_testing.xnum, setup_for_testing.ynum)])
            ans.append(bytes(p & 0xFF for p in pixels))  # the low byte of a pixel is its alpha
        return ans

    def assert_frames_match_replay(self, build, *ops):
        # a screen uploaded after each op shows what a new one given the same ops and uploaded once does
        s, f = build(), build()
        frame(s)
        for op in ops:
            apply(s, op)
            frame(s)
        for op in ops:
            apply(f, op)
        self.ae(frame(s), frame(f))

    def test_visual_order(self):
        for text, cols, want in (
            (MIXED, 10, 'abcגבא'),
            ('אב, גד', 10, 'דג ,בא'),
            ('א好ב', 10, 'א好ב'),
            ('אב好גד', 10, 'בא好דג'),
            ('א😀ב', 10, 'ב😀א'),
            (NSI, 5, '12 בא'),
        ):
            with self.subTest(text=text):
                self.ae(visual(self.screen(cols=cols, text=text)), want)
        # no assigned R/AL letter lies outside the classifier; U+FEFD and U+FEFE are unassigned, AL by default
        for cp in (0x0710, 0x0784, 0x07CA, 0x0800, 0x0840, 0x08A0, 0x0870, 0xFB2A, 0xFB50, 0xFE8D, 0x10A10, 0x1E900, 0x1EE00, 0xFEFD, 0xFEFE):
            with self.subTest(hex(cp)):
                self.ae(orders(self.screen(text='ab ' + chr(cp) * 2))[0][3:5], (4, 3))

    def test_rows_without_a_map(self):
        self.assertIsNone(orders(self.screen(text='hello world'))[0])
        s = self.create_screen(cols=10, options={})  # never sent CSI 8 h
        s.draw(MIXED)
        self.assertIsNone(orders(s)[0])
        self.assertIsNone(orders(self.screen(text=MIXED, force_ltr=True))[0])
        # a row with an image placeholder is not reordered, its cells shaped by the direction guessed from their text
        s = self.screen(text=A)
        s.draw(chr(0x10EEEE))
        self.ae(orders(s)[0], tuple(range(10)))
        # scaled text stays in its logical columns, the text before it reordered
        s = self.screen(text=A)
        draw_multicell(s, 'x', scale=2)
        self.ae(orders(s)[0][:5], (2, 1, 0, 3, 4))

    def test_frame_without_bidi_mode(self):
        # A screen that never sent CSI 8 h uploads each row in logical order, renders no cell at a level, and shapes each row
        # as a line rendered without levels. The font has Arabic glyphs too.
        tdir = tempfile.mkdtemp()
        self.addCleanup(self.rmtree_ignoring_errors, tdir)
        path = os.path.join(tdir, 'DejaVuSansMono.ttf')
        with open(path, 'wb') as f:
            f.write(testing_font_data('DejaVuSansMono.ttf'))
        self.enterContext(setup_for_testing(size=FONT_SIZE, dpi=DPI, main_face_path=path))
        # test_render_line writes its sprites into the cells of the line, so the oracle is a twin given the same data and ops
        # that is never framed
        s, twin = (self.create_screen(cols=12, lines=6, scrollback=10, options={'pixel_scroll': True}) for _ in range(2))
        for x in (s, twin):
            pb(x, 'שלום עולם 12\r\nمرحبا عالم!\r\nab שָׁלוֹם é\r\nxy ')
            draw_multicell(x, 'א', width=2)
            pb(x, ' 3\r\n')
            draw_multicell(x, 'ש', scale=2)
            pb(x, 'בג de')
        none = bytes(s.columns)

        def unmapped():
            buf = frame(s)
            for r in range(screen_render_rows(s)):
                self.assertIsNone(s.test_bidi_v2l(r), r)
                self.assertIn(s.test_render_levels(r), (none, None), r)  # None for the leading row before any scrollback
            return buf

        def unlevelled(overlay_row=None):
            # the sprites of each screen row, checked against the line rendered without levels
            buf = unmapped()
            ans = []
            for y in range(s.lines):
                row = [c[0] for c in main_row(s, buf, y)]
                if y != overlay_row:
                    line = twin.line(y)
                    test_render_line(line)
                    self.ae(row, [line.sprite_at(x) for x in range(s.columns)], y)
                ans.append(row)
            self.assertTrue(any(ans[0]))
            return ans

        unlevelled()
        s.cursor_position(2, 4)
        s.test_update_overlay_text('xy')
        unlevelled(overlay_row=1)
        self.ae(s.test_render_levels(0, True), none)
        s.test_update_overlay_text('')
        # a narrow vertical region, a horizontal one and a full-width one, each shifted by whole cells and then by half a cell
        for rid, region, delta in ((1, (2, 0, 8, 4, 1, False, False), 20), (2, (0, 0, 12, 2, 1, False, True), -20), (3, (0, 0, 12, 4), 20)):
            for x in (s, twin):
                self.assertTrue(x.smooth_scroll_define(rid, *region))
            for d in (delta, delta // 2):
                for x in (s, twin):
                    x.smooth_scroll(rid, d)
                rows = unlevelled()
            for x in (s, twin):
                self.assertTrue(x.smooth_scroll_remove(rid))
        rows = unlevelled()
        # the rows pushed into the scrollback, scrolled back into view by pixels, are shaped as they were on the screen
        pb(s, '\x1b[6H' + '\n' * 3)
        s.scroll(3, True)
        buf = unmapped()
        self.ae([[c[0] for c in main_row(s, buf, y)] for y in range(3)], rows[:3])

    def test_scaled_rtl_text_shaped_as_without_bidi(self):
        # without bidi mode HarfBuzz guesses the direction of scaled text, which reads right to left. Compared by pixels, as a
        # group of cells shaped right to left has sprites of its own.
        for text in ('שלום', 'ש'):  # one code point is stored in the cell, not in the text cache
            with self.subTest(text=text):
                s, plain = self.bidi_and_plain(lambda x: draw_multicell(x, text, scale=2), cols=12, lines=4)
                self.ae([self.bitmaps(s, y) for y in (0, 1)], [self.bitmaps(plain, y) for y in (0, 1)])

    def test_scaled_rtl_text_scrolled_into_view(self):
        # moving the view by pixels renders a clean row again at the levels stored for it, which keep the scaled cells' level
        def scroll(n, upwards=True):
            return lambda s: s.scroll(n, upwards)

        for text in ('אב', 'אבג'):
            with self.subTest(text=text):
                s, plain = self.bidi_and_plain(lambda x: None, cols=8, lines=4, scrollback=50)
                for i, op in enumerate(('\x1b[Hא\x1b]66;s=2;' + text + '\x07ב', '\x1b[4H' + '\n' * 6, scroll(5), scroll(1), scroll(1, False))):
                    apply(s, op)
                    apply(plain, op)
                    self.ae([self.bitmaps(s, y) for y in range(4)], [self.bitmaps(plain, y) for y in range(4)], f'after op {i}')

    def test_scaled_cell_is_a_barrier(self):
        # a scaled cell keeps its logical columns on every row it covers, and the text beside it is reordered as without it
        def block(*seqs):
            s = self.screen(*seqs)
            draw_multicell(s, 'x', scale=2)
            return s

        def keeps_block(row):
            # a row with nothing to reorder has no map
            return row is None or row[:2] == (0, 1)

        with self.subTest('text after the block'):
            s = block()
            pb(s, ' שלום')
            rows = orders(s)
            self.ae(rows[0], orders(self.screen('\x1b[1;3H', text=' שלום'))[0])
            self.assertTrue(keeps_block(rows[1]), rows[1])
        with self.subTest('text beside the bottom half'):
            s = block()
            pb(s, '\x1b[2;3Hשלום')
            rows = orders(s)
            self.ae(rows[1], orders(self.screen('\x1b[2;3H', text='שלום'))[1])
            self.assertTrue(keeps_block(rows[0]), rows[0])
        with self.subTest('the rows above a block in a wrapped paragraph'):
            text = 'אבגדהוזחטיכלמנ'
            s = self.screen(text=text)
            draw_multicell(s, 'x', scale=2)
            self.assertTrue(s.linebuf.is_continued(1))
            self.ae(orders(s)[0], orders(self.screen(text=text))[0])
        # the block is no strong char: a paragraph whose only other chars are blanks takes the fallback direction, and one
        # with right-to-left text after the block is right to left, the span after the block reversed within itself
        rtl_beside_block = (0, 1) + tuple(range(9, 1, -1))
        with self.subTest('right-to-left fallback'):
            s = block(AUTO, SCP_RTL)
            pb(s, ' שלום')
            self.ae(orders(s)[:2], [rtl_beside_block] * 2)
        with self.subTest('auto direction'):
            s = block(AUTO)
            pb(s, ' שלום')
            rows = orders(s)
            self.ae(rows[0], rtl_beside_block)
            self.ae(rows[1], tuple(range(10)))  # the block and blanks take the left-to-right fallback

    def test_rtl_multicell_reads_right_to_left(self):
        # the cells of a multicell holding right-to-left letters show what they show without bidi mode
        for text in ('אב', 'שלום'):
            with self.subTest(text=text):
                s, plain = self.bidi_and_plain(lambda x: draw_multicell(x, text, width=len(text)))
                self.ae(self.bitmaps(s), self.bitmaps(plain))

    def test_multicell_text_direction(self):
        # the text of a multicell led by a neutral char is shaped in the direction it has without bidi mode
        for text in ('(אבג', '1אב'):
            with self.subTest(text=text):
                s, plain = self.bidi_and_plain(lambda x: draw_multicell(x, text, width=len(text)))
                self.ae(self.bitmaps(s), self.bitmaps(plain))
        # led by a strong left-to-right char the text is left to right either way
        s, plain = self.bidi_and_plain(lambda x: draw_multicell(x, 'aאבג', width=4))
        self.ae(sprites(s), sprites(plain))

    def test_upload_permutes_cells(self):
        # each visual cell is the logical cell order[visual], told apart by style, also after a style table remap, live or paused
        for paused in (False, True):
            with self.subTest(paused=paused):
                s = self.screen(cols=5)
                pb(s, '\x1b[3H')
                draw_coloured(s, 'abcde', first_colour=100)
                s.erase_in_line(2)
                s.cursor_position(1, 1)
                draw_coloured(s, NSI)
                logical = [s.cell_style_idx(0, x) for x in range(5)]
                self.ae(styles(s), [logical[x] for x in (3, 4, 2, 1, 0)])
                if paused:
                    s.pause_rendering(True, 1000)
                    frame(s)
                s.test_gc_style_table()
                remapped = [s.cell_style_idx(0, x) for x in range(5)]
                self.assertNotEqual(remapped, logical)
                self.ae(styles(s), [remapped[x] for x in (3, 4, 2, 1, 0)])
        s = self.screen(force_ltr=True)
        draw_coloured(s, MIXED)
        self.ae(styles(s)[:6], [s.cell_style_idx(0, x) for x in range(6)])

    def test_may_reorder_writers(self):
        # on a stamped buffer each writer marks the row it stores a char that may reorder on, and nothing else does
        def stamped(*seqs):
            s = self.screen('x\x1b[2H', *seqs, cols=10, lines=3)
            frame(s)
            return s

        s = stamped()
        self.ae([s.test_bidi_may_reorder(y) for y in range(3)], [False] * 3)
        pb(s, 'ab' + A)
        self.ae((s.test_bidi_may_reorder(1), visual(s, 1)), (True, 'abגבא'))
        s = stamped()
        test_set_batched_non_ascii_draw(False)
        try:
            pb(s, 'ab' + A)
        finally:
            test_set_batched_non_ascii_draw(True)
        self.ae((s.test_bidi_may_reorder(1), visual(s, 1)), (True, 'abגבא'))
        for added in ('\u05b0', RLM, '\u2067', '\u061c'):
            s = stamped()
            pb(s, 'a' + added)
            self.assertTrue(s.test_bidi_may_reorder(1), repr(added))
        s = stamped()
        pb(s, 'a' + LRM + '\u0301b')
        self.assertFalse(s.test_bidi_may_reorder(1))
        s = stamped('\x1b]66;s=2;ab\x07')
        self.ae([s.test_bidi_may_reorder(y) for y in range(3)], [False, True, True])

    def test_may_reorder_when_stamped(self):
        # a buffer getting its first record marks the rows written before, on screen and in the history paragraph its first row
        # continues
        s = self.create_screen(cols=10, lines=3, options={})
        s.draw(A)
        pb(s, '\x1b[8hx')
        self.ae((s.test_bidi_may_reorder(0), visual(s, 0)), (True, 'גבאx'))
        s = self.create_screen(cols=5, lines=2, scrollback=10, options={'pixel_scroll': False})
        s.draw('אבגדה' + 'וזח')
        pb(s, '\r\n\x1b[8hab')
        self.ae((str(s.historybuf.line(0)), s.test_bidi_may_reorder(0)), ('אבגדה', True))
        # without a record its history line stays in logical order
        s = self.create_screen(cols=5, lines=2, scrollback=10, options={'pixel_scroll': False})
        s.draw(A)
        pb(s, '\r\n\r\n\x1b[8hab')
        self.ae(s.historybuf.count, 1)
        s.scroll(1, True)
        self.assertIsNone(orders(s)[0])
        # also for a history row of that paragraph more than a screen height above row 0, which a view scrolled back lays out
        s = self.create_screen(cols=5, lines=3, scrollback=50, options={'pixel_scroll': False})
        s.draw('אבגדה' + 'a' * 30)
        pb(s, '\x1b[H\x1b[8ha')
        frame(s)
        s.scroll(4, True)
        frame(s)
        self.ae(order(s, 0), (4, 3, 2, 1, 0))
        # a history row written without a stamp and back in a stamped buffer gets its bit from its cells
        s = self.create_screen(cols=5, lines=3, scrollback=10, options={'pixel_scroll': False})
        pb(s, A + '\r\n\r\n\r\n\x1b[2;1H\x1b[8hy\x1b[8l')
        s.reverse_scroll(1, True)
        pb(s, '\x1b[1;4H\x1b[8hz\x1b[8l')
        frame(s)
        self.ae((str(s.line(0)), s.test_bidi_may_reorder(0), order(s, 0)), (A + 'z', True, (2, 1, 0, 3, 4)))

    def test_may_reorder_of_history_rows_a_popped_row_continues(self):
        # the history rows above a line popped into a stamped buffer were written without a stamp, and a record later
        # written on that line lays them out
        s = self.create_screen(cols=5, lines=3, scrollback=10, options={'pixel_scroll': False})
        s.draw('אבגדה' + 'a' * 5)
        pb(s, '\r\n\n\n\x1b[2;1H\x1b[8hx\x1b[8l\x1b[1+T\x1b[1;5H\x1b[8hb\x1b[8l')
        s.scroll(1, True)
        frame(s)
        self.ae((str(s.historybuf.line(0)), order(s, 0)), ('אבגדה', (4, 3, 2, 1, 0)))

    def test_pixel_scroll_row_after_history_pops(self):
        # the leading row of pixel scrolling shows history line 0, which a pop and a push leave a different line with the same
        # number of lines pushed
        s = self.create_screen(cols=5, lines=3, scrollback=10, options={'pixel_scroll': True})
        pb(s, '\x1b[8h' + A + '\r\n\x1b[8l' + 'x\r\n' * 4)
        frame(s)
        pb(s, '\x1b[1+T\x1b[H\x1b[8hבגד\x1b[8l\x1b[3;1H\n')
        frame(s)
        self.ae((str(s.historybuf.line(0)), s.test_bidi_v2l(0)), ('בגד', (2, 1, 0, 3, 4)))

    def test_writes_leave_the_recording_loop_after_the_last_record(self):
        opts = {'pixel_scroll': False}
        s = self.create_screen(cols=5, lines=2, scrollback=10, options=opts)
        pb(s, '\x1b[8h' + A + '\r\n\r\n\x1b[8l')
        self.ae(s.historybuf.count, 1)
        self.assertTrue(s.test_writes_are_recorded())
        frame(s)
        self.assertFalse(s.test_writes_are_recorded())
        pb(s, 'ab')
        self.assertFalse(s.test_writes_are_recorded())
        s.scroll(1, True)
        self.ae(tuple(orders(s)[0][:3]), (2, 1, 0))
        # a record left on screen keeps the loop
        s = self.create_screen(cols=5, lines=2, scrollback=10, options=opts)
        pb(s, '\x1b[8h' + A + '\x1b[8l')
        frame(s)
        self.assertTrue(s.test_writes_are_recorded())
        frame(s)
        self.assertTrue(s.test_writes_are_recorded())
        # the record lapses at the first frame after the erase
        pb(s, '\x1b[2K')
        self.assertTrue(s.test_writes_are_recorded())
        frame(s)
        self.assertFalse(s.test_writes_are_recorded())
        # and after a screen alignment test fills the screen
        s = self.create_screen(cols=5, lines=2, scrollback=10, options=opts)
        pb(s, '\x1b[8h' + A + '\x1b[8l')
        frame(s)
        pb(s, '\x1b#8')
        frame(s)
        self.assertFalse(s.test_writes_are_recorded())

    def test_writes_follow_the_active_buffer_across_the_alternate_screen(self):
        s = self.create_screen(cols=5, lines=2, scrollback=10, options={'pixel_scroll': False})
        pb(s, '\x1b[?1049h\x1b[8hab\x1b[8l')
        frame(s)
        self.assertTrue(s.test_writes_are_recorded())
        pb(s, '\x1b[?1049l')
        frame(s)
        self.assertFalse(s.test_writes_are_recorded())
        # a record on the main screen takes no hold on the alternate one
        s = self.create_screen(cols=5, lines=2, scrollback=10, options={'pixel_scroll': False})
        pb(s, '\x1b[8h' + A + '\x1b[8l')
        frame(s)
        self.assertTrue(s.test_writes_are_recorded())
        pb(s, '\x1b[?1049h')
        self.assertFalse(s.test_writes_are_recorded())
        pb(s, '\x1b[?1049l')
        self.assertTrue(s.test_writes_are_recorded())

    def test_may_reorder_base(self):
        # a stamped paragraph with nothing that may reorder still has odd levels at a right-to-left base
        s = self.screen(SCP_RTL, AUTO, text='12 34')
        self.ae((s.test_bidi_may_reorder(0), visual(s)), (False, ' ' * 5 + '34 12'))

    def test_may_reorder_reflow(self):
        # rows joined by a reflow keep the bit of each, also when only the continuation has it
        s = self.screen(cols=5, text='abcde')
        pb(s, '\x1b[8l' + A)
        self.ae((s.test_bidi_line_record(1)[0], s.test_bidi_may_reorder(1), visual(s, 1)), (0, True, 'גבא'))
        s.resize(5, 10)
        self.ae((s.test_bidi_may_reorder(0), visual(s, 0)), (True, 'abcdeגבא'))
        # the lower row of a scaled char rewrapped onto a row of its own keeps the bit
        s = self.screen(cols=6, lines=4, text='abcd')
        pb(s, '\x1b]66;s=2;x\x07' + A)
        s.resize(4, 3)
        rows = [y for y in range(4) if any(s.cpu_cells(y, x)['mcd'] for x in range(3))]
        self.ae(len(rows), 2)
        self.ae([s.test_bidi_may_reorder(y) for y in rows], [True, True])
        frame(s)

    def test_paragraph_over_rows(self):
        # the continuation row has no RTL char of its own and is laid out with its paragraph, also from the history
        s = self.paragraph('אבגדה', '12 34')
        self.ae((visual(s, 0), visual(s, 1)), ('הדגבא', '34 12'))
        for lines, text, rows in ((2, 'אבגדהובזחטיכלמנ12 34', ('נמלכי', '34 12')), (1, 'אבגדהובזחט12 34', ('34 12',))):
            with self.subTest(lines=lines):
                s = self.screen(cols=5, lines=lines, scrollback=10, text=text)
                self.ae(s.historybuf.count, 2)
                self.ae(tuple(visual(s, y) for y in range(lines)), rows)
        # written before CSI 8 h, a row is reordered only with a stamped row of its paragraph
        s = self.create_screen(cols=5, lines=5, options={})
        s.draw('אבגדה')
        pb(s, '\x1b[8h\x1b[3Habc')
        self.assertIsNone(orders(s)[0])
        s = self.create_screen(cols=5, lines=5, options={})
        s.draw('אבגדה')
        pb(s, '\x1b[8hוזח')
        self.ae((visual(s, 0), visual(s, 1)), ('הדגבא', 'חזו'))
        # rewrapped wider, the rows merge
        s = self.screen(cols=5, text='abcde' + A)
        self.ae(visual(s, 1), 'גבא')
        s.resize(5, 25)
        self.ae(visual(s, 0), 'abcdeגבא')
        # a recorded continuation joined onto a row written without a record brings its record along
        s = self.create_screen(cols=4, lines=4, scrollback=10, options={})
        pb(s, 'abcd\x1b[8h' + A)
        self.ae((s.test_bidi_line_record(0)[0], visual(s, 1)), (0, 'גבא'))
        s.resize(4, 10)
        self.assertNotEqual(s.test_bidi_line_record(0)[0], 0)
        self.ae(visual(s), 'abcdגבא')

    def test_tall_paragraph_keeps_uploaded_maps(self):
        # 400 rows on 300 lines (100 in history): ! between R letters maps (1,0) except at the paragraph end where it is (0,1). The
        # window, the rows on view and a screen height above them, holds the whole paragraph.
        s = self.screen(cols=2, lines=300, scrollback=200, text='א!' * 400)
        self.ae(s.historybuf.count, 100)
        frame(s)
        maps = tuple(s.test_bidi_v2l(r) for r in range(s.lines + 1))
        self.ae(set(maps), {(0, 1), (1, 0)})
        self.ae([r for r, m in enumerate(maps) if m == (0, 1)], [300])

    def test_osc66_cells(self):
        self.ae(visual(self.written('ab\x1b]66;w=1;א\x07\x1b]66;w=1;ב\x07c')), 'abבאc')
        # a right-to-left char keeps its cells together, shown last to first
        s = self.screen()
        draw_multicell(s, 'א', width=2)
        draw_multicell(s, 'ב', width=2)
        self.ae((visual(s), order(s)[:4]), ('בא', (3, 2, 1, 0)))
        # a bidi control in an OSC 66 cell resolves as ! does, among many and nested to FriBidi's deepest level
        for text, cols, lines in (
            ('a\u2067bא\u2069\u2066ב\u2069\u2068ג\u2069', 12, 2),
            ('א' + '\u2067x\u2069' * 3000, 200, 50),
            ('aא' + RLE + 'bc', 12, 2),
            ('a' + RLO + 'bc' + PDF + 'd' + LRO + 'אב', 12, 2),
            ((RLE + LRE) * 62 + 'אa', 200, 50),
        ):
            with self.subTest(text=text[:12]):
                neutral = orders(self.written(osc66_controls(text, '!'), cols=cols, lines=lines))
                self.assertIsNotNone(neutral[0])
                self.ae(orders(self.written(osc66_controls(text), cols=cols, lines=lines)), neutral)
        # an RLM in an OSC 66 cell of its own is a strong char: the digits after it read right to left with no RTL letter on the row
        self.ae(visual(self.written('\x1b]66;w=1;' + RLM + '\x07' + '12 34')), '34 12' + RLM)

    def test_text_after_a_tab_starts_at_the_tab_stop(self):
        # the cells a tab skips stay with it at the paragraph level, as without bidi mode the text after it starts at the stop
        self.ae(orders(self.written(A + '\tדהו', cols=20))[0], (2, 1, 0) + tuple(range(3, 8)) + (10, 9, 8) + tuple(range(11, 20)))
        # under a right-to-left base the row is the mirror image of the row without bidi mode, each word in reading order
        mirrored = tuple(range(19, 10, -1)) + (8, 9, 10) + tuple(range(7, 2, -1)) + (0, 1, 2)
        self.ae(orders(self.written('abc\tdef', SCP_RTL, cols=20))[0], mirrored)
        # a char written into a skipped cell afterwards is fed as itself
        self.ae(orders(self.written('abc\tdef\x1b[1;6Hאב', cols=20))[0], (0, 1, 2, 3, 4, 6, 5) + tuple(range(7, 20)))

    def test_rows_without_a_record_in_a_recorded_paragraph(self):
        # a row written with bidi mode off is laid out with its paragraph when another row of it holds a record, also when that
        # row holds no right-to-left text
        s = self.screen(text='a' * 10)
        pb(s, '\x1b[8l' + A + ' xy')
        self.ae(orders(s)[:2], [None, (2, 1, 0) + tuple(range(3, 10))])
        # its first strong char sets the direction of the paragraph under ?2501
        s = self.screen(AUTO, text='12 34 56 7')
        pb(s, '\x1b[8l' + A + ' xy')
        self.ae(orders(s)[:2], [(9, 8, 6, 7, 5, 3, 4, 2, 0, 1), (9, 8, 7, 6, 4, 5, 3, 2, 1, 0)])

    def test_bracket_pairs(self):
        # With a FriBidi before 1.0.17 a pair is not resolved by N0 when its opening bracket is far after the previous letter or
        # digit, which no later text changes: א(ב) keeps its mirrored pair whatever follows it
        def both(text, cols=80, lines=1):
            return self.written(text, cols=cols, lines=lines), self.written(text.replace('(', '!').replace(')', '!'), cols=cols, lines=lines)

        for text, cols, lines in (('א(ב)' + '()' * 35, 80, 1), ('א(ב)' + '()' * 36, 80, 1), ('א(ב)' + '()' * 3000, 200, 50)):
            with self.subTest(pairs=len(text) // 2 - 2):
                kept, plain = both(text, cols, lines)
                self.ae((visual(kept)[:4], visual(plain)[:4]), (')ב(א', 'ב!א!'))
        near, plain = both('א' + '!' * 20 + '(ב)')
        self.assertNotEqual(orders(near), orders(plain))

        # Paired, ( and ) take the direction of the letter inside, which the letter before them shares (N0), so ) joins the run
        # of the text before it; unpaired, ) is a neutral between that letter and the end of an opposite paragraph (N2)
        def ltr_paragraph(run):
            return [tuple(range(run - 1, -1, -1)) + tuple(range(run, 80))]

        def rtl_paragraph(run):
            return [tuple(range(79, run - 1, -1)) + tuple(range(run))]

        self.ae(orders(near), ltr_paragraph(24))
        far, plain = both('א' + '!' * 40 + '(ב)')
        limited, info = far.test_bidi_bracket_limit()
        slow = n0_walk_is_slow(far)
        self.ae(limited, slow, info)
        self.ae(orders(plain), ltr_paragraph(43))
        self.ae(orders(far), ltr_paragraph(43 if slow else 44))
        far = self.written('a' + '!' * 40 + '(b)', SCP_RTL, cols=80)
        self.ae(orders(far), rtl_paragraph(43 if slow else 44))

    def test_incremental_frames_match_a_fresh_upload(self):
        # an edit, split, scroll or history change re-shapes every row whose levels it changes, written or not, on view or not
        def history(*data, **kw):
            def build():
                s = self.screen(cols=5, lines=3, scrollback=10, **kw)
                for d in data:
                    apply(s, d)
                return s

            return build

        def ring():
            s = self.screen(cols=5, lines=4, scrollback=0, pixel_scroll=False)
            pb(s, '\r\n'.join(['אב 12', 'א2 3(', 'ab אב', 'אבגד.', 'א 12b', '(12ב', 'אב cd', 'a אבג']))
            for up in (True, False):
                s.scroll(s.historybuf.count, up)
                frame(s)
            return s

        def clipped():
            return self.screen(AUTO, cols=8, lines=3, scrollback=100, pixel_scroll=False, text='א1234567' + '12 (3) 4' * 4)

        def up(n=1):
            return lambda s: s.scroll(n, True)

        def down(s):
            s.scroll(1, False)

        def pause(s):
            s.pause_rendering(True, 1000)

        def unpause(s):
            s.pause_rendering(False)

        for name, build, ops in (
            ('level change', lambda: self.paragraph('אבגד.', '12 34'), ('\x1b[Habcd',)),
            ('split', lambda: self.paragraph('אבגדה', '(12)'), ('\x1b[1;5Hx',)),
            ('split by ED 1', lambda: self.paragraph('אבגדה', '(12)'), ('\x1b[1;5H\x1b[1J',)),
            ('split by IL', lambda: self.paragraph('אבגדה', '(12)'), ('\x1b[2H\x1b[L',)),
            ('first strong char', lambda: self.screen(AUTO, cols=5, text='אבגדהab 1'), ('\x1b[Hx', '\x1b[Hא')),
            ('split, LTR', lambda: self.screen(AUTO, cols=5, text='abcde' + A), ('\x1b[1;5Hx',)),
            ('split, RTL', lambda: self.screen(AUTO, cols=5, text='אבגדהabc'), ('\x1b[1;5Hx',)),
            ('history sibling', history('top\r\nאבגד(12 34\r\nab\r\ncd'), (up(), '\x1b[Ha')),
            ('below the view', history('h1\r\nh2\r\nh3\r\nאבגד (12)'), (up(), '\x1b[2Habcd', down)),
            ('above the view', history('אבגד(12 34\r\nab\r\ncd', pixel_scroll=False), (up(), down, '\x1b[Ha', up())),
            ('dirty below the view', history('אבגדהאבגדה12 3!abcde'), (up(), '\x1b[3Hב')),
            ('split off view', history('x\r\ny\r\nאבגדה(12ב'), (up(), '\x1b[2;5Hו', down)),
            ('split off view, paused', history('x\r\ny\r\nאבגדה(12ב'), (up(), '\x1b[2;5Hו', down, pause)),
            ('paused, continues from history', history('אבגדה(12ב\r\nx\r\ny', pixel_scroll=False), (pause, unpause)),
            (
                # the history row was shown reordered by the record of the row it wraps into, which the erase removes
                'paused when the frame stops reordering',
                lambda: self.screen('\x1b[8lאבגדה\x1b[8hו\r\n', cols=5, lines=2, scrollback=10, pixel_scroll=False),
                (up(), lambda s: (pb(s, '\x1b[2J'), pause(s))),
            ),
            (
                'paused when the frame stops reordering, pixel scroll',
                lambda: self.screen('\x1b[8lאבגדה\x1b[8hו\r\n', cols=5, lines=2, scrollback=10, pixel_scroll=True),
                (up(), lambda s: (pb(s, '\x1b[2J'), pause(s))),
            ),
            (
                'erased prompt in history',
                history(AUTO + '12 34א' + PROMPT + '$ c\r\no1\r\no2\r\no3\r\n' + PROMPT + '$ ', pixel_scroll=False),
                (up(5), lambda s: s.erase_last_command(), up(5)),
            ),
            ('pushed with an edit below the view', history('h1\r\nh2\r\nh3\r\nאבגדה12345(ab\r\nc1\r\nc2'), (up(3), '\x1b[1;5Hב\x1b[3H\n')),
            (
                # the edit turns the paragraph on view right-to-left
                'pushed with an edit below the view, paused before a frame',
                history('h1\r\nh2\r\nh3\r\n' + AUTO + '12 34 56 78 9 x\r\nc1\r\nc2'),
                (up(3), lambda s: (pb(s, '\x1b[1;5Hא\x1b[3H\n'), pause(s)), unpause),
            ),
            (
                # the rows on view keep the levels of the first view, from their render cache
                'pushed with an edit while not scrolled back',
                history('h1\r\nh2\r\nאבגדה!?;:@&*^_~x\r\nc1\r\nc2', pixel_scroll=False),
                (up(4), lambda s: s.scroll(4, False), '\x1b[Hא\x1b[3H\n', up(5)),
            ),
            (
                'erased bidi line over plain history',
                history('\x1b[8lp1\r\np2\r\np3\r\np4\r\np5'),
                ('\x1b[8h\x1b[3Hab אב\x1b[8l\r\x1b[2K', up(3), lambda s: s.scroll(3, False), '\x1b[8h\x1b[3Hאב 12\x1b[8l', up(3)),
            ),
            (
                'unrecorded row continuing a recorded history row',
                history('\x1b[8lp1\r\np2\r\n\x1b[8hאבגדהab אב\x1b[8l\r\nx\r\ny'),
                ('\x1b[H\x1b[2Kcd', up(1), lambda s: s.scroll(1, False), '\x1b[Hx'),
            ),
            (
                'erased record of a row continued from history',
                history('\x1b[8lp1\r\np2\r\nאבגדה\x1b[8hab אב\x1b[8l\r\nx\r\ny', pixel_scroll=False),
                (up(1), '\x1b[H\x1b[2K'),
            ),
            (
                'stamped again after an erased record',
                history('\x1b[8lp1\r\nאבגדהאבגדה\x1b[8hab אב\x1b[8l\r\nx\r\ny', pixel_scroll=False),
                (up(2), '\x1b[H\x1b[2K', '\x1b[8h\x1b[3Hz'),
            ),
            (
                'recorded history line in the pixel scrolling row',
                history('\x1b[8lp\r\n\x1b[8hאב 12\r\nq\x1b[8l\r\nx\r\ny', pixel_scroll=True),
                ('\x1b[H\x1b[2K',),
            ),
            ('recorded line back from the history', history('\x1b[8hאב 12\x1b[8l\r\nx\r\ny\r\nz', pixel_scroll=False), (lambda s: s.reverse_scroll(1, True),)),
            (
                'recorded paragraph above the pixel scrolling row',
                history('\x1b[8hאבגדה\x1b[8l12 3456 7890 12\r\nx\r\ny', pixel_scroll=True),
                (up(3), lambda s: s.scroll(3, False), '\x1b[Hz'),
            ),
            ('recorded pixel scrolling row pushed away', history('\x1b[8hאבגדהוזח\x1b[8l\r\nx\r\ny', pixel_scroll=True), ('\x1b[3H\n',)),
            ('resized into the history', history('h1\r\nאבגדה12 3(\r\nx\r\ny'), (lambda s: s.resize(2, 5), up(2))),
            ('rewrapped into the history', history('h1\r\nאבגדה12 3(\r\nx\r\ny'), (lambda s: s.resize(3, 4), up(3))),
            (
                'erased prompt continuing the history, scrolled back',
                history('h\r\nאבגדה!?;:@&*^_~א' + PROMPT + 'b$ c\r\no1\r\n' + PROMPT + '$ ', pixel_scroll=False),
                (up(4), lambda s: s.erase_last_command()),
            ),
            (
                'erased command in the history, continued by the prompt row',
                history(PROMPT + '$ c\r\nאבגדה1 2' + PROMPT + '$ \x1b[3H\n\n', pixel_scroll=False),
                (lambda s: s.erase_last_command(),),
            ),
            (
                'erased command in the history, continued by the prompt row, auto',
                history(AUTO + PROMPT + '$ c\r\nabcdeאב' + PROMPT + '$ \x1b[3H\n\n'),
                (lambda s: s.erase_last_command(),),
            ),
            (
                # the window the paragraph is resolved in moves down its rows, cutting its first strong char off
                'paragraph clipped by the window',
                clipped,
                ('\r\nq0', '\r\nq1'),
            ),
            ('paragraph clipped by the window, paused before a frame', clipped, ('\r\nq0', lambda s: (pb(s, '\r\nq1'), pause(s)), unpause)),
            ('ring', ring, (up(2), '\x1b[4H\n')),
            ('ring, scrolled past it', ring, (up(10), '\x1b[4H\n')),
            (
                # the row below the view gains a record, its cells unchanged
                'recorded below the view',
                history(AUTO + 'h\r\n1 2 3 4 5 6 7 8\x1b[8lאבגדה', pixel_scroll=False),
                (up(), '\x1b[3Hאבגדה', '\x1b[8h\x1b[3Hאבגדה'),
            ),
            (
                # the row below the view is written back to what the paragraph was last resolved from below the view, after the
                # rows on view were rendered with it on view
                'rewritten below the view after it was on view',
                history(AUTO + 'h\r\nq\r\n1 2 3 4 5 abcdexy', pixel_scroll=False),
                (up(2), '\x1b[2Habcde', down, '\x1b[2Hאבגדה', up(), '\x1b[2Habcde'),
            ),
            (
                # the paused walk reads the row below the view, while the rows on view keep the levels of the last frame
                'written below the view, paused before a frame',
                history(AUTO + 'h\r\nq\r\n1 2 3 4 5 abcdexy', pixel_scroll=False),
                (up(2), lambda s: (pb(s, '\x1b[2Hאבגדה'), pause(s)), unpause),
            ),
            (
                # the alternate screen renders the history rows without the rows below the view of the main one
                'back from the alternate screen, scrolled back',
                history(AUTO + '1 2 3 4 5 6 7 8 9 0 1 2 3אבגדהx', pixel_scroll=False),
                (up(3), '\x1b[2Hאבגדה', lambda s: (pb(s, '\x1b[?1049h'), s.scroll(4, True)), lambda s: (pb(s, '\x1b[?1049l'), s.scroll(4, True))),
            ),
            ('cleared under a new base', lambda: self.screen(AUTO, text='abc ' + A), ('\x1b[2J\x1b[H' + SCP_RTL + A + ' abc',)),
        ):
            with self.subTest(name):
                self.assert_frames_match_replay(build, *ops)
        # a history line number reused after its line was popped back onto the screen
        for paused in (False, True):
            with self.subTest('history number reused', paused=paused):
                o = history('א2 3ב\r\nh\r\ni\r\nj', pixel_scroll=False)
                ops = [up(), lambda s: s.reverse_scroll(1, True), '\x1b[Hא2 3(\x1b[3H\n', up()]
                if paused:
                    ops[1:1] = [pause]
                    ops[-1:-1] = [unpause]
                self.assert_frames_match_replay(o, *ops)

    def test_idle_uploads(self):
        # scrolled back, a paragraph that continues below the view is resolved once, not on every upload
        s = self.screen(cols=5, lines=3, scrollback=50, pixel_scroll=False)
        pb(s, 'h\r\n' * 3 + 'אבגדה' * 4 + '\r\n' + 't\r\n' * 6)
        s.scroll(9, True)
        frame(s)
        self.ae((order(s, 0), order(s, 1)), (None, (4, 3, 2, 1, 0)))
        frame(s)
        self.ae(s.test_bidi_resolved(), 0)
        # a bidi line written and erased leaves no record, and the uploads stop walking the rows, though the history is not empty
        s = self.create_screen(cols=10, lines=3, scrollback=10, options={'pixel_scroll': False})
        pb(s, 'a\r\nb\r\nc\r\n\x1b[8h' + MIXED + '\x1b[8l\r\x1b[2K')
        self.assertGreater(s.historybuf.count, 0)
        frame(s)
        self.assertIsNone(s.test_bidi_resolved())
        # a recorded line in the history is reordered when scrolled back, and the uploads walk the rows only then
        pb(s, '\x1b[8h' + MIXED + '\x1b[8l\r\n\r\n\r\n')
        frame(s)
        self.assertIsNone(s.test_bidi_resolved())
        s.scroll(1, True)
        frame(s)
        self.ae(order(s)[:6], (0, 1, 2, 5, 4, 3))
        self.assertIsNotNone(s.test_bidi_resolved())
        s.scroll(1, False)
        pb(s, '\x1b[3J')
        s.scroll(1, True)
        frame(s)
        self.assertIsNone(s.test_bidi_resolved())
        # with pixel scrolling the leading row shows history line 0: a recorded line far above it does not keep the walk on
        s = self.create_screen(cols=120, lines=50, scrollback=1000, options={'pixel_scroll': True})
        pb(s, '\x1b[8h' + MIXED + '\x1b[8l\r\n' + 'plain\r\n' * 300)
        frame(s)
        frame(s)
        self.assertIsNone(s.test_bidi_resolved())
        # but the tail of a recorded paragraph in that row is still reordered
        s = self.create_screen(cols=5, lines=2, scrollback=10, options={'pixel_scroll': True})
        pb(s, '\x1b[8hאבגדהוזח\x1b[8l\r\nx\r\ny')
        frame(s)
        self.ae((str(s.historybuf.line(0)), s.test_bidi_v2l(0)), ('וזח', (2, 1, 0, 3, 4)))
        # a row without a record continuing a recorded history line is laid out with it
        s = self.create_screen(cols=5, lines=1, scrollback=10, options={})
        pb(s, '\x1b[8hאבגדהab\x1b[8l\r\x1b[2K12 34')
        self.ae((s.historybuf.count, s.test_bidi_line_record(0)[0], visual(s)), (1, 0, '34 12'))

    def test_unchanged_frames_reuse_the_maps(self):
        # a frame with nothing changed since the last maps no paragraph again and leaves the maps and the rendered levels as they
        # were; an edit of one row maps only its paragraph again
        s = self.screen('אבג def\r\nxyz\r\nab גדה 12', cols=10, lines=3, pixel_scroll=False)

        def maps():
            return [order(s, y) for y in range(s.lines)], [s.test_render_levels(y) for y in range(s.lines)]

        frame(s)
        self.ae(s.test_bidi_resolved(), 3)
        before = maps()
        frame(s)
        self.ae((s.test_bidi_resolved(), s.test_bidi_walk_reused()), (0, True))
        self.ae(maps(), before)
        self.assertTrue(s.test_bidi_walk_matches_full())
        pb(s, '\x1b[3;1Hאב')
        frame(s)
        self.ae((s.test_bidi_resolved(), s.test_bidi_walk_reused()), (1, True))
        self.ae(maps()[0][:2], before[0][:2])
        self.assertNotEqual(order(s, 2), before[0][2])
        self.assertTrue(s.test_bidi_walk_matches_full())
        # a resize or a scroll moves the rows, and the next frame maps every paragraph again
        s.resize(4, 10)
        frame(s)
        self.ae((s.test_bidi_resolved(), s.test_bidi_walk_reused()), (4, False))
        frame(s)
        self.assertTrue(s.test_bidi_walk_reused())
        pb(s, '\x1b[4;1H' + 'ab גד\r\n' * 3)
        frame(s)
        s.scroll(1, True)
        frame(s)
        self.assertIsNotNone(s.test_bidi_resolved())
        self.assertFalse(s.test_bidi_walk_reused())

    def test_idle_uploads_with_output_below_the_view(self):
        # scrolled back, the rows below the view stay dirty, as they are not rendered: the paragraph they continue is resolved
        # again only when one of them changes, and each frame is what a new screen given the same input shows
        def build():
            s = self.screen(cols=5, lines=3, scrollback=10, pixel_scroll=False)
            pb(s, 'h\r\n' + 'אבגדה' * 4)
            frame(s)
            return s

        s, ops = build(), []
        # written in place, written on into a new line that pushes one into the history, written again, back at the bottom
        for op in (lambda s: s.scroll(1, True), '\x1b[3Hab אב', 'גד', '\x1b[3Hא', lambda s: s.scroll(2, False)):
            ops.append(op)
            apply(s, op)
            resolved = []
            for _ in range(3):
                frame(s)
                resolved.append(s.test_bidi_resolved())
            self.ae(resolved, [1, 0, 0])
            f = build()
            for o in ops:
                apply(f, o)
            self.ae(frame(s), frame(f))
            self.ae(orders(s), orders(f))

    def test_below_the_view_after_text_cache_gc(self):
        # the text cache renumbers the cells that hold a cluster: a row below the view changed to text that takes the index
        # its old text had before the collection is still a row the next resolve must read
        def build(gc):
            s = self.screen(AUTO, cols=5, lines=3, scrollback=10, pixel_scroll=False)
            pb(s, 'b\u0301\x1b[2J\x1b[H' * gc + 'x\r\ny\r\nאבגדה' + 'א\u05b8')
            s.scroll(1, True)
            frame(s)
            if gc:
                s.garbage_collect_text_cache()
            pb(s, '\x1b[3;1Ha\u0301')
            frame(s)
            return s

        s, f = build(True), build(False)
        self.ae(s.test_bidi_resolved(), f.test_bidi_resolved())
        s.scroll(1, False)
        f.scroll(1, False)
        self.ae(frame(s), frame(f))

    def test_split_below_the_view_reshaped_when_scrolled_into_view(self):
        # scrolled back, the last row on view loses its soft wrap: the row below it, off view, is then a paragraph of its own,
        # left-to-right, and is shaped so once shown
        def build():
            s = self.screen(AUTO, cols=5, lines=3, scrollback=10, pixel_scroll=False)
            pb(s, 'x0\r\nx1\r\nאבגדהab אב')
            self.ae((str(s.line(1)), str(s.line(2)), s.linebuf.is_continued(2)), ('אבגדה', 'ab אב', True))
            return s

        self.assert_frames_match_replay(build, lambda s: s.scroll(1, True), '\x1b[2;5Hו', lambda s: s.scroll(1, False))

    def test_paused_frames_show_the_snapshot(self):
        # the split changes row 1 from ב12( to (12ב: paused frames show the snapshot, so a split made during the pause shows once unpaused
        fresh = self.fresh_sprites('(12ב')
        for split_before_pause in (False, True):
            with self.subTest(split_before_pause=split_before_pause):
                s = self.paragraph('אבגדה', '(12ב')
                self.ae(visual(s, 1), 'ב12(')
                self.assertNotEqual(sprites(s, 1), fresh)
                if split_before_pause:
                    self.split(s)
                s.pause_rendering(True, 1000)
                if not split_before_pause:
                    self.split(s)
                self.ae(visual(s, 1), '(12ב' if split_before_pause else 'ב12(')
                self.ae(s.linebuf.dirty_lines(), [0])  # paused frames shape the snapshot's rows, not the live ones
                s.pause_rendering(False)
                self.ae((visual(s, 1), sprites(s, 1)), ('(12ב', fresh))
        # no live frame runs, so only the snapshot's own stamp can give a paused frame maps
        for stamped in (False, True):
            s = self.create_screen(cols=10, lines=5, scrollback=5, options={})
            if stamped:
                pb(s, '\x1b[8h')
            draw_coloured(s, MIXED)
            logical = [s.cell_style_idx(0, x) for x in range(6)]
            s.pause_rendering(True, 1000)
            self.ae(styles(s)[:6], [logical[x] for x in ((0, 1, 2, 5, 4, 3) if stamped else range(6))])

    def test_paused_frame_matches_live(self):
        # a paragraph crossing the edge of the view is laid out with its rows off view, also by a paused frame
        for name, text, back in (
            ('starts above the view', 'אבגדה12 (3)\r\nx', 0),
            ('auto, strong char above the view', AUTO + 'אבגדהabc 12 d\r\nx', 0),
            ('auto, strong char below the view', 'h\r\ni\r\nj\r\nk\r\n' + AUTO + '12 34 56 78 9אבגד', 2),
        ):
            for pixel_scroll in (False, True):
                with self.subTest(name, pixel_scroll=pixel_scroll):
                    s = self.screen(cols=5, lines=3, scrollback=20, pixel_scroll=pixel_scroll)
                    pb(s, text)
                    s.scroll(back, True)
                    live, live_orders = frame(s), orders(s)
                    self.assertTrue(any(live_orders))
                    s.pause_rendering(True, 1000)
                    self.ae((frame(s), orders(s)), (live, live_orders))
                    s.pause_rendering(False)
                    self.ae((frame(s), orders(s)), (live, live_orders))
        # paused right after scrolling back to history rows evicted from the history render cache since they were rendered
        text = '\r\n'.join(['אב 12', 'ab', 'אבגדה12 (3)'] * 4)
        fresh = self.screen(cols=5, lines=3, scrollback=20, pixel_scroll=False)
        pb(fresh, text)
        fresh.scroll(5, True)
        s = self.screen(cols=5, lines=3, scrollback=20, pixel_scroll=False)
        pb(s, text)
        for n, back in ((5, True), (4, True), (4, False)):
            frame(s)
            s.scroll(n, back)
        s.pause_rendering(True, 1000)
        self.ae(frame(s), frame(fresh))

    def selected(self, s, start, end):
        # the visual columns lit on row 0 by a new frame when logical cells start..end are selected; no other row may be lit
        s.clear_selection()
        s.start_selection(start, 0)
        s.update_selection(end, 0)
        return self.lit(s)

    def lit(self, s):
        frame(s)
        raw = s.current_selections()
        offset = len(raw) // s.columns - s.lines  # the extra leading render row of pixel scroll
        rows = [list(raw[s.columns * (y + offset) : s.columns * (y + offset + 1)]) for y in range(s.lines)]
        self.ae(rows[1:], [[0] * s.columns] * (s.lines - 1))
        return [x for x, b in enumerate(rows[0]) if b]

    def test_selection(self):
        # NSI's map is not its own inverse: logical 0 lights visual 4 and logical 3 visual 0
        s = self.screen(cols=5, text=NSI)
        self.ae([self.selected(self.screen(text=MIXED), 3, 4), self.selected(s, 0, 0), self.selected(s, 3, 3)], [[4, 5], [4], [0]])
        self.ae(self.selected(self.screen(AUTO, text=A), 0, 2), [7, 8, 9])
        # extra cursors on logical cells 3 and 0 of row 0 and 3 of row 1
        s = self.screen(text=MIXED)
        pb(s, '\x1b[>1;2:1:4;2:1:1;2:2:4; q')
        frame(s)
        raw, c = s.current_selections(), EXTRA_CURSOR
        offset = len(raw) // s.columns - s.lines
        self.ae(list(raw[10 * offset : 10 * offset + 20]), [c, 0, 0, 0, 0, c, 0, 0, 0, 0] + [0, 0, 0, c, 0, 0, 0, 0, 0, 0])
        # beam extra cursors on logical cells 3, 5 and 0 are at the visual column of their own cell, RTL ones included
        pb(s, '\x1b[>0;4 q\x1b[>2;2:1:4;2:1:6;2:1:1 q')
        frame(s)
        raw, b = s.current_selections(), 2 * EXTRA_CURSOR
        self.ae(list(raw[10 * offset : 10 * offset + 10]), [b, 0, 0, b, 0, b, 0, 0, 0, 0])

    def drawn(self, s, x, shape=CURSOR_BLOCK):
        s.cursor_position(1, x + 1)
        frame(s)
        return s.test_cursor_x(shape)[0]

    def test_beam_on_odd_level_cells(self):
        # Every cursor shape is drawn at the visual column of the cursor's cell, the cell after the text included. A beam on an
        # odd-level cell is on the left edge of the column past the cell's full width, in the last column on the cell's own edge.
        def shapes(s, x):
            return tuple(self.drawn(s, x, shape) for shape in (CURSOR_BLOCK, CURSOR_UNDERLINE, CURSOR_HOLLOW, CURSOR_BEAM))

        s = self.screen(text=MIXED)
        self.ae([shapes(s, x) for x in (0, 1, 3, 4, 5, 6)], [(0,) * 4, (1,) * 4, (5, 5, 5, 6), (4, 4, 4, 5), (3, 3, 3, 4), (6,) * 4])
        self.ae(shapes(self.screen(cols=6, text=MIXED), 3), (5, 5, 5, 5))
        s = self.screen(text='a')
        draw_multicell(s, 'א', width=2)
        draw_multicell(s, 'ב', width=2)
        self.ae([shapes(s, x) for x in (1, 2, 3, 4)], [(3, 3, 3, 5), (3, 3, 3, 5), (1, 1, 1, 3), (1, 1, 1, 3)])
        # until the next frame, maps sized for an old width are not used
        s = self.screen(cols=20, lines=3, text=''.join(chr(0x5D0 + i) for i in range(20)))
        self.ae(self.drawn(s, 2), 17)
        s.resize(3, 10)
        s.cursor_position(1, 3)
        self.ae(s.test_cursor_x(CURSOR_BLOCK)[0], 2)
        self.ae(self.drawn(s, 2), 7)

    def test_block_on_a_wide_char_across_a_region_edge(self):
        # the block on a wide char across the left edge of a region narrower than the screen covers the char's two visual columns
        s = self.screen('\x1b]2254;a=d:i=1:x=6:y=1:w=10:h=3\x1b\\\x1b[1;1Hab' + 'אב' + '😀' + 'גד', cols=20, lines=4, pixel_scroll=False)
        self.ae(self.drawn(s, 4), 4)
        self.ae(order(s)[4:6], (4, 5))

    def test_ime_anchor_follows_visual_caret(self):
        s = self.screen(text=MIXED)
        s.cursor_position(1, 4)
        frame(s)
        self.ae(s.test_cursor_x(CURSOR_BLOCK)[1], 5)
        # an edit that reorders the row moves the caret's cell, the anchor is read after the upload
        s.draw('x')
        frame(s)
        self.ae((s.cursor.x, s.test_cursor_x(CURSOR_BLOCK)), (4, (5, 5)))

    def test_click_on_a_reordered_row(self):
        # a click lands on the logical cell shown under it; the left half of a right-to-left cell is drawn on its right
        s = self.screen(text=MIXED)
        frame(s)
        self.ae([s.test_bidi_logical_click(x, 0, True) for x in (1, 3, 5, 6)], [(1, True), (5, False), (3, False), (6, True)])
        self.ae(s.test_bidi_logical_click(5, 0, False), (3, True))
        self.ae(s.test_bidi_logical_click(5, 1, True), (5, True))  # a row without levels
        # NSI is shown 12 בא: the digits are at an even level, and its map is not its own inverse
        s = self.screen(cols=5, text=NSI)
        frame(s)
        self.ae([s.test_bidi_logical_click(x, 0, True) for x in range(5)], [(3, True), (4, True), (2, False), (1, False), (0, False)])

    def test_hyperlink_target_at_the_hovered_column(self):
        # the hyperlink target is drawn at the column the pointer is over, the visual column of the hovered logical cell
        s = self.screen(text='abc')
        pb(s, '\x1b]8;;https://example.invalid/\x1b\\' + A + '\x1b]8;;\x1b\\')
        frame(s)
        w = create_mock_window(s)
        for logical, shown in ((3, 5), (4, 4), (5, 3)):
            send_mock_mouse_event_to_window(w, -1, 0, False, logical, 0, False, True)
            self.ae(s.test_hyperlink_under_mouse(), (shown, 0))

    def test_maps_follow_the_frame(self):
        # without pixel scroll the alternate screen has as many render rows as the main one: only the source and its stamp tell the maps apart
        s = self.screen(text=MIXED, pixel_scroll=False)
        self.ae((self.selected(s, 3, 4), s.test_cursor_x(CURSOR_BLOCK)[0]), ([4, 5], 6))
        pb(s, '\x1b[?1049h\x1b[H')
        s.draw(MIXED)
        self.ae((self.selected(s, 3, 4), s.test_cursor_x(CURSOR_BLOCK)[0]), ([3, 4], 6))
        # once stamped too, the alternate screen has no maps of its own until its next frame, nor the main one after
        pb(s, '\x1b[8h\x1b[H' + MIXED + '\x1b[1;4H')
        self.ae(s.test_cursor_x(CURSOR_BLOCK)[0], 3)
        pb(s, '\x1b[?1049l\x1b[1;4H')
        self.ae(s.test_cursor_x(CURSOR_BLOCK)[0], 3)
        # force_ltr set at runtime: the next frame is uploaded in logical order, has no maps and redraws the selection
        s = self.screen(text=MIXED)
        self.ae(self.selected(s, 3, 4), [4, 5])
        self.set_options({'force_ltr': True})
        frame(s)
        self.ae((order(s), s.test_cursor_x(CURSOR_BLOCK)[0], s.is_selection_dirty()), (None, 6, True))
        self.ae(self.lit(s), [3, 4])

    def test_force_ltr_stores_nothing_and_keeps_the_program_modes(self):
        def reload(s):
            # a reload marks every row dirty, which set_options alone does not
            s.disable_ligatures = 'always'
            s.disable_ligatures = 'never'

        def modes(s):
            s.callbacks.clear()
            pb(s, '\x1b[8$p\x1b[?2501$p')
            return tuple(int(m) for m in re.findall(rb';(\d)\$y', s.callbacks.wtcbuf))

        text = 'abc' + 'אבג' + '\r\n\u200ex'
        for set_first in (True, False):
            if set_first:
                s = self.screen()
                self.set_options({'force_ltr': True})
            else:
                s = self.screen(force_ltr=True)
                pb(s, '\x1b[8h')
            reload(s)
            pb(s, text)
            self.ae((s.test_bidi_line_record(0), s.cpu_cells(1, 0)['text'], modes(s), order(s)), ((0, False, False), 'x', (4, 4), None))
            self.set_options({'force_ltr': False})
            reload(s)
            pb(s, '\r\n\u200ey')
            self.ae((modes(s), s.test_bidi_line_record(2), s.cpu_cells(2, 0)['text']), ((1, 2), (1, False, False), 'y'))
        # set at runtime it keeps no record on a row left without text: text written to the row under it takes none, nor do the
        # rows written with bidi mode off in the paragraph the row ends once force_ltr is cleared, here continuing a history line
        with self.subTest('text written under it'):
            s = self.screen(SCP_RTL + '\x1b[2H' + A)
            pb(s, '\x1b[2K')
            self.set_options({'force_ltr': True})
            reload(s)
            pb(s, '\x1b[2Habc')
            self.set_options({'force_ltr': False})
            reload(s)
            self.ae((s.test_bidi_line_record(1), visual(s, 1)), ((0, False, False), 'abc'))
        with self.subTest('paragraph the row ends'):
            s = self.screen(SCP_RTL + A + '\r\n\x1b[8l' + 'abcdefgh!!' * 2 + '\x1b[8h' + A + '\r\n\x1b[8lz', lines=3, scrollback=10)
            frame(s)
            self.assertIsNotNone(order(s, 0))
            self.set_options({'force_ltr': True})
            pb(s, '\x1b[2H\x1b[2K')
            frame(s)
            self.set_options({'force_ltr': False})
            pb(s, '\x1b[8l\x1b[Hx')
            self.ae((orders(s)[0], s.test_bidi_line_record(1)), (None, (0, False, False)))

    def test_runs_shaped_in_resolved_direction(self):
        # ( between R letters resolves to an odd level, so the frame shapes it right to left, mirrored, unlike force_ltr
        text = 'abc א(ב'
        plain = self.fresh_sprites(text, cols=10, force_ltr=True)
        s = self.screen(text=text)
        self.ae(visual(s), 'abc ב(א')
        shaped = sprites(s)
        self.ae(shaped[:4], plain[:4])
        self.assertNotEqual(shaped[5], plain[5])

    def test_bdsm_reset_keeps_records(self):
        # CSI 8 l changes only what rows written afterwards are stamped with: overwriting a stamped row keeps its stamp
        s = self.screen(text=NSI)
        pb(s, '\x1b[2H' + NSI)
        before = uploaded(s, 0), uploaded(s, 1)
        self.ae((visual(s, 0), visual(s, 1)), ('12 בא',) * 2)
        plain, reordered = self.guessed_sprites(NSI, cols=10), self.fresh_sprites(NSI, cols=10)
        self.assertNotEqual(plain, reordered)
        pb(s, '\x1b[8l')
        self.ae((uploaded(s, 0), uploaded(s, 1)), before)
        pb(s, '\x1b[H' + NSI + '\x1b[4H' + NSI)
        self.ae((visual(s, 0), sprites(s, 0)), ('12 בא', reordered))
        self.ae((orders(s)[3], sprites(s, 3)), (None, plain))

    def test_paragraph_direction(self):
        # P2-P3: the first strong char (R, AL or L; not EN or AN) sets the direction under ?2501; the blanks of an RTL paragraph take
        # its level (L1), so its text is right-aligned
        for text, cols, seqs, rows in (
            ('שלום!', 10, (AUTO,), ['     !םולש']),
            ('שלום!', 10, (), ['םולש!']),
            ('אבג abc', 10, (AUTO,), ['   abc גבא']),
            ('abc אבג', 10, (AUTO,), ['abc גבא']),
            ('12 אב ab', 10, (AUTO,), ['  ab בא 12']),
            ('(12 aאבגדה', 5, (AUTO,), ['(12 a', 'הדגבא']),
            ('אבגדהabcde', 5, (AUTO,), ['הדגבא', 'abcde']),
            ('مرحبا!', 10, (AUTO,), ['    !ابحرم']),
            ('١٢٣ 45!', 10, (AUTO,), ['١٢٣ 45!']),
            ('שלום abc', 10, (SCP_LTR,), ['םולש abc']),
            ('שלום abc', 10, (AUTO, '\x1b[?2501l'), ['םולש abc']),
            ('abc def', 10, (SCP_RTL,), ['   abc def']),  # SCP 2 alone: an RTL paragraph of Latin text
            ('abc def', 10, (AUTO, SCP_RTL), ['abc def']),  # with ?2501 the first strong char decides
            (A + ' abc', 10, (AUTO, SCP_RTL), ['   abc גבא']),
            ('12 34', 10, (AUTO, SCP_RTL), ['     34 12']),  # and a line with none takes SCP's
            ('abcd efg', 5, (SCP_RTL,), [' abcd', '  efg']),  # L1 resets the space ending row 0 to the paragraph level
        ):
            with self.subTest(text, seqs=seqs):
                s = self.screen(*seqs, cols=cols, text=text)
                self.ae([visual(s, y) for y in range(len(rows))], rows)
        self.assertIsNone(orders(self.screen(AUTO, text='12 34'))[0])
        self.assertIsNone(orders(self.screen(AUTO, '\x1b[8l', text='שלום abc'))[0])
        # an RTL paragraph's blank cells are drawn empty
        s = self.screen(AUTO)
        draw_coloured(s, A)
        logical = [s.cell_style_idx(0, x) for x in range(3)]
        row = uploaded(s)
        self.ae(([c[0] for c in row[:7]], all(c[0] for c in row[7:])), ([0] * 7, True))
        self.ae([c[1] >> CELL_GPU_STYLE_SHIFT for c in row[7:]], logical[::-1])

    def test_blank_rows_under_an_rtl_base(self):
        # a paragraph of one blank row has nothing for FriBidi: under an RTL base it is reversed, under LTR it has no map
        for seqs in ((SCP_RTL,), (AUTO, SCP_RTL)):
            self.ae(orders(self.screen(*seqs, text=' '))[0], tuple(range(9, -1, -1)))
        self.assertIsNone(orders(self.screen(AUTO, text=' '))[0])
        # also a blank last row of a wrapped paragraph
        s = self.screen(SCP_RTL, text='א' * 11)
        pb(s, '\x1b[2H\x1b[X')
        self.assertTrue(s.linebuf.is_continued(1))
        self.ae(orders(s)[:2], [tuple(range(9, -1, -1))] * 2)
        # the blank tail goes first, reversed, ahead of the reordered rest
        s = self.screen(SCP_RTL, text='אב中')
        self.ae(visual(s), ' ' * 6 + '中בא')
        s = self.screen(SCP_RTL, text='אב')
        draw_multicell(s, 'x', width=2)
        self.ae(visual(s), ' ' * 6 + 'xבא')

    def test_controls_change_no_paragraph_with_text(self):
        # records are stamped: toggling the controls, CSI 8 l included, re-resolves no paragraph whose first row has text
        for first in ((), (AUTO,), (SCP_RTL,)):
            with self.subTest(first=first):
                s = self.screen(*first, text=A + ' abc')
                pb(s, '\r\n' + 'abc ' + A)
                want = orders(s)
                for seq in (AUTO, '\x1b[?2501l', SCP_RTL, SCP_LTR, '\x1b[0 k', '\x1b[8l', '\x1b[8h', AUTO, SCP_RTL):
                    pb(s, seq)
                    self.ae(orders(s), want, seq)
        # an overwrite keeps the old base, and so does an EL that leaves text on the row
        s = self.screen(text='abc ' + A)
        pb(s, AUTO + SCP_RTL + '\x1b[Hב')
        self.ae(visual(s), 'בbc גבא')
        s = self.screen(text=A + ' abc')
        pb(s, AUTO + SCP_RTL + '\x1b[1;6H\x1b[K')
        self.ae(visual(s), 'גבא a')
        # a cleared line takes the new base, as does a line inserted and rewritten
        for clear in ('\x1b[2J\x1b[H', '\x1b[H\x1b[L'):
            s = self.screen(text=A + ' abc')
            pb(s, AUTO + SCP_RTL + clear + A + ' abc')
            self.ae(visual(s), '   abc גבא')

    def preedit_reference(self, text, x, preedit='xy'):
        # the row a screen that never sent CSI 8 h uploads for text with the pre-edit at x
        f = self.create_screen(cols=10, lines=5, scrollback=5, options={})
        draw_coloured(f, text)
        f.cursor_position(1, x + 1)
        self.assertTrue(any(sprites(f)))
        f.test_update_overlay_text(preedit)
        return uploaded(f)

    def test_preedit(self):
        # the pre-edit block starts at the visual column of the cursor cell and extends right, the rest of the row stays in visual order
        ref = self.preedit_reference(MIXED, 1)
        s = self.screen()
        draw_coloured(s, MIXED)
        s.cursor_position(1, 2)
        before = uploaded(s)
        self.ae(self.drawn(s, 1, CURSOR_BEAM), 1)
        s.test_update_overlay_text('xy')
        row = uploaded(s)
        self.ae((s.test_cursor_x(CURSOR_BEAM), order(s)), ((3, 1), (0, 1, 2, 5, 4, 3, 6, 7, 8, 9)))
        self.ae((row[:1] + row[3:], row[1:3]), (before[:1] + before[3:], ref[1:3]))
        # also when the cell is at an odd level
        ref = self.preedit_reference(A + ' ' + A, 7, 'xyzw')  # right-aligned there, at columns 6-9
        s = self.screen(AUTO)
        draw_coloured(s, A + ' ' + A)
        before = uploaded(s)
        s.test_update_overlay_text('xyzw')
        row = uploaded(s)
        self.ae((s.test_cursor_x(CURSOR_BEAM), row[2:6]), ((6, 2), ref[6:10]))
        self.ae((row[:2] + row[6:], order(s)), (before[:2] + before[6:], tuple(range(9, -1, -1))))
        # a block that cuts a wide character, at either edge, blanks the other half
        for seq, text, x, preedit, blanked in (('', 'a', 3, 'x', 4), ('', 'a', 5, 'x', 2), ('', 'a', 2, 'x', 6), (SCP_RTL, '', 0, 'xyz', 6)):
            s = self.screen(seq, text=text)
            for ch in A:
                draw_multicell(s, ch, width=2)
            s.cursor_position(1, x + 1)
            before = sprites(s)
            s.test_update_overlay_text(preedit)
            row = sprites(s)
            start = s.test_cursor_x()[1]
            expected = before[:start] + row[start : start + len(preedit)] + before[start + len(preedit) :]
            expected[blanked] = 0
            self.assertTrue(before[blanked])
            self.ae(row, expected)
            s.test_update_overlay_text('')
        # a zero-width pre-edit covers no cell, also beside a wide char shown at column 0
        for preedit, x in product(('́', '\u200c', RLM), (6, 7)):
            s = self.screen(SCP_RTL, cols=8, text=A + A + '好')
            s.cursor_position(1, x + 1)
            before = sprites(s)
            s.test_update_overlay_text(preedit)
            self.ae(sprites(s), before, (preedit, x))
            s.test_update_overlay_text('')
        # a right-to-left pre-edit is drawn as without bidi mode, on a row with a map or without one
        for text in ('abc ', A + ' '):
            with self.subTest(text=text):
                ref = self.preedit_reference(text, 4, A)
                s = self.screen()
                draw_coloured(s, text)
                frame(s)
                s.test_update_overlay_text(A)
                self.ae(uploaded(s)[4:7], ref[4:7])
        # a Latin row has no map: its pre-edit row is uploaded as without bidi, and the line record is left alone
        ref = self.preedit_reference('abc def', 7)
        s = self.screen(AUTO)
        draw_coloured(s, 'abc def')
        frame(s)
        record = s.test_bidi_line_record(0)
        s.test_update_overlay_text('xy')
        self.ae((s.test_cursor_x(CURSOR_BEAM), uploaded(s), order(s)), ((9, 7), ref, None))
        s.test_update_overlay_text(RLM + 'xy')
        frame(s)
        s.test_update_overlay_text('')
        self.ae((s.test_bidi_line_record(0), orders(s)[0]), (record, None))

    # The randomized differential: after every frame, the cell data uploaded for a screen that is rendered after each operation
    # equals that of a fresh screen given the same operations and rendered once.
    DIFF_POOL = 'אבגדהוזחט' * 3 + 'abcdefghij' * 3 + '0123456789' * 2 + '  ' * 3 + '()!.-'
    DIFF_KINDS = dict(
        zip(
            'text flip unwrap crlf lf el ed ech dch ich il dl region ri su sd resize alt back fwd pause scp auto bdsm prompt erase osc66'.split(),
            (30, 6, 4, 6, 6, 3, 2, 2, 2, 2, 6, 6, 5, 4, 3, 3, 1, 2, 3, 3, 2, 3, 3, 1, 3, 2, 8),
        )
    )

    # Writers that store text without going through the draw loop, or move a char onto a row
    WRITER_KINDS = {'cht': 3, 'decaln': 1, 'widened': 3}

    def diff_op(self, rng, s, kinds=None):
        L, C = s.lines, s.columns
        y, x, n = rng.randrange(L) + 1, rng.randrange(C) + 1, rng.randrange(1, 4)
        kinds = kinds or self.DIFF_KINDS
        kind = rng.choices(tuple(kinds), tuple(kinds.values()))[0]

        def at(data):
            data = f'\x1b[{y};{x}H'.encode() + data
            return lambda s: parse_bytes(s, data)

        if kind == 'text':
            text = ''.join(rng.choices(self.DIFF_POOL, k=rng.randrange(1, 3 * C // 2)))
            if rng.random() < 0.2:
                # an isolate written after a char is stored in its cell
                i = rng.randrange(len(text))
                text = text[: i + 1] + rng.choice(ISOLATES) + text[i + 1 :]
            return kind, at(text.encode() + (b'\r\n' if rng.random() < 0.5 else b''))
        if kind == 'flip':
            return kind, lambda s, ch=rng.choice('אa'): parse_bytes(s, f'\x1b[{y};1H{ch}'.encode())
        if kind == 'unwrap':
            # a char written over the last cell of a row drops its soft wrap, which splits a paragraph below that row
            return kind, lambda s, ch=rng.choice('אa1 '): parse_bytes(s, f'\x1b[{y};{s.columns}H{ch}'.encode())
        if kind == 'crlf':
            return kind, at(b'\r\n')
        if kind == 'lf':
            return kind, lambda s: parse_bytes(s, f'\x1b[{s.lines};1H\n'.encode())
        if kind == 'el':
            return kind, at(f'\x1b[{rng.randrange(3)}K'.encode())
        if kind == 'ed':
            return kind, at(f'\x1b[{rng.randrange(4)}J'.encode())
        if kind in ('ech', 'dch', 'ich'):
            return kind, at(f'\x1b[{n}{"XP@"[("ech", "dch", "ich").index(kind)]}'.encode())
        if kind in ('il', 'dl'):
            return kind, at(f'\x1b[{n}{"LM"[kind == "dl"]}'.encode())
        if kind in ('region', 'ri'):
            top = rng.randrange(1, L)
            bottom = rng.randrange(top + 1, L + 1)
            move = f'\x1b[{bottom};1H\x1bD' if kind == 'region' else f'\x1b[{top};1H\x1bM'
            data = f'\x1b[{top};{bottom}r{move * n}\x1b[r'.encode()
            return kind, lambda s: parse_bytes(s, data)
        if kind in ('su', 'sd'):
            top = rng.randrange(1, L)
            data = f'\x1b[{top};{L}r\x1b[{n}{"ST"[kind == "sd"]}\x1b[r'.encode()
            return kind, lambda s: parse_bytes(s, data)
        if kind == 'resize':
            lines, cols = rng.randrange(4, 8), rng.randrange(6, 11)
            return kind, lambda s: s.resize(lines, cols)
        if kind == 'alt':
            data = rng.choice((b'\x1b[?1049h', b'\x1b[?1049l'))
            return kind, lambda s: parse_bytes(s, data)
        if kind in ('back', 'fwd'):
            # the alternate screen has no scrollback to scroll
            return kind, lambda s: s.is_main_linebuf() and s.scroll(n, kind == 'back')
        if kind == 'pause':
            pause = rng.random() < 0.5
            return kind, lambda s: s.pause_rendering(pause, 1000000)
        if kind == 'scp':
            data = rng.choice((SCP_RTL, SCP_LTR, '\x1b[0 k')).encode()
            return kind, lambda s: parse_bytes(s, data)
        if kind == 'auto':
            data = rng.choice((AUTO, '\x1b[?2501l')).encode()
            return kind, lambda s: parse_bytes(s, data)
        if kind == 'prompt':
            return kind, at((PROMPT + '$ ' + ''.join(rng.choices(self.DIFF_POOL, k=n))).encode() + b'\r\n')
        if kind == 'erase':
            return kind, lambda s: s.erase_last_command()
        if kind == 'cht':
            return kind, at(f'\x1b[{n}I'.encode())
        if kind == 'decaln':
            return kind, lambda s: parse_bytes(s, b'\x1b#8')
        if kind == 'widened':
            # a narrow char in the last column widened by VS16 moves to the next row
            return kind, lambda s: parse_bytes(s, f'\x1b[{y};{s.columns}H\u263a\ufe0f'.encode())
        if kind == 'osc66':
            # a scaled cell over two or three rows, or a multicell of up to three columns holding mixed text, then text
            if rng.random() < 0.5:
                size, k = f's={rng.randrange(2, 4)}', rng.randrange(1, 3)
            else:
                size, k = f'w={rng.randrange(1, 4)}', rng.randrange(1, 5)
            text = ''.join(rng.choices('אבגדabcd12', k=k))
            tail = ''.join(rng.choices(self.DIFF_POOL, k=rng.randrange(6)))
            return kind, at(f'\x1b]66;{size};{text}\x07{tail}'.encode())
        data = b'\x1b[8l' if rng.random() < 0.3 else b'\x1b[8h'
        return kind, lambda s: parse_bytes(s, data)

    # An auto-direction paragraph over four rows, which an edit of its first cell turns from LTR to RTL and back
    FLIP_START = '\x1b[?2501h\x1b[2;1Habc 12 אב de fg 34 hi ג jk lm\r\n'.encode()

    # An auto-direction paragraph of thirteen rows, longer than two screens, which scrolls its start into the scrollback
    LONG_START = '\x1b[?2501h' + '\u05d01234567' + '12 (3) 4' * 12 + '\r\n'

    def differential(self, seed, count, long_paragraph=False):
        rng = random.Random(seed)

        start = self.LONG_START.encode() if long_paragraph else self.FLIP_START

        def new():
            s = self.screen(cols=8, lines=6, scrollback=2000)
            parse_bytes(s, start)
            return s

        def replay():
            # not kept by the test base, which would hold every one until the test ends
            c = Callbacks()
            f = Screen(c, 6, 8, 2000, 10, 20, 0, c)
            c.color_profile = f.color_profile
            parse_bytes(f, b'\x1b[8h' + start)
            return f

        def flip(ch):
            return 'flip', lambda s: parse_bytes(s, f'\x1b[2;1H{ch}'.encode())

        # a long paragraph's start is in the history: the window it is resolved in takes it in when the view goes back and
        # drops it again as output pushes the rows down
        def lf(s):
            parse_bytes(s, f'\x1b[{s.lines};1H\n'.encode())

        fixed = [('back', lambda s: s.scroll(2, True)), ('lf', lf), ('lf', lf), ('lf', lf)] if long_paragraph else []
        fixed += [flip('\u05d0'), flip('a')]
        s, ops = new(), []
        for i in range(count):
            if i < len(fixed):
                name, op = fixed[i]
            else:
                name, op = self.diff_op(rng, s)
            op(s)
            ops.append(op)
            got = frame(s)
            f = replay()
            for o in ops:
                o(f)
            self.ae(got, frame(f), f'seed {seed}, op {i} ({name})')
            self.ae(f.test_verify_styles(), [], f'seed {seed}, op {i} ({name})')

    def test_random_differential(self):
        for seed in range(15):
            self.differential(seed, 250)
        for seed in range(100, 104):
            self.differential(seed, 250, long_paragraph=True)

    def test_unreordered_line_shaped_left_to_right(self):
        # digits of an RTL script have bidi class EN: no reordering, so the frame passes no levels, and shaping must not
        # guess a direction from the text
        digits = '\u06f1\u06f2\u06f3'
        alone = [sprites(self.screen(text=ch, cols=3))[0] for ch in digits]
        shaped = sprites(self.screen(text=f'n {digits} m', cols=10))[2:5]
        self.ae(shaped, alone)

    def test_paragraph_with_a_placeholder_shaped_as_without_bidi(self):
        # a paragraph with an image placeholder is not resolved: its text is shaped as without bidi mode, scaled text on every
        # row it covers, here also the row below, a paragraph of its own
        def draw(x):
            x.draw(chr(0x10EEEE))
            draw_multicell(x, 'שלום', scale=2)
            x.draw('۱۲۳')

        with self.subTest('scaled'):
            s, plain = self.bidi_and_plain(draw, cols=12, lines=4)
            self.ae([self.bitmaps(s, y) for y in (0, 1)], [self.bitmaps(plain, y) for y in (0, 1)])
        # also with the placeholder and the Hebrew on different rows of the paragraph
        for text, cols, rows in ((chr(0x10EEEE) + ' ' + A + ' abc', 12, 1), ('abcd' + chr(0x10EEEE) + A + ' x', 5, 2)):
            with self.subTest(text=text):
                s, plain = self.bidi_and_plain(lambda x: x.draw(text), cols=cols)
                seen = orders(s)[:rows], [sprites(s, y) for y in range(rows)]
                self.ae(seen, ([tuple(range(cols))] * rows, [sprites(plain, y) for y in range(rows)]))

        # such a line written with bidi mode off is shaped as on a screen that never sent CSI 8 h
        def draw_after_reset(x):
            x.draw('abc')
            pb(x, '\x1b[8l\x1b[3;1H' + chr(0x10EEEE))
            draw_multicell(x, 'x', scale=2)
            x.draw('שלום مرحبا')

        s, plain = self.bidi_and_plain(draw_after_reset, cols=20)
        self.ae([self.bitmaps(s, y) for y in (2, 3)], [self.bitmaps(plain, y) for y in (2, 3)])

    def test_row_left_without_its_placeholder(self):
        # a row no longer holding the placeholder its flag was set for is laid out as a fresh one
        for clear in ('\x1b[2K', '\x1b[12X', ''):
            with self.subTest(clear=clear):
                s = self.screen(cols=12, lines=2)
                pb(s, chr(0x10EEEE) + ' x')
                frame(s)
                pb(s, '\x1b[H' + clear + A + ' abc')
                fresh = self.screen(cols=12, lines=2, text=A + ' abc')
                self.ae((orders(s)[0], sprites(s)), (orders(fresh)[0], sprites(fresh)))

    def test_line_left_without_text_by_a_scaled_char(self):
        # A line left without text by removing a scaled char through its other row, or in the history, has no record: text
        # written to it later is laid out as on a fresh screen, with bidi mode off or on
        s2 = '\x1b]66;s=2;א\x07'
        for lines, data, text in (
            (5, s2 + '\x1b[8l\x1b[2;1H\x1b[2K', A + ' abc'),
            (3, '\x1b[2;1H' + s2 + '\x1b[3;1H\n\n\x1b[8l\x1b[1;1H\x1b[2K\x1b[+T', A + ' abc'),
            # a wide char written in place of a one-cell char in the last column wraps
            (5, SCP_RTL + '\x1b[1;10H\x1b]66;w=1;א\x07\x1b[8l\x1b[1;10H中\x1b[2;1H\x1b[K', A + ' abc'),
            # a char that does not fit above the bottom margin scrolls the region, the row below the margin is not written and is
            # then moved up
            (6, '\x1b[3;1H' + SCP_RTL + s2 + '\x1b[8l\x1b[1;3r\x1b[3;1H\x1b]66;s=2;zz\x07\x1b[r\x1b[3M', A + ' abc'),
        ):
            for upload in (False, True):
                with self.subTest(data=data, upload=upload):
                    s, plain = self.screen(data, lines=lines), self.create_screen(cols=10, lines=lines, options={})
                    if upload:
                        frame(s)
                    for x in (s, plain):
                        pb(x, '\x1b[1;1H' + text)
                    seen = [([x.cpu_cells(0, c)['text'] for c in range(10)], orders(x)[0], visual(x)) for x in (s, plain)]
                    self.ae(seen[0], seen[1])
        # a char written over the only char of a line leaves it holding text, with its record
        s = self.written(SCP_RTL + s2 + '\x1b[8l\x1b[1;1Hz', lines=5)
        self.ae((s.test_bidi_line_record(0), visual(s)), ((1, True, False), '         z'))

    def test_paragraph_base_from_its_first_recorded_row(self):
        # a wide char that does not fit the last column of a blank row wraps, leaving that row first in the paragraph with no
        # record: the base comes from the row holding the char, as when it is written there
        want = visual(self.written('\x1b[2;1H中', SCP_RTL, cols=6, lines=3), 1)
        self.ae((visual(self.written('\x1b[1;6H中', SCP_RTL, cols=6, lines=3), 1), want), ('    中', '    中'))

    def test_zero_width_char_dirties_the_row_above(self):
        # a zero width char at the start of a continuation row joins the last cell of the row above
        rli, pdi = ISOLATES[1], ISOLATES[3]
        self.assert_frames_match_replay(lambda: self.screen(cols=10, lines=3, text='abcdefghijk'), '\r' + rli + '12 34' + pdi)

    def test_cht_dirties_its_row(self):
        # CHT stores a tab cell outside the draw loop, laid out as a literal tab is
        def build():
            return self.screen(cols=20, lines=2, text='אב      גד')

        self.assert_frames_match_replay(build, '\x1b[1;3H\x1b[I')
        s, h = build(), build()
        frame(s), frame(h)
        pb(s, '\x1b[1;3H\x1b[I')
        pb(h, '\x1b[1;3H\t')
        self.ae(orders(s)[0], orders(h)[0])

    def test_row_pulled_back_into_a_recorded_paragraph(self):
        # a row without a record pulled back from the history after an upload is laid out with the recorded line it continues
        def build():
            return self.screen('אבגדהוזח\x1b[8l12 34\r\n\n\n', cols=8, lines=3, scrollback=10, pixel_scroll=False)

        self.assert_frames_match_replay(build, '\x1b[+T')
        s = build()
        frame(s)
        pb(s, '\x1b[+T')
        self.ae(visual(s), '34 12')

    def test_rows_left_without_text_take_no_older_settings(self):
        # text written with bidi mode off to a row whose record was left without text is laid out as on a screen that never
        # set bidi mode: (columns, lines, the bytes after CSI 8 h, the same bytes without the bidi controls, the text)
        widened = '\u263a\ufe0f'
        region = '\x1b[2;2H\x1b]66;s=3;aא\x07\x1b[3;4r\x1b[3;1H\u0e01\u0e33\x1b[r'
        for cols, lines, pre, plain_pre, text in (
            # written by CHT and the draw loop
            (10, 2, SCP_RTL + A + '\x1b[2K\x1b[8l', '', '\r\x1b[Iabc ' + A),
            # on a one-line screen, the row a widened char left, pulled back from the history
            (5, 1, '\x1b[1;5H' + widened + '\x1b[+T\x1b[8l', '\x1b[1;5H' + widened + '\x1b[+T', '\x1b[H' + A + ' x'),
            # the row a widened char left when its move past a scaled char scrolled a region, its soft wrap cut, as the row the
            # char went to holds a record that would lay out their paragraph
            (8, 4, region + '\x1b[8l', region, '\x1b[3;1H' + A + ' abc\x1b[3;8Hd'),
        ):
            with self.subTest(pre=pre):
                s = self.screen(pre, cols=cols, lines=lines, scrollback=10)
                plain = self.create_screen(cols=cols, lines=lines, scrollback=10, options={})
                pb(plain, plain_pre)
                for x in (s, plain):
                    pb(x, text)
                y = s.cursor.y
                seen = [([x.cpu_cells(y, c)['text'] for c in range(cols)], orders(x)[y], visual(x, y)) for x in (s, plain)]
                self.ae((seen[0], s.test_bidi_line_record(y)), (seen[1], (0, False, False)))

    def test_resize_joins_a_record_with_a_cell(self):
        # a continuation whose first char does not fit the free cell at the end of the row it joins gives that row no record:
        # the screen is as one created at the new width
        data = '\x1b[8labcdefghij\x1b[8h' + SCP_RTL + '漢אבגדהו'
        s = self.create_screen(cols=10, lines=4, options={})
        pb(s, data)
        s.resize(4, 11)
        f = self.create_screen(cols=11, lines=4, options={})
        pb(f, data)
        self.ae(*[([x.test_bidi_line_record(y) for y in (0, 1)], [visual(x, y) for y in (0, 1)]) for x in (s, f)])

    # Operations on smooth scroll regions: define one, vertical using the scrollback, full width with kept rows, narrow, or
    # horizontal, narrow or as wide as the screen; scroll one by whole cells or fractions, either way; remove one
    REGION_KINDS = {'ssr_define': 4, 'ssr_scroll': 8, 'ssr_remove': 2}
    REGION_DELTAS = (-45, -25, -20, -13, -10, -5, -3, 3, 5, 10, 13, 20, 25, 45)

    # Runs of operations, each followed by a frame or not: text left as the only text of a row, which an erase that keeps the
    # row's settings removes, then text written to the row again with other settings; the only recorded row moved out of the
    # screen by a region and back, through the scrollback or the kept rows, or its text through the kept columns
    RUN_KINDS = {'stale': 4, 'history': 3, 'kept rows': 2, 'kept columns': 3}

    def region_steps(self, rng, s, kind):
        L, C = s.lines, s.columns
        rid = rng.choice((1, 2))
        if kind == 'ssr_define':
            shape = rng.choice(('history', 'kept rows', 'narrow', 'horizontal', 'horizontal full'))
            top = 0 if shape == 'history' else rng.randrange(L)
            bottom = rng.randrange(top + 1, L + 1)
            left = rng.randrange(C - 1) if shape in ('narrow', 'horizontal') else 0
            right = rng.randrange(left + 1, C + 1) if shape in ('narrow', 'horizontal') else C
            size = right - left if shape.startswith('horizontal') else bottom - top
            args = (rid, left, top, right, bottom, rng.randrange(1, min(size, 3) + 1), shape == 'kept rows', shape.startswith('horizontal'))
            return [(f'define {shape} {args}', lambda s: s.smooth_scroll_define(*args))]
        if kind == 'ssr_scroll':
            delta = rng.choice(self.REGION_DELTAS)
            return [(f'scroll {rid} by {delta}', lambda s: s.smooth_scroll(rid, delta))]
        if kind == 'ssr_remove':
            return [(f'remove {rid}', lambda s: s.smooth_scroll_remove(rid))]
        scp = rng.choice((SCP_RTL, SCP_LTR, AUTO))
        text = rng.choice((A, MIXED, NSI, 'abc'))
        if kind == 'stale':
            y, x = rng.randrange(L) + 1, rng.randrange(C) + 1
            erase = rng.choice(('\x1b[2K', '\x1b[K', f'\x1b[{C}X', f'\x1b[{C}P'))
            again = rng.choice(('\x1b[8l', '\x1b[8h' + SCP_LTR + '\x1b[?2501l', '\x1b[8h' + SCP_RTL, '\x1b[8h' + AUTO))
            return [
                ('stale text', f'\x1b[8h{scp}\x1b[{y};1H{text}'),
                ('stale erase', f'\x1b[{y};1H{erase}'),
                ('stale again', f'{again}\x1b[{y};{x}H{rng.choice(("abc", A, "12"))}'),
            ]

        # the recorded text is the only one on the screen, and the regions defined before are removed
        def alone(y, x, text):
            return (f'{kind} text', f'\x1b[8l\x1b[2J\x1b[3J\x1b[8h{scp}\x1b[{y + 1};{x + 1}H{text}\x1b[8l')

        def define(*args):
            return (f'{kind} define', lambda s: (s.smooth_scroll_remove(1), s.smooth_scroll_remove(2), s.smooth_scroll_define(3, *args)))

        if kind == 'history':
            out = rng.choice((5, 20, 25, 45))
            steps = [alone(0, 0, text), define(0, 0, C, L), (f'out {out}', lambda s: s.smooth_scroll(3, out))]
            steps.append((f'back {out}', lambda s: s.smooth_scroll(3, -out)))
        elif kind == 'kept rows':
            top, out = rng.randrange(L - 1), rng.choice((5, 20, 25))
            steps = [alone(top, 0, text), define(0, top, C, L, rng.choice((1, 2)), True), (f'out {out}', lambda s: s.smooth_scroll(3, out))]
            steps.append((f'back {out}', lambda s: s.smooth_scroll(3, -out)))
        else:
            y, left = rng.randrange(L), rng.randrange(C - 2)
            right = rng.randrange(left + 2, C + 1)
            # two cells moved wholly into the two kept columns on the left
            out = rng.choice((17, 20))
            steps = [alone(y, left, rng.choice(('אב', 'ab', '1א'))), define(left, y, right, y + 1, 2, False, True)]
            steps.append((f'out {out}', lambda s: s.smooth_scroll(3, out)))
            steps.append((f'back {out}', lambda s: s.smooth_scroll(3, -out)))
        if rng.random() < 0.5:
            steps.append((f'{kind} remove', lambda s: s.smooth_scroll_remove(3)))
        return steps

    # Operations after which the framed screen is uploaded: a second frame with no change, a cursor move, an edit within a row
    BETWEEN_FRAMES_KINDS = {'again': 6, 'cursor': 4, 'row edit': 6}

    def between_frames_op(self, rng, s, kind):
        y, x = rng.randrange(s.lines) + 1, rng.randrange(s.columns) + 1
        if kind == 'again':
            return kind, lambda s: None
        if kind == 'cursor':
            return kind, f'\x1b[{y};{x}H'
        return kind, f'\x1b[{y};{x}H' + ''.join(rng.choices('אבab1 ', k=rng.randrange(1, s.columns - x + 2)))

    def test_frames_do_not_change_the_result(self):
        # a seeded random stream given to a screen uploaded after random operations and to one uploaded only at the end leaves
        # the same records and the same final frame. Every frame of the first leaves maps a full walk would leave.
        kinds = {**self.DIFF_KINDS, **self.WRITER_KINDS, **self.REGION_KINDS, **self.RUN_KINDS, **self.BETWEEN_FRAMES_KINDS}
        reused = []
        for seed in range(40):
            rng = random.Random(seed)
            framed, unframed = self.screen(cols=8, lines=6, scrollback=50), self.screen(cols=8, lines=6, scrollback=50)
            for x in (framed, unframed):
                self._screens_to_verify_styles.remove(x)
                parse_bytes(x, self.FLIP_START)
            done = []
            reused.append(0)
            for _ in range(120):
                kind = rng.choices(tuple(kinds), tuple(kinds.values()))[0]
                if kind in self.REGION_KINDS or kind in self.RUN_KINDS:
                    steps = self.region_steps(rng, framed, kind)
                elif kind in self.BETWEEN_FRAMES_KINDS:
                    steps = [self.between_frames_op(rng, framed, kind)]
                else:
                    steps = [self.diff_op(rng, framed, {kind: 1})]
                for name, op in steps:
                    apply(framed, op)
                    apply(unframed, op)
                    if kind in self.BETWEEN_FRAMES_KINDS or rng.random() < (0.5 if len(steps) > 1 else 0.3):
                        for _ in range(1 + (kind == 'again')):
                            frame(framed)
                            reused[-1] += framed.test_bidi_walk_reused()
                            self.assertTrue(framed.test_bidi_walk_matches_full(), f'seed {seed}: {done + [name]}')
                        name += ' frame'
                    done.append(name)
            records = [list(map(x.test_bidi_line_record, range(x.lines))) for x in (framed, unframed)]
            self.ae(records[0], records[1], f'seed {seed}: {done}')
            self.ae(frame(framed), frame(unframed), f'seed {seed}: {done}')
        # the frames reusing the maps are those whose debug builds compare them with a full walk
        self.assertGreater(sum(reused), 0, reused)

    def test_full_width_region_scroll_joins_paragraphs(self):
        # a scroll of a full width region by a row joins or splits the auto-direction paragraphs across its top or bottom edge:
        # a frame taken before the scroll leaves the same records and final frame as a frame taken only after it. Each case:
        # (the text, the region's top, bottom and kept rows, the scroll, the visual rows it leaves)
        top_edge = '\x1b[2;1Hאבגדהab\x1b[4;1Hxy'  # row 1 wraps into the region's first row
        for text, top, bottom, kept, delta, want in (
            # the row moved up after the paragraph's first row joins it
            (top_edge, 2, 5, True, 20, ['', 'הדגבא', '   xy']),
            # the row moved down from under the paragraph's first row leaves it
            (top_edge, 2, 5, True, -20, ['', 'הדגבא', '', 'ab']),
            # the row below a region using the scrollback leaves the paragraph of the region's last row, which moved up
            ('\x1b[3;1Hאבגדהab', 0, 3, False, 20, ['', 'הדגבא', '', 'ab']),
            # the row below the region continues the row moved down onto the region's last row
            ('\x1b[1;1Habcdeאבגדהוזחטיab', 1, 3, True, -20, ['abcde', '', 'הדגבא', '   ab']),
        ):
            seen = []
            for framed in (True, False):
                s = self.screen(AUTO, text, cols=5, lines=6, scrollback=10)
                self._screens_to_verify_styles.remove(s)
                self.assertTrue(s.smooth_scroll_define(1, 0, top, 5, bottom, 1, kept))
                if framed:
                    frame(s)
                self.ae(s.smooth_scroll(1, delta), delta // 20)
                buf = frame(s)
                seen.append(([visual(s, y) for y in range(len(want))], [s.test_bidi_line_record(y) for y in range(s.lines)], buf))
            with self.subTest(text=text, delta=delta):
                self.ae(seen[0][0], want)
                self.ae(seen[0][1:], seen[1][1:])

    REGION_ROWS = (MIXED, NSI, 'אבג def', 'x אב')

    def region_screen(self, top=1, pixel_scroll=False, private_overflow=True, rows=REGION_ROWS):
        # four rows in a full width region starting at row top
        s = self.screen('\r\n'.join(('top',) * top + rows), cols=10, lines=4 + top, scrollback=5, pixel_scroll=pixel_scroll)
        self.assertTrue(s.smooth_scroll_define(1, 0, top, 10, 4 + top, 1, private_overflow))
        return s

    def test_full_width_region_moves_rows_with_their_order(self):
        # the rows a full width region moves keep their order; the cursor on a moved row is drawn at its visual column
        for pixel_scroll in (False, True):
            with self.subTest(pixel_scroll=pixel_scroll):
                s = self.region_screen(pixel_scroll=pixel_scroll)
                before = orders(s)
                self.ae(s.smooth_scroll(1, 20), 1)  # one row up, unshifted
                s.cursor_position(2, 1)  # the first cell of NSI, which moved to row 1
                self.ae(orders(s)[1:4], before[2:5])
                self.ae(s.test_cursor_x(CURSOR_BLOCK)[0], before[2].index(0))

    def assert_full_width_strip(self, s, top, shown, regions=None):
        # the strip of region 1 shows its rows as the screen does, and in its partial row above the row that left as it was
        # uploaded while on screen
        buf = frame(s)
        strip = strips(s, buf, regions)[1]
        self.ae(strip[0], shown)
        self.ae(strip[1:5], [main_row(s, buf, y) for y in range(top, top + 4)])
        return buf

    def test_full_width_region_strip(self):
        # shifted by a fraction of a row: the row that left is a kept row, or the newest scrollback line shown by pixel scroll
        for top, pixel_scroll in ((1, False), (1, True), (0, True)):
            with self.subTest(top=top, pixel_scroll=pixel_scroll):
                s = self.region_screen(top, pixel_scroll, private_overflow=top > 0)
                shown = main_row(s, frame(s), top)
                self.assertNotEqual(order(s, top), tuple(range(10)))
                self.ae(s.smooth_scroll(1, 5), 1)
                self.ae(s.smooth_scroll_regions()[0]['uses_history'], top == 0)
                self.assert_full_width_strip(s, top, shown)
        # text written, with bidi mode on or off, to the row a scroll cleared after it was shown at levels, and moved into the kept
        # row before a frame showed it, is drawn there as a frame before the move showed it
        for mode in ('', '\x1b[8l'):
            with self.subTest(mode=mode):
                seen = []
                for framed in (True, False):
                    s = self.region_screen()
                    frame(s)
                    self.ae(s.smooth_scroll(1, 20), 1)
                    pb(s, f'\x1b[5H{mode}abcdefg')
                    if framed:
                        frame(s)
                    self.ae(s.smooth_scroll(1, 65), 4)
                    seen.append(strips(s, frame(s))[1][0])
                self.ae(seen[0], seen[1])
        # a kept row of a paragraph that goes on in a row beside it is laid out with the whole paragraph: (text, region, the scroll
        # in pixels, text written after a first frame, the row of the strip)
        wrapped = AUTO + 'top\r\n12 34 56 7'
        for name, text, region, delta, edit, row in (
            ('base from the next row', wrapped + A + '\r\nx\r\ny', (1, 0, 1, 10, 5, 1, True), 5, '', 0),
            ('narrow, base from the next row', wrapped + A + '\r\nx\r\ny', (1, 2, 1, 8, 5), 5, '', 0),
            ('clean row, next row edited', wrapped + 'x\r\ny\r\nz', (1, 0, 1, 10, 5, 1, True), 5, '\x1b[3H' + A, 0),
            ('neutral after the wrap', 'top\r\nabc אבגדהו זחט xyz\r\nq\r\nw', (1, 0, 1, 10, 3, 1, True), -5, '', -1),
        ):
            with self.subTest(name):
                seen = []
                for framed in (True, False):
                    s = self.screen(text, pixel_scroll=False)
                    self.assertTrue(s.smooth_scroll_define(*region))
                    if edit:
                        frame(s)
                        pb(s, edit)
                    if framed:
                        frame(s)
                    s.smooth_scroll(1, delta)
                    seen.append(strips(s, frame(s))[1][row])
                    self._screens_to_verify_styles.remove(s)
                self.ae(seen[0], seen[1])
        # a kept row whose paragraph starts in a history line popped back in the step before, with no frame since, is drawn as when a
        # frame ran between the steps
        seen = []
        for framed in (True, False):
            s = self.create_screen(cols=5, lines=3, scrollback=10, options={'pixel_scroll': False})
            pb(s, AUTO)
            s.draw('אבגדה' + 'ab')
            self.assertTrue(s.smooth_scroll_define(1, 0, 0, 5, 2, 1, False))
            self.ae(s.smooth_scroll(1, 40), 2)
            self.ae(s.historybuf.count, 2)
            pb(s, '\x1b[3;1H\x1b[8hx\x1b[8l')
            self.ae(s.smooth_scroll(1, -20), -1)
            self.ae((s.historybuf.count, str(s.historybuf.line(0))), (1, 'אבגדה'))
            pb(s, '\x1b[1;5H\x1b[8hbc\x1b[8l')
            self.assertTrue(s.linebuf.is_continued(1))
            self.assertTrue(s.scroll(1, True))
            if framed:
                frame(s)
            self.ae(s.smooth_scroll(1, -5), -1)
            seen.append(strips(s, frame(s))[1][-1])
            self._screens_to_verify_styles.remove(s)
        self.ae(seen[0], seen[1])
        # c ends the paragraph laid out right to left from the history line
        self.ae([bool(c[0]) for c in seen[0]], [False] * 4 + [True])

    def test_full_width_region_strip_paused(self):
        # a paused frame shows the strip the live frame showed, the scrollback line without pixel scroll as with bidi mode off
        rows = self.REGION_ROWS[1::-1] + self.REGION_ROWS[2:]
        plain = self.create_screen(cols=10, lines=4, scrollback=5, options={'pixel_scroll': False})
        plain.draw(rows[0])
        bidi_off = main_row(plain, frame(plain), 0)
        for top, pixel_scroll in ((1, False), (1, True), (0, True), (0, False)):
            with self.subTest(top=top, pixel_scroll=pixel_scroll):
                s = self.region_screen(top, pixel_scroll, private_overflow=top > 0, rows=rows)
                shown = main_row(s, frame(s), top)
                if not top and not pixel_scroll:
                    shown = bidi_off
                self.ae(s.smooth_scroll(1, 5), 1)
                regions = s.smooth_scroll_regions()
                live = self.assert_full_width_strip(s, top, shown)
                s.pause_rendering(True, 1000)
                self.ae(strips(s, self.assert_full_width_strip(s, top, shown, regions), regions), strips(s, live, regions))
                s.pause_rendering(False)

    def test_scrollback_row_of_a_region_without_pixel_scroll(self):
        # without pixel scroll, the newest scrollback line in the partial row of a region is drawn as with bidi mode off, where
        # the direction of its text is guessed
        rows = self.REGION_ROWS[1::-1] + self.REGION_ROWS[2:]
        plain = self.create_screen(cols=10, lines=4, scrollback=5, options={'pixel_scroll': False})
        plain.draw(rows[0])
        bidi_off = main_row(plain, frame(plain), 0)
        s = self.region_screen(0, private_overflow=False, rows=rows)
        shown = main_row(s, frame(s), 0)
        self.assertNotEqual(shown, bidi_off)
        self.ae(s.smooth_scroll(1, 5), 1)
        self.assert_full_width_strip(s, 0, bidi_off)
        # scrolled back, the line is shown as it was on screen
        s.scroll(1, True)
        self.ae(main_row(s, frame(s), 0), shown)

    def test_narrow_region_spans(self):
        # a region narrower than the screen is a span of its own: no cell crosses its edges, the cells inside and outside it are
        # reordered within their spans, and the strip shows the kept row in the order it had on screen
        s = self.screen('אבגדהוזחטיabc', cols=20, lines=4, pixel_scroll=False)
        self.assertTrue(s.smooth_scroll_define(1, 5, 0, 15, 4))
        self.ae(orders(s)[0], (4, 3, 2, 1, 0, 9, 8, 7, 6, 5) + tuple(range(10, 20)))
        shown = main_row(s, frame(s), 0, 5, 15)
        self.ae(s.smooth_scroll(1, 5), 1)
        buf = frame(s)
        strip = strips(s, buf)[1]
        self.ae(strip[0], shown)
        self.ae(strip[1:5], [main_row(s, buf, y, 5, 15) for y in range(4)])
        # scrolled back, a render row shows the spans of the screen row it shows, not those of the row it showed before
        H = 'אבגדהוזחטי'
        s = self.screen('h1\r\nh2\r\n' + H + '\r\na\r\n' + H + '\r\nb', cols=20, lines=4, scrollback=5, pixel_scroll=False)
        self.assertTrue(s.smooth_scroll_define(1, 5, 0, 15, 2))
        live = orders(s)
        self.ae(live[0], (4, 3, 2, 1, 0, 9, 8, 7, 6, 5) + tuple(range(10, 20)))
        s.scroll(2, True)
        self.ae(orders(s)[2:], live[:2])

    def wide_char_at_region_edge(self, data, cols=20):
        # data, which defines a region, written after CSI 8 h and on a screen that never sent it
        s = self.screen(cols=cols, lines=4, pixel_scroll=False)
        plain = self.create_screen(cols=cols, lines=4, options={'pixel_scroll': False})
        for x in (s, plain):
            pb(x, data)
            self.ae(len(x.smooth_scroll_regions()), 1)
        return s, plain

    def assert_wide_char_whole(self, s, plain, cols):
        # the wide char in the logical columns cols is shown in those visual columns, and no other cell shows any part of it
        got, want = uploaded(s), uploaded(plain)
        self.ae(order(s)[cols[0] : cols[-1] + 1], cols)
        parts = {want[c][0] for c in cols}
        self.ae([x for x, c in enumerate(got) if c[0] in parts], list(cols))

    def assert_wide_char_drawn(self, data, cols):
        # No bundled font has 😀, so a wide char of the test font in its place is drawn in its columns as without bidi mode
        s, plain = self.wide_char_at_region_edge(data.replace('😀', '\x1b]66;w=2;W\x07'))
        self.assert_wide_char_whole(s, plain, cols)
        got, want = uploaded(s), uploaded(plain)
        self.ae(self.pixels(got[c] for c in cols), self.pixels(want[c] for c in cols))

    WIDE_IN_NARROW = '\x1b[1;1Hab' + 'אב' + '😀' + 'גד', (0, 1, 3, 2, 4, 5, 7, 6) + tuple(range(8, 20)), (4, 5)
    WIDE_IN_HORIZONTAL = SCP_RTL + '\x1b[1;1H' + 'אב' + '😀' + 'ג', (2, 3)

    def define_region(self, spec):
        return f'\x1b]2254;a=d:i=1:{spec}\x1b\\'

    def test_wide_char_at_a_narrow_region_left_edge(self):
        # a wide char across the left edge of a region narrower than the screen keeps its columns, and the text on either side is
        # reordered within its own span
        text, want, wide = self.WIDE_IN_NARROW
        data = self.define_region('x=6:y=1:w=10:h=3') + text
        s, plain = self.wide_char_at_region_edge(data)
        self.ae(orders(s)[0], want)
        self.assert_wide_char_whole(s, plain, wide)
        self.assert_wide_char_drawn(data, wide)

    def test_narrow_region_defined_after_a_frame(self):
        # a frame shows the row as if the narrow region had been there when it was written, and once the region is gone as if
        # it never had been
        text, want, _ = self.WIDE_IN_NARROW
        never = orders(self.screen(text, cols=20, lines=4, pixel_scroll=False))[0]
        self.assertNotEqual(never, want)
        s = self.screen(text, cols=20, lines=4, pixel_scroll=False)
        orders(s)
        pb(s, self.define_region('x=6:y=1:w=10:h=3'))
        self.ae(orders(s)[0], want)
        self.assertTrue(s.smooth_scroll_remove(1))
        self.ae(orders(s)[0], never)

    def test_wide_char_at_a_horizontal_region_left_edge(self):
        # a wide char partly in a horizontally scrolling region keeps its columns, as the region's cells do. Its pixels have no
        # oracle: the fixed cells are shaped as one run in the direction guessed from them, while without bidi mode it is guessed
        # from the whole row, so a wide char beside right-to-left text can be placed differently.
        text, wide = self.WIDE_IN_HORIZONTAL
        s, plain = self.wide_char_at_region_edge(text + self.define_region('x=4:y=1:w=2:h=1:o=h'))
        self.ae(orders(s)[0], (1, 0, 2, 3, 4) + tuple(range(19, 4, -1)))
        self.assert_wide_char_whole(s, plain, wide)

    def test_wide_char_at_region_right_edges(self):
        text, want, wide = self.WIDE_IN_NARROW
        data = self.define_region('x=1:y=1:w=5:h=3') + text
        s, plain = self.wide_char_at_region_edge(data)
        self.ae(orders(s)[0], want)
        self.assert_wide_char_whole(s, plain, wide)
        self.assert_wide_char_drawn(data, wide)
        text, wide = self.WIDE_IN_HORIZONTAL  # no pixel oracle, see the left edge
        s, plain = self.wide_char_at_region_edge(text + self.define_region('x=2:y=1:w=2:h=1:o=h'))
        self.ae(orders(s)[0], (0, 1, 2, 3) + tuple(range(19, 3, -1)))
        self.assert_wide_char_whole(s, plain, wide)

    def test_strip_selection_describes_its_cells(self):
        # the selection data of every strip cell is that of the cell it shows, each told apart by its own colour: that of the
        # same cell on screen, none for the cells of the kept rows (columns). A region's shift leaves blank cells, which have
        # no colour of their own and are not checked.
        H = 'אבגדהוזחטי'
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                s = self.screen(cols=20, lines=4, pixel_scroll=False)
                for y in range(4):
                    pb(s, f'\x1b[{y + 1};1H')
                    draw_coloured(s, 'ab' + H + 'cd' + H[:6], 1 + 20 * y)
                self.assertTrue(s.smooth_scroll_define(1, 5, 0, 15, 4, 1, False, horizontal))
                self.ae(s.smooth_scroll(1, 5), 1)
                s.start_selection(12, 1)
                s.update_selection(8, 2)
                buf = frame(s)
                raw = s.current_selections(True)
                on_screen = {}
                for y in range(s.lines):
                    for (_, style), b in zip(main_row(s, buf, y), raw[y * s.columns : (y + 1) * s.columns]):
                        on_screen[style >> CELL_GPU_STYLE_SHIFT] = b
                cells = [c for row in strips(s, buf)[1] for c in row]
                selection = [b for row in strips(s, b''.join(GPU_CELL.pack(b, 0) for b in raw))[1] for b, _ in row]
                seen = [(on_screen.get(style >> CELL_GPU_STYLE_SHIFT, 0), b) for (_, style), b in zip(cells, selection) if style]
                self.assertIn(1, selection)
                self.ae([b for _, b in seen], [want for want, _ in seen])

    def test_narrow_region_moves_records(self):
        # region columns 5-14 of 20: (row 0, row 1, the scroll in pixels, row 0 shown and its record after the scroll)
        at = '\x1b[{};6H'.format
        off = '\x1b[8l{}\x1b[8h'.format
        for name, row0, row1, deltas, want in (
            # the moved text keeps its settings on a row without text beside the region
            ('nothing beside', at(1) + SCP_RTL + A, at(2) + SCP_LTR + 'abc', (20,), (' ' * 5 + 'abc', (1, False, False))),
            ('bidi off text onto a recorded row', at(1) + A, at(2) + off(A), (20,), (' ' * 5 + A, (0, False, False))),
            # a row with text beside the region keeps what it has
            ('recorded text onto bidi off text', off(A), at(2) + A, (20,), (A + '  ' + A, (0, False, False))),
            ('onto a recorded row with text beside', SCP_RTL + 'אבגדה', at(2) + SCP_LTR + 'abc', (20,), ('הדגבא' + ' ' * 7 + 'abc', (1, True, False))),
            # through a kept row and back, with a frame while the row holds no text
            ('through a kept row', at(1) + SCP_RTL + A, '', (20, -20), (' ' * 12 + 'גבא', (1, True, False))),
        ):
            with self.subTest(name):
                s = self.screen('\x1b[H' + row0 + '\x1b[2H' + row1, cols=20, lines=3, pixel_scroll=False)
                self.assertTrue(s.smooth_scroll_define(1, 5, 0, 15, 3))
                before = orders(s)[0]
                for delta in deltas:
                    s.smooth_scroll(1, delta)
                    frame(s)
                self.ae((visual(s, 0), s.test_bidi_line_record(0)), want)
                if name.startswith('onto'):
                    self.ae(order(s, 0)[:5], before[:5])

    def test_narrow_region_defined_on_drawn_rows(self):
        # defining or removing a narrow region on rows already drawn changes their order on the next frame; while paused, on
        # the first frame after the pause
        joined, split = tuple(range(9, -1, -1)) + tuple(range(10, 20)), (4, 3, 2, 1, 0, 9, 8, 7, 6, 5) + tuple(range(10, 20))
        s = self.screen('אבגדהוזחטי', cols=20, lines=3, pixel_scroll=False)
        self.ae(orders(s)[0], joined)
        self.assertTrue(s.smooth_scroll_define(1, 5, 0, 15, 2))
        self.ae(orders(s)[0], split)
        self.assertTrue(s.smooth_scroll_remove(1))
        self.ae(orders(s)[0], joined)
        for change, before, after in ((lambda: s.smooth_scroll_define(1, 5, 0, 15, 2), joined, split), (lambda: s.smooth_scroll_remove(1), split, joined)):
            live = frame(s)
            s.pause_rendering(True, 1000)
            self.assertTrue(change())
            self.ae((frame(s), order(s, 0)), (live, before))
            s.pause_rendering(False)
            self.ae(orders(s)[0], after)

    def test_kept_row_holding_the_only_record(self):
        # the only recorded row scrolled into the kept row above a region is drawn there as it was on screen, also when it left
        # before a frame showed it
        text = 'top\r\n\x1b[2;3Habc\x1b[3;3H\x1b[8h' + MIXED + '\x1b[8l\x1b[4;3Hxyz'
        for (name, region, cols), framed in product((('narrow', (1, 2, 1, 8, 4), (2, 8)), ('full width', (1, 0, 1, 10, 4, 1, True), (0, 10))), (True, False)):
            with self.subTest(name, framed=framed):
                s = self.create_screen(cols=10, lines=4, scrollback=5, options={'pixel_scroll': False})
                pb(s, text)
                self.assertTrue(s.smooth_scroll_define(*region))
                if framed:
                    shown = main_row(s, frame(s), 2, *cols)
                    self.assertNotEqual(order(s, 2), tuple(range(10)))
                self.ae(s.smooth_scroll(1, 25), 2)
                self.ae(strips(s, frame(s))[1][0], shown)

    def test_click_in_a_shifted_region(self):
        # a click on a reordered row of a shifted region lands on the logical cell shown under it
        s = self.region_screen()
        frame(s)
        self.ae(s.smooth_scroll(1, 5), 1)  # MIXED is in the kept row, NSI on row 1
        frame(s)
        self.ae([s.test_bidi_logical_click(x, 1, True) for x in range(5)], [(3, True), (4, True), (2, False), (1, False), (0, False)])
        s = self.screen('top\r\n' + 'אבגדהוזחטי\r\n' * 2, cols=20, lines=4, pixel_scroll=False)
        self.assertTrue(s.smooth_scroll_define(1, 5, 1, 15, 4))
        frame(s)
        self.ae(s.smooth_scroll(1, 5), 1)
        frame(s)
        self.ae([s.test_bidi_logical_click(x, 1, True) for x in (0, 4, 5, 9, 10)], [(4, False), (0, False), (9, False), (5, False), (10, True)])

    def test_scrollback_row_holding_the_only_record(self):
        # the only recorded row, pushed into the scrollback by a region that uses it, is drawn in the partial row of the region as
        # with bidi mode off without pixel scroll, and as it was on screen with it
        plain = self.create_screen(cols=10, lines=4, scrollback=5, options={'pixel_scroll': False})
        plain.draw(NSI)
        bidi_off = main_row(plain, frame(plain), 0)
        for pixel_scroll in (False, True):
            with self.subTest(pixel_scroll=pixel_scroll):
                s = self.create_screen(cols=10, lines=4, scrollback=5, options={'pixel_scroll': pixel_scroll})
                pb(s, 'top\r\n\x1b[8h' + NSI + '\x1b[8l\r\nabc\r\nxyz')
                self.assertTrue(s.smooth_scroll_define(1, 0, 0, 10, 4))
                shown = main_row(s, frame(s), 1)
                self.assertNotEqual(shown, bidi_off)
                self.ae(s.smooth_scroll(1, 25), 2)
                self.ae(strips(s, frame(s))[1][0], shown if pixel_scroll else bidi_off)

    def horizontal_and_plain(self, text, region, cols=20, lines=3):
        # text drawn after CSI 8 h and on a screen that never sent it, each with the same horizontally scrolling region
        s, plain = self.bidi_and_plain(lambda x: pb(x, text), cols=cols, lines=lines)
        for x in (s, plain):
            self.assertTrue(x.smooth_scroll_define(*region, False, True))
        return s, plain

    def assert_region_shown_as_without_bidi(self, s, plain, rows, left, right):
        # the cells of the rectangle in the frame and its strip with the partial columns show what they show without bidi mode
        seen = []
        for x in (s, plain):
            buf = frame(x)
            seen.append(([self.pixels(main_row(x, buf, y, left, right)) for y in rows], [self.pixels(row) for row in strips(x, buf).get(1, ())]))
        self.ae(seen[0], seen[1])
        return seen[0][1]

    def test_horizontal_region_cells_keep_their_columns(self):
        # region columns 5-14 of 20: its cells are not reordered and are shaped as with bidi mode off, in the rectangle and in the
        # partial columns of its strip, also on a row whose only right-to-left text is in it; the text beside it is reordered
        # within its own span. Without bidi mode a run of text crossing an edge is shaped in the direction guessed from all of it,
        # so the cells beside the edges are empty.
        text = 'אבגד\x1b[1;6Hוזחטיabcde\x1b[1;17Hכלמנ\x1b[2;6H' + A + '\x1b[2;14Hדה'
        s, plain = self.horizontal_and_plain(text, (1, 5, 0, 15, 2, 2))
        self.ae(orders(s)[:2], [(3, 2, 1, 0, 4) + tuple(range(5, 15)) + (19, 18, 17, 16, 15), tuple(range(20))])
        self.assertFalse(self.assert_region_shown_as_without_bidi(s, plain, (0, 1), 5, 15))
        # shifted left by a fraction, then right: the partial column on the left, then the one on the right holds Hebrew
        for delta, kept in ((3, ('ו', 'א')), (-15, ('', ''))):
            for x in (s, plain):
                x.smooth_scroll(1, delta)
            self.ae(s.smooth_scroll_overflow(1, True), kept)
            self.assertTrue(self.assert_region_shown_as_without_bidi(s, plain, (0, 1), 5, 15))
        self.ae(s.smooth_scroll_overflow(1, False), ('de', 'דה'))

    def test_full_width_horizontal_region(self):
        # a horizontally scrolling region as wide as the screen has no edge to split its rows at, and its cells keep their columns
        s, plain = self.horizontal_and_plain('אבגדה abc ' + A, (1, 0, 0, 20, 2, 2))
        self.ae(orders(s)[0], tuple(range(20)))
        for delta in (0, 3, -15):
            for x in (s, plain):
                x.smooth_scroll(1, delta)
            self.assert_region_shown_as_without_bidi(s, plain, (0,), 0, 20)

    def test_horizontal_region_defined_on_drawn_rows(self):
        # defining or removing a horizontally scrolling region on rows already drawn changes their order on the next frame
        text = 'אבגדהוזחטיכלמנסעפצקר'
        joined = tuple(range(19, -1, -1))
        for left, right, want in ((5, 15, (4, 3, 2, 1, 0) + tuple(range(5, 15)) + (19, 18, 17, 16, 15)), (0, 20, tuple(range(20)))):
            with self.subTest(left=left, right=right):
                s = self.screen(text=text, cols=20, lines=3)
                self.ae(orders(s)[0], joined)
                self.assertTrue(s.smooth_scroll_define(1, left, 0, right, 2, 1, False, True))
                self.ae(orders(s)[0], want)
                self.assertTrue(s.smooth_scroll_remove(1))
                self.ae(orders(s)[0], joined)

    def test_text_back_from_kept_columns(self):
        # a row whose only text went into the kept columns of a horizontally scrolling region holds no text and loses its
        # settings: the text coming back has none, whether or not a frame was drawn while it was away
        seen = []
        for framed in (False, True):
            s = self.screen('\x1b[1;6H' + SCP_RTL + 'אב', cols=20, lines=2, pixel_scroll=False)
            self.assertTrue(s.smooth_scroll_define(1, 5, 0, 15, 2, 2, False, True))
            frame(s)
            self.ae(s.smooth_scroll(1, 20), 2)
            self.ae(s.smooth_scroll_overflow(1, True), ('אב', ''))
            if framed:
                frame(s)
            self.ae(s.smooth_scroll(1, -20), -2)
            seen.append((s.test_bidi_line_record(0), [s.cpu_cells(0, x)['text'] for x in (5, 6)], frame(s)))
        self.ae(seen[0][:2], ((0, False, False), ['א', 'ב']))
        self.ae(seen[0], seen[1])

    def test_placeholders_in_regions(self):
        # a region row holding an image placeholder and right-to-left text is not reordered: it uploads what it uploads without
        # bidi mode, before and after a scroll, and the images are placed as without bidi mode
        from .graphics import put_helpers

        put_image = put_helpers(self, 10, 20, cols=10, lines=6)[3]
        placeholders = ''.join('\U0010eeee̅' + c for c in '̅̍̎̐')

        def draw(x):
            put_image(x, 40, 20, num_cols=4, num_lines=1, unicode_placeholder=1, id=42)
            pb(x, '\x1b[3;2H\x1b[38;5;42m' + placeholders + '\x1b[39m ' + A)

        for name, region in (('vertical', (1, 2, 1, 8, 5)), ('horizontal', (1, 2, 1, 8, 5, 2, False, True))):
            with self.subTest(name):
                s, plain = self.bidi_and_plain(draw, cols=10, lines=6)
                for x in (s, plain):
                    self.assertTrue(x.smooth_scroll_define(*region))
                for delta in (0, 5, -12):
                    for x in (s, plain):
                        x.smooth_scroll(1, delta)
                    self.ae(frame(s), frame(plain), f'after {delta}')
                    layers = s.update_graphics_layers()
                    self.assertTrue(layers)
                    self.ae(layers, plain.update_graphics_layers(), f'after {delta}')
