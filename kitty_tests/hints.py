#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
from . import BaseTest


class TestHints(BaseTest):

    def test_url_hints(self):
        from kittens.hints.main import (
            Mark, convert_text, functions_for, linenum_marks,
            linenum_process_result, mark, parse_hints_args
        )
        args = parse_hints_args([])[0]
        pattern, post_processors = functions_for(args)

        def create_marks(text, cols=20, mark=mark):
            text = convert_text(text, cols)
            return tuple(mark(pattern, post_processors, text, args))

        def t(text, url, cols=20):
            marks = create_marks(text, cols)
            urls = [m.text for m in marks]
            self.ae(urls, [url])

        u = 'http://test.me/'
        t(u, 'http://test.me/')
        t(f'"{u}"', u)
        t(f'({u})', u)
        t(u + '\nxxx', u + 'xxx', len(u))
        t(f'link:{u}[xxx]', u)
        t(f'`xyz <{u}>`_.', u)
        t(f'<a href="{u}">moo', u)

        def m(text, path, line, cols=20):

            def adapt(pattern, postprocessors, text, *a):
                return linenum_marks(text, args, Mark, ())

            marks = create_marks(text, cols, mark=adapt)
            data = {'groupdicts': [m.groupdict for m in marks], 'match': [m.text for m in marks]}
            self.ae(linenum_process_result(data), (path, line))

        args = parse_hints_args('--type=linenum'.split())[0]
        m('file.c:23', 'file.c', 23)
        m('file.c:23:32', 'file.c', 23)
        m('file.cpp:23:1', 'file.cpp', 23)
        m('a/file.c:23', 'a/file.c', 23)
        m('a/file.c:23:32', 'a/file.c', 23)
        m('~/file.c:23:32', os.path.expanduser('~/file.c'), 23)

    def test_ip_hints(self):
        from kittens.hints.main import (
            convert_text, functions_for, mark, parse_hints_args
        )
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
