#!/usr/bin/env python3
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
        from kittens.diff.render import Segment, split_with_highlights, truncate_points
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
            ans = Segment(s, f'S{w}S')
            ans.end = e
            ans.end_code = f'E{w}E'
            return ans

        highlights = [h(0, 1, 1), h(1, 3, 2)]
        self.ae(['S1SaE1ES2SbcE2Ed'], split_with_highlights('abcd', 10, highlights))

    def test_walk(self):
        import tempfile
        from pathlib import Path

        from kittens.diff.collect import walk

        with tempfile.TemporaryDirectory() as tmpdir:
            # /tmp/test/
            # ├── a
            # │   └── b
            # │       └── c
            # ├── d
            # ├── #d#
            # ├── e
            # ├── e~
            # └── f
            # │   └── g
            # └── h space
            Path(tmpdir, "a/b").mkdir(parents=True)
            Path(tmpdir, "a/b/c").touch()
            Path(tmpdir, "b").touch()
            Path(tmpdir, "d").touch()
            Path(tmpdir, "#d#").touch()
            Path(tmpdir, "e").touch()
            Path(tmpdir, "e~").touch()
            Path(tmpdir, "f").mkdir()
            Path(tmpdir, "f/g").touch()
            Path(tmpdir, "h space").touch()
            expected_names = {"d", "e", "f/g", "h space"}
            expected_pmap = {
                "d": f"{tmpdir}/d",
                "e": f"{tmpdir}/e",
                "f/g": f"{tmpdir}/f/g",
                "h space": f"{tmpdir}/h space"
            }
            names = set()
            pmap = {}
            walk(tmpdir, names, pmap, ("*~", "#*#", "b"))
            self.ae(expected_names, names)
            self.ae(expected_pmap, pmap)
