#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from . import BaseTest


class TestDiff(BaseTest):

    def test_changed_center(self):
        from kittens.diff.diff_speedup import changed_center
        for left, right, prefix, suffix in [
                ('abc', 'def', '', ''),
                ('', 'def', '', ''),
                ('abc', '', '', ''),
                ('abc', 'abc', 'abc', ''),
                ('abc', 'abcdef', 'abc', ''),
                ('aa111bb', 'aa2bb', 'aa', 'bb'),
        ]:
            pc, sc = changed_center(left, right)
            for src in (left, right):
                self.assertEqual((prefix, suffix), (src[:pc], src[-sc:] if sc else ''))
