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
