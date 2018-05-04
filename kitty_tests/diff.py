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

    def test_split_to_size(self):
        from kittens.diff.render import split_to_size_with_center
        for line, width, prefix_count, suffix_count, expected in [
                ('abcdefgh', 20, 2, 3, ('abSScdeEEfgh',)),
                ('abcdefgh', 20, 2, 0, ('abSScdefgh',)),
                ('abcdefgh', 3, 2, 3, ('abSSc', 'SSdeEEf', 'gh')),
                ('abcdefgh', 2, 4, 1, ('ab', 'cd', 'SSef', 'SSgEEh')),
        ]:
            self.ae(expected, tuple(split_to_size_with_center(
                line, width, prefix_count, suffix_count, 'SS', 'EE')))
