#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from base64 import standard_b64decode

from kitty.activation_token import InvalidRequest, Request, error_reply, parse_request, query_reply, token_reply

from .base import BaseTest


class TestActivationToken(BaseTest):
    def test_activation_token_requests(self):
        for raw, expected in {
            'i=abc': Request('abc'),
            'i=a.b-c_d+e': Request('a.b-c_d+e'),
            'i=q:p=?': Request('q', True),
            'p=?:i=q': Request('q', True),
            'i=abc;ignored payload': Request('abc'),
            'i=abc:x=unknown': Request('abc'),
            'i=' + 'a' * 64: Request('a' * 64),
        }.items():
            self.ae(parse_request(raw), expected, raw)
        for raw in ('', 'i=', 'abc', 'i=a b', 'i=' + 'a' * 65, 'i=a:p=x', 'i=a\x1b', 'i=a:junk', 'i=a\n', 'i=a\n:p=?', 'i=\na', 'i=a\r'):
            with self.assertRaises(InvalidRequest, msg=repr(raw)):
                parse_request(raw)

        req = Request('x1')
        self.ae(query_reply(Request('q', True)), '5524;i=q:p=?;ok')
        self.ae(error_reply(req, 'ENOTFOCUSED'), '5524;i=x1:e=ENOTFOCUSED')
        token = 'a;b\x1b\\cé'
        reply = token_reply(req, token)
        prefix = '5524;i=x1;'
        self.assertTrue(reply.startswith(prefix))
        payload = reply[len(prefix) :]
        # The token is encoded so it cannot terminate or corrupt the escape code
        self.assertNotIn(';', payload)
        self.assertNotIn('\x1b', payload)
        self.ae(standard_b64decode(payload).decode(), token)
