#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial

from . import BaseTest

from kitty.fast_data_types import parse_bytes, parse_bytes_dump


class CmdDump(list):

    def __call__(self, *a):
        self.append(a)


class TestScreen(BaseTest):

    def parse_buytes_dump(self, s, x, *cmds):
        cd = CmdDump()
        if isinstance(x, str):
            x = x.encode('utf-8')
        parse_bytes_dump(s, x, cd)
        self.ae(tuple(cd), cmds)

    def test_simple_parsing(self):
        s = self.create_screen()
        pb = partial(self.parse_buytes_dump, s)

        pb('12')
        self.ae(str(s.line(0)), '12   ')
        pb('3456')
        self.ae(str(s.line(0)), '12345')
        self.ae(str(s.line(1)), '6    ')
        pb(b'\n123\n\r45', ('screen_linefeed', '\n'), ('screen_linefeed', '\n'), ('screen_carriage_return', '\r'))
        self.ae(str(s.line(1)), '6    ')
        self.ae(str(s.line(2)), ' 123 ')
        self.ae(str(s.line(3)), '45   ')
        parse_bytes(s, b'\rabcde')
        self.ae(str(s.line(3)), 'abcde')
        parse_bytes(s, '\rßxyz1'.encode('utf-8'))
        self.ae(str(s.line(3)), 'ßxyz1')
        pb('ニチ '.encode('utf-8'))
        self.ae(str(s.line(4)), 'ニチ ')

    def test_esc_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_buytes_dump, s)
        pb('12\033Da', ('screen_index',))
        self.ae(str(s.line(0)), '12   ')
        self.ae(str(s.line(1)), '  a  ')
        pb('\033x', ('Unknown char in escape_dispatch: ', ord('x')))
        pb('\033c123', ('screen_reset',))
        self.ae(str(s.line(0)), '123  ')
