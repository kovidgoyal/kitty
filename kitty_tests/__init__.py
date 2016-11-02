#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import defaultdict
from unittest import TestCase

from kitty.screen import Screen
from kitty.tracker import ChangeTracker
from kitty.config import defaults


class BaseTest(TestCase):

    ae = TestCase.assertEqual

    def create_screen(self, cols=5, lines=5, history_size=5):
        t = ChangeTracker()
        opts = defaults._replace(scrollback_lines=history_size)
        s = Screen(opts, t, columns=cols, lines=lines)
        return s, t

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2

    def assertChanges(self, t, ignore='', **expected_changes):
        actual_changes = t.consolidate_changes()
        ignore = frozenset(ignore.split())
        for k, v in actual_changes.items():
            if isinstance(v, defaultdict):
                v = dict(v)
            if k not in ignore:
                if k in expected_changes:
                    self.ae(expected_changes[k], v)
                else:
                    self.assertFalse(v, 'The property {} was expected to be empty but is: {}'.format(k, v))
