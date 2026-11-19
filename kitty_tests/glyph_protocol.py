#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import array
import math

from kitty.fast_data_types import (
    DECAWM,
    parse_glyph_command,
    parse_vg,
    render_vg,
    set_glyph_protocol_sprite_limits,
    sprite_idx_to_pos,
    test_render_line,
    vg_live_glyph_memory,
    vg_set_window_limits,
)
from kitty.fonts.render import setup_for_testing

from .base import BaseTest, draw_multicell, parse_bytes
from .fonts import FontBaseTest


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

        q('s', ['s;fmt=vg'])
        # replies are sent in the order the requests arrive
        q('s\x1b\\\x1b_25a1;q;cp=41', ['s;fmt=vg', 'q;cp=41;reason=unknown'])
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

    def test_vg_rendering(self):
        V = (0, 0, 24, 24)

        def r(payload, w=24, h=24, vb=V, **kw):
            return render_vg(payload.encode(), vb, w, h, **kw)

        def mask(payload, w=24, h=24, vb=V, **kw):
            ans = r(payload, w, h, vb, **kw)
            self.assertIsNone(ans['color'])
            return ans['fg']

        def area(m):
            return sum(m) / 255

        def at(m, x, y, w=24):
            return m[y * w + x]

        # Simple fills
        self.ae(set(mask('fill=nonzero,fg:M0 0H24V24H0Z')), {255})
        self.ae(set(mask('fill=nonzero,fg:M0 0H24V24H0Z', 7, 13, fit='stretch')), {255})
        m = mask('fill=nonzero,fg:M0 0H12.5V24H0Z')
        self.ae({at(m, x, y) for x in range(12) for y in range(24)}, {255})
        self.ae({at(m, x, y) for x in range(13, 24) for y in range(24)}, {0})
        self.ae({at(m, 12, y) for y in range(24)}, {128})
        # horizontal edges have coverage quantized to the sub-scanlines
        m = mask('fill=nonzero,fg:M0 0H24V12.5H0Z')
        self.ae({at(m, x, 12) for x in range(24)}, {128})
        # open subpaths are closed for filling
        self.ae(mask('fill=nonzero,fg:M0 0H24V24H0'), mask('fill=nonzero,fg:M0 0H24V24H0Z'))
        # nothing to fill
        self.ae(set(mask('fill=nonzero,fg:M0 0L24 24')), {0})
        self.ae(set(mask('fill=nonzero,fg:M0 0')), {0})

        # Circle area
        sz = 120
        m = mask('fill=nonzero,fg:M12 2A10 10 0 1 1 12 22A10 10 0 1 1 12 2Z', sz, sz)
        expected = math.pi * (10 * sz / 24) ** 2
        self.assertLess(abs(area(m) - expected) / expected, 0.002)

        # Fill rules
        same_dir = 'M2 2H22V22H2ZM7 7H17V17H7Z'
        opposite_dir = 'M2 2H22V22H2ZM7 7V17H17V7Z'
        self.ae(area(mask('fill=evenodd,fg:' + same_dir)), 400 - 100)
        self.ae(area(mask('fill=nonzero,fg:' + same_dir)), 400)
        self.ae(area(mask('fill=nonzero,fg:' + opposite_dir)), 400 - 100)
        self.ae(area(mask('fill=evenodd,fg:' + opposite_dir)), 400 - 100)
        # self intersecting path
        self.ae(area(mask('fill=evenodd,fg:M0 0H24V24H0ZM0 0H24V24H0Z')), 0)
        self.ae(area(mask('fill=nonzero,fg:M0 0H24V24H0ZM0 0V24H24V0Z')), 0)

        # Placement
        sq = 'fill=nonzero,fg:M0 0H24V24H0Z'

        def columns(m, w):
            return [x for x in range(w) if m[x] == 255]

        self.ae(columns(mask(sq, 48, 24), 48), list(range(12, 36)))
        self.ae(columns(mask(sq, 48, 24, align=('start', 'center')), 48), list(range(24)))
        self.ae(columns(mask(sq, 48, 24, align=('end', 'center')), 48), list(range(24, 48)))
        self.ae(set(mask(sq, 48, 24, fit='cover')), {255})
        self.ae(set(mask(sq, 48, 24, fit='stretch')), {255})
        m = mask(sq, 24, 48, align=('center', 'start'))
        self.ae([y for y in range(48) if m[y * 24] == 255], list(range(24)))
        m = mask(sq, 24, 48, align=('center', 'end'))
        self.ae([y for y in range(48) if m[y * 24] == 255], list(range(24, 48)))
        # cover crops, aligning picks the visible part
        m = mask('fill=nonzero,fg:M0 0H12V24H0Z', 24, 48, fit='cover', align=('start', 'center'))
        self.ae(set(m), {255})
        m = mask('fill=nonzero,fg:M0 0H12V24H0Z', 24, 48, fit='cover', align=('end', 'center'))
        self.ae(set(m), {0})
        # the viewBox origin
        self.ae(mask('fill=nonzero,fg:M10 10H34V34H10Z', vb=(10, 10, 24, 24)), mask(sq))
        # ink outside the viewBox but inside the area is drawn, as SVG clips at the viewport
        m = mask('fill=nonzero,fg:M-12 0H36V24H-12Z', 48, 24)
        self.ae(set(m), {255})
        # and ink outside the area is clipped
        self.ae(area(mask('fill=nonzero,fg:M-24 -24H48V48H-24Z')), 24 * 24)

        # Layer matrix
        self.ae(area(mask('fill=nonzero,fg,m 0.5 0 0 0.5 0 0:M0 0H24V24H0Z')), 144)
        self.ae(area(mask('fill=nonzero,fg,m 1 0 0 1 12 0:M0 0H24V24H0Z')), 288)
        # a matrix with negative determinant reverses orientation, which does not affect filling
        self.ae(area(mask('fill=nonzero,fg,m -1 0 0 1 24 0:M0 0H12V24H0Z')), 288)

        # Strokes
        def close(a, b, tolerance=0.01):
            self.assertLess(abs(a - b) / b, tolerance, f'{a} != {b}')

        sz = 240
        scale = sz / 24
        # butt caps
        close(area(mask('stroke=2/butt,fg:M4 12H20', sz, sz)), 2 * 16 * scale**2)
        # square caps extend by half the width at both ends
        close(area(mask('stroke=2/square,fg:M4 12H20', sz, sz)), 2 * 18 * scale**2)
        # round caps add a circle
        close(area(mask('stroke=2/round,fg:M4 12H20', sz, sz)), (2 * 16 + math.pi) * scale**2)
        # stroke is centered on the path
        m = mask('stroke=2/butt,fg:M0 12H24', 24, 24)
        self.ae([m[y * 24 + 5] for y in range(24)], [0] * 11 + [255] * 2 + [0] * 11)
        # a closed rectangle: each side plus miter joins fill the corners
        close(area(mask('stroke=2/butt/miter,fg:M4 4H20V20H4Z', sz, sz)), (18 * 18 - 14 * 14) * scale**2)
        # bevel joins cut off the corners: 4 triangles of 1 x 1 / 2
        close(area(mask('stroke=2/butt/bevel,fg:M4 4H20V20H4Z', sz, sz)), (18 * 18 - 14 * 14 - 2) * scale**2)
        # round joins: quarter circles at the corners
        close(area(mask('stroke=2/butt/round,fg:M4 4H20V20H4Z', sz, sz)), (18 * 18 - 14 * 14 - 4 + math.pi) * scale**2)
        # an unclosed rectangle has caps instead of a join at its start
        close(area(mask('stroke=2/butt/miter,fg:M4 4H20V20H4V4', sz, sz)), (18 * 18 - 14 * 14 - 1) * scale**2)
        # miter limit: a sharp angle has a miter only if the limit allows it
        sharp = 'M2 20L12 4L22 20'
        bevelled = area(mask(f'stroke=2/butt/bevel,fg:{sharp}', sz, sz))
        self.ae(area(mask(f'stroke=2/butt/miter1,fg:{sharp}', sz, sz)), bevelled)
        self.assertGreater(area(mask(f'stroke=2/butt/miter10,fg:{sharp}', sz, sz)), bevelled + scale**2)
        # zero length subpaths are dots with round and square caps only
        close(area(mask('stroke=4/round,fg:M12 12Z', sz, sz)), math.pi * 4 * scale**2)
        close(area(mask('stroke=4/round,fg:M12 12L12 12', sz, sz)), math.pi * 4 * scale**2)
        close(area(mask('stroke=4/square,fg:M12 12Z', sz, sz)), 16 * scale**2)
        self.ae(area(mask('stroke=4/butt,fg:M12 12Z', sz, sz)), 0)
        # a moveto alone draws nothing
        self.ae(area(mask('stroke=4/round,fg:M12 12', sz, sz)), 0)
        # a non-uniform matrix gives an elliptical pen, here a vertical line
        # stroked with a pen 3 times wider horizontally
        close(area(mask('stroke=2/butt,fg,m 3 0 0 1 -24 0:M12 4V20', sz, sz)), 6 * 16 * scale**2)
        # stroked curves: a semicircle of radius 8
        close(area(mask('stroke=2/butt,fg:M4 12A8 8 0 0 1 20 12', sz, sz)), math.pi / 2 * (9 * 9 - 7 * 7) * scale**2)

        # Colors
        ans = r('fill=nonzero,#ff800080:M0 0H24V24H0Z')
        self.assertIsNone(ans['fg'])
        self.ae(set(zip(*[iter(ans['color'])] * 4)), {(128, 64, 0, 128)})
        ans = r('fill=nonzero,fg@0.5:M0 0H24V24H0Z')
        self.assertIsNone(ans['color'])
        self.ae(set(ans['fg']), {128})
        # mixed: fg layer under a half transparent red layer
        ans = r('fill=nonzero,fg:M0 0H24V24H0Z|fill=nonzero,#ff000080:M0 0H24V24H0Z')
        self.ae(set(zip(*[iter(ans['color'])] * 4)), {(128, 0, 0, 255)})
        self.ae(set(ans['fg']), {127})
        # fg layer over a red layer
        ans = r('fill=nonzero,#ff0000:M0 0H24V24H0Z|fill=nonzero,fg@0.25:M0 0H24V24H0Z')
        self.ae(set(zip(*[iter(ans['color'])] * 4)), {(191, 0, 0, 255)})
        self.ae(set(ans['fg']), {64})

        # Gradients
        def row(m, y=0, w=24):
            return list(m[y * w : (y + 1) * w])

        m = mask('fill=nonzero,lin(0 0 24 0 / 0 fg@0 / 1 fg):M0 0H24V24H0Z')
        self.ae(row(m), [round((x + 0.5) / 24 * 255) for x in range(24)])
        self.ae(row(m), row(m, 23))
        # pad
        m = mask('fill=nonzero,lin(6 0 18 0 / 0 fg@0 / 1 fg):M0 0H24V24H0Z')
        self.ae(row(m)[:6], [0] * 6)
        self.ae(row(m)[18:], [255] * 6)
        # repeat and reflect
        m = mask('fill=nonzero,lin(0 0 12 0 repeat / 0 fg@0 / 1 fg):M0 0H24V24H0Z')
        self.ae(row(m)[:12], row(m)[12:])
        m = mask('fill=nonzero,lin(0 0 12 0 reflect / 0 fg@0 / 1 fg):M0 0H24V24H0Z')
        self.ae(row(m)[:12], row(m)[12:][::-1])
        # gradient matrix: rotated by 90 degrees, so the gradient is vertical
        m = mask('fill=nonzero,lin(0 0 24 0 m 0 1 -1 0 0 0 / 0 fg@0 / 1 fg):M0 0H24V24H0Z')
        self.ae([m[y * 24] for y in range(24)], [round((y + 0.5) / 24 * 255) for y in range(24)])
        # the gradient goes through the layer matrix
        m = mask('fill=nonzero,lin(0 0 12 0 / 0 fg@0 / 1 fg),m 2 0 0 1 0 0:M0 0H12V24H0Z')
        self.ae(row(m), [round((x + 0.5) / 24 * 255) for x in range(24)])
        # hard stops
        m = mask('fill=nonzero,lin(0 0 24 0 / 0 fg / 0.5 fg / 0.5 fg@0 / 1 fg@0):M0 0H24V24H0Z')
        self.ae(row(m), [255] * 12 + [0] * 12)
        # radial
        m = mask('fill=nonzero,rad(12 12 0 12 12 12 / 0 fg / 1 fg@0):M0 0H24V24H0Z')
        self.ae(at(m, 12, 12), round(255 * (1 - math.hypot(0.5, 0.5) / 12)))
        self.ae(at(m, 0, 0), 0)
        self.ae(at(m, 0, 12), at(m, 12, 0))
        # radial with the focal circle outside the end circle paints only inside the cone
        m = mask('fill=nonzero,rad(2 12 1 18 12 3 / 0 fg / 1 fg):M0 0H24V24H0Z')
        self.ae(at(m, 0, 0), 0)
        self.ae(at(m, 12, 12), 255)
        # degenerate gradients paint their last stop
        self.ae(set(mask('fill=nonzero,lin(5 5 5 5 / 0 fg@0 / 1 fg):M0 0H24V24H0Z')), {255})
        self.ae(set(mask('fill=nonzero,rad(5 5 2 5 5 2 / 0 fg@0 / 1 fg):M0 0H24V24H0Z')), {255})
        # mixed fg and fixed stops
        ans = r('fill=nonzero,lin(0 0 24 0 / 0 fg / 1 #ff0000):M0 0H24V24H0Z')
        self.ae(ans['fg'][0] + ans['color'][0], 255)
        self.assertGreater(ans['fg'][0], 240)
        self.assertGreater(ans['color'][23 * 4], 240)
        self.ae(set(ans['color'][3::4]), {255})

        # Clips
        circle = 'M12 2A10 10 0 1 1 12 22A10 10 0 1 1 12 2Z'
        sz = 120
        clipped = mask(f'clip=1,nonzero:{circle}|fill=nonzero,fg:M0 0H24V24H0Z', sz, sz)
        self.ae(clipped, mask(f'fill=nonzero,fg:{circle}', sz, sz))
        # clips apply only to the specified number of layers
        m = mask(f'clip=1,nonzero:{circle}|fill=nonzero,fg:M0 0H1V1H0Z|fill=nonzero,fg:M23 23H24V24H23Z', sz, sz)
        self.ae(m[0], 0)
        self.ae(m[-1], 255)
        m = mask(f'clip=2,nonzero:{circle}|fill=nonzero,fg:M0 0H1V1H0Z|fill=nonzero,fg:M23 23H24V24H23Z', sz, sz)
        self.ae(set(m), {0})
        # an empty clip hides everything
        self.ae(set(mask('clip=1,nonzero:M0 0|fill=nonzero,fg:M0 0H24V24H0Z')), {0})
        # evenodd clips
        self.ae(area(mask('clip=1,evenodd:M2 2H22V22H2ZM7 7H17V17H7Z|fill=nonzero,fg:M0 0H24V24H0Z')), 300)

        # Rendering is bounded in time: geometry that is huge relative to
        # the area it is rendered into is rejected
        bomb = 'stroke=0.001,fg:M0.5 0' + ' q2e-05 2e-05 0 4e-05 q-2e-05 -2e-05 0 -4e-05' * 64
        with self.assertRaisesRegex(ValueError, '^too_complex'):
            render_vg(bomb.encode(), (0, 0, 1, 1 / 4096), 80, 160, fit='cover')
        self.assertIn('work', render_vg(bomb.encode(), (0, 0, 1, 1 / 4096), 80, 160, fit='contain'))
        # the most expensive valid payloads are well within the limit
        heavy = '|'.join(['fill=nonzero,rad(4 4 1 12 12 30 reflect / 0 fg / 0.3 #ff0000 / 0.6 #00ff0080 / 1 #0000ff):M0 0H24V24H0Z'] * 16)
        for w, h in ((10, 20), (80, 160), (560, 1120)):
            r(heavy, w, h, fit='stretch')

        # Determinism
        p = 'stroke=1.5,lin(0 0 24 24 reflect / 0 fg / 1 #00ff0080):M3 12c3-8 6-8 9 0s6 8 9 0|fill=evenodd,fg@0.5:' + circle
        self.ae(r(p, 37, 71), r(p, 37, 71))


class GlyphRendering(FontBaseTest):
    def sprite(self, sprite_idx):
        pos = sprite_idx_to_pos(sprite_idx, setup_for_testing.xnum, setup_for_testing.ynum)
        pixels = array.array('I', self.sprites[pos])
        # the last row is the underline exclusion zone
        return pixels[: self.cell_width * self.cell_height]

    def register(self, s, cp, layers, vb='0 0 24 24', **kw):
        extra = ''.join(f';{k}={v}' for k, v in kw.items())
        s.callbacks.wtcbuf = b''
        parse_bytes(s, f'\x1b_25a1;r;cp={cp:x};fmt=vg;vb={vb}{extra};{layers}\x1b\\'.encode())
        self.ae(s.callbacks.wtcbuf, f'\x1b_25a1;r;cp={cp:x};status=0\x1b\\'.encode())

    def render(self, s, text, y=0):
        s.reset_mode(DECAWM)
        s.cursor_position(y + 1, 1)
        s.erase_in_line(2)
        s.draw(text)
        line = s.line(y)
        test_render_line(line)
        return line

    def test_registered_glyph_rendering(self):
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        cw, ch = self.cell_width, self.cell_height
        full = 'fill=nonzero,fg:M-24 -24H48V48H-24Z'
        self.register(s, 0x100000, full)
        line = self.render(s, '\U00100000x')
        idx = line.sprite_at(0)
        self.ae(idx & 0xC0000000, 0)
        self.ae(set(self.sprite(idx)), {0xFFFFFF00 | 255})
        # unregistered codepoints in the block are rendered via fonts
        line = self.render(s, '\U00100001x')
        self.assertNotEqual(line.sprite_at(0), idx)

        # a glyph with fixed colors is a colored sprite with unpremultiplied colors
        self.register(s, 0x100002, 'fill=nonzero,#ff000080:M-24 -24H48V48H-24Z')
        line = self.render(s, '\U00100002x')
        cidx = line.sprite_at(0)
        self.ae(cidx & 0xC0000000, 0x80000000)
        self.ae(set(self.sprite(cidx)), {0xFF000080})

        # a glyph mixing fixed colors and the foreground color has the weight
        # of the foreground color in the sprite to its right
        self.register(s, 0x100003, 'fill=nonzero,fg:M-24 -24H48V48H-24Z|fill=nonzero,#0000ff80:M-24 -24H48V48H-24Z', fit='stretch')
        line = self.render(s, '\U00100003x')
        midx = line.sprite_at(0)
        self.ae(midx & 0xC0000000, 0xC0000000)
        midx &= 0x3FFFFFFF
        pos, fg_pos = (sprite_idx_to_pos(i, setup_for_testing.xnum, setup_for_testing.ynum) for i in (midx, midx + 1))
        self.ae(fg_pos, (pos[0] + 1, pos[1], pos[2]))
        # K = (0, 0, 128) with A = 255 and F = 127, relative to alpha
        self.ae(set(self.sprite(midx)), {0x000080FF})
        self.ae(set(self.sprite(midx + 1)), {0xFFFFFF00 | 127})

        # identical glyphs share sprites, even at different codepoints
        self.register(s, 0x100004, full)
        self.ae(self.render(s, '\U00100004x').sprite_at(0), idx)

        # changing a registration changes the rendering
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H24V12H0Z', fit='stretch')
        line = self.render(s, '\U00100000x')
        half_idx = line.sprite_at(0)
        self.assertNotEqual(half_idx, idx)
        pixels = self.sprite(half_idx)
        self.ae(set(pixels[: cw * (ch // 2 - 1)]), {0xFFFFFF00 | 255})
        self.ae(set(pixels[cw * (ch // 2 + 1) :]), {0xFFFFFF00})

        # a clear makes the codepoint render via fonts again
        parse_bytes(s, b'\x1b_25a1;c;cp=100000;reply=0\x1b\\')
        self.assertNotIn(self.render(s, '\U00100000x').sprite_at(0), (idx, half_idx))

    def test_registered_glyph_width(self):
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        cw, ch = self.cell_width, self.cell_height
        self.assertGreater(ch, cw)
        # a square glyph followed by a space is rendered across two cells, as
        # its width when fitting the cell height is more than one cell. It is
        # contained in the two cells, which can be narrower than the cell height.
        sq = 'fill=nonzero,fg:M0 0H24V24H0Z'
        self.register(s, 0x100000, sq)
        line = self.render(s, '\U00100000 x')
        left, right = self.sprite(line.sprite_at(0)), self.sprite(line.sprite_at(1))
        coverage = sum(p & 0xFF for p in left) + sum(p & 0xFF for p in right)
        side = min(ch, 2 * cw)
        self.assertAlmostEqual(coverage / 255, side * side, delta=side)
        # the glyph is centered in the two cells
        self.ae(sum(p & 0xFF for p in left), sum(p & 0xFF for p in right))
        # without a trailing space it is rendered in one cell
        line = self.render(s, '\U00100000x')
        self.assertAlmostEqual(sum(p & 0xFF for p in self.sprite(line.sprite_at(0))) / 255, cw * cw, delta=cw)
        # a glyph whose viewBox fits in one cell is not widened
        self.register(s, 0x100001, sq, vb='0 0 8 24')
        line = self.render(s, '\U00100001 x')
        self.ae(line.sprite_at(1), 0)

    def test_registered_glyph_text_sizing(self):
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        cw, ch = self.cell_width, self.cell_height
        # with s=2 the glyph covers 2x2 cells
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H24V24H0Z', fit='stretch')
        draw_multicell(s, '\U00100000', scale=2)
        total = 0
        for y in range(2):
            line = s.line(y)
            test_render_line(line)
            for x in range(2):
                total += sum(p & 0xFF for p in self.sprite(line.sprite_at(x))) / 255
        self.ae(total, 4 * cw * ch)
        # with w=3 the glyph covers 3 cells
        s.reset()
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H12V24H0Z', fit='stretch')
        draw_multicell(s, '\U00100000', width=3)
        line = s.line(0)
        test_render_line(line)
        cov = [sum(p & 0xFF for p in self.sprite(line.sprite_at(x))) / 255 for x in range(3)]
        # the left half of the 3 cell wide area is covered
        self.assertAlmostEqual(sum(cov), 1.5 * cw * ch, delta=ch)
        self.ae(cov[0], cw * ch)
        self.ae(cov[2], 0)

    def test_registered_glyphs_are_bound_when_printed(self):
        s = self.create_screen(cols=8, lines=4, scrollback=20)
        base_memory = vg_live_glyph_memory()
        circle = 'fill=nonzero,fg:M12 2A10 10 0 1 1 12 22A10 10 0 1 1 12 2Z'
        square = 'fill=nonzero,fg:M2 2H22V22H2Z'
        self.register(s, 0x100000, circle)
        line = self.render(s, '\U00100000x')
        circle_idx = line.sprite_at(0)
        # the text of the cell is just the codepoint
        self.ae(str(line), '\U00100000x')
        # re-registering does not change what was already printed
        self.register(s, 0x100000, square)
        test_render_line(line)
        self.ae(line.sprite_at(0), circle_idx)
        # but text printed later uses the new glyph
        line2 = self.render(s, '\U00100000x', y=1)
        square_idx = line2.sprite_at(0)
        self.assertNotEqual(square_idx, circle_idx)
        # combining chars keep the glyph bound to the cell
        s.cursor_position(1, 2)
        s.draw('\u0301')
        self.ae(str(s.line(0)), '\U00100000\u0301x')
        line = s.line(0)
        test_render_line(line)
        self.ae(line.sprite_at(0), circle_idx)
        # clearing does not affect printed text
        parse_bytes(s, b'\x1b_25a1;c;reply=0\x1b\\')
        for y, idx in ((0, circle_idx), (1, square_idx)):
            line = s.line(y)
            test_render_line(line)
            self.ae(line.sprite_at(0), idx)
        # but text printed later is not rendered with a registered glyph
        self.assertNotIn(self.render(s, '\U00100000x', y=2).sprite_at(0), (circle_idx, square_idx))
        # registering identical glyphs shares the glyph objects
        self.register(s, 0x100001, circle)
        self.register(s, 0x100002, circle)
        self.ae(self.render(s, '\U00100001\U00100002', y=3).sprite_at(0), circle_idx)
        self.ae(s.line(3).sprite_at(1), circle_idx)
        # text with bound glyphs keeps them alive until the text is gone
        self.assertGreater(vg_live_glyph_memory(), base_memory)
        parse_bytes(s, b'\x1b_25a1;c;reply=0\x1b\\')
        self.assertGreater(vg_live_glyph_memory(), base_memory)
        s.erase_in_display(3, False)
        s.erase_in_display(2, False)
        s.garbage_collect_text_cache()
        self.ae(vg_live_glyph_memory(), base_memory)
        # text in the scrollback keeps its glyphs
        self.register(s, 0x100003, circle)
        s.draw('\U00100003')
        for i in range(6):
            s.index()
        s.garbage_collect_text_cache()
        self.assertGreater(vg_live_glyph_memory(), base_memory)
        # RIS releases all glyphs
        s.reset()
        self.ae(vg_live_glyph_memory(), base_memory)

    def test_registered_glyphs_in_multicell(self):
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H24V24H0Z', fit='stretch')
        draw_multicell(s, '\U00100000', scale=2)
        line = s.line(0)
        test_render_line(line)
        first = line.sprite_at(0)
        # re-registering does not change the multicell char
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H12V24H0Z', fit='stretch')
        for y in range(2):
            line = s.line(y)
            test_render_line(line)
            self.ae(sum(p & 0xFF for x in range(2) for p in self.sprite(line.sprite_at(x))) / 255, 2 * self.cell_width * self.cell_height)
        self.ae(s.line(0).sprite_at(0), first)

    def test_registered_glyph_sprites_are_reused(self):
        import gc

        # free screens from earlier tests, as freeing their glyphs creates holes
        gc.collect()
        s = self.create_screen(cols=8, lines=4, scrollback=0)

        def glyph(i, mixed=False):
            ans = f'fill=nonzero,fg:M0 0H{1 + i % 23}V24H0Z'
            if mixed:
                ans += f'|fill=nonzero,#ff0000:M0 0H24V{1 + i % 23}H0Z'
            return ans

        def show(i, mixed=False):
            self.register(s, 0x100000, glyph(i, mixed))
            return self.render(s, '\U00100000x').sprite_at(0) & 0x3FFFFFFF

        def release():
            # erase the text and the registration, so the glyph is freed
            s.erase_in_display(2, False)
            parse_bytes(s, b'\x1b_25a1;c;reply=0\x1b\\')
            s.garbage_collect_text_cache()

        a = show(1)
        release()
        self.ae(show(2), a)
        release()
        # a pair of slots for a glyph mixing fg and fixed colors is reused for another such glyph
        m = show(3, True)
        release()
        self.ae(show(4, True), m)
        release()
        # single slots are reused before pairs are split
        self.ae(show(5), a)
        # and then pairs are split into single slots
        self.register(s, 0x100001, glyph(6))
        self.register(s, 0x100002, glyph(7))
        line = self.render(s, '\U00100001\U00100002', y=1)
        self.ae([line.sprite_at(x) for x in range(2)], [m, m + 1])
        release()

        # registering and printing new glyphs uses a bounded number of sprites
        before = len(self.sprites)
        for i in range(200):
            show(100 + i, i % 3 == 0)
            if i % 10 == 9:
                s.garbage_collect_text_cache()
        self.assertLess(len(self.sprites) - before, 40)

    def test_registered_glyph_window_limits(self):
        self.addCleanup(vg_set_window_limits)
        vg_set_window_limits(1 << 30, 10)
        s = self.create_screen(cols=8, lines=4, scrollback=100)

        def reg(screen, i):
            screen.callbacks.wtcbuf = b''
            parse_bytes(screen, f'\x1b_25a1;r;cp=100000;fmt=vg;vb=0 0 24 24;fill=nonzero,fg:M0 0H{i / 4}V1Z\x1b\\'.encode())
            return screen.callbacks.wtcbuf.decode()

        ok, full = '\x1b_25a1;r;cp=100000;status=0\x1b\\', '\x1b_25a1;r;cp=100000;status=1;reason=no_space\x1b\\'
        # each new glyph printed into the scrollback is kept alive by the text
        results = []
        for i in range(1, 20):
            results.append(reg(s, i))
            s.draw('\U00100000')
            s.linefeed()
            s.carriage_return()
        self.ae(results[:8], [ok] * 8)
        self.ae(results[-1], full)
        # other windows are not affected
        s2 = self.create_screen()
        self.ae(reg(s2, 50), ok)
        # once the text is gone the glyphs are released and registering works again
        s.erase_in_display(3, False)
        s.erase_in_display(2, False)
        s.garbage_collect_text_cache()
        self.ae(reg(s, 60), ok)
        # the text cache is garbage collected automatically when the limits are reached
        s3 = self.create_screen(cols=8, lines=4, scrollback=0)
        for i in range(1, 6):
            self.ae(reg(s3, i), ok)
            s3.draw('\U00100000')
        s3.erase_in_display(2, False)
        for i in range(6, 12):
            self.ae(reg(s3, i), ok, f'registration {i} failed')
            s3.draw('\U00100000')

    def test_registered_glyph_sprite_limits(self):
        import gc

        gc.collect()
        self.addCleanup(set_glyph_protocol_sprite_limits)
        MISSING = 1

        # each glyph can be rendered with a limited number of distinct parameters
        set_glyph_protocol_sprite_limits(65536, 16384, 12)
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H24V24H0Z')
        results = []
        for n in range(1, 8):
            s.reset_mode(DECAWM)
            s.cursor_position(1, 1)
            draw_multicell(s, '\U00100000', width=2, subscale_n=n, subscale_d=8)
            line = s.line(0)
            test_render_line(line)
            results.append(line.sprite_at(0))
        # 2 sprites per variant, the seventh variant exceeds the limit of 12
        self.assertNotIn(MISSING, results[:6])
        self.ae(results[6], MISSING)

        # each window can use a limited number of sprite slots
        # 2 slots are reserved per sprite, as glyphs mixing colors use a pair
        set_glyph_protocol_sprite_limits(65536, 6, 1024)
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        for i in range(8):
            self.register(s, 0x100000 + i, f'fill=nonzero,fg:M0 0H{i + 1}V24H0Z')
        line = self.render(s, ''.join(chr(0x100000 + i) for i in range(8)))
        sprites = [line.sprite_at(x) for x in range(8)]
        self.assertNotIn(MISSING, sprites[:5])
        self.ae(sprites[5:], [MISSING] * 3)
        # other windows are not affected
        s2 = self.create_screen(cols=8, lines=4, scrollback=0)
        self.register(s2, 0x100000, 'fill=nonzero,fg:M0 0H20V24H0Z')
        self.assertNotEqual(self.render(s2, '\U00100000').sprite_at(0), MISSING)
        # once the glyphs are no longer used the window can render again
        s.erase_in_display(2, False)
        parse_bytes(s, b'\x1b_25a1;c;reply=0\x1b\\')
        s.garbage_collect_text_cache()
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H21V24H0Z')
        self.assertNotEqual(self.render(s, '\U00100000').sprite_at(0), MISSING)
        set_glyph_protocol_sprite_limits()

        # glyphs that are too complex to render are rendered as the missing glyph
        s = self.create_screen(cols=8, lines=8, scrollback=0)
        bomb = 'stroke=0.001,fg:M0.5 0' + ' q2e-05 2e-05 0 4e-05 q-2e-05 -2e-05 0 -4e-05' * 64
        self.register(s, 0x100001, bomb, vb=f'0 0 1 {1 / 4096}', fit='cover')
        draw_multicell(s, '\U00100001', scale=7)
        for i in range(2):  # the second time the failure is cached
            line = s.line(0)
            test_render_line(line)
            self.ae([line.sprite_at(x) for x in range(7)], [MISSING] * 7)

    def test_paused_rendering_releases_glyphs(self):
        import gc

        gc.collect()
        base = vg_live_glyph_memory()
        s = self.create_screen(cols=8, lines=4, scrollback=0)
        self.register(s, 0x100000, 'fill=nonzero,fg:M0 0H24V24H0Z')
        s.draw('\U00100000')
        self.assertTrue(s.pause_rendering(True, 5000))
        self.assertTrue(s.pause_rendering(False, 0))
        s.reset()
        self.ae(vg_live_glyph_memory(), base)
