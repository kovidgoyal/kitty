#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.fast_data_types import parse_glyph_command

from .base import BaseTest, parse_bytes


class Dump(list):
    def __call__(self, window_id, *a):
        if a and a[0] == 'bytes':
            return
        self.append(a)


class TestGlyphProtocol(BaseTest):
    def test_glyph_command_parsing(self):
        def p(x):
            return parse_glyph_command(('25a1;' + x).encode())

        def ae(x, **expected):
            expected.setdefault('fmt', '')
            expected.setdefault('reply', 1)
            if not expected.pop('placement_invalid', False):
                expected.setdefault('fit', 'contain')
                expected.setdefault('align', ('center', 'center'))
            else:
                expected['placement_invalid'] = True
            self.ae(p(x), expected)

        def err(x, msg):
            with self.assertRaisesRegex(ValueError, msg):
                parse_glyph_command(x.encode())

        err('25a1', 'not a glyph protocol message')
        err('25a2;s', 'not a glyph protocol message')
        err('G25a1;s', 'not a glyph protocol message')
        err('25a1;', 'invalid verb')
        err('25a1;ss', 'invalid verb')
        err('25a1;x', 'unknown verb')
        err('25a1;S', 'unknown verb')

        ae('s', verb='s')
        ae('s;', verb='s')
        ae('s;unknown=1;fmt=glyf', verb='s', fmt='glyf')

        # query
        ae('q;cp=e0a0', verb='q', cp=0xE0A0)
        ae('q;cp=E0A0', verb='q', cp=0xE0A0)
        ae('q;cp=100000', verb='q', cp=0x100000)
        ae('q;cp=10ffff', verb='q', cp=0x10FFFF)
        for bad in ('110000', 'd800', 'dfff', '', 'xyz', '123456789', '-1', ' 41'):
            ae(f'q;cp={bad}', verb='q', cp=None)
        ae('q;grapheme=1f468,200d,1f469', verb='q', grapheme=(0x1F468, 0x200D, 0x1F469))
        ae('q;grapheme=' + ','.join(['41'] * 32), verb='q', grapheme=(0x41,) * 32)
        ae('q;grapheme=' + ','.join(['41'] * 33), verb='q', grapheme=None)
        ae('q;grapheme=41,,42', verb='q', grapheme=None)
        ae('q;grapheme=41,d800', verb='q', grapheme=None)
        ae('q;grapheme=', verb='q', grapheme=None)
        ae('q;cp=41;grapheme=42', verb='q', cp=0x41, grapheme=(0x42,))
        # fields that are not key=value pairs are ignored
        ae('q;junk;cp=41', verb='q', cp=0x41)

        # clear
        ae('c', verb='c')
        ae('c;cp=100001;reply=0', verb='c', cp=0x100001, reply=0)
        ae('c;reply=2', verb='c', reply=2)
        ae('c;reply=7', verb='c', reply=1)
        ae('c;reply=', verb='c', reply=1)

        # register, the payload is the last field, by position
        ae('r', verb='r')
        ae('r;', verb='r', payload=b'')
        ae('r;payload', verb='r', payload=b'payload')
        ae('r;cp=100000', verb='r', payload=b'cp=100000')
        ae('r;cp=100000;fmt=glyf;AAA=', verb='r', cp=0x100000, fmt='glyf', payload=b'AAA=')
        ae(
            'r;cp=100000;fmt=vg;vb=0,0,24,24;fill=nonzero,fg:M0 0H24V24Z',
            verb='r',
            cp=0x100000,
            fmt='vg',
            vb=(0, 0, 24, 24),
            payload=b'fill=nonzero,fg:M0 0H24V24Z',
        )
        ae('r;fmt=colrv0;x', verb='r', fmt='colrv0', payload=b'x')
        ae('r;fmt=colrv1;x', verb='r', fmt='colrv1', payload=b'x')
        ae('r;fmt=svg;x', verb='r', fmt='unknown', payload=b'x')
        ae('r;cp=100000;;;x', verb='r', cp=0x100000, payload=b'x')
        # last key wins
        ae('r;fmt=glyf;fmt=vg;x', verb='r', fmt='vg', payload=b'x')
        # ignored keys
        ae('r;width=2;upm=1000;size=height;pad=0,0,0,0;x', verb='r', payload=b'x')

        # placement
        ae('r;vb=-1.5 2e1 , 3 .5;x', verb='r', vb=(-1.5, 20, 3, 0.5), payload=b'x')
        ae('r;vb=0 0 1e6 1000000;x', verb='r', vb=(0, 0, 1e6, 1e6), payload=b'x')
        for bad in (
            '0,0,24',
            '0,0,24,24,1',
            '0,0,0,24',
            '0,0,24,-1',
            '0,,0,24,24',
            '0,0,24,24 ',
            '0,0,1.,24',
            '1000001,0,1,1',
            '0,0,1,1e7',
            'a,b,c,d',
            '0 0 1 1x',
            '',
        ):
            ae(f'r;vb={bad};x', verb='r', placement_invalid=True, payload=b'x')
        ae('r;fit=cover;align=start,end;x', verb='r', fit='cover', align=('start', 'end'), payload=b'x')
        ae('r;fit=stretch;x', verb='r', fit='stretch', payload=b'x')
        for bad in ('fit=fill', 'fit=', 'align=center', 'align=center,baseline', 'align=start,end,', 'align=,'):
            ae(f'r;{bad};x', verb='r', placement_invalid=True, payload=b'x')
        # extreme aspect ratios
        ae('r;vb=0 0 4096 1;x', verb='r', vb=(0, 0, 4096, 1), payload=b'x')
        ae('r;vb=0 0 0.5 2048;x', verb='r', vb=(0, 0, 0.5, 2048), payload=b'x')
        for bad in ('0 0 4097 1', '0 0 1 1e-6', '0 0 1e-45 1e-40'):
            ae(f'r;vb={bad};x', verb='r', placement_invalid=True, payload=b'x')
        # numbers with very many digits and large exponents
        zeros = '0' * 200000
        ae(f'r;vb=0.{zeros}1e200001,0,1,1;x', verb='r', vb=(1, 0, 1, 1), payload=b'x')
        ae(f'r;vb=0.{zeros}1e2000000,0,1,1;x', verb='r', placement_invalid=True, payload=b'x')
        ae(f'r;vb=1{zeros}e-2000000,0,1,1;x', verb='r', vb=(0, 0, 1, 1), payload=b'x')
        ae(f'r;vb=1{zeros}e-200000,0,1,1;x', verb='r', vb=(1, 0, 1, 1), payload=b'x')

    def test_glyph_command_via_parser(self):
        s = self.create_screen()
        d = Dump()
        parse_bytes(s, b'\x1b_25a1;q;cp=41\x1b\\', d)
        self.ae(d, [('glyph_command', {'verb': 'q', 'cp': 0x41, 'fmt': '', 'reply': 1, 'fit': 'contain', 'align': ('center', 'center')})])
        d = Dump()
        parse_bytes(s, b'\x1b_25a1;z\x1b\\', d)
        self.ae(d, [('error', 'Ignoring APC escape code that is not a valid glyph protocol message: unknown verb')])
        d = Dump()
        parse_bytes(s, b'\x1b_2xyz\x1b\\', d)
        self.ae(d, [('error', 'Ignoring APC escape code that is not a valid glyph protocol message: not a glyph protocol message')])

    def test_glyph_support_and_query_replies(self):
        s = self.create_screen()

        def q(cmd, expected):
            s.callbacks.wtcbuf = b''
            parse_bytes(s, f'\x1b_25a1;{cmd}\x1b\\'.encode())
            self.ae(s.callbacks.wtcbuf.decode(), ''.join(f'\x1b_25a1;{x}\x1b\\' for x in expected))

        q('s', ['s;fmt='])
        # replies are sent in the order the requests arrive
        q('s\x1b\\\x1b_25a1;q;cp=41', ['s;fmt=', 'q;cp=41;reason=unknown'])
        q('q;cp=E0A0', ['q;cp=e0a0;reason=unknown'])
        q('q;cp=100000', ['q;cp=100000;status='])
        q('q;cp=1003ff', ['q;cp=1003ff;status='])
        q('q;cp=100400', ['q;cp=100400;reason=unknown'])
        q('q', ['q;reason=malformed_query'])
        q('q;cp=d800', ['q;reason=malformed_query'])
        q('q;cp=41;grapheme=42', ['q;reason=malformed_query'])
        q('q;grapheme=41,d800', ['q;reason=malformed_query'])
        q('q;grapheme=1F468,200d,1f469', ['q;grapheme=1f468,200d,1f469;reason=unsupported'])
        q('q;grapheme=' + ','.join(['10ffff'] * 32), ['q;grapheme=' + ','.join(['10ffff'] * 32) + ';reason=unsupported'])
