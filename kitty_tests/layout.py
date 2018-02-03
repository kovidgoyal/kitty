#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest
from kitty.config import defaults
from kitty.layout import Stack, Horizontal


class Window:

    def __init__(self, win_id, overlay_for=None, overlay_window_id=None):
        self.id = win_id
        self.overlay_for = overlay_for
        self.overlay_window_id = overlay_window_id
        self.is_visible_in_layout = True

    def set_visible_in_layout(self, idx, val):
        self.is_visible_in_layout = bool(val)

    def set_geometry(self, idx, geometry):
        self.geometry = geometry


def create_layout(cls, opts=None, border_width=2):
    if opts is None:
        opts = defaults
    ans = cls(1, 1, opts, border_width)
    ans.set_active_window_in_os_window = lambda idx: None
    ans.swap_windows_in_os_window = lambda a, b: None
    return ans


def create_windows(num=5):
    return [Window(i + 1) for i in range(num)]


class TestLayout(BaseTest):

    def do_ops_test(self, q):
        windows = create_windows()

        def ids():
            return [w.id for w in windows]

        def visible_ids():
            return {w.id for w in windows if w.is_visible_in_layout}

        def expect_ids(*a):
            self.assertEqual(tuple(ids()), a)

        def check_visible():
            if q.only_active_window_visible:
                self.ae(visible_ids(), {windows[active_window_idx].id})
            else:
                self.ae(visible_ids(), set(ids()))

        active_window_idx = 0
        # Test layout
        self.ae(q(windows, active_window_idx), active_window_idx)
        expect_ids(*range(1, len(windows)+1))
        check_visible()
        # Test nth_window
        for i in range(len(windows)):
            active_window_idx = q.nth_window(windows, i)
            self.ae(active_window_idx, i)
            expect_ids(*range(1, len(windows)+1))
            check_visible()
        # Test next_window
        for i in range(2 * len(windows)):
            expected = (active_window_idx + 1) % len(windows)
            active_window_idx = q.next_window(windows, active_window_idx)
            self.ae(active_window_idx, expected)
            expect_ids(*range(1, len(windows)+1))
            check_visible()
        # Test move_window
        active_window_idx = 0
        active_window_idx = q.move_window(windows, active_window_idx, 3)
        self.ae(active_window_idx, 3)
        expect_ids(4, 2, 3, 1, 5)
        check_visible()
        q.move_window(windows, 0, 3)
        expect_ids(*range(1, len(windows)+1))
        check_visible()
        # Test add_window
        active_window_idx = q.add_window(windows, Window(6), active_window_idx)
        self.ae(active_window_idx, 5)
        expect_ids(*range(1, len(windows)+1))
        check_visible()
        # Test remove_window
        active_window_idx = 3
        expected = active_window_idx
        active_window_idx = q.remove_window(windows, windows[active_window_idx], active_window_idx)
        self.ae(active_window_idx, expected)
        check_visible()
        expect_ids(1, 2, 3, 5, 6)
        w = windows[active_window_idx]
        active_window_idx = q.remove_window(windows, windows[0], active_window_idx)
        self.ae(active_window_idx, windows.index(w))
        check_visible()
        expect_ids(2, 3, 5, 6)
        # Test set_active_window
        for i in range(len(windows)):
            active_window_idx = q.set_active_window(windows, i)
            self.ae(i, active_window_idx)
            check_visible()

    def test_layout_operations(self):
        for layout_class in Stack, Horizontal:
            q = create_layout(Stack)
            self.do_ops_test(q)
