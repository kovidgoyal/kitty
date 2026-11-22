#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.fast_data_types import Screen

from .base import BaseTest, parse_bytes
from .base import draw_multicell as multicell

H = 20  # the cell height used by create_screen()


def fill(s: Screen) -> None:
    # Row y is filled with the letter A + y
    for y in range(s.lines):
        s.cursor_position(y + 1, 1)
        s.draw(chr(ord('A') + y) * s.columns)
    s.cursor_position(1, 1)


def lines(s: Screen) -> list[str]:
    return [str(s.line(y)) for y in range(s.lines)]


def region(s: Screen, id: int = 1) -> dict[str, int | bool]:
    for r in s.smooth_scroll_regions():
        if r['id'] == id:
            return r
    raise KeyError(id)


class TestSmoothScroll(BaseTest):
    def test_smooth_scroll_define(self):
        s = self.create_screen(cols=10, lines=5)
        ae = self.ae
        # invalid rectangles and capacities
        for args in ((0, 0, 0, 10, 5), (1, 3, 0, 3, 5), (1, 0, 2, 10, 2), (1, 0, 0, 11, 5), (1, 0, 0, 10, 6), (1, 0, 0, 10, 2, 0), (1, 0, 0, 10, 2, 3)):
            self.assertFalse(s.smooth_scroll_define(*args), args)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 5, 2))
        # overlapping
        self.assertFalse(s.smooth_scroll_define(2, 4, 1, 6, 3))
        self.assertTrue(s.smooth_scroll_define(2, 5, 0, 10, 2))
        self.assertTrue(s.smooth_scroll_define(3, 0, 2, 10, 3))
        self.assertTrue(s.smooth_scroll_define(4, 0, 3, 10, 4))
        # at most four regions
        self.assertFalse(s.smooth_scroll_define(5, 0, 4, 10, 5))
        # redefining an existing region replaces it, even if it overlaps its old rectangle
        self.assertTrue(s.smooth_scroll_define(4, 0, 3, 10, 5, 2))
        ae(region(s, 4)['bottom'], 5)
        ae(region(s, 4)['capacity'], 2)
        ae(len(s.smooth_scroll_regions()), 4)
        self.assertTrue(s.smooth_scroll_remove(4))
        self.assertFalse(s.smooth_scroll_remove(4))
        ae(len(s.smooth_scroll_regions()), 3)
        self.assertIsNone(s.smooth_scroll(4, 10))

    def test_smooth_scroll_partial_width(self):
        s = self.create_screen(cols=10, lines=5)
        ae = self.ae
        fill(s)
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 4))
        # Scrolling up by less than a row moves the cells by a full row so the
        # row entering at the bottom can be drawn and renders them shifted
        ae(s.smooth_scroll(1, 5), 1)
        ae(lines(s), ['AAAAAAAAAA', 'BBCCCCBBBB', 'CCDDDDCCCC', 'DD    DDDD', 'EEEEEEEEEE'])
        ae(region(s)['offset'], H - 5)
        ae(s.smooth_scroll_overflow(1, True), ('BBBB',))
        ae(s.smooth_scroll_overflow(1, False), ())
        ae(s.smooth_scroll(1, 10), 0)
        ae(region(s)['offset'], 5)
        ae(s.smooth_scroll(1, 5), 0)
        ae(region(s)['offset'], 0)
        ae(s.smooth_scroll(1, 1), 1)
        ae(region(s)['offset'], H - 1)
        ae(lines(s), ['AAAAAAAAAA', 'BBDDDDBBBB', 'CC    CCCC', 'DD    DDDD', 'EEEEEEEEEE'])
        ae(s.smooth_scroll_overflow(1, True), ('CCCC',))  # capacity is one row
        # Reversing the direction restores rows from the overflow buffers,
        # returning to a row boundary moves the cells back
        ae(s.smooth_scroll(1, -1), -1)
        ae(region(s)['offset'], 0)
        ae(lines(s), ['AAAAAAAAAA', 'BBCCCCBBBB', 'CCDDDDCCCC', 'DD    DDDD', 'EEEEEEEEEE'])
        ae(s.smooth_scroll_overflow(1, True), ())
        ae(s.smooth_scroll_overflow(1, False), ('',))
        # The row entering at the top is blank as there are no more rows above
        ae(s.smooth_scroll(1, -1), -1)
        ae(region(s)['offset'], -(H - 1))
        ae(lines(s), ['AAAAAAAAAA', 'BB    BBBB', 'CCCCCCCCCC', 'DDDDDDDDDD', 'EEEEEEEEEE'])
        ae(s.smooth_scroll_overflow(1, False), ('',))
        ae(s.smooth_scroll(1, -H), -1)
        ae(region(s)['offset'], -(H - 1))
        ae(lines(s), ['AAAAAAAAAA', 'BB    BBBB', 'CC    CCCC', 'DDCCCCDDDD', 'EEEEEEEEEE'])
        ae(s.smooth_scroll_overflow(1, False), ('DDDD',))
        ae(s.smooth_scroll(1, -1), 0)
        ae(region(s)['offset'], -(H - 2))

    def test_smooth_scroll_capacity(self):
        s = self.create_screen(cols=4, lines=6, scrollback=0)
        ae = self.ae
        fill(s)
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 4, 5, 3))
        ae(region(s)['uses_history'], False)
        ae(s.smooth_scroll(1, 2 * H), 2)
        ae(s.smooth_scroll_overflow(1, True), ('CCCC', 'BBBB'))
        ae(s.smooth_scroll(1, 2 * H), 2)
        ae(s.smooth_scroll_overflow(1, True), ('EEEE', 'DDDD', 'CCCC'))
        ae(lines(s), ['AAAA', '', '', '', '', 'FFFF'])
        # Huge scrolls only move as many rows as there are in the rectangle and its overflow buffer
        ae(s.smooth_scroll(1, 1000 * H), 1000)
        ae(s.smooth_scroll_overflow(1, True), ('', '', ''))
        ae(region(s)['offset'], 0)
        ae(s.smooth_scroll(1, -(2**31)), -((2**31 + H - 1) // H))

    def test_smooth_scroll_history(self):
        s = self.create_screen(cols=4, lines=5, scrollback=10)
        ae = self.ae
        fill(s)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 4, 3))
        ae(region(s)['uses_history'], True)
        ae(s.smooth_scroll(1, H + 3), 2)
        ae(s.historybuf.count, 2)
        ae(str(s.historybuf.line(0)), 'BBBB')
        ae(str(s.historybuf.line(1)), 'AAAA')
        ae(s.smooth_scroll_overflow(1, True), ())
        ae(lines(s), ['CCCC', '', '', 'DDDD', 'EEEE'])
        ae(s.smooth_scroll(1, -(H + 3)), -2)
        ae(s.historybuf.count, 0)
        ae(lines(s), ['AAAA', 'BBBB', 'CCCC', 'DDDD', 'EEEE'])
        ae(s.smooth_scroll_overflow(1, False), ('',))
        # A scrolled back viewport stays on the same content
        ae(s.smooth_scroll(1, 2 * H), 2)
        s.scroll(1, True)
        ae(s.scrolled_by, 1)
        ae(s.smooth_scroll(1, H), 1)
        ae(s.scrolled_by, 2)
        ae(s.smooth_scroll(1, -H), -1)
        ae(s.scrolled_by, 1)
        # Huge scrolls do not fill the scrollback with blank lines
        s.scroll(10, False)
        before = s.historybuf.count
        ae(s.smooth_scroll(1, 100 * H), 100)
        ae(s.historybuf.count, before + 3)

        # Opting out of using the scrollback
        s = self.create_screen(cols=4, lines=5, scrollback=10)
        fill(s)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 4, 3, 1, True))
        ae(region(s)['uses_history'], False)
        ae(s.smooth_scroll(1, H), 1)
        ae(s.historybuf.count, 0)
        ae(s.smooth_scroll_overflow(1, True), ('AAAA',))

        # Only full width regions at the top of the main screen use the scrollback
        s = self.create_screen(cols=4, lines=5, scrollback=10)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 3, 3))
        ae(region(s)['uses_history'], False)
        self.assertTrue(s.smooth_scroll_define(2, 0, 3, 4, 5))
        ae(region(s, 2)['uses_history'], False)
        parse_bytes(s, b'\x1b[?1049h')
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 4, 3))
        ae(region(s)['uses_history'], False)

    def test_smooth_scroll_invalidation(self):
        ae = self.ae

        def setup(**kw):
            s = self.create_screen(cols=4, lines=6, scrollback=10)
            fill(s)
            self.assertTrue(s.smooth_scroll_define(1, 0, 1, 4, 4, **kw))
            ae(s.smooth_scroll(1, 5), 1)
            ae(s.smooth_scroll(1, -10), -2)
            ae((region(s)['num_before'], region(s)['num_after'], region(s)['offset']), (0, 1, -15))
            ae(s.smooth_scroll(1, 2), 1)
            ae((region(s)['num_before'], region(s)['num_after'], region(s)['offset']), (1, 0, 3))
            return s

        def discarded(s):
            r = region(s)
            ae((r['num_before'], r['num_after'], r['offset']), (0, 0, 0))

        # Moving the lines of the screen discards the overflow buffers
        for cmd in (b'\x1b[6H\n', b'\x1b[S', b'\x1b[T', b'\x1bM', b'\x1b[2;1H\x1b[L', b'\x1b[2;1H\x1b[M', b'\x1b[2J', b'\x1b[3J', b'\x1b[22J', b'\x1b#8'):
            s = setup()
            parse_bytes(s, cmd)
            discarded(s)
        # but not moving lines that do not intersect the region
        s = setup()
        parse_bytes(s, b'\x1b[5;6r\x1b[6H\n\x1b[r')
        ae(region(s)['num_before'], 1)
        # Erasing parts of the screen does not affect the region
        s = setup()
        parse_bytes(s, b'\x1b[2;1H\x1b[K\x1b[J\x1b[1J')
        ae(region(s)['num_before'], 1)
        # Removing all regions
        for cmd in (b'\x1bc', b'\x1b[!p', b'\x1b[?1049h'):
            s = setup()
            parse_bytes(s, cmd)
            ae(s.smooth_scroll_regions(), ())
        s = setup()
        s.resize(6, 4)
        ae(s.smooth_scroll_regions(), ())

        # When the scrollback is the overflow buffer above the region scrolling
        # the screen into it only discards the rows below the region
        s = self.create_screen(cols=4, lines=5, scrollback=10)
        fill(s)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 4, 3))
        ae(s.smooth_scroll(1, -5), -1)
        ae((region(s)['num_after'], region(s)['offset']), (1, -15))
        parse_bytes(s, b'\x1b[5H\n')
        ae((region(s)['num_after'], region(s)['offset']), (0, 0))
        ae(s.smooth_scroll(1, 5), 1)
        parse_bytes(s, b'\x1b[5H\n')
        ae((region(s)['num_after'], region(s)['offset']), (0, 15))

    def test_smooth_scroll_selections(self):
        ae = self.ae
        s = self.create_screen(cols=10, lines=5)
        fill(s)
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 5))

        def select(x1, y1, x2, y2, rectangle=False):
            s.start_selection(x1, y1, rectangle)
            s.update_selection(x2, y2)
            self.assertTrue(s.has_selection())

        # A selection inside the rectangle moves with it
        select(2, 2, 4, 2)
        ae(s.text_for_selection(False, False), ('CCC',))
        ae(s.smooth_scroll(1, 1), 1)
        ae(s.text_for_selection(False, False), ('CCC',))
        ae(s.smooth_scroll(1, -1), -1)
        ae(s.text_for_selection(False, False), ('CCC',))
        ae(s.smooth_scroll(1, -H), -1)
        ae(s.text_for_selection(False, False), ('CCC',))
        # and is cleared when it moves out of it
        ae(s.smooth_scroll(1, 3 * H), 3)
        self.assertFalse(s.has_selection())
        # A selection crossing the edges is cleared
        fill(s)
        select(0, 2, 4, 2)
        s.smooth_scroll(1, H)
        self.assertFalse(s.has_selection())
        # A multi-line selection spans the full width so it is not inside the rectangle
        fill(s)
        select(2, 2, 3, 3)
        s.smooth_scroll(1, H)
        self.assertFalse(s.has_selection())
        # unless it is a rectangle selection
        fill(s)
        select(2, 2, 3, 3, True)
        before = s.text_for_selection(False, False)
        ae(''.join(before), 'CC\nDD')
        s.smooth_scroll(1, H)
        ae(s.text_for_selection(False, False), before)
        # Selections that do not intersect the rectangle are not affected
        fill(s)
        select(7, 2, 8, 2)
        s.smooth_scroll(1, H)
        self.assertTrue(s.has_selection())

    def test_smooth_scroll_multicell(self):
        ae = self.ae

        def cell(s, x, y):
            return s.cpu_cells(y, x)

        # Wide chars that cross the left and right edges of the rectangle are removed
        s = self.create_screen(cols=10, lines=4)
        s.cursor_position(2, 2)
        s.draw('好')
        s.cursor_position(3, 6)
        s.draw('好')
        s.cursor_position(4, 4)
        s.draw('好')
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 4))
        s.smooth_scroll(1, 1)
        ae(lines(s), ['', '', ' ' * 3 + '好', ''])
        ae(region(s)['offset'], H - 1)

        # Multiline chars that cross the top or bottom edge into cells outside the rectangle are removed
        s = self.create_screen(cols=10, lines=6)
        s.cursor_position(1, 3)
        multicell(s, 'A', scale=2)
        s.cursor_position(4, 3)
        multicell(s, 'B', scale=2)
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 10, 4))
        s.smooth_scroll(1, 1)
        for y in range(6):
            for x in (2, 3):
                self.assertIsNone(cell(s, x, y)['mcd'], (x, y))

        # Multiline chars split by scrolling between the rectangle and the
        # overflow buffers are kept and partially visible
        s = self.create_screen(cols=10, lines=6)
        s.cursor_position(2, 3)
        multicell(s, 'A', scale=2)
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 10, 5))
        ae(s.smooth_scroll(1, 1), 1)
        ae(cell(s, 2, 1)['y'], 1)
        ae(s.smooth_scroll_overflow(1, True)[0], '  A')
        # and restored when scrolling back
        ae(s.smooth_scroll(1, -1), -1)
        ae(cell(s, 2, 1)['y'], 0)
        ae(cell(s, 2, 2)['y'], 1)
        ae(s.smooth_scroll_overflow(1, True), ())
        # also at the bottom edge
        ae(s.smooth_scroll(1, -3 * H), -3)
        ae(cell(s, 2, 4)['y'], 0)
        ae(s.smooth_scroll_overflow(1, False)[0], '  ')
        # overwriting a split char removes its part in the overflow buffer too
        s.cursor_position(5, 3)
        s.draw('x')
        ae(str(s.line(4)), '  x')
        self.assertIsNone(cell(s, 3, 4)['mcd'])
        r = region(s)
        ae(s.smooth_scroll_overflow(1, False), ('',) * r['num_after'])
        ae(s.smooth_scroll(1, 3 * H), 3)
        for y in range(6):
            for x in (2, 3):
                self.assertIsNone(cell(s, x, y)['mcd'], (x, y))

        # A blank row entering next to a char tears it
        s = self.create_screen(cols=10, lines=6)
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 10, 4))
        s.cursor_position(4, 3)
        multicell(s, 'A', scale=2)  # rows 3 and 4, crossing the bottom edge
        ae(s.smooth_scroll(1, -1), -1)
        # moved into the overflow buffer below, not torn as it crossed the edge and was removed
        self.assertIsNone(cell(s, 2, 3)['mcd'])
        s = self.create_screen(cols=10, lines=6)
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 10, 5))
        s.cursor_position(2, 3)
        multicell(s, 'A', scale=2)
        ae(s.smooth_scroll(1, 1), 1)  # top row of the char in the overflow buffer
        s.smooth_scroll_remove(1)  # discarding it tears the char
        for y in range(6):
            for x in (2, 3):
                self.assertIsNone(cell(s, x, y)['mcd'], (x, y))

        # With the scrollback as the overflow buffer chars split into it are kept
        s = self.create_screen(cols=10, lines=6, scrollback=10)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 10, 4))
        s.cursor_position(1, 3)
        multicell(s, 'A', scale=2)
        ae(s.smooth_scroll(1, 1), 1)
        ae(cell(s, 2, 0)['y'], 1)
        ae(s.historybuf.count, 1)
        s.smooth_scroll_remove(1)
        ae(cell(s, 2, 0)['y'], 1)

    def test_smooth_scroll_gc(self):
        ae = self.ae
        s = self.create_screen(cols=10, lines=4)
        s.cursor_position(2, 1)
        parse_bytes(s, '\x1b]8;;https://x.com\x1b\\é\x1b[31mred\x1b]8;;\x1b\\'.encode())
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 10, 3, 1, True))
        ae(s.smooth_scroll(1, H), 1)
        s.erase_in_display(2)
        ae(s.smooth_scroll_overflow(1, True), ())  # erasing the screen discarded the overflow buffer
        s.cursor_position(2, 1)
        parse_bytes(s, '\x1b]8;;https://x.com\x1b\\é\x1b[31mred\x1b]8;;\x1b\\'.encode())
        ae(s.smooth_scroll(1, H), 1)
        for i in range(200):
            s.cursor_position(4, 1)
            parse_bytes(s, f'\x1b]8;;https://{i}\x1b\\{chr(0x300 + i % 50)}â\x1b[38;5;{i}mx\x1b]8;;\x1b\\'.encode())
        s.garbage_collect_text_cache()
        s.garbage_collect_hyperlink_pool()
        ae(s.smooth_scroll_overflow(1, True), ('éred',))
        ae(s.smooth_scroll(1, -H), -1)
        ae(str(s.line(1)), 'éred')
        ae(s.hyperlink_at(0, 1), 'https://x.com')
        self.assertIn('\x1b[31m', s.line(1).as_ansi())

    def test_smooth_scroll_images(self):
        from .graphics import put_helpers

        ae = self.ae
        cw, ch = 10, H
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch, cols=10, lines=8)

        def rows(scrolled_by=0):
            s.update_only_line_graphics_data()
            return sorted(
                (round((r['dest_rect']['top'] + 1) / dy) - scrolled_by, round((r['dest_rect']['bottom'] + 1) / dy) - scrolled_by)
                for r in layers(s, scrolled_by)
            )

        def put(x, y, num_cols=2, num_lines=2):
            s.cursor_position(y + 1, x + 1)
            put_image(s, cw * num_cols, ch * num_lines, num_cols=num_cols, num_lines=num_lines, cursor_movement=1)

        # Images inside the rectangle move with it, images crossing its edges
        # or outside it do not
        put(2, 2)  # inside
        put(6, 1)  # crossing the top edge
        put(0, 4, num_cols=1)  # outside
        self.assertTrue(s.smooth_scroll_define(1, 2, 2, 8, 6, 2))
        ae(rows(), [(1, 3), (2, 4), (4, 6)])
        ae(s.smooth_scroll(1, 1), 1)
        ae(rows(), [(1, 3), (1, 3), (4, 6)])
        ae(s.smooth_scroll(1, -1), -1)
        ae(rows(), [(1, 3), (2, 4), (4, 6)])
        ae(s.smooth_scroll(1, -2 * H), -2)
        ae(rows(), [(1, 3), (4, 6), (4, 6)])
        # Images in the overflow buffers are kept as long as part of them is in them
        ae(s.smooth_scroll(1, -3 * H), -3)
        ae(rows(), [(1, 3), (4, 6), (7, 9)])
        ae(s.smooth_scroll(1, -H), -1)
        ae(rows(), [(1, 3), (4, 6)])  # moved out of the two rows of the overflow buffer

        # When the region is removed images are clipped to its rectangle
        put(2, 2)
        ae(s.smooth_scroll(1, 1), 1)
        ae(rows(), [(1, 3), (1, 3), (4, 6)])
        s.smooth_scroll_remove(1)
        ae(rows(), [(1, 3), (2, 3), (4, 6)])
        # and no longer move with it
        self.assertTrue(s.smooth_scroll_define(1, 2, 3, 8, 6, 2))
        ae(s.smooth_scroll(1, -1), -1)
        ae(rows(), [(1, 3), (2, 3), (4, 6)])

        # With the scrollback as the overflow buffer, images move into it and stay there
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch, cols=10, lines=8)
        put(2, 1)
        put(2, 6)  # below the rectangle
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 10, 4))
        ae(s.smooth_scroll(1, 3 * H), 3)
        ae(rows(), [(6, 8)])  # the other image is in the scrollback
        ae(s.historybuf.count, 3)
        s.smooth_scroll_remove(1)
        s.scroll(3, True)
        ae(rows(3), [(-2, 0)])  # the other image is below the viewport
        s.scroll(3, False)
        self.assertTrue(s.smooth_scroll_define(1, 0, 0, 10, 4))
        ae(s.smooth_scroll(1, -2 * H), -2)
        ae(rows(), [(0, 2), (6, 8)])

        # Images from unicode placeholders move with their cells
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch, cols=10, lines=8)
        put_image(s, cw, ch, num_cols=1, num_lines=1, unicode_placeholder=1, id=42)
        s.cursor_position(3, 3)
        s.apply_sgr('38;5;42')
        s.draw('\U0010eeee̅')
        s.apply_sgr('39')
        ae(rows(), [(2, 3)])
        self.assertTrue(s.smooth_scroll_define(1, 2, 2, 8, 6))
        ae(s.smooth_scroll(1, 1), 1)
        ae(rows(), [(1, 2)])  # in the overflow buffer
        ae(s.smooth_scroll(1, -1), -1)
        ae(rows(), [(2, 3)])
        ae(s.smooth_scroll(1, -H), -1)
        ae(rows(), [(3, 4)])

    def test_smooth_scroll_pause_rendering(self):
        ae = self.ae
        for uses_history in (True, False):
            s = self.create_screen(cols=4, lines=5, scrollback=10)
            fill(s)
            self.assertTrue(s.smooth_scroll_define(1, 0, 0, 4, 3, 1, not uses_history))
            ae(s.smooth_scroll(1, 5), 1)
            ae(s.smooth_scroll(1, -10), -2)
            ae(region(s)['offset'], -15)
            self.assertTrue(s.pause_rendering(True))
            # changes while paused do not affect the captured state and do not crash
            ae(s.smooth_scroll(1, 30), 3)
            s.smooth_scroll_remove(1)
            s.garbage_collect_text_cache()
            self.assertTrue(s.pause_rendering(False))

    def test_smooth_scroll_horizontal(self):
        ae = self.ae
        W = 10  # the cell width used by create_screen()
        s = self.create_screen(cols=10, lines=4)
        # the capacity is limited by the width for horizontal scrolling
        self.assertFalse(s.smooth_scroll_define(1, 2, 1, 6, 3, 5, False, True))
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, 4, False, True))
        ae(region(s)['uses_history'], False)
        for y in range(s.lines):
            s.cursor_position(y + 1, 1)
            s.draw('0123456789')
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, 1, False, True))
        ae(region(s)['horizontal'], True)
        ae(s.smooth_scroll(1, 3), 1)
        ae(region(s)['offset'], W - 3)
        ae(lines(s), ['0123456789', '01345 6789', '01345 6789', '0123456789'])
        ae(s.smooth_scroll_overflow(1, True), ('2', '2'))
        ae(s.smooth_scroll_overflow(1, False), ('', ''))
        ae(s.smooth_scroll(1, 7), 0)
        ae(region(s)['offset'], 0)
        ae(s.smooth_scroll(1, 1), 1)
        ae(lines(s)[1], '0145  6789')
        ae(s.smooth_scroll_overflow(1, True), ('3', '3'))
        # Reversing the direction restores columns from the overflow buffers
        ae(s.smooth_scroll(1, -1), -1)
        ae(region(s)['offset'], 0)
        ae(lines(s)[1], '01345 6789')
        ae(s.smooth_scroll(1, -1), -1)
        ae(region(s)['offset'], -(W - 1))
        ae(lines(s)[1], '01 3456789')
        ae(s.smooth_scroll_overflow(1, True), ('', ''))
        ae(s.smooth_scroll_overflow(1, False), ('', ''))
        # Huge scrolls only move as many columns as there are in the rectangle and its overflow buffer
        ae(s.smooth_scroll(1, 1000 * W), 1001)
        ae(lines(s)[1], '01    6789')

        # Selections inside the rectangle move with it
        s = self.create_screen(cols=10, lines=4)
        for y in range(s.lines):
            s.cursor_position(y + 1, 1)
            s.draw('0123456789')
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, 1, False, True))
        s.start_selection(3, 1)
        s.update_selection(4, 1)
        ae(s.text_for_selection(False, False), ('34',))
        ae(s.smooth_scroll(1, 1), 1)
        ae(s.text_for_selection(False, False), ('34',))
        ae(s.smooth_scroll(1, -1), -1)
        ae(s.smooth_scroll(1, -W), -1)
        ae(s.text_for_selection(False, False), ('34',))
        ae(s.smooth_scroll(1, 2 * W), 2)
        ae(s.text_for_selection(False, False), ('34',))
        ae(s.smooth_scroll(1, W), 1)
        self.assertFalse(s.has_selection())  # moved out of the rectangle

        # Moving the lines of the screen discards the overflow buffers
        s = self.create_screen(cols=10, lines=4)
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, 1, False, True))
        ae(s.smooth_scroll(1, 1), 1)
        parse_bytes(s, b'\x1b[S')
        r = region(s)
        ae((r['num_before'], r['num_after'], r['offset']), (0, 0, 0))

    def test_smooth_scroll_horizontal_multicell(self):
        ae = self.ae
        W = 10

        def cell(s, x, y):
            return s.cpu_cells(y, x)

        def setup(k=1):
            s = self.create_screen(cols=10, lines=4)
            self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, k, False, True))
            s.cursor_position(2, 3)
            s.draw('好xy')
            return s

        # Wide chars split between the rectangle and its overflow buffers are kept
        s = setup()
        ae(s.smooth_scroll(1, 1), 1)
        ae(s.smooth_scroll_overflow(1, True), ('好', ''))
        ae((cell(s, 2, 1)['x'], cell(s, 2, 1)['mcd']['width']), (1, 2))
        ae(str(s.line(1)), '  xy')
        # and restored when scrolling back
        ae(s.smooth_scroll(1, -1), -1)
        ae((cell(s, 2, 1)['x'], cell(s, 3, 1)['x']), (0, 1))
        ae(str(s.line(1)), '  好xy')
        ae(s.smooth_scroll_overflow(1, True), ('', ''))
        # overwriting a split char removes its part in the overflow buffer too
        ae(s.smooth_scroll(1, 1), 1)
        s.cursor_position(2, 3)
        s.draw('Z')
        ae(str(s.line(1)), '  Zxy')
        ae(s.smooth_scroll_overflow(1, True), (' ', ''))  # replaced by a space, as when overwriting chars on screen
        # also on the right
        s = setup()
        ae(s.smooth_scroll(1, -2 * W), -2)
        ae(str(s.line(1)), '    好')
        ae(s.smooth_scroll(1, -1), -1)
        ae(s.smooth_scroll_overflow(1, False), ('', ''))  # the char is followed by blank cells, nearest first
        ae(cell(s, 5, 1)['x'], 0)
        ae(s.smooth_scroll(1, 2 * W), 3)
        s = setup()
        ae(s.smooth_scroll(1, -3 * W), -3)
        ae(cell(s, 5, 1)['x'], 0)
        ae(s.smooth_scroll_overflow(1, False)[0], '')  # the right half of the char
        s.cursor_position(2, 6)
        s.draw('Z')
        self.assertIsNone(cell(s, 5, 1)['mcd'])
        ae(s.smooth_scroll(1, 1), 1)
        self.assertIsNone(cell(s, 5, 1)['mcd'])

        # A char whose other half was dropped from the overflow buffer is torn
        # when a blank column enters next to it
        s = setup()
        ae(s.smooth_scroll(1, 2 * W), 2)  # both halves moved out, the left half dropped
        ae(s.smooth_scroll(1, -W), -1)
        ae(cell(s, 2, 1)['x'], 1)
        ae(s.smooth_scroll(1, -W), -1)
        self.assertIsNone(cell(s, 3, 1)['mcd'])

        # Wide chars crossing the edges into cells outside the rectangle are removed
        s = self.create_screen(cols=10, lines=4)
        s.cursor_position(2, 2)
        s.draw('好')
        s.cursor_position(3, 6)
        s.draw('好')
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, 1, False, True))
        s.smooth_scroll(1, 1)
        ae(lines(s), ['', '', '', ''])
        # Multiline chars crossing the top or bottom edge are removed as well
        s = self.create_screen(cols=10, lines=6)
        s.cursor_position(1, 3)
        multicell(s, 'A', scale=2)
        self.assertTrue(s.smooth_scroll_define(1, 0, 1, 10, 4, 1, False, True))
        s.smooth_scroll(1, 1)
        for y in range(6):
            for x in range(10):
                self.assertIsNone(cell(s, x, y)['mcd'], (x, y))

    def test_smooth_scroll_horizontal_images(self):
        from .graphics import put_helpers

        ae = self.ae
        cw, ch = 10, H
        s, dx, dy, put_image, put_ref, layers, rect_eq = put_helpers(self, cw, ch, cols=10, lines=6)

        def cols():
            s.update_only_line_graphics_data()
            return sorted((round((r['dest_rect']['left'] + 1) / dx), round((r['dest_rect']['right'] + 1) / dx)) for r in layers(s))

        def put(x, y, num_cols=2, num_lines=1):
            s.cursor_position(y + 1, x + 1)
            put_image(s, cw * num_cols, ch * num_lines, num_cols=num_cols, num_lines=num_lines, cursor_movement=1)

        put(3, 2)  # inside
        put(1, 3)  # crossing the left edge
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 8, 5, 2, False, True))
        ae(cols(), [(1, 3), (3, 5)])
        ae(s.smooth_scroll(1, 1), 1)
        ae(cols(), [(1, 3), (2, 4)])
        ae(s.smooth_scroll(1, 2 * cw), 2)
        ae(cols(), [(0, 2), (1, 3)])  # in the overflow buffer
        ae(s.smooth_scroll(1, 2 * cw), 2)
        ae(cols(), [(1, 3)])  # moved out of the two columns of the overflow buffer
        ae(s.smooth_scroll(1, cw - 1), 0)
        ae(region(s)['offset'], 0)
        # When the region is removed images are clipped to its rectangle
        put(2, 2)
        ae(s.smooth_scroll(1, 1), 1)
        ae(cols(), [(1, 3), (1, 3)])
        s.smooth_scroll_remove(1)
        ae(cols(), [(1, 3), (2, 3)])

    def test_smooth_scroll_horizontal_pause_rendering(self):
        ae = self.ae
        s = self.create_screen(cols=10, lines=4)
        for y in range(s.lines):
            s.cursor_position(y + 1, 1)
            s.draw('0123456789')
        self.assertTrue(s.smooth_scroll_define(1, 2, 1, 6, 3, 2, False, True))
        ae(s.smooth_scroll(1, 3), 1)
        self.assertTrue(s.pause_rendering(True))
        ae(s.smooth_scroll(1, -13), -2)
        s.smooth_scroll_remove(1)
        s.garbage_collect_text_cache()
        self.assertTrue(s.pause_rendering(False))

    def test_smooth_scroll_protocol(self):
        from kitty.fast_data_types import SMOOTH_SCROLL_CODE

        ae = self.ae
        s = self.create_screen(cols=10, lines=6)

        def cmd(payload):
            parse_bytes(s, f'\x1b]{SMOOTH_SCROLL_CODE};{payload}\x1b\\'.encode())

        def rect(id=1):
            r = region(s, id)
            return r['left'], r['top'], r['right'], r['bottom'], r['capacity'], r['horizontal'], r['private_overflow']

        def reply(payload):
            s.callbacks.clear()
            cmd(payload)
            return s.callbacks.wtcbuf.decode()

        # coordinates are one based, the size defaults to the rest of the screen
        cmd('a=d:i=1')
        ae(rect(), (0, 0, 10, 6, 1, False, False))
        cmd('a=d:i=1:x=3:y=2:w=4:h=3:k=2:p=1')
        ae(rect(), (2, 1, 6, 4, 2, False, True))
        cmd('a=d:i=2:x=7:o=h:k=100')
        ae(rect(2), (6, 0, 10, 6, 4, True, False))  # the capacity is clamped to the width
        # invalid commands are ignored
        for bad in ('a=d', 'a=d:i=3:x=11', 'a=d:i=3:y=7', 'a=d:i=3:x=9:w=3', 'a=d:i=3:y=6:h=2', 'a=d:i=3:x=3:y=3', 'a=d:i=3:Q=1'):
            cmd(bad)
            ae(len(s.smooth_scroll_regions()), 2, bad)
        self.assertEqual(s.callbacks.wtcbuf, b'')  # nothing but queries reply
        # scrolling
        fill(s)
        cmd('a=s:i=1:d=5')
        ae((region(s)['offset'], region(s)['num_before']), (H - 5, 1))
        cmd('a=s:i=1:d=-5')
        ae(region(s)['offset'], 0)
        cmd('a=s:d=5')  # no id
        ae(region(s)['offset'], 0)
        # removing
        cmd('a=r:i=1')
        ae([r['id'] for r in s.smooth_scroll_regions()], [2])
        cmd('a=d:i=1:h=1')
        cmd('a=r')
        ae(s.smooth_scroll_regions(), ())

        # queries
        prefix = f'\x1b]{SMOOTH_SCROLL_CODE};a=q'
        ae(reply('a=q'), f'{prefix}:n=4\x1b\\')
        ae(reply('a=q:e=d:o=h:k=3:p=1:x=2:d=4'), f'{prefix}:e=d:x=2:k=3:o=h:p=1\x1b\\')
        ae(reply('a=q:e=s:d=-4:x=2'), f'{prefix}:e=s:d=-4\x1b\\')
        ae(reply('a=q:e=r:i=3'), f'{prefix}:e=r\x1b\\')
        ae(reply('a=q:e=Z:d=1'), f'{prefix}\x1b\\')  # unknown action
        ae(reply('a=q:Z=1'), '')  # unknown keys make the command malformed
        ae(s.smooth_scroll_regions(), ())  # queries have no effect
