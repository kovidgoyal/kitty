#!/usr/bin/env python
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
