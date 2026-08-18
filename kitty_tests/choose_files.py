#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import shlex

from .base import BaseTest


class TestChooseFiles(BaseTest):
    def test_format_selection_for_paste(self) -> None:
        from kittens.choose_files.main import format_selection_for_paste

        paths = ['/work/simple', '/work/a path', '/work/a;command', '/work/*.txt', '/work/~root', '/work/a>output', r'/work/a\b', "/work/it's"]
        text = format_selection_for_paste(paths, '/work', at_prompt=True)
        self.assertEqual(shlex.split(text), [path.removeprefix('/work/') for path in paths])
        self.assertEqual(format_selection_for_paste(paths[:2], '/work', at_prompt=False), 'simple\na path')
