#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.config import defaults
from kitty.layout.interface import Grid, Horizontal, Splits, Stack, Tall
from kitty.types import WindowGeometry
from kitty.window import EdgeWidths
from kitty.window_list import WindowList, reset_group_id_counter

from . import BaseTest


class Window:

    def __init__(self, win_id, overlay_for=None, overlay_window_id=None):
        self.id = win_id
        self.overlay_for = overlay_for
        self.overlay_window_id = overlay_window_id
        self.is_visible_in_layout = True
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.padding = EdgeWidths()
        self.margin = EdgeWidths()
        self.focused = False

    def focus_changed(self, focused):
        self.focused = focused

    def effective_border(self):
        return 1

    def effective_padding(self, edge):
        return 1

    def effective_margin(self, edge):
        return 1

    def set_visible_in_layout(self, val):
        self.is_visible_in_layout = bool(val)

    def set_geometry(self, geometry):
        self.geometry = geometry


def create_layout(cls, opts=None, border_width=2):
    if opts is None:
        opts = defaults
    ans = cls(1, 1)
    ans.set_active_window_in_os_window = lambda idx: None
    ans.swap_windows_in_os_window = lambda a, b: None
    return ans


class Tab:

    def active_window_changed(self):
        self.current_layout.update_visibility(self.windows)


def create_windows(layout, num=5):
    t = Tab()
    t.current_layout = layout
    t.windows = ans = WindowList(t)
    ans.tab_mem = t
    reset_group_id_counter()
    for i in range(num):
        ans.add_window(Window(i + 1))
    ans.set_active_group_idx(0)
    return ans


def utils(self, q, windows):
    def ids():
        return [w.id for w in windows.groups]

    def visible_ids():
        return {gr.id for gr in windows.groups if gr.is_visible_in_layout}

    def expect_ids(*a):
        self.assertEqual(tuple(ids()), a)

    def check_visible():
        if q.only_active_window_visible:
            self.ae(visible_ids(), {windows.active_group.id})
        else:
            self.ae(visible_ids(), {gr.id for gr in windows.groups})
    return ids, visible_ids, expect_ids, check_visible


class TestLayout(BaseTest):

    def do_ops_test(self, q):
        windows = create_windows(q)
        ids, visible_ids, expect_ids, check_visible = utils(self, q, windows)
        # Test layout
        q(windows)
        self.ae(windows.active_group_idx, 0)
        expect_ids(*range(1, len(windows)+1))
        check_visible()

        # Test nth_window
        for i in range(windows.num_groups):
            q.activate_nth_window(windows, i)
            self.ae(windows.active_group_idx, i)
            expect_ids(*range(1, len(windows)+1))
            check_visible()

        # Test next_window
        for i in range(2 * windows.num_groups):
            expected = (windows.active_group_idx + 1) % windows.num_groups
            q.next_window(windows)
            self.ae(windows.active_group_idx, expected)
            expect_ids(*range(1, len(windows)+1))
            check_visible()

        # Test move_window
        windows.set_active_group_idx(0)
        expect_ids(1, 2, 3, 4, 5)
        q.move_window(windows, 3)
        self.ae(windows.active_group_idx, 3)
        expect_ids(4, 2, 3, 1, 5)
        check_visible()
        windows.set_active_group_idx(0)
        q.move_window(windows, 3)
        expect_ids(*range(1, len(windows)+1))
        check_visible()

        # Test add_window
        windows.set_active_group_idx(4)
        q.add_window(windows, Window(6))
        self.ae(windows.num_groups, 6)
        self.ae(windows.active_group_idx, 5)
        expect_ids(*range(1, windows.num_groups+1))
        check_visible()

        # Test remove_window
        prev_window = windows.active_window
        windows.set_active_group_idx(3)
        self.ae(windows.active_group_idx, 3)
        windows.remove_window(windows.active_window)
        self.ae(windows.active_window, prev_window)
        check_visible()
        expect_ids(1, 2, 3, 5, 6)

        windows.set_active_group_idx(0)
        to_remove = windows.active_window
        windows.set_active_group_idx(3)
        windows.remove_window(to_remove)
        self.ae(windows.active_group_idx, 3)
        check_visible()
        expect_ids(2, 3, 5, 6)

        # Test set_active_window
        for i in range(windows.num_groups):
            windows.set_active_group_idx(i)
            self.ae(i, windows.active_group_idx)
            check_visible()

    def do_overlay_test(self, q):
        windows = create_windows(q)
        ids, visible_ids, expect_ids, check_visible = utils(self, q, windows)

        # Test add_window
        w = Window(len(windows) + 1)
        before = windows.active_group_idx
        overlaid_group = before
        overlay_window_id = w.id
        windows.add_window(w, group_of=windows.active_window)
        self.ae(before, windows.active_group_idx)
        self.ae(w, windows.active_window)
        expect_ids(1, 2, 3, 4, 5)
        check_visible()

        # Test layout
        q(windows)
        expect_ids(1, 2, 3, 4, 5)
        check_visible()
        w = Window(len(windows) + 1)
        windows.add_window(w)
        expect_ids(1, 2, 3, 4, 5, 6)
        self.ae(windows.active_group_idx, windows.num_groups - 1)

        # Test nth_window
        for i in range(windows.num_groups):
            q.activate_nth_window(windows, i)
            self.ae(windows.active_group_idx, i)
            if i == overlaid_group:
                self.ae(windows.active_window.id, overlay_window_id)
            expect_ids(1, 2, 3, 4, 5, 6)
            check_visible()

        # Test next_window
        for i in range(windows.num_groups):
            expected = (windows.active_group_idx + 1) % windows.num_groups
            q.next_window(windows)
            self.ae(windows.active_group_idx, expected)
            expect_ids(1, 2, 3, 4, 5, 6)
            check_visible()

        # Test move_window
        windows.set_active_group_idx(overlaid_group)
        expect_ids(1, 2, 3, 4, 5, 6)
        q.move_window(windows, 3)
        self.ae(windows.active_group_idx, 3)
        self.ae(windows.active_window.id, overlay_window_id)
        expect_ids(4, 2, 3, 1, 5, 6)
        check_visible()
        windows.set_active_group_idx(0)
        q.move_window(windows, 3)
        expect_ids(1, 2, 3, 4, 5, 6)
        check_visible()

        # Test set_active_window
        for i in range(windows.num_groups):
            windows.set_active_group_idx(i)
            self.ae(i, windows.active_group_idx)
            if i == overlaid_group:
                self.ae(windows.active_window.id, overlay_window_id)
            check_visible()

        # Test remove_window
        expect_ids(1, 2, 3, 4, 5, 6)
        windows.set_active_group_idx(overlaid_group)
        windows.remove_window(overlay_window_id)
        self.ae(windows.active_group_idx, overlaid_group)
        self.ae(windows.active_window.id, 1)
        expect_ids(1, 2, 3, 4, 5, 6)
        check_visible()

    def test_layout_operations(self):
        for layout_class in (Stack, Horizontal, Tall, Grid):
            q = create_layout(layout_class)
            self.do_ops_test(q)

    def test_overlay_layout_operations(self):
        for layout_class in (Stack, Horizontal, Tall, Grid):
            q = create_layout(layout_class)
            self.do_overlay_test(q)

    def test_splits(self):
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        q.add_window(all_windows, Window(1))
        self.ae(all_windows.active_group_idx, 0)
        q.add_window(all_windows, Window(2), location='vsplit')
        self.ae(all_windows.active_group_idx, 1)
        q(all_windows)
        self.ae(q.pairs_root.pair_for_window(2).horizontal, True)
        q.add_window(all_windows, Window(3), location='hsplit')
        self.ae(q.pairs_root.pair_for_window(2).horizontal, False)
        q.add_window(all_windows, Window(4), location='vsplit')
        windows = list(all_windows)
        windows[0].set_geometry(WindowGeometry(0, 0, 10, 20, 0, 0))
        windows[1].set_geometry(WindowGeometry(11, 0, 20, 10, 0, 0))
        windows[2].set_geometry(WindowGeometry(11, 11, 15, 20, 0, 0))
        windows[3].set_geometry(WindowGeometry(16, 11, 20, 20, 0, 0))
        self.ae(q.neighbors_for_window(windows[0], all_windows), {'left': [], 'right': [2, 3], 'top': [], 'bottom': []})
        self.ae(q.neighbors_for_window(windows[1], all_windows), {'left': [1], 'right': [], 'top': [], 'bottom': [3, 4]})
        self.ae(q.neighbors_for_window(windows[2], all_windows), {'left': [1], 'right': [4], 'top': [2], 'bottom': []})
        self.ae(q.neighbors_for_window(windows[3], all_windows), {'left': [3], 'right': [], 'top': [2], 'bottom': []})
