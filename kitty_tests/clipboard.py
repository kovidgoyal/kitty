#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

from base64 import standard_b64decode, standard_b64encode

from kitty.clipboard import WriteRequest
from kitty.fast_data_types import StreamingBase64Decoder

from . import BaseTest


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
