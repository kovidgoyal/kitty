#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import time
from base64 import standard_b64encode
from binascii import hexlify
from functools import partial

from kitty.fast_data_types import CURSOR_BLOCK, base64_decode, base64_encode
from kitty.notify import NotificationCommand, handle_notification_cmd, notification_activated, reset_registry

from . import BaseTest, parse_bytes


def cnv(x):
    if isinstance(x, memoryview):
        x = str(x, 'utf-8')
    return x


class CmdDump(list):

    def __call__(self, *a):
        if a and isinstance(a[0], int):
            a = a[1:]
        self.append(tuple(map(cnv, a)))


class TestParser(BaseTest):

    def parse_bytes_dump(self, s, x, *cmds):
        cd = CmdDump()
        if isinstance(x, str):
            x = x.encode('utf-8')
        cmds = tuple(('draw', x) if isinstance(x, str) else tuple(map(cnv, x)) for x in cmds)
        s.vt_parser.parse_bytes(s, x, cd)
        current = ''
        q = []
        for args in cd:
            if args[0] == 'draw':
                if args[1] is not None:
                    current += args[1]
            else:
                if current:
                    q.append(('draw', current))
                    current = ''
                q.append(args)
        if current:
            q.append(('draw', current))
        self.ae(tuple(q), cmds)

    def test_base64(self):
        for src, expected in {
            'bGlnaHQgdw==': 'light w',
            'bGlnaHQgd28=': 'light wo',
            'bGlnaHQgd29y': 'light wor',
        }.items():
            self.ae(base64_decode(src.encode()), expected.encode(), f'Decoding of {src} failed')
            self.ae(base64_decode(src.replace('=', '').encode()), expected.encode(), f'Decoding of {src} failed')
            self.ae(base64_encode(expected.encode()), src.replace('=', '').encode(), f'Encoding of {expected} failed')

    def test_simple_parsing(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)

        pb('12', '12')
        self.ae(str(s.line(0)), '12')
        self.ae(s.cursor.x, 2)
        pb('3456', '3456')
        self.ae(str(s.line(0)), '12345')
        self.ae(str(s.line(1)), '6')
        pb(b'\n123\n\r45', ('screen_linefeed',), '123', ('screen_linefeed',), ('screen_carriage_return',), '45')
        self.ae(str(s.line(1)), '6')
        self.ae(str(s.line(2)), ' 123')
        self.ae(str(s.line(3)), '45')
        s.vt_parser.parse_bytes(s, b'\rabcde')
        self.ae(str(s.line(3)), 'abcde')
        pb('\rßxyz1', ('screen_carriage_return',), 'ßxyz1')
        self.ae(str(s.line(3)), 'ßxyz1')
        pb('ニチ ', 'ニチ ')
        self.ae(str(s.line(4)), 'ニチ ')

    def test_esc_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('12\033Da', '12', ('screen_index',), 'a')
        self.ae(str(s.line(0)), '12')
        self.ae(str(s.line(1)), '  a')
        pb('\033x', ('Unknown char after ESC: 0x%x' % ord('x'),))
        pb('\033c123', ('screen_reset', ), '123')
        self.ae(str(s.line(0)), '123')

    def test_csi_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('abcde', 'abcde')
        s.cursor_back(5)
        pb('x\033[2@y', 'x', ('screen_insert_characters', 2), 'y')
        self.ae(str(s.line(0)), 'xy bc')
        pb('x\033[2;7@y', 'x', ('CSI code @ has 2 > 1 parameters',), 'y')
        pb('x\033[2;-7@y', 'x', ('CSI code @ has 2 > 1 parameters',), 'y')
        pb('x\033[-2@y', 'x', ('CSI code @ is not allowed to have negative parameter (-2)',), 'y')
        pb('x\033[2-3@y', 'x', ('CSI code can contain hyphens only at the start of numbers',), 'y')
        pb('x\033[@y', 'x', ('screen_insert_characters', 1), 'y')
        pb('x\033[345@y', 'x', ('screen_insert_characters', 345), 'y')
        pb('x\033[345;@y', 'x', ('screen_insert_characters', 345), 'y')
        pb('\033[H', ('screen_cursor_position', 1, 1))
        self.ae(s.cursor.x, 0), self.ae(s.cursor.y, 0)
        pb('\033[4H', ('screen_cursor_position', 4, 1))
        pb('\033[4;0H', ('screen_cursor_position', 4, 0))
        pb('\033[3;2H', ('screen_cursor_position', 3, 2))
        pb('\033[3;2;H', ('screen_cursor_position', 3, 2))
        pb('\033[00000000003;0000000000000002H', ('screen_cursor_position', 3, 2))
        self.ae(s.cursor.x, 1), self.ae(s.cursor.y, 2)
        pb('\033[J', ('screen_erase_in_display', 0, 0))
        pb('\033[?J', ('screen_erase_in_display', 0, 1))
        pb('\033[?2J', ('screen_erase_in_display', 2, 1))
        pb('\033[h')
        pb('\033[20;4h', ('screen_set_mode', 20, 0), ('screen_set_mode', 4, 0))
        pb('\033[?1000;1004h', ('screen_set_mode', 1000, 1), ('screen_set_mode', 1004, 1))
        pb('\033[20;4;20l', ('screen_reset_mode', 20, 0), ('screen_reset_mode', 4, 0), ('screen_reset_mode', 20, 0))
        pb('\033[=c', ('report_device_attributes', 0, 61))
        s.reset()

        def sgr(params):
            return (('select_graphic_rendition', f'{x} ') for x in params.split())

        pb('\033[1;2;3;4;7;9;34;44m', *sgr('1 2 3 4 7 9 34 44'))
        for attr in 'bold italic reverse strikethrough dim'.split():
            self.assertTrue(getattr(s.cursor, attr))
        self.ae(s.cursor.decoration, 1)
        self.ae(s.cursor.fg, 4 << 8 | 1)
        self.ae(s.cursor.bg, 4 << 8 | 1)
        pb('\033[38;5;1;48;5;7m', ('select_graphic_rendition', '38 5 1 '), ('select_graphic_rendition', '48 5 7 '))
        self.ae(s.cursor.fg, 1 << 8 | 1)
        self.ae(s.cursor.bg, 7 << 8 | 1)
        pb('\033[38;2;1;2;3;48;2;7;8;9m', ('select_graphic_rendition', '38 2 1 2 3 '), ('select_graphic_rendition', '48 2 7 8 9 '))
        self.ae(s.cursor.fg, 1 << 24 | 2 << 16 | 3 << 8 | 2)
        self.ae(s.cursor.bg, 7 << 24 | 8 << 16 | 9 << 8 | 2)
        pb('\033[0;2m', *sgr('0 2'))
        pb('\033[;2m', *sgr('0 2'))
        pb('\033[m', *sgr('0 '))
        pb('\033[1;;2m', *sgr('1 0 2'))
        pb('\033[38;5;1m', ('select_graphic_rendition', '38 5 1 '))
        pb('\033[58;2;1;2;3m', ('select_graphic_rendition', '58 2 1 2 3 '))
        pb('\033[38;2;1;2;3m', ('select_graphic_rendition', '38 2 1 2 3 '))
        pb('\033[1001:2:1:2:3m', ('select_graphic_rendition', '1001 2 1 2 3 '))
        pb('\033[38:2:1:2:3;48:5:9;58;5;7m', (
            'select_graphic_rendition', '38 2 1 2 3 '), ('select_graphic_rendition', '48 5 9 '), ('select_graphic_rendition', '58 5 7 '))
        c = s.callbacks
        pb('\033[5n', ('report_device_status', 5, 0))
        self.ae(c.wtcbuf, b'\033[0n')
        c.clear()
        pb('\033[6n', ('report_device_status', 6, 0))
        self.ae(c.wtcbuf, b'\033[1;1R')
        pb('12345', '12345')
        c.clear()
        pb('\033[6n', ('report_device_status', 6, 0))
        self.ae(c.wtcbuf, b'\033[2;1R')
        c.clear()
        s.cursor_key_mode = True
        pb('\033[?1$p', ('report_mode_status', 1, 1))
        self.ae(c.wtcbuf, b'\033[?1;1$y')
        pb('\033[?1l', ('screen_reset_mode', 1, 1))
        self.assertFalse(s.cursor_key_mode)
        c.clear()
        pb('\033[?1$p', ('report_mode_status', 1, 1))
        self.ae(c.wtcbuf, b'\033[?1;2$y')
        pb('\033[2;4r', ('screen_set_margins', 2, 4))
        c.clear()
        pb('\033[14t', ('screen_report_size', 14))
        self.ae(c.wtcbuf, b'\033[4;100;50t')
        self.ae(s.margin_top, 1), self.ae(s.margin_bottom, 3)
        pb('\033[r', ('screen_set_margins', 0, 0))
        self.ae(s.margin_top, 0), self.ae(s.margin_bottom, 4)
        pb('\033[1 q', ('screen_set_cursor', 1, ord(' ')))
        self.assertTrue(s.cursor.blink)
        self.ae(s.cursor.shape, CURSOR_BLOCK)

        s.reset()
        pb('\033[3 @', ('Shift left escape code not implemented',))
        pb('\033[3 A', ('Shift right escape code not implemented',))
        pb('\033[3;4 S', ('Select presentation directions escape code not implemented',))
        pb('\033[1T', ('screen_reverse_scroll', 1))
        pb('\033[T', ('screen_reverse_scroll', 1))
        pb('\033[+T', ('screen_reverse_scroll_and_fill_from_scrollback', 1))

    def test_csi_code_rep(self):
        s = self.create_screen(8)
        pb = partial(self.parse_bytes_dump, s)
        pb('\033[1b', ('screen_repeat_character', 1))
        self.ae(str(s.line(0)), '')
        pb('x\033[7b', 'x', ('screen_repeat_character', 7))
        self.ae(str(s.line(0)), 'xxxxxxxx')
        pb('\033[1;3H', ('screen_cursor_position', 1, 3))
        pb('\033[byz\033[b', ('screen_repeat_character', 1), 'yz', ('screen_repeat_character', 1))
        # repeat 'x' at 3, then 'yz' at 4-5, then repeat 'z' at 6
        self.ae(str(s.line(0)), 'xxxyzzxx')
        s.reset()
        pb(' \033[3b', ' ', ('screen_repeat_character', 3))
        self.ae(str(s.line(0)), '    ')
        s.reset()
        pb('\t\033[b', ('screen_tab',), ('screen_repeat_character', 1))
        self.ae(str(s.line(0)), '\t')
        s.reset()
        b']]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]'

    def test_osc_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        c = s.callbacks
        pb('a\033]2;x\\ryz\033\\bcde', 'a', ('set_title', 'x\\ryz'), 'bcde')
        self.ae(str(s.line(0)), 'abcde')
        self.ae(c.titlebuf, ['x\\ryz'])
        c.clear()
        pb('\033]\x07', ('set_title', ''), ('set_icon', ''))
        self.ae(c.titlebuf, ['']), self.ae(c.iconbuf, '')
        pb('\033]ab\x07', ('set_title', 'ab'), ('set_icon', 'ab'))
        self.ae(c.titlebuf, ['', 'ab']), self.ae(c.iconbuf, 'ab')
        c.clear()
        pb('\033]2;;;;\x07', ('set_title', ';;;'))
        self.ae(c.titlebuf, [';;;'])
        c.clear()
        pb('\033]2;\x07', ('set_title', ''))
        self.ae(c.titlebuf, [''])
        pb('\033]110\x07', ('set_dynamic_color', 110, ''))
        self.ae(c.colorbuf, '')
        c.clear()
        pb('\033]9;\x07', ('desktop_notify', 9, ''))
        pb('\033]9;test it\x07', ('desktop_notify', 9, 'test it'))
        pb('\033]99;moo=foo;test it\x07', ('desktop_notify', 99, 'moo=foo;test it'))
        self.ae(c.notifications, [(9, ''), (9, 'test it'), (99, 'moo=foo;test it')])
        c.clear()
        pb('\033]8;;\x07', ('set_active_hyperlink', None, None))
        pb('\033]8moo\x07', ('Ignoring malformed OSC 8 code',))
        pb('\033]8;moo\x07', ('Ignoring malformed OSC 8 code',))
        pb('\033]8;id=xyz;\x07', ('set_active_hyperlink', 'xyz', None))
        pb('\033]8;moo:x=z:id=xyz:id=abc;http://yay;.com\x07', ('set_active_hyperlink', 'xyz', 'http://yay;.com'))
        c.clear()
        payload = '1' * 1024
        pb(f'\033]52;p;{payload}\x07', ('clipboard_control', 52, f'p;{payload}'))
        c.clear()
        pb('\033]52;p;xyz\x07', ('clipboard_control', 52, 'p;xyz'))

    def test_desktop_notify(self):
        reset_registry()
        notifications = []
        activations = []
        prev_cmd = NotificationCommand()

        def reset():
            nonlocal prev_cmd
            reset_registry()
            del notifications[:]
            del activations[:]
            prev_cmd = NotificationCommand()

        def notify(title, body, identifier):
            notifications.append((title, body, identifier))

        def h(raw_data, osc_code=99, window_id=1):
            nonlocal prev_cmd
            x = handle_notification_cmd(osc_code, raw_data, window_id, prev_cmd, notify)
            if x is not None and osc_code == 99:
                prev_cmd = x

        def activated(identifier, window_id, focus, report):
            activations.append((identifier, window_id, focus, report))

        h('test it', osc_code=9)
        self.ae(notifications, [('test it', '', 'i0')])
        notification_activated(notifications[-1][-1], activated)
        self.ae(activations, [('0', 1, True, False)])
        reset()

        h('d=0:i=x;title')
        h('d=1:i=x:p=body;body')
        self.ae(notifications, [('title', 'body', 'i0')])
        notification_activated(notifications[-1][-1], activated)
        self.ae(activations, [('x', 1, True, False)])
        reset()

        h('i=x:p=body:a=-focus;body')
        self.ae(notifications, [('body', '', 'i0')])
        notification_activated(notifications[-1][-1], activated)
        self.ae(activations, [])
        reset()

        h('i=x:e=1;' + standard_b64encode(b'title').decode('ascii'))
        self.ae(notifications, [('title', '', 'i0')])
        notification_activated(notifications[-1][-1], activated)
        self.ae(activations, [('x', 1, True, False)])
        reset()

        h('d=0:i=x:a=-report;title')
        h('d=1:i=x:a=report;body')
        self.ae(notifications, [('titlebody', '', 'i0')])
        notification_activated(notifications[-1][-1], activated)
        self.ae(activations, [('x', 1, True, True)])
        reset()

        h(';title')
        self.ae(notifications, [('title', '', 'i0')])
        notification_activated(notifications[-1][-1], activated)
        self.ae(activations, [('0', 1, True, False)])
        reset()

    def test_dcs_codes(self):
        s = self.create_screen()
        c = s.callbacks
        pb = partial(self.parse_bytes_dump, s)
        q = hexlify(b'kind').decode('ascii')
        pb(f'a\033P+q{q}\033\\bcde', 'a', ('screen_request_capabilities', 43, q), 'bcde')
        self.ae(str(s.line(0)), 'abcde')
        self.ae(c.wtcbuf, '1+r{}={}'.format(q, '1b5b313b3242').encode('ascii'))
        c.clear()
        pb('\033P$q q\033\\', ('screen_request_capabilities', ord('$'), ' q'))
        self.ae(c.wtcbuf, b'\033P1$r1 q\033\\')
        c.clear()
        pb('\033P$qm\033\\', ('screen_request_capabilities', ord('$'), 'm'))
        self.ae(c.wtcbuf, b'\033P1$rm\033\\')
        for sgr in '0;34;102;1;2;3;4 0;38:5:200;58:2:10:11:12'.split():
            expected = set(sgr.split(';')) - {'0'}
            c.clear()
            parse_bytes(s, f'\033[{sgr}m\033P$qm\033\\'.encode('ascii'))
            r = c.wtcbuf.decode('ascii').partition('r')[2].partition('m')[0]
            self.ae(expected, set(r.split(';')))
        c.clear()
        pb('\033P$qr\033\\', ('screen_request_capabilities', ord('$'), 'r'))
        self.ae(c.wtcbuf, f'\033P1$r{s.margin_top + 1};{s.margin_bottom + 1}r\033\\'.encode('ascii'))

    def test_pending(self):
        s = self.create_screen()
        timeout = 0.1
        s.set_pending_timeout(timeout)
        pb = partial(self.parse_bytes_dump, s)

        pb('\033P=1s\033\\', ('screen_start_pending_mode',))
        pb('a')
        self.ae(str(s.line(0)), '')
        pb('\033P=2s\033\\', ('draw', 'a'), ('screen_stop_pending_mode',))
        self.ae(str(s.line(0)), 'a')
        pb('\033P=1s\033\\', ('screen_start_pending_mode',))
        pb('b')
        self.ae(str(s.line(0)), 'a')
        time.sleep(timeout)
        pb('c', ('draw', 'bc'))
        self.ae(str(s.line(0)), 'abc')
        pb('\033P=1s\033\\d', ('screen_start_pending_mode',))
        pb('\033P=2s\033\\', ('draw', 'd'), ('screen_stop_pending_mode',))
        pb('\033P=1s\033\\e', ('screen_start_pending_mode',))
        pb('\033P'), pb('='), pb('2s')
        pb('\033\\', ('draw', 'e'), ('screen_stop_pending_mode',))
        pb('\033P=1sxyz;.;\033\\''\033P=2skjf".,><?_+)98\033\\', ('screen_start_pending_mode',))
        pb('\033P=1s\033\\f\033P=1s\033\\', ('screen_start_pending_mode',), ('screen_start_pending_mode',))
        pb('\033P=2s\033\\', ('draw', 'f'), ('screen_stop_pending_mode',))
        pb('\033P=1s\033\\XXX\033P=2s\033\\', ('screen_start_pending_mode',), ('draw', 'XXX'), ('screen_stop_pending_mode',))

        pb('\033[?2026hXXX\033[?2026l', ('screen_set_mode', 2026, 1), ('draw', 'XXX'), ('screen_reset_mode', 2026, 1))
        pb('\033[?2026h\033[32ma\033[?2026l', ('screen_set_mode', 2026, 1), ('select_graphic_rendition', '32 '), ('draw', 'a'), ('screen_reset_mode', 2026, 1))
        pb('\033[?2026h\033P+q544e\033\\ama\033P=2s\033\\',
           ('screen_set_mode', 2026, 1), ('screen_request_capabilities', 43, '544e'), ('draw', 'ama'), ('screen_stop_pending_mode',))

        s.reset()
        s.set_pending_timeout(timeout)
        pb('\033[?2026h', ('screen_set_mode', 2026, 1),)
        pb('\033P+q')
        time.sleep(1.2 * timeout)
        pb(
            '544e' + '\033\\\033P=2s\033\\',
            ('screen_request_capabilities', 43, '544e'),
            ('Pending mode stop command issued while not in pending mode, this can be '
             'either a bug in the terminal application or caused by a timeout with no '
             'data received for too long or by too much data in pending mode',),
            ('screen_stop_pending_mode',)
        )
        self.assertEqual(str(s.line(0)), '')

        pb('\033[?2026h', ('screen_set_mode', 2026, 1),)
        pb('ab')
        s.set_pending_activated_at(0.00001)
        pb('cd', ('draw', 'abcd'))
        pb('\033[?2026h', ('screen_set_mode', 2026, 1),)
        pb('\033')
        s.set_pending_activated_at(0.00001)
        pb('7', ('screen_save_cursor',))
        pb('\033[?2026h\033]', ('screen_set_mode', 2026, 1),)
        s.set_pending_activated_at(0.00001)
        pb('8;;\x07', ('set_active_hyperlink', None, None))
        pb('\033[?2026h\033', ('screen_set_mode', 2026, 1),)
        s.set_pending_activated_at(0.00001)
        pb(']8;;\x07', ('set_active_hyperlink', None, None))

    def test_oth_codes(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('a\033_+\\+\033\\bcde', ('draw', 'a'), ('Unrecognized APC code: 0x2b',), ('draw', 'bcde'))
        pb('a\033^+\\+\033\\bcde', ('draw', 'a'), ('Unrecognized PM code: 0x2b',), ('draw', 'bcde'))

    def test_graphics_command(self):
        from base64 import standard_b64encode

        def enc(x):
            return standard_b64encode(x.encode('utf-8') if isinstance(x, str) else x).decode('ascii')

        def c(**k):
            for p, v in tuple(k.items()):
                if isinstance(v, str) and p != 'payload':
                    k[p] = v.encode('ascii')
            for f in 'action delete_action transmission_type compressed'.split():
                k.setdefault(f, b'\0')
            for f in ('format more id data_sz data_offset width height x_offset y_offset data_height data_width cursor_movement'
                      ' num_cells num_lines cell_x_offset cell_y_offset z_index placement_id image_number quiet unicode_placement'
                      ' parent_id parent_placement_id offset_from_parent_x offset_from_parent_y'
            ).split():
                k.setdefault(f, 0)
            p = k.pop('payload', '').encode('utf-8')
            k['payload_sz'] = len(p)
            return ('graphics_command', k, p)

        def t(cmd, **kw):
            pb('\033_G{};{}\033\\'.format(cmd, enc(kw.get('payload', ''))), c(**kw))

        def e(cmd, err):
            pb(f'\033_G{cmd}\033\\', (err,))

        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        uint32_max = 2**32 - 1
        t('i=%d' % uint32_max, id=uint32_max)
        t('i=3,p=4', id=3, placement_id=4)
        e('i=%d' % (uint32_max + 1), 'Malformed GraphicsCommand control block, number is too large')
        pb('\033_Gi=12\033\\', c(id=12))
        t('a=t,t=d,s=100,z=-9', payload='X', action='t', transmission_type='d', data_width=100, z_index=-9, payload_sz=1)
        t('a=t,t=d,s=100,z=9', payload='payload', action='t', transmission_type='d', data_width=100, z_index=9, payload_sz=7)
        t('a=t,t=d,s=100,z=9,q=2', action='t', transmission_type='d', data_width=100, z_index=9, quiet=2)
        e(',s=1', 'Malformed GraphicsCommand control block, invalid key character: 0x2c')
        e('W=1', 'Malformed GraphicsCommand control block, invalid key character: 0x57')
        e('1=1', 'Malformed GraphicsCommand control block, invalid key character: 0x31')
        e('a=t,,w=2', 'Malformed GraphicsCommand control block, invalid key character: 0x2c')
        e('s', 'Malformed GraphicsCommand control block, no = after key')
        e('s=', 'Malformed GraphicsCommand control block, expecting an integer value')
        e('s==', 'Malformed GraphicsCommand control block, expecting an integer value for key: s')
        e('s=1=', 'Malformed GraphicsCommand control block, expecting a comma or semi-colon after a value, found: 0x3d')

    def test_deccara(self):
        s = self.create_screen()
        pb = partial(self.parse_bytes_dump, s)
        pb('\033[$r', ('deccara', '0 0 0 0 0 '))
        pb('\033[;;;;4:3;38:5:10;48:2:1:2:3;1$r',
           ('deccara', '0 0 0 0 4 3 '), ('deccara', '0 0 0 0 38 5 10 '), ('deccara', '0 0 0 0 48 2 1 2 3 '), ('deccara', '0 0 0 0 1 '))
        for y in range(s.lines):
            line = s.line(y)
            for x in range(s.columns):
                c = line.cursor_from(x)
                self.ae(c.bold, True)
                self.ae(c.italic, False)
                self.ae(c.decoration, 3)
                self.ae(c.fg, (10 << 8) | 1)
                self.ae(c.bg, (1 << 24 | 2 << 16 | 3 << 8 | 2))
        self.ae(s.line(0).cursor_from(0).bold, True)
        pb('\033[1;2;2;3;22;39$r', ('deccara', '1 2 2 3 22 '), ('deccara', '1 2 2 3 39 '))
        self.ae(s.line(0).cursor_from(0).bold, True)
        line = s.line(0)
        for x in range(1, s.columns):
            c = line.cursor_from(x)
            self.ae(c.bold, False)
            self.ae(c.fg, 0)
        line = s.line(1)
        for x in range(0, 3):
            c = line.cursor_from(x)
            self.ae(c.bold, False)
        self.ae(line.cursor_from(3).bold, True)
        pb('\033[2*x\033[3;2;4;3;34$r\033[*x', ('screen_decsace', 2), ('deccara', '3 2 4 3 34 '), ('screen_decsace', 0))
        for y in range(2, 4):
            line = s.line(y)
            for x in range(s.columns):
                self.ae(line.cursor_from(x).fg, (10 << 8 | 1) if x < 1 or x > 2 else (4 << 8) | 1)
