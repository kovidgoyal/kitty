#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

from base64 import standard_b64decode, standard_b64encode

from kitty.clipboard import WriteRequest
from kitty.fast_data_types import StreamingBase64Decoder

from .base import BaseTest


class TestClipboard(BaseTest):
    def test_clipboard_write_request(self):
        def t(data, expected):
            wr = WriteRequest(max_size=64)
            wr.add_base64_data(data)
            self.ae(wr.data_for(), expected)

        t('dGl0bGU=', b'title')
        t('dGl0bGU', b'title')
        t('dGl0bG', b'titl')
        t('dGl0bG==', b'titl')
        t('dGl0b', b'tit')
        t('bGlnaHQgd29yaw', b'light work')
        t('bGlnaHQgd29yaw==', b'light work')
        wr = WriteRequest(max_size=64)
        wr.add_base64_data('bGlnaHQgd29')
        for x in b'y', b'a', b'y', b'4', b'=':
            wr.add_base64_data(x)
        self.ae(wr.data_for(), b'light work.')
        wr = WriteRequest(max_size=64)
        for x in 'bGlnaHQgd29y':
            wr.add_base64_data(x)
        self.ae(wr.data_for(), b'light wor')

    def test_base64_streaming_decoder(self):
        d = StreamingBase64Decoder()
        c = standard_b64encode(b'abcdef')
        self.ae(b'abcdef', d.decode(c))
        self.assertFalse(d.needs_more_data())
        a = d.decode(c[:4])
        self.assertFalse(d.needs_more_data())
        self.ae(b'abcdef', a + d.decode(c[4:]))
        self.assertFalse(d.needs_more_data())
        a = d.decode(c[:1])
        self.assertTrue(d.needs_more_data())
        self.ae(b'abcdef', a + d.decode(c[1:4]) + d.decode(c[4:]))
        self.assertFalse(d.needs_more_data())
        c = standard_b64encode(b'abcd')
        self.ae(b'abcd', d.decode(c[:2]) + d.decode(c[2:]))
        c1 = standard_b64encode(b'1' * 4096)
        c2 = standard_b64encode(b'2' * 4096)
        self.ae(standard_b64decode(c1) + standard_b64decode(c2), d.decode(c1) + d.decode(c2))
        self.assertFalse(d.needs_more_data())

    def test_clipboard_write_too_much_data(self):
        from kitty.clipboard import Clipboard, ClipboardRequestManager, ClipboardType, encode_mime
        from kitty.fast_data_types import set_boss

        class Window:
            id = 1

            def __init__(self, screen):
                self.screen = screen

        class Boss:
            def __init__(self, window):
                self.clipboard = Clipboard()
                self.primary_selection = Clipboard(ClipboardType.primary_selection)
                self.window_id_map = {window.id: window}

        s = self.create_screen(options={'clipboard_max_size': 16 / (1024 * 1024)})
        c = s.callbacks
        w = Window(s)
        set_boss(Boss(w))
        try:
            crm = ClipboardRequestManager(w.id)

            def send(metadata, payload=b''):
                data = metadata.encode('ascii')
                if payload:
                    data += b';' + standard_b64encode(payload)
                crm.parse_osc_5522(memoryview(data))

            mime = f'mime={encode_mime("text/plain")}'
            send('type=write')
            send(f'type=wdata:{mime}', b'a' * 16)
            self.ae(c.wtcbuf, b'')
            self.assertIsNotNone(crm.in_flight_write_request)
            send(f'type=wdata:{mime}', b'a' * 4)
            self.assertIn(b'type=write:status=EFBIG', c.wtcbuf)
            self.assertIsNone(crm.in_flight_write_request)
            # further packets for the aborted request must be ignored
            c.clear()
            send(f'type=wdata:{mime}', b'a' * 4)
            send('type=wdata')
            self.ae(c.wtcbuf, b'')
        finally:
            set_boss(None)

    def test_clipboard_malformed_write_packets(self):
        from kitty.clipboard import Clipboard, ClipboardRequestManager, ClipboardType, encode_mime
        from kitty.fast_data_types import set_boss

        class Window:
            id = 1

            def __init__(self, screen):
                self.screen = screen

        class Boss:
            def __init__(self, window):
                self.clipboard = Clipboard()
                self.primary_selection = Clipboard(ClipboardType.primary_selection)
                self.window_id_map = {window.id: window}

        s = self.create_screen()
        c = s.callbacks
        w = Window(s)
        set_boss(Boss(w))
        try:
            crm = ClipboardRequestManager(w.id)

            def send(metadata, epayload=b''):
                data = metadata.encode('ascii')
                if epayload:
                    data += b';' + epayload
                crm.parse_osc_5522(memoryview(data))

            mime = f'mime={encode_mime("text/plain")}'

            def t(*packets):
                c.clear()
                send('type=write:id=w1')
                send(f'type=wdata:{mime}', standard_b64encode(b'xxx'))
                c.clear()
                for packet in packets:
                    send(*packet)
                self.ae(c.wtcbuf, b'\x1b]5522;type=write:status=EINVAL:id=w1\x1b\\')
                self.assertIsNone(crm.in_flight_write_request)
                # further packets for the aborted request must be ignored
                c.clear()
                send(f'type=wdata:{mime}', standard_b64encode(b'xxx'))
                send('type=wdata')
                self.ae(c.wtcbuf, b'')

            # alias payload that is not valid base64
            t((f'type=walias:{mime}', b'AAA'))
            # alias payload that is not valid UTF-8
            t((f'type=walias:{mime}', b'/w=='))
            # alias packet without a MIME type
            t(('type=walias', standard_b64encode(b'text/rtf')))
            # metadata value that is not valid base64
            t(('type=walias:mime=AAA', standard_b64encode(b'text/rtf')))
            t(('type=wdata:mime=AAA', standard_b64encode(b'xxx')))
            # a malformed read packet must not abort the write request
            c.clear()
            send('type=write:id=w2')
            send('type=read:id=r1', b'AAA')
            self.ae(c.wtcbuf, b'')
            self.assertIsNotNone(crm.in_flight_write_request)
        finally:
            set_boss(None)
