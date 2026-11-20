#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

import random
import re
import struct

from kitty.fast_data_types import Screen, get_options, test_screen_update_cell_data
from kitty.fonts.render import setup_for_testing

from .base import BaseTest, Callbacks, draw_multicell, parse_bytes

A = 'אבג'  # three Hebrew letters, bidi class R
MIXED = 'abc' + A
NSI = 'אב 12'  # R R WS EN EN: its map (3, 4, 2, 1, 0) is not its own inverse
ISOLATES = '\u2066\u2067\u2068\u2069'  # LRI RLI FSI PDI
LRE, RLE, PDF, LRO, RLO = '\u202a\u202b\u202c\u202d\u202e'
AUTO, SCP_RTL, SCP_LTR = '\x1b[?2501h', '\x1b[2 k', '\x1b[1 k'
PROMPT = '\x1b]133;A\x07'  # OSC 133 prompt start, as shell integration sends it
GPU_CELL = struct.Struct('=II')  # CellGPUData in kitty/line.h: sprite_idx, style_and_mark
CELL_GPU_STYLE_SHIFT = 2
EXTRA_CURSOR = 1 << 2  # an extra cursor of shape 1 in the selection buffer


def pb(s, data):
    parse_bytes(s, data.encode())


def frame(s):
    return test_screen_update_cell_data(s)


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
        self.enterContext(setup_for_testing())

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
        # a row with an image placeholder or scaled text is not reordered
        for extra in (lambda s: s.draw(chr(0x10EEEE)), lambda s: draw_multicell(s, 'x', scale=2)):
            s = self.screen(text=A)
            extra(s)
            self.assertIsNone(orders(s)[0])

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

    def test_bracket_pairs(self):
        # A pair is not resolved by N0 when its opening bracket is far after the previous letter or digit, which no later text
        # changes: א(ב) keeps its mirrored pair whatever follows it
        def both(text, cols=80, lines=1):
            return self.written(text, cols=cols, lines=lines), self.written(text.replace('(', '!').replace(')', '!'), cols=cols, lines=lines)

        for text, cols, lines in (('א(ב)' + '()' * 35, 80, 1), ('א(ב)' + '()' * 36, 80, 1), ('א(ב)' + '()' * 3000, 200, 50)):
            with self.subTest(pairs=len(text) // 2 - 2):
                kept, plain = both(text, cols, lines)
                self.ae((visual(kept)[:4], visual(plain)[:4]), (')ב(א', 'ב!א!'))
        near, plain = both('א' + '!' * 20 + '(ב)')
        self.assertNotEqual(orders(near), orders(plain))
        far, plain = both('א' + '!' * 40 + '(ב)')
        self.ae(orders(far), orders(plain))

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

    # The randomized differential: after every frame, the cell data uploaded for a screen that is rendered after each operation
    # equals that of a fresh screen given the same operations and rendered once.
    DIFF_POOL = 'אבגדהוזחט' * 3 + 'abcdefghij' * 3 + '0123456789' * 2 + '  ' * 3 + '()!.-'
    DIFF_KINDS = dict(
        zip(
            'text flip unwrap crlf lf el ed ech dch ich il dl region ri su sd resize alt back fwd pause scp auto bdsm prompt erase'.split(),
            (30, 6, 4, 6, 6, 3, 2, 2, 2, 2, 6, 6, 5, 4, 3, 3, 1, 2, 3, 3, 2, 3, 3, 1, 3, 2),
        )
    )

    def diff_op(self, rng, s):
        L, C = s.lines, s.columns
        y, x, n = rng.randrange(L) + 1, rng.randrange(C) + 1, rng.randrange(1, 4)
        kind = rng.choices(tuple(self.DIFF_KINDS), tuple(self.DIFF_KINDS.values()))[0]

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
            got = test_screen_update_cell_data(s)
            f = replay()
            for o in ops:
                o(f)
            self.ae(got, test_screen_update_cell_data(f), f'seed {seed}, op {i} ({name})')
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
