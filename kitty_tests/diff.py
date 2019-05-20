#!/usr/bin/env python3
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

    def test_split_with_highlights(self):
        from kittens.diff.render import split_with_highlights, Segment, truncate_points
        self.ae(list(truncate_points('1234567890ab', 3)), [3, 6, 9])
        for line, width, prefix_count, suffix_count, expected in [
                ('abcdefgh', 20, 2, 3, ('abSScdeEEfgh',)),
                ('abcdefgh', 20, 2, 0, ('abSScdefghEE',)),
                ('abcdefgh', 3, 2, 3, ('abSScEE', 'SSdeEEf', 'gh')),
                ('abcdefgh', 2, 4, 1, ('ab', 'cd', 'SSefEE', 'SSgEEh')),
        ]:
            seg = Segment(prefix_count, 'SS')
            seg.end = len(line) - suffix_count
            seg.end_code = 'EE'
            self.ae(expected, tuple(split_with_highlights(line, width, [], seg)))

        def h(s, e, w):
            ans = Segment(s, 'S{}S'.format(w))
            ans.end = e
            ans.end_code = 'E{}E'.format(w)
            return ans

        highlights = [h(0, 1, 1), h(1, 3, 2)]
        self.ae(['S1SaE1ES2SbcE2Ed'], split_with_highlights('abcd', 10, highlights))
