#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest

from kitty.fast_data_types import parse_bytes


class TestScreen(BaseTest):

    def test_simple_parsing(self):
        s = self.create_screen()
        parse_bytes(s, b'12')
        self.ae(str(s.line(0)), '12   ')
        parse_bytes(s, b'3456')
        self.ae(str(s.line(0)), '12345')
        self.ae(str(s.line(1)), '6    ')
        parse_bytes(s, b'\n123\n\r45')
        self.ae(str(s.line(1)), '6    ')
        self.ae(str(s.line(2)), ' 123 ')
        self.ae(str(s.line(3)), '45   ')
        parse_bytes(s, b'\rabcde')
        self.ae(str(s.line(3)), 'abcde')
        parse_bytes(s, '\rßxyz1'.encode('utf-8'))
        self.ae(str(s.line(3)), 'ßxyz1')
        parse_bytes(s, 'ニチ '.encode('utf-8'))
        self.ae(str(s.line(4)), 'ニチ ')
