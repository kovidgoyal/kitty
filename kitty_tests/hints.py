#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from . import BaseTest


class TestHints(BaseTest):

    def test_url_hints(self):
        from kittens.hints.main import parse_hints_args, functions_for, mark, convert_text
        args = parse_hints_args([])[0]
        pattern, post_processors = functions_for(args)

        def create_marks(text, cols=20):
            text = convert_text(text, cols)
            return tuple(mark(pattern, post_processors, text, args))

        def t(text, url, cols=20):
            marks = create_marks(text, cols)
            urls = [m.text for m in marks]
            self.ae(urls, [url])

        u = 'http://test.me/'
        t(u, 'http://test.me/')
        t('"{}"'.format(u), u)
        t('({})'.format(u), u)
        t(u + '\nxxx', u + 'xxx', len(u))
        t('link:{}[xxx]'.format(u), u)
        t('`xyz <{}>`_.'.format(u), u)
        t('<a href="{}">moo'.format(u), u)

    def test_ip_hints(self):
        from kittens.hints.main import parse_hints_args, functions_for, mark, convert_text
        args = parse_hints_args(['--type', 'ip'])[0]
        pattern, post_processors = functions_for(args)

        def create_marks(text, cols=60):
            text = convert_text(text, cols)
            return tuple(mark(pattern, post_processors, text, args))

        testcases = (
            ('100.64.0.0', ['100.64.0.0']),
            ('2001:0db8:0000:0000:0000:ff00:0042:8329', ['2001:0db8:0000:0000:0000:ff00:0042:8329']),
            ('2001:db8:0:0:0:ff00:42:8329', ['2001:db8:0:0:0:ff00:42:8329']),
            ('2001:db8::ff00:42:8329', ['2001:db8::ff00:42:8329']),
            ('2001:DB8::FF00:42:8329', ['2001:DB8::FF00:42:8329']),
            ('0000:0000:0000:0000:0000:0000:0000:0001', ['0000:0000:0000:0000:0000:0000:0000:0001']),
            ('::1', ['::1']),
            # Invalid IPs won't match
            ('255.255.255.256', []),
            (':1', []),
        )

        for testcase, expected in testcases:
            with self.subTest(testcase=testcase, expected=expected):
                marks = create_marks(testcase)
                ips = [m.text for m in marks]
                self.ae(ips, expected)
