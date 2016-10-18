#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest

from kitty.screen import mo


class TestScreen(BaseTest):

    def test_draw_fast(self):
        # Test in line-wrap, non-insert mode
        s, t = self.create_screen()
        s.draw(b'a' * 5)
        self.ae(str(s.linebuf[0]), 'a' * 5)
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw(b'b' * 7)
        self.assertTrue(s.linebuf[1].continued)
        self.assertTrue(s.linebuf[2].continued)
        self.ae(str(s.linebuf[0]), 'a' * 5)
        self.ae(str(s.linebuf[1]), 'b' * 5)
        self.ae(str(s.linebuf[2]), 'b' * 2 + ' ' * 3)
        self.ae(s.cursor.x, 2), self.ae(s.cursor.y, 2)
        self.assertChanges(t, ignore='cursor', cells={1: ((0, 4),), 2: ((0, 1),)})
        s.draw(b'c' * 15)
        self.ae(str(s.linebuf[0]), 'b' * 5)
        self.ae(str(s.linebuf[1]), 'bbccc')

        # Now test without line-wrap
        s.reset(), t.reset()
        s.reset_mode(mo.DECAWM)
        s.draw(b'0123456789')
        self.ae(str(s.linebuf[0]), '56789')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw(b'ab')
        self.ae(str(s.linebuf[0]), '567ab')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((3, 4),)})

        # Now test in insert mode
        s.reset(), t.reset()
        s.set_mode(mo.IRM)
        s.draw(b'12345' * 5)
        s.cursor_back(5)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 4)
        t.reset()
        s.draw(b'ab')
        self.ae(str(s.linebuf[4]), 'ab123')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))
        self.assertChanges(t, ignore='cursor', cells={4: ((0, 4),)})
