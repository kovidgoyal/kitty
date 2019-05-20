#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from . import BaseTest
from kitty.config import defaults
from kitty.layout import Stack, Horizontal, idx_for_id
from kitty.fast_data_types import pt_to_px


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
    mw, pw = map(pt_to_px, (opts.window_margin_width, opts.window_padding_width))
    ans = cls(1, 1, mw, mw, pw, border_width)
    ans.set_active_window_in_os_window = lambda idx: None
    ans.swap_windows_in_os_window = lambda a, b: None
    return ans


def create_windows(num=5):
    return [Window(i + 1) for i in range(num)]


def utils(self, q, windows):
    def ids():
        return [w.id for w in windows]

    def visible_ids():
        return {w.id for w in windows if w.is_visible_in_layout}

    def expect_ids(*a):
        self.assertEqual(tuple(ids()), a)

    def check_visible(active_window_idx):
        if q.only_active_window_visible:
            self.ae(visible_ids(), {windows[active_window_idx].id})
        else:
            self.ae(visible_ids(), {w.id for w in windows if w.overlay_window_id is None})
    return ids, visible_ids, expect_ids, check_visible


class TestLayout(BaseTest):

    def do_ops_test(self, q):
        windows = create_windows()
        ids, visible_ids, expect_ids, cv = utils(self, q, windows)

        def check_visible():
            return cv(active_window_idx)
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

    def do_overlay_test(self, q):
        windows = create_windows()
        ids, visible_ids, expect_ids, cv = utils(self, q, windows)

        def check_visible():
            return cv(active_window_idx)

        def aidx(i):
            return idx_for_id(visible_windows[i].id, windows)

        # Test add_window
        w = Window(len(windows) + 1)
        active_window_idx = 1
        w.overlay_for = windows[active_window_idx].id
        windows[active_window_idx].overlay_window_id = w.id
        active_window_idx = q.add_window(windows, w, active_window_idx)
        self.ae(active_window_idx, 1)
        expect_ids(1, 6, 3, 4, 5, 2)
        check_visible()
        # Test layout
        self.ae(q(windows, active_window_idx), active_window_idx)
        expect_ids(1, 6, 3, 4, 5, 2)
        check_visible()
        w = Window(len(windows) + 1)
        active_window_idx = q.add_window(windows, w, active_window_idx)
        self.ae(active_window_idx, 6)
        visible_windows = [w for w in windows if w.overlay_window_id is None]
        # Test nth_window
        for i in range(len(visible_windows)):
            active_window_idx = q.nth_window(windows, i)
            self.ae(active_window_idx, aidx(i))
            expect_ids(1, 6, 3, 4, 5, 2, 7)
            check_visible()
        # Test next_window
        for i in range(len(visible_windows)):
            active_window_idx = q.next_window(windows, aidx(i))
            expected = (i + 1) % len(visible_windows)
            self.ae(active_window_idx, aidx(expected))
            expect_ids(1, 6, 3, 4, 5, 2, 7)
            check_visible()
        # Test move_window
        active_window_idx = q.move_window(windows, 4)
        self.ae(active_window_idx, 6)
        expect_ids(1, 6, 3, 4, 7, 2, 5)
        check_visible()
        # Test set_active_window
        active_window_idx = q.set_active_window(windows, 0)
        self.ae(active_window_idx, 0)
        check_visible()
        active_window_idx = q.set_active_window(windows, 5)
        self.ae(active_window_idx, 1)
        check_visible()
        # Test remove_window
        active_window_idx = q.remove_window(windows, windows[1], 1)
        expect_ids(1, 2, 3, 4, 7, 5)
        self.ae(active_window_idx, 1)
        check_visible()

    def test_layout_operations(self):
        for layout_class in Stack, Horizontal:
            q = create_layout(layout_class)
            self.do_ops_test(q)

    def test_overlay_layout_operations(self):
        for layout_class in Stack, Horizontal:
            q = create_layout(layout_class)
            self.do_overlay_test(q)
