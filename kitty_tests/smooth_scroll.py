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
            ae((region(s)['num_above'], region(s)['num_below'], region(s)['offset']), (0, 1, -15))
            ae(s.smooth_scroll(1, 2), 1)
            ae((region(s)['num_above'], region(s)['num_below'], region(s)['offset']), (1, 0, 3))
            return s

        def discarded(s):
            r = region(s)
            ae((r['num_above'], r['num_below'], r['offset']), (0, 0, 0))

        # Moving the lines of the screen discards the overflow buffers
        for cmd in (b'\x1b[6H\n', b'\x1b[S', b'\x1b[T', b'\x1bM', b'\x1b[2;1H\x1b[L', b'\x1b[2;1H\x1b[M', b'\x1b[2J', b'\x1b[3J', b'\x1b[22J', b'\x1b#8'):
            s = setup()
            parse_bytes(s, cmd)
            discarded(s)
        # but not moving lines that do not intersect the region
        s = setup()
        parse_bytes(s, b'\x1b[5;6r\x1b[6H\n\x1b[r')
        ae(region(s)['num_above'], 1)
        # Erasing parts of the screen does not affect the region
        s = setup()
        parse_bytes(s, b'\x1b[2;1H\x1b[K\x1b[J\x1b[1J')
        ae(region(s)['num_above'], 1)
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
        ae((region(s)['num_below'], region(s)['offset']), (1, -15))
        parse_bytes(s, b'\x1b[5H\n')
        ae((region(s)['num_below'], region(s)['offset']), (0, 0))
        ae(s.smooth_scroll(1, 5), 1)
        parse_bytes(s, b'\x1b[5H\n')
        ae((region(s)['num_below'], region(s)['offset']), (0, 15))

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
        ae(s.smooth_scroll_overflow(1, False), ('',) * r['num_below'])
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
