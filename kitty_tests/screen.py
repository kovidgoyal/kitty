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
        self.ae(str(s.line(0)), 'a' * 5)
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw(b'b' * 7)
        self.assertTrue(s.linebuf.is_continued(1))
        self.assertTrue(s.linebuf.is_continued(2))
        self.ae(str(s.line(0)), 'a' * 5)
        self.ae(str(s.line(1)), 'b' * 5)
        self.ae(str(s.line(2)), 'b' * 2 + ' ' * 3)
        self.ae(s.cursor.x, 2), self.ae(s.cursor.y, 2)
        self.assertChanges(t, ignore='cursor', cells={1: ((0, 4),), 2: ((0, 1),)})
        s.draw(b'c' * 15)
        self.ae(str(s.line(0)), 'b' * 5)
        self.ae(str(s.line(1)), 'bbccc')

        # Now test without line-wrap
        s.reset(), t.reset()
        s.reset_mode(mo.DECAWM)
        s.draw(b'0123456789')
        self.ae(str(s.line(0)), '01239')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw(b'ab')
        self.ae(str(s.line(0)), '0123b')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((4, 4),)})

        # Now test in insert mode
        s.reset(), t.reset()
        s.set_mode(mo.IRM)
        s.draw(b'12345' * 5)
        s.cursor_back(5)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 4)
        t.reset()
        s.draw(b'ab')
        self.ae(str(s.line(4)), 'ab123')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))
        self.assertChanges(t, ignore='cursor', cells={4: ((0, 4),)})

    def test_draw_char(self):
        # Test in line-wrap, non-insert mode
        s, t = self.create_screen()
        s.draw('ココx'.encode('utf-8'))
        self.ae(str(s.line(0)), 'ココx')
        self.ae(tuple(map(s.line(0).width, range(5))), (2, 0, 2, 0, 1))
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw('ニチハ'.encode('utf-8'))
        self.ae(str(s.line(0)), 'ココx')
        self.ae(str(s.line(1)), 'ニチ ')
        self.ae(str(s.line(2)), 'ハ   ')
        self.assertChanges(t, ignore='cursor', cells={1: ((0, 3),), 2: ((0, 1),)})
        self.ae(s.cursor.x, 2), self.ae(s.cursor.y, 2)
        s.draw('Ƶ̧\u0308'.encode('utf-8'))
        self.ae(str(s.line(2)), 'ハƵ̧\u0308  ')
        self.ae(s.cursor.x, 3), self.ae(s.cursor.y, 2)
        self.assertChanges(t, ignore='cursor', cells={2: ((2, 2),)})
        s.draw(b'xy'), s.draw('\u0306'.encode('utf-8'))
        self.ae(str(s.line(2)), 'ハƵ̧\u0308xy\u0306')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 2)
        self.assertChanges(t, ignore='cursor', cells={2: ((3, 4),)})
        s.draw(b'c' * 15)
        self.ae(str(s.line(0)), 'ニチ ')

        # Now test without line-wrap
        s.reset(), t.reset()
        s.reset_mode(mo.DECAWM)
        s.draw('0\u030612345\u03066789\u0306'.encode('utf-8'))
        self.ae(str(s.line(0)), '0\u03061239\u0306')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw('ab\u0306'.encode('utf-8'))
        self.ae(str(s.line(0)), '0\u0306123b\u0306')
        self.ae(s.cursor.x, 5), self.ae(s.cursor.y, 0)
        self.assertChanges(t, ignore='cursor', cells={0: ((4, 4),)})

        # Now test in insert mode
        s.reset(), t.reset()
        s.set_mode(mo.IRM)
        s.draw('1\u03062345'.encode('utf-8') * 5)
        s.cursor_back(5)
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 4)
        t.reset()
        s.draw('a\u0306b'.encode('utf-8'))
        self.ae(str(s.line(4)), 'a\u0306b1\u030623')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))
        self.assertChanges(t, ignore='cursor', cells={4: ((0, 4),)})

    def test_char_manipulation(self):
        s, t = self.create_screen()

        def init():
            s.reset(), t.reset()
            s.draw(b'abcde')
            s.cursor.bold = True
            s.cursor_back(4)
            t.reset()
            self.ae(s.cursor.x, 1)

        init()
        s.insert_characters(2)
        self.ae(str(s.line(0)), 'a  bc')
        self.assertTrue(s.line(0).cursor_from(1).bold)
        self.assertChanges(t, ignore='cursor', cells={0: ((1, 4),)})
        s.cursor_back(1)
        s.insert_characters(20)
        self.ae(str(s.line(0)), '     ')
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})
        s.draw('xココ'.encode('utf-8'))
        s.cursor_back(5)
        t.reset()
        s.insert_characters(1)
        self.ae(str(s.line(0)), ' xコ ')
        self.assertChanges(t, ignore='cursor', cells={0: ((0, 4),)})

        init()
        s.delete_characters(2)
        self.ae(str(s.line(0)), 'ade  ')
        self.assertTrue(s.line(0).cursor_from(4).bold)
        self.assertFalse(s.line(0).cursor_from(2).bold)
        self.assertChanges(t, ignore='cursor', cells={0: ((1, 4),)})

        init()
        s.erase_characters(2)
        self.ae(str(s.line(0)), 'a  de')
        self.assertTrue(s.line(0).cursor_from(1).bold)
        self.assertFalse(s.line(0).cursor_from(4).bold)
        self.assertChanges(t, cells={0: ((1, 2),)})
        s.erase_characters(20)
        self.ae(str(s.line(0)), 'a    ')

        init()
        s.erase_in_line()
        self.ae(str(s.line(0)), 'a    ')
        self.assertTrue(s.line(0).cursor_from(1).bold)
        self.assertFalse(s.line(0).cursor_from(0).bold)
        self.assertChanges(t, cells={0: ((1, 4),)})
        init()
        s.erase_in_line(1)
        self.ae(str(s.line(0)), '  cde')
        self.assertChanges(t, cells={0: ((0, 1),)})
        init()
        s.erase_in_line(2)
        self.ae(str(s.line(0)), '     ')
        self.assertChanges(t, cells={0: ((0, 4),)})
        init()
        s.erase_in_line(2, private=True)
        self.ae((False, False, False, False, False), tuple(map(lambda i: s.line(0).cursor_from(i).bold, range(5))))

    def test_erase_in_screen(self):
        s, t = self.create_screen()

        def init():
            s.reset()
            s.draw(b'12345' * 5)
            t.reset()
            s.cursor.x, s.cursor.y = 2, 1
            s.cursor.bold = True

        init()
        s.erase_in_display()
        self.ae(s.display, ('12345', '12   ', '     ', '     ', '     '))
        self.assertChanges(t, lines={2, 3, 4}, cells={1: ((2, 4),)})

        init()
        s.erase_in_display(1)
        self.ae(s.display, ('     ', '   45', '12345', '12345', '12345'))
        self.assertChanges(t, lines={0}, cells={1: ((0, 2),)})

        init()
        s.erase_in_display(2)
        self.ae(s.display, ('     ', '     ', '     ', '     ', '     '))
        self.assertChanges(t, lines=set(range(5)))
        self.assertTrue(s.line(0).cursor_from(1).bold)
        init()
        s.erase_in_display(2, private=True)
        self.ae(s.display, ('     ', '     ', '     ', '     ', '     '))
        self.assertChanges(t, lines=set(range(5)))
        self.assertFalse(s.line(0).cursor_from(1).bold)

    def test_cursor_movement(self):
        s, t = self.create_screen()
        s.draw(b'12345' * 5)
        t.reset()
        s.cursor_up(2)
        self.ae((s.cursor.x, s.cursor.y), (4, 2))
        s.cursor_up1()
        self.ae((s.cursor.x, s.cursor.y), (0, 1))
        s.cursor_forward(3)
        self.ae((s.cursor.x, s.cursor.y), (3, 1))
        s.cursor_back()
        self.ae((s.cursor.x, s.cursor.y), (2, 1))
        s.cursor_down()
        self.ae((s.cursor.x, s.cursor.y), (2, 2))
        s.cursor_down1(5)
        self.ae((s.cursor.x, s.cursor.y), (0, 4))

        s, t = self.create_screen()
        s.draw(b'12345' * 5)
        s.index()
        self.ae(str(s.line(4)), ' ' * 5)
        for i in range(4):
            self.ae(str(s.line(i)), '12345')
        s.draw(b'12345' * 5)
        s.cursor_up(5)
        s.reverse_index()
        self.ae(str(s.line(0)), ' ' * 5)
        for i in range(1, 5):
            self.ae(str(s.line(i)), '12345')
