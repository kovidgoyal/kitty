#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from . import BaseTest


class TestUnicodeInput(BaseTest):

    def test_word_trie(self):
        from kittens.unicode_input.unicode_names import codepoints_for_word

        def matches(a, *words):
            ans = codepoints_for_word(a)
            for w in words:
                ans &= codepoints_for_word(w)
            return set(ans)

        self.ae(matches('horiz', 'ell'), {0x2026, 0x22ef, 0x2b2c, 0x2b2d, 0xfe19})
        self.ae(matches('horizontal', 'ell'), {0x2026, 0x22ef, 0x2b2c, 0x2b2d, 0xfe19})
        self.assertFalse(matches('sfgsfgsfgfgsdg'))
