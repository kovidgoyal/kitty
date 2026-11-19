#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.fast_data_types import parse_glyph_command, parse_vg

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

    def test_vg_parsing(self):
        vb = (0, 0, 24, 24)

        def pv(payload, vb=vb):
            return parse_vg(payload.encode(), vb)

        def path(d, vb=vb):
            return pv('fill=nonzero,fg:' + d, vb)['layers'][0]['path']

        def bad(payload, reason='malformed_payload', msg='', vb=vb):
            with self.assertRaisesRegex(ValueError, f'^{reason}: {msg}', msg=payload):
                pv(payload, vb)

        def badpath(d, reason='malformed_payload', msg=''):
            bad('fill=nonzero,fg:' + d, reason, msg)

        # numbers and separators
        self.ae(path('M1 2'), 'M 1 2')
        self.ae(path('M1,2'), 'M 1 2')
        self.ae(path('M 1 , 2'), 'M 1 2')
        self.ae(path('M-1-2'), 'M -1 -2')
        self.ae(path('M.5.5'), 'M 0.5 0.5')
        self.ae(path('M1.5.5'), 'M 1.5 0.5')
        self.ae(path('M+1e1-1E-1'), 'M 10 -0.1')
        self.ae(path('M0.1e+1 2'), 'M 1 2')
        self.ae(path('M 1 2 '), 'M 1 2')
        badpath('M1. 2', msg='invalid or missing number')
        badpath('M1,,2')
        badpath('M,1 2')
        badpath('M1 2,')
        badpath('M1 2,L3 4', msg='comma not followed by a number')
        badpath('M1e 2')
        badpath('M1 2 3')
        badpath('M1 2 L')
        badpath('M1 2 X3 4', msg='invalid path command')
        badpath('M1 2Z3 4')
        badpath('M1 1e39', 'outline_too_large')
        badpath('M1 1e9999', 'outline_too_large')
        self.ae(path('M1 1e-9999'), 'M 1 0')
        bad('stroke=1/miter,fg:M0 0', msg='invalid stroke cap')
        badpath('', msg='path data must start with a moveto')
        badpath('  ', msg='path data must start with a moveto')
        badpath('L1 2', msg='path data must start with a moveto')

        # commands
        self.ae(path('M0 0 1 1 2 2'), 'M 0 0 L 1 1 L 2 2')
        self.ae(path('m1 1 1 1'), 'M 1 1 L 2 2')
        self.ae(path('M1 1h2v3H0V0'), 'M 1 1 L 3 1 L 3 4 L 0 4 L 0 0')
        self.ae(path('M1 1l1 1zl1 1'), 'M 1 1 L 2 2 Z M 1 1 L 2 2')
        self.ae(path('M1 1l1 1zm1 1'), 'M 1 1 L 2 2 Z M 2 2')
        self.ae(path('M0 0L1 1ZZz'), 'M 0 0 L 1 1 Z')
        self.ae(path('M0 0Z'), 'M 0 0 Z')
        self.ae(path('M0 0C1 1 2 2 3 3S5 5 6 6'), 'M 0 0 C 1 1 2 2 3 3 C 4 4 5 5 6 6')
        self.ae(path('M0 0c1 1 2 2 3 3s2 2 3 3'), 'M 0 0 C 1 1 2 2 3 3 C 4 4 5 5 6 6')
        self.ae(path('M1 1S2 2 3 3'), 'M 1 1 C 1 1 2 2 3 3')
        self.ae(path('M0 0Q1 1 2 0T4 0'), 'M 0 0 Q 1 1 2 0 Q 3 -1 4 0')
        self.ae(path('M0 0q1 1 2 0t2 0t2 0'), 'M 0 0 Q 1 1 2 0 Q 3 -1 4 0 Q 5 1 6 0')
        self.ae(path('M1 1T3 3'), 'M 1 1 Q 1 1 3 3')
        self.ae(path('M0 0C1 1 2 2 3 3T5 5'), 'M 0 0 C 1 1 2 2 3 3 Q 3 3 5 5')

        # arcs
        self.ae(path('M0 0A0 5 0 0 1 10 0'), 'M 0 0 L 10 0')
        self.ae(path('M1 1A5 5 0 0 1 1 1'), 'M 1 1')
        self.ae(path('M0 0a5 5 0 1010 0'), path('M0 0A5 5 0 1 0 10 0'))
        self.ae(path('M0 0a5,5,0,1,0,10,0'), path('M0 0A5 5 0 1 0 10 0'))
        # half circle: two quarter turns
        self.ae(path('M2 12A10 10 0 0 1 22 12').count('C'), 2)
        # radii that are too small are scaled up to a half circle
        self.ae(path('M2 12A1 1 0 0 1 22 12'), path('M2 12A10 10 0 0 1 22 12'))
        # three quarters of a circle
        self.ae(path('M12 2A10 10 0 1 1 2 12').count('C'), 3)
        # less than a quarter
        self.ae(path('M12 2A10 10 0 0 1 19.07 4.93').count('C'), 1)
        p = path('M12 2A10 10 0 0 1 22 12').split()
        self.ae(p[-2:], ['22', '12'])
        self.ae(len(p), 3 + 7)
        # Control points of a quarter circle are at 4/3*tan(pi/8)*r from the end points
        k = 4 / 3 * 0.41421356237 * 10
        self.assertAlmostEqual(float(p[4]), 12 + k, places=3)
        self.assertAlmostEqual(float(p[7]), 12 - k, places=3)
        # drawing after an arc of identical endpoints
        self.ae(path('M1 1A5 5 0 0 1 1 1L2 2'), 'M 1 1 L 2 2')
        badpath('M0 0A5 5 0 2 0 10 0', msg='invalid arc flag')
        badpath('M0 0A5 5 0 1 0 10', msg='invalid or missing number')

        # layers
        r = pv(
            'fill=evenodd,#FF000080:M0 0|stroke=2,fg@0.5:M0 0|stroke=1.5/butt/miter10.5,#00ff00:M0 0|stroke=1/square/bevel,fg:M0 0|'
            'clip=1,nonzero,m 1 0 0 1 2 3:M0 0|'
            'fill=nonzero,fg,m2 0 0 2 0 0:M0 0'
        )
        self.assertTrue(r['uses_fg'])
        self.assertTrue(r['uses_fixed_color'])
        l0, l1, l2, l3, l4, l5 = r['layers']
        self.ae(l0['rule'], 'evenodd')
        self.ae(l0['paint'][:3], (1, 0, 0))
        self.assertAlmostEqual(l0['paint'][3], 128 / 255)
        self.ae(l1, {'kind': 'stroke', 'path': 'M 0 0', 'matrix': None, 'paint': 'fg@0.5', 'width': 2, 'cap': 'round', 'join': 'round', 'miter_limit': 4})
        self.ae((l2['cap'], l2['join'], l2['miter_limit'], l2['width']), ('butt', 'miter', 10.5, 1.5))
        self.ae((l3['cap'], l3['join']), ('square', 'bevel'))
        self.ae(l4, {'kind': 'clip', 'path': 'M 0 0', 'matrix': (1, 0, 0, 1, 2, 3), 'rule': 'nonzero', 'clip_count': 1})
        self.ae(l5['matrix'], (2, 0, 0, 2, 0, 0))
        self.assertFalse(pv('fill=nonzero,#000000:M0 0')['uses_fg'])
        self.assertFalse(pv('fill=nonzero,fg:M0 0')['uses_fixed_color'])
        self.ae(pv('stroke=1/round/miter,fg:M0 0')['layers'][0]['miter_limit'], 4)
        self.ae(pv('stroke=1/butt/miter1,fg:M0 0')['layers'][0]['miter_limit'], 1)
        for x in (
            'stroke=0,fg',
            'stroke=-1,fg',
            'stroke=1/flat,fg',
            'stroke=1/round/sharp,fg',
            'stroke=1/round/miter0.5,fg',
            'stroke=1/round/miter1001,fg',
            'stroke=1/round/miter/,fg',
            'stroke=1',
            'stroke=1/,fg',
            'fill=nonzero',
            'fill=winding,fg',
            'fill=nonzero,fg,',
            'fill=nonzero,fg,m',
            'fill=nonzero,fg,m 1 0 0 1 0',
            'fill=nonzero,fg,m 1 0 0 1 0 0 1',
            'fill=nonzero,fg ,m 1 0 0 1 0 0',
            'fill=nonzero,fg, m 1 0 0 1 0 0',
            'fill=nonzero,fgx',
            'fill=nonzero,fg@',
            'fill=nonzero,fg@1.5',
            'fill=nonzero,fg@-0.5',
            'fill=nonzero,#fff',
            'fill=nonzero,#fffffff',
            'fill=nonzero,#ff00ff00f',
            'fill=nonzero,#gggggg',
            'fill=nonzero,red',
            'blur=1,fg',
            'clip=0,nonzero',
            'clip=128,nonzero',
            'clip=1.5,nonzero',
            'clip=1',
            'clip=1,fg',
            'fill=nonzero,fg,m 0 0 0 0 0 0',
            'fill=nonzero,fg,m 4097 0 0 1 0 0',
            'fill=nonzero,fg,m 1 0 0 0.0002 0 0',
            'stroke=25,fg',
            'stroke=13,fg,m 2 0 0 2 0 0',
        ):
            bad(x + ':M0 0')
        self.ae(len(pv('stroke=24,fg:M0 0|stroke=6,fg,m 4 0 0 1 0 0:M0 0|fill=nonzero,fg,m 4096 0 0 1 0 0:M0 0')['layers']), 3)
        bad('fill=nonzero,fg', msg='layer has no path data')
        bad('fill=nonzero,fg:M0 0|', msg='layer has no path data')
        bad('fill=nonzero,fg:M0 0\tL1 1', msg='payload contains invalid characters')
        bad('fill=nonzero,fg:M0 0\x7fL1 1', msg='payload contains invalid characters')

        # clips
        self.ae(len(pv('clip=2,evenodd:M0 0|fill=nonzero,fg:M0 0|stroke=1,fg:M0 0|clip=1,nonzero:M0 0|fill=nonzero,fg:M0 0')['layers']), 5)
        bad('clip=2,evenodd:M0 0|fill=nonzero,fg:M0 0', msg='clip layer applies to layers that do not exist')
        bad('clip=2,evenodd:M0 0|clip=1,nonzero:M0 0|fill=nonzero,fg:M0 0', msg='clip layers cannot be clipped')
        bad('fill=nonzero,fg:M0 0|clip=1,nonzero:M0 0')

        # gradients
        g = pv('fill=nonzero,lin(0 0 24 0 / 0 fg / 0.5 fg@0.5 / 1 #0000ff):M0 0')['layers'][0]['paint']
        self.ae(g, {'type': 'lin', 'params': (0, 0, 24, 0), 'spread': 'pad', 'matrix': None, 'stops': ((0, 'fg'), (0.5, 'fg@0.5'), (1, (0, 0, 1, 1)))})
        g = pv('fill=nonzero,rad(1,2,0,3,4,5 repeat m 1 0 0 1 0 0/0 fg/0 #000000):M0 0')['layers'][0]['paint']
        self.ae(g, {'type': 'rad', 'params': (1, 2, 0, 3, 4, 5), 'spread': 'repeat', 'matrix': (1, 0, 0, 1, 0, 0), 'stops': ((0, 'fg'), (0, (0, 0, 0, 1)))})
        g = pv('fill=nonzero,lin(0 0 1 1 reflect/0 fg/1 fg),m 2 0 0 2 0 0:M0 0')['layers'][0]
        self.ae((g['paint']['spread'], g['matrix']), ('reflect', (2, 0, 0, 2, 0, 0)))
        self.assertTrue(pv('stroke=1,lin(0 0 1 1 / 0 #000000 / 1 #ffffff):M0 0')['uses_fixed_color'])
        stops = ' '.join(f'/ {i / 15} fg' for i in range(16))
        self.ae(len(pv(f'fill=nonzero,lin(0 0 1 1 {stops}):M0 0')['layers'][0]['paint']['stops']), 16)
        bad(f'fill=nonzero,lin(0 0 1 1 {stops} / 1 fg):M0 0', 'outline_too_large', 'too many gradient stops')
        for x in (
            'lin(0 0 1 1 / 0 fg)',
            'lin(0 0 1 / 0 fg / 1 fg)',
            'lin(0 0 1 1 / 0 fg / 1 fg',
            'lin(0 0 1 1 / 1 fg / 0 fg)',
            'lin(0 0 1 1 / 0 fg / 1.5 fg)',
            'lin(0 0 1 1 / -0.5 fg / 1 fg)',
            'lin(0 0 1 1 / 0fg / 1 fg)',
            'lin(0 0 1 1 / 0 lin(0 0 1 1 / 0 fg / 1 fg) / 1 fg)',
            'lin(0 0 1 1 mirror / 0 fg / 1 fg)',
            'lin(0 0 1 1, / 0 fg / 1 fg)',
            'lin(0 0 1 1 m 1 0 0 1 0 / 0 fg / 1 fg)',
            'lin(0 0 1 1 m 0 0 0 0 0 0 / 0 fg / 1 fg)',
            'rad(0 0 -1 0 0 1 / 0 fg / 1 fg)',
            'rad(0 0 0 0 0 -1 / 0 fg / 1 fg)',
            'rad(0 0 0 0 0 / 0 fg / 1 fg)',
            'lin(0 0 1 1 / 0 fg / 1 fg) ',
            'lin(0 0 1 1 / 0 fg / 1 fg)x',
            'lin (0 0 1 1 / 0 fg / 1 fg)',
        ):
            bad(f'fill=nonzero,{x}:M0 0')

        # limits
        self.ae(path('M-24-24L48 48'), 'M -24 -24 L 48 48')
        self.ae(path('M0 0L50 54', vb=(2, 6, 24, 24)), 'M 0 0 L 50 54')
        badpath('M0 0L48.01 0', 'outline_too_large', 'path point too far outside the viewBox')
        badpath('M0 0C0 -24.01 0 0 0 0', 'outline_too_large', 'path point too far outside the viewBox')
        bad('fill=nonzero,fg,m 2 0 0 2 0 0:M0 0L24.01 0', 'outline_too_large', 'path point too far outside the viewBox')
        self.ae(len(pv('fill=nonzero,fg,m 2 0 0 2 0 0:M0 0L24 0')['layers']), 1)
        # the viewBox size is the larger dimension
        self.ae(path('M0 0L0 -48', vb=(0, 0, 48, 8)), 'M 0 0 L 0 -48')
        # segments: movetos, lines, curves and closes each count one
        self.ae(len(path('M0 0' + 'L1 1' * 2047).split()), 3 + 2047 * 3)
        badpath('M0 0' + 'L1 1' * 2048, 'outline_too_large', 'too many path segments')
        badpath('M0 0' + 'L0 0Z' * 1024, 'outline_too_large', 'too many path segments')
        self.ae(path('M0 0' + 'L0 0' * 2046 + 'Z' * 5000).count('Z'), 1)
        # the implied moveto after Z counts
        badpath('M0 0' + 'ZL0 0' * 1024, 'outline_too_large', 'too many path segments')
        # an arc counts as its cubics
        path('M0 0' + 'L1 1' * 2045 + 'A10 10 0 0 1 21 1')
        badpath('M0 0' + 'L1 1' * 2046 + 'A10 10 0 0 1 21 1', 'outline_too_large', 'too many path segments')
        # and segments are counted across layers
        badpath('M0 0' + 'L1 1' * 1023 + '|fill=nonzero,fg:M0 0' + 'L1 1' * 1024, 'outline_too_large', 'too many path segments')
        # path length: 64 viewBox sizes
        self.ae(len(path('M0 0' + 'H24H0' * 32).split()), 3 + 64 * 3)
        badpath('M0 0' + 'H24H0' * 32 + 'H0.1', 'outline_too_large', 'path too long')
        badpath('M0 0' + 'H24H0' * 31 + 'H24V24Z', 'outline_too_large', 'path too long')
        # curves count the length of their control polygon
        path('M0 0' + 'C0 24 24 24 24 0C24 24 0 24 0 0' * 10)
        badpath('M0 0' + 'C0 24 24 24 24 0C24 24 0 24 0 0' * 11, 'outline_too_large', 'path too long')
        # strokes add their width for every segment, moveto included
        pv('stroke=4,fg:M0 0' + 'H24H0' * 27 + 'H16')
        bad('stroke=4,fg:M0 0' + 'H24H0' * 27 + 'H16.1', 'outline_too_large', 'path too long')
        # lengths are measured after the layer matrix
        pv('fill=nonzero,fg,m 2 0 0 2 0 0:M0 0' + 'H12H0' * 32)
        bad('fill=nonzero,fg,m 2 0 0 2 0 0:M0 0' + 'H12H0' * 32 + 'H0.1', 'outline_too_large', 'path too long')
        # layers
        self.ae(len(pv('|'.join(['fill=nonzero,fg:M0 0'] * 128))['layers']), 128)
        bad('|'.join(['fill=nonzero,fg:M0 0'] * 129), 'outline_too_large', 'too many layers')
        # payload size
        bad('fill=nonzero,fg:M0 0' + ' ' * 32 * 1024, 'outline_too_large', 'payload too large')

    def test_glyph_registration(self):
        s = self.create_screen()

        def send(cmd, *expected):
            s.callbacks.wtcbuf = b''
            parse_bytes(s, f'\x1b_25a1;{cmd}\x1b\\'.encode())
            self.ae(s.callbacks.wtcbuf.decode(), ''.join(f'\x1b_25a1;{x}\x1b\\' for x in expected))

        icon = 'fill=nonzero,fg:M0 0H24V24Z'
        send(f'r;cp=100000;fmt=vg;vb=0 0 24 24;{icon}', 'r;cp=100000;status=0')
        send('q;cp=100000', 'q;cp=100000;status=glossary')
        send('q;cp=100001', 'q;cp=100001;status=')
        send(f'r;cp=1003ff;fmt=vg;vb=0 0 24 24;fit=cover;align=start,end;reply=2;{icon}')
        send('q;cp=1003ff', 'q;cp=1003ff;status=glossary')
        # failures
        send(f'r;cp=e0a0;fmt=vg;vb=0 0 24 24;{icon}', 'r;cp=e0a0;status=1;reason=out_of_namespace')
        send(f'r;cp=100400;fmt=vg;vb=0 0 24 24;{icon}', 'r;cp=100400;status=1;reason=out_of_namespace')
        send(f'r;cp=d800;fmt=vg;vb=0 0 24 24;{icon}', 'r;status=1;reason=out_of_namespace')
        send(f'r;fmt=vg;vb=0 0 24 24;{icon}', 'r;status=1;reason=out_of_namespace')
        send('r;cp=100002;AAAA', 'r;cp=100002;status=1;reason=unsupported_format')
        for fmt in ('glyf', 'colrv0', 'colrv1', 'svg'):
            send(f'r;cp=100002;fmt={fmt};AAAA', 'r;cp=100002;status=1;reason=unsupported_format')
        send(f'r;cp=100002;fmt=vg;{icon}', 'r;cp=100002;status=1;reason=malformed_payload')
        send(f'r;cp=100002;fmt=vg;vb=0 0 0 24;{icon}', 'r;cp=100002;status=1;reason=malformed_payload')
        send(f'r;cp=100002;fmt=vg;vb=0 0 24 24;align=center,baseline;{icon}', 'r;cp=100002;status=1;reason=malformed_payload')
        send('r;cp=100002;fmt=vg;vb=0 0 24 24;fill=nonzero,fg:L0 0', 'r;cp=100002;status=1;reason=malformed_payload')
        send('r;cp=100002;fmt=vg;vb=0 0 24 24;fill=nonzero,fg:M0 0L100 0', 'r;cp=100002;status=1;reason=outline_too_large')
        send('r;cp=100002;fmt=vg;vb=0 0 24 24;fill=nonzero,fg:M0 0' + ' ' * (32 * 1024), 'r;cp=100002;status=1;reason=payload_too_large')
        send('r;cp=100002;fmt=vg;vb=0 0 24 24;reply=2;fill=nonzero,fg:L0 0', 'r;cp=100002;status=1;reason=malformed_payload')
        send('r;cp=100002;fmt=vg;vb=0 0 24 24;reply=0;fill=nonzero,fg:L0 0')
        send('q;cp=100002', 'q;cp=100002;status=')
        # a failed registration does not affect an existing one
        send('r;cp=100000;fmt=vg;vb=0 0 24 24;fill=nonzero,fg:L0 0', 'r;cp=100000;status=1;reason=malformed_payload')
        send('q;cp=100000', 'q;cp=100000;status=glossary')
        # clear
        send('c;cp=100000', 'c;cp=100000;status=0')
        send('q;cp=100000', 'q;cp=100000;status=')
        send('c;cp=100000;reply=2')
        send('c;cp=100000;reply=0')
        send('c;cp=41', 'c;cp=41;status=1;reason=out_of_namespace')
        send('c;cp=zz', 'c;status=1;reason=out_of_namespace')
        send('c;cp=41;reply=0')
        send('q;cp=1003ff', 'q;cp=1003ff;status=glossary')
        send('c', 'c;status=0')
        send('q;cp=1003ff', 'q;cp=1003ff;status=')
        # RIS clears registrations
        send(f'r;cp=100005;fmt=vg;vb=0 0 24 24;reply=0;{icon}')
        send('q;cp=100005', 'q;cp=100005;status=glossary')
        parse_bytes(s, b'\x1bc')
        send('q;cp=100005', 'q;cp=100005;status=')
        # registrations are shared between the main and alternate screens but not between screens
        send(f'r;cp=100005;fmt=vg;vb=0 0 24 24;reply=0;{icon}')
        parse_bytes(s, b'\x1b[?1049h')
        send('q;cp=100005', 'q;cp=100005;status=glossary')
        parse_bytes(s, b'\x1b[?1049l')
        s2 = self.create_screen()
        s2.callbacks.wtcbuf = b''
        parse_bytes(s2, b'\x1b_25a1;q;cp=100005\x1b\\')
        self.ae(s2.callbacks.wtcbuf, b'\x1b_25a1;q;cp=100005;status=\x1b\\')

    def test_vg_parsing_robustness(self):
        import random

        rng = random.Random(1234)
        valid = [
            'fill=nonzero,fg:M0 0H24V24Z',
            'stroke=2/butt/miter10,lin(0 0 24 0 reflect m 1 0 0 1 0 0 / 0 fg / 1 #ff000080):M2 2a10 10 0 0 1 20 0c1 1 2 2 3 3s1 1 2 2q1 1 2 2t2 2',
            'clip=1,evenodd,m 1 0 0 1 0 0:M0 0h24v24h-24z|fill=nonzero,rad(1 2 0 12 12 10 / 0 fg@0.5 / 1 #00ff00):M12 2A10 10 0 1 1 11.99 2Z',
        ]
        alphabet = 'MmLlHhVvCcSsQqTtAaZz0123456789.,-+eE /|:=#()@fgnonzerovdlicprtsk'
        for i in range(4000):
            if i % 2:
                p = list(rng.choice(valid))
                for _ in range(rng.randint(1, 4)):
                    op = rng.randint(0, 2)
                    pos = rng.randint(0, len(p))
                    if op == 0 and pos < len(p):
                        del p[pos]
                    elif op == 1:
                        p.insert(pos, rng.choice(alphabet))
                    elif pos < len(p):
                        p[pos] = rng.choice(alphabet)
                payload = ''.join(p)
            else:
                payload = ''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
            try:
                parse_vg(payload.encode(), (0, 0, 24, 24))
            except ValueError as e:
                self.assertRegex(str(e), '^(malformed_payload|outline_too_large): ')
