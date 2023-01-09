#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.clipboard import WriteRequest

from . import BaseTest


class TestClipboard(BaseTest):

    def test_clipboard_write_request(self):
        wr = WriteRequest(max_size=64)
        wr.add_base64_data('bGlnaHQgd29yaw')
        self.ae(bytes(wr.current_leftover_bytes), b'aw')
        wr.flush_base64_data()
        self.ae(wr.data_for(), b'light work')
        wr = WriteRequest(max_size=64)
        wr.add_base64_data('bGlnaHQgd29yaw==')
        self.ae(wr.data_for(), b'light work')
        wr = WriteRequest(max_size=64)
        wr.add_base64_data('bGlnaHQgd29')
        for x in b'y', b'a', b'y', b'4', b'=':
            wr.add_base64_data(x)
        self.ae(wr.data_for(), b'light work.')
        wr = WriteRequest(max_size=64)
        for x in 'bGlnaHQgd29y':
            wr.add_base64_data(x)
        self.ae(wr.data_for(), b'light wor')
