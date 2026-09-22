#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from unittest.mock import patch

from kitty.borders import Border, BorderColor, add_borders
from kitty.config import defaults
from kitty.fast_data_types import BOTTOM_EDGE, LEFT_EDGE, RIGHT_EDGE, TOP_EDGE, Region
from kitty.layout.base import CellBias, calculate_cells_map, layout_dimension, lgd, normalize_biases
from kitty.layout.constraints import FixedConstraintModel, FixedSize, LinearConstraintModel, SplitConstraintModel
from kitty.layout.interface import Grid, Horizontal, Splits, Stack, Tall, Vertical
from kitty.layout.splits import Pair, SplitsLayoutOpts
from kitty.types import DockData, WindowGeometry
from kitty.window import EdgeWidths
from kitty.window_list import WindowList, reset_group_id_counter

from .base import BaseTest


class Window:
    def __init__(self, win_id, overlay_for=None, overlay_window_id=None):
        self.id = win_id
        self.serialized_id = 0
        self.overlay_for = overlay_for
        self.overlay_window_id = overlay_window_id
        self.is_visible_in_layout = True
        self.geometry = WindowGeometry(0, 0, 0, 0, 0, 0)
        self.padding = EdgeWidths()
        self.margin = EdgeWidths()
        self.focused = False
        self.dock_data = None

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
    orig = ans._set_dimensions

    def set_dimensions(all_windows):
        orig(all_windows)
        # we need a non-zero width and height for central
        lgd.central = Region((0, 0, 0, 0, 1, 1))

    ans._set_dimensions = set_dimensions
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
    def setUp(self):
        super().setUp()
        self.set_options({'tab_bar_style': 'hidden'})

    def test_window_border_radius_geometry(self):
        q = create_layout(Splits)
        windows = create_windows(q, 1)
        windows.active_window.set_geometry(WindowGeometry(10, 20, 110, 120, 0, 0))
        group = windows.active_group
        color = BorderColor.active
        straight = [
            Border(8, 18, 112, 19, color, -1, True),
            Border(8, 121, 112, 122, color, 1, True),
            Border(8, 18, 9, 122, color, -1),
            Border(111, 18, 112, 122, color, 1),
        ]

        rects = []
        add_borders(rects, color, group)
        self.ae(rects, straight)

        rects = []
        add_borders(rects, color, group, 12)
        self.ae(
            rects,
            [
                *(border._replace(render=False) for border in straight),
                Border(8, 18, 112, 122, color, render=False, radius=12, thickness=1),
            ],
        )

    def do_ops_test(self, q):
        windows = create_windows(q)
        ids, visible_ids, expect_ids, check_visible = utils(self, q, windows)
        # Test layout
        q(windows)
        self.ae(windows.active_group_idx, 0)
        expect_ids(*range(1, len(windows) + 1))
        check_visible()

        # Test nth_window
        for i in range(windows.num_groups):
            q.activate_nth_window(windows, i)
            self.ae(windows.active_group_idx, i)
            expect_ids(*range(1, len(windows) + 1))
            check_visible()

        # Test next_window
        for i in range(2 * windows.num_groups):
            expected = (windows.active_group_idx + 1) % windows.num_groups
            q.next_window(windows)
            self.ae(windows.active_group_idx, expected)
            expect_ids(*range(1, len(windows) + 1))
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
        expect_ids(*range(1, len(windows) + 1))
        check_visible()

        # Test add_window
        windows.set_active_group_idx(4)
        q.add_window(windows, Window(6))
        self.ae(windows.num_groups, 6)
        self.ae(windows.active_group_idx, 5)
        expect_ids(*range(1, windows.num_groups + 1))
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

        # Test

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
        self.ae(q.neighbors_for_window(windows[0], all_windows), {'right': [2, 3]})
        self.ae(q.neighbors_for_window(windows[1], all_windows), {'left': [1], 'bottom': [3, 4]})
        self.ae(q.neighbors_for_window(windows[2], all_windows), {'left': [1], 'right': [4], 'top': [2]})
        self.ae(q.neighbors_for_window(windows[3], all_windows), {'left': [3], 'top': [2]})

    def test_splits_unserialize_into_unused_layout(self):
        # Restoring the state of a layout that was not the active one when the session
        # was saved: its pairs tree is empty, and the window list must not be
        # reordered, since only the layout being made current does that.
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        for wid, loc in ((1, None), (2, 'hsplit'), (3, 'vsplit')):
            win = Window(wid)
            win.serialized_id = wid
            q.add_window(all_windows, win, location=loc)
        q(all_windows)
        expected = {'horizontal': False, 'one': 1, 'two': {'one': 2, 'two': 3}}
        self.ae(q.pairs_root.serialize(), expected)
        state = q.serialize(all_windows)
        groups_before = [g.id for g in all_windows.groups]

        fresh = create_layout(Splits)
        self.ae(fresh.pairs_root.serialize(), {})
        self.assertTrue(fresh.unserialize(state, all_windows, apply_to_window_list=False))
        self.ae(fresh.pairs_root.serialize(), expected)
        self.ae([g.id for g in all_windows.groups], groups_before)

    def test_unserialize_malformed_state(self):
        # unserialize() must return False gracefully for bad session data rather
        # than raising KeyError or similar.
        q = create_layout(Tall)
        all_windows = create_windows(q, num=3)
        for w in all_windows.all_windows:
            w.serialized_id = w.id
        q(all_windows)

        # Missing 'all_windows' key
        state = q.serialize(all_windows)
        del state['all_windows']
        self.assertFalse(q.unserialize(state, all_windows))

        # Wrong 'class' value
        state = q.serialize(all_windows)
        state['class'] = 'NonExistentLayout'
        self.assertFalse(q.unserialize(state, all_windows))

        # Mismatched layout type (Tall state passed to Splits)
        state = q.serialize(all_windows)
        other = create_layout(Splits)
        self.assertFalse(other.unserialize(state, all_windows))

    def test_unserialize_inactive_layout_non_splits(self):
        # apply_to_window_list=False must not reorder windows for non-Splits layouts.
        q = create_layout(Tall)
        all_windows = create_windows(q, num=3)
        for w in all_windows.all_windows:
            w.serialized_id = w.id
        q(all_windows)
        state = q.serialize(all_windows)
        groups_before = [g.id for g in all_windows.groups]
        active_before = all_windows.active_group_idx

        fresh = create_layout(Tall)
        self.assertTrue(fresh.unserialize(state, all_windows, apply_to_window_list=False))
        self.ae([g.id for g in all_windows.groups], groups_before)
        self.ae(all_windows.active_group_idx, active_before)

    def test_active_group_idx_preserved_after_unserialize(self):
        # When unserialize reorders the window list, active_group_idx must be
        # updated so it still points to the same group object.
        #
        # Simulate a session restore where windows were created in a different
        # order than the serialised state expects.  The original session had
        # windows [1,2,3] in that order with window 3 active.  The fresh list
        # has windows with the same serialised ids but inserted in reverse
        # order, so after unserialize the groups array is shuffled.
        original = create_layout(Stack)
        orig_windows = create_windows(original, num=0)
        for wid in (1, 2, 3):
            win = Window(wid)
            win.serialized_id = wid
            orig_windows.add_window(win)
        original(orig_windows)
        orig_windows.set_active_group_idx(2)  # window 3 active
        state = original.serialize(orig_windows)

        # Fresh window list: windows added in reverse serialised-id order so
        # their group positions differ from the serialised group order.
        fresh = create_layout(Stack)
        fresh_windows = create_windows(fresh, num=0)
        for actual_id, serialized_id in ((10, 3), (20, 2), (30, 1)):
            win = Window(actual_id)
            win.serialized_id = serialized_id
            fresh_windows.add_window(win)
        fresh(fresh_windows)
        # Simulate _startup: set active to the window whose serialised id is 3
        # (i.e. the window with actual_id=10, which is at index 0).
        fresh_windows.set_active_group_idx(0)
        active_group = fresh_windows.active_group

        self.assertTrue(fresh.unserialize(state, fresh_windows))
        # active_group_idx must still point to the same group object after reorder.
        self.assertIs(fresh_windows.groups[fresh_windows.active_group_idx], active_group)

    def test_unserialize_session_roundtrip_splits(self):
        # Full serialize → unserialize round-trip for Splits: tree structure and
        # window ordering are both restored correctly.
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        for wid, loc in ((1, None), (2, 'vsplit'), (3, 'hsplit')):
            win = Window(wid)
            win.serialized_id = wid
            q.add_window(all_windows, win, location=loc)
        q(all_windows)
        tree_before = q.pairs_root.serialize()
        state = q.serialize(all_windows)
        expected_groups = [g.id for g in all_windows.groups]

        # Restore into the same window list (simulating a session with identical
        # windows but a fresh layout object, as happens on restart).
        fresh = create_layout(Splits)
        self.assertTrue(fresh.unserialize(state, all_windows))
        self.ae(fresh.pairs_root.serialize(), tree_before)
        self.ae([g.id for g in all_windows.groups], expected_groups)

    def test_unserialize_session_roundtrip_tall(self):
        # Full serialize → unserialize round-trip for the Tall layout: custom
        # bias values and window ordering are preserved.
        q = create_layout(Tall)
        all_windows = create_windows(q, num=3)
        for w in all_windows.all_windows:
            w.serialized_id = w.id
        q(all_windows)
        # Skew the main bias so we have something non-default to verify.
        q.main_bias = list(q.main_bias)
        q.main_bias[0] = 0.7
        state = q.serialize(all_windows)
        expected_groups = [g.id for g in all_windows.groups]

        fresh = create_layout(Tall)
        self.assertTrue(fresh.unserialize(state, all_windows))
        self.ae(fresh.main_bias[0], 0.7)
        self.ae([g.id for g in all_windows.groups], expected_groups)

    def test_splits_maximize(self):
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        w1 = Window(1)
        q.add_window(all_windows, w1)
        w2 = Window(2)
        q.add_window(all_windows, w2, location='vsplit')
        w3 = Window(3)
        q.add_window(all_windows, w3, location='hsplit')
        # Layout: w1 | (w2 above w3) — horizontal split at root, vertical split on right
        root = q.pairs_root
        # root is horizontal, containing w1 and [w2/w3 vertical pair]
        self.ae(root.horizontal, True)
        right_pair = root.two if isinstance(root.two, Pair) else root.one
        self.assertIsInstance(right_pair, Pair)

        # Focus window 3 (bottom-right)
        all_windows.set_active_group_idx(all_windows.groups.index(all_windows.group_for_window(w3)))

        # Save original biases
        root_bias_before = root.bias
        right_pair_bias_before = right_pair.bias

        # maximize vertical (fill full height) — affects vertical (horizontal==False) pairs
        result = q.layout_action('maximize', ('vertical',), all_windows)
        self.assertTrue(result)
        # right_pair is vertical (horizontal==False) so its bias should be 0.0 (w3 is in 'two')
        self.ae(right_pair.bias, 0.0)
        # root is horizontal so its bias should be unchanged
        self.ae(root.bias, root_bias_before)
        # _maximized_biases should track w3's vertical maximize
        self.assertIn((all_windows.active_group.id, False), q._maximized_biases)

        # Toggle back
        result = q.layout_action('maximize', ('vertical',), all_windows)
        self.assertTrue(result)
        self.ae(right_pair.bias, right_pair_bias_before)
        self.ae(getattr(q, '_maximized_biases', {}), {})

        # maximize horizontal (fill full width) — affects horizontal pairs
        result = q.layout_action('maximize', ('horizontal',), all_windows)
        self.assertTrue(result)
        # root is horizontal, w3 is under root.two (right side), so bias should be 0.0
        self.ae(root.bias, 0.0)
        # right_pair is vertical, so unchanged
        self.ae(right_pair.bias, right_pair_bias_before)

        # Toggle back
        result = q.layout_action('maximize', ('horizontal',), all_windows)
        self.assertTrue(result)
        self.ae(root.bias, root_bias_before)

    def test_splits_equalize(self):
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        w1 = Window(1)
        q.add_window(all_windows, w1)
        w2 = Window(2)
        q.add_window(all_windows, w2, location='vsplit')
        w3 = Window(3)
        q.add_window(all_windows, w3, location='vsplit')
        # Tree: root(H) -> w1, Pair(H) -> w2, w3
        # Proportional equalize: root.bias=1/3, inner.bias=0.5
        root = q.pairs_root
        inner = root.two if isinstance(root.two, Pair) else root.one
        self.assertIsInstance(inner, Pair)

        # Skew biases so equalize has something to fix
        root.bias = 0.8
        inner.bias = 0.8

        result = q.layout_action('equalize', (), all_windows)
        self.assertTrue(result)
        self.assertAlmostEqual(root.bias, 1 / 3, places=5)
        self.assertAlmostEqual(inner.bias, 0.5, places=5)

        # Single window — equalize should still succeed
        q2 = create_layout(Splits)
        aw2 = create_windows(q2, num=0)
        q2.add_window(aw2, Window(10))
        result = q2.layout_action('equalize', (), aw2)
        self.assertTrue(result)

    def test_splits_equalize_mixed(self):
        # One vsplit then three hsplits, each from the freshly added window:
        #   root(H) -> w1, inner1(V) -> w2, inner2(V) -> w3, inner3(V) -> w4, w5
        # Equalize should give each of w2-w5 an equal share of the right column.
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        q.add_window(all_windows, Window(1))
        q.add_window(all_windows, Window(2), location='vsplit')
        q.add_window(all_windows, Window(3), location='hsplit')
        q.add_window(all_windows, Window(4), location='hsplit')
        q.add_window(all_windows, Window(5), location='hsplit')

        root = q.pairs_root
        inner1 = root.two
        self.assertIsInstance(inner1, Pair)
        inner2 = inner1.two
        self.assertIsInstance(inner2, Pair)
        inner3 = inner2.two
        self.assertIsInstance(inner3, Pair)

        for pair in root.self_and_descendants():
            pair.bias = 0.9

        result = q.layout_action('equalize', (), all_windows)
        self.assertTrue(result)
        self.assertAlmostEqual(root.bias, 0.5, places=5)  # w1 vs right column: 1:1
        self.assertAlmostEqual(inner1.bias, 1 / 4, places=5)  # w2 vs [w3,w4,w5]: 1:3
        self.assertAlmostEqual(inner2.bias, 1 / 3, places=5)  # w3 vs [w4,w5]: 1:2
        self.assertAlmostEqual(inner3.bias, 0.5, places=5)  # w4 vs w5: 1:1

    def test_splits_equalize_after_remove(self):
        # 1 vsplit + 2 hsplits: root(H) -> w1, inner1(V) -> w2, inner2(V) -> w3, w4
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        w1, w2, w3, w4 = Window(1), Window(2), Window(3), Window(4)
        q.add_window(all_windows, w1)
        q.add_window(all_windows, w2, location='vsplit')
        q.add_window(all_windows, w3, location='hsplit')
        q.add_window(all_windows, w4, location='hsplit')

        root = q.pairs_root
        inner1 = root.two
        inner2 = inner1.two
        self.assertIsInstance(inner1, Pair)
        self.assertIsInstance(inner2, Pair)

        result = q.layout_action('equalize', (), all_windows)
        self.assertTrue(result)
        self.assertAlmostEqual(root.bias, 0.5, places=5)  # w1 vs right column: 1:1
        self.assertAlmostEqual(inner1.bias, 1 / 3, places=5)  # w2 vs [w3,w4]: 1:2 → RHS in thirds
        self.assertAlmostEqual(inner2.bias, 0.5, places=5)  # w3 vs w4: 1:1

        # Remove w4 — inner2 collapses: inner1.two becomes grp_w3 leaf
        g4 = all_windows.group_for_window(w4)
        q.remove_windows(g4.id)

        self.assertNotIsInstance(inner1.two, Pair)  # collapsed to a leaf

        result = q.layout_action('equalize', (), all_windows)
        self.assertTrue(result)
        self.assertAlmostEqual(root.bias, 0.5, places=5)  # w1 vs right column: 1:1
        self.assertAlmostEqual(inner1.bias, 0.5, places=5)  # w2 vs w3 top/bottom: 1:1

    def test_splits_collapse_nested_empty_pairs(self):
        # Removing every window of a nested sub-tree in a single pass must not
        # leave an empty pair behind, still consuming its share of the space.
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        for i in range(1, 6):
            q.add_window(all_windows, Window(i))
        q.pairs_root.unserialize({'one': {'one': {'one': 1, 'two': 2}, 'two': {'one': 3, 'two': 4}}, 'two': 5}, lambda x: x)
        q.remove_windows(3, 2, 1, 4)
        self.ae(list(q.pairs_root.all_window_ids()), [5])
        for pair in q.pairs_root.self_and_descendants():
            self.assertFalse(pair.one is None and pair.two is None, f'empty pair left in tree: {q.pairs_root}')
        self.ae(q.pairs_root.window_weights(), {5: 1.0})

    def test_splits_relayout_after_root_collapse(self):
        # Windows added in the same relayout that collapses the root must go into
        # the new root, not the discarded one.
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        for i in (1, 2, 3):
            q.add_window(all_windows, Window(i), location='vsplit')
        all_windows.remove_window(all_windows.id_map[1])
        all_windows.add_window(Window(4))
        q(all_windows)
        self.ae(sorted(q.pairs_root.all_window_ids()), [2, 3, 4])

    def test_layout_opts_serialization(self):
        opts = SplitsLayoutOpts({})
        s = opts.serialized()
        self.ae(s, SplitsLayoutOpts(s).serialized())

    def test_splits_equalize_on_close(self):
        q = create_layout(Splits)
        q.layout_opts = SplitsLayoutOpts({})
        q.layout_opts.equalize_on_close = True
        all_windows = create_windows(q, num=0)
        w1, w2, w3 = Window(1), Window(2), Window(3)
        q.add_window(all_windows, w1)
        q.add_window(all_windows, w2, location='vsplit')
        q.add_window(all_windows, w3, location='vsplit')

        root = q.pairs_root
        root.bias = 0.9
        inner = root.two if isinstance(root.two, Pair) else root.one
        self.assertIsInstance(inner, Pair)
        inner.bias = 0.9

        g3 = all_windows.group_for_window(w3)
        q.remove_windows(g3.id)

        result = q.on_window_removed(all_windows)
        self.assertTrue(result)
        self.assertAlmostEqual(root.bias, 0.5, places=5)

        # equalize_on_close=false (default) must not trigger equalization
        q2 = create_layout(Splits)
        aw2 = create_windows(q2, num=0)
        q2.add_window(aw2, Window(10))
        q2.add_window(aw2, Window(11), location='vsplit')
        q2.pairs_root.bias = 0.9
        result = q2.on_window_removed(aw2)
        self.assertFalse(result)
        self.assertAlmostEqual(q2.pairs_root.bias, 0.9, places=5)

    def test_splits_equalize_redundant_pair(self):
        # Equalizing must leave a pair holding a single window with an even bias,
        # as that bias is used when the pair is split again, see #10522
        def split_after(equalize_on_close: bool, bias: float) -> float:
            q = create_layout(Splits)
            q.layout_opts = SplitsLayoutOpts({})
            q.layout_opts.equalize_on_close = equalize_on_close
            all_windows = create_windows(q, num=0)
            q.add_window(all_windows, Window(1))
            w2 = Window(2)
            q.add_window(all_windows, w2, location='vsplit')
            q.pairs_root.bias = bias
            q.remove_windows(all_windows.group_for_window(w2).id)
            all_windows.remove_window(w2)
            if equalize_on_close:
                self.assertTrue(q.on_window_removed(all_windows))
            else:
                self.assertTrue(q.layout_action('equalize', (), all_windows))
            q.add_window(all_windows, Window(3), location='hsplit')
            return q.pairs_root.bias

        for equalize_on_close in (False, True):
            with self.subTest(equalize_on_close=equalize_on_close):
                self.assertAlmostEqual(split_after(equalize_on_close, 0.5), 0.5, places=5)
                self.assertAlmostEqual(split_after(equalize_on_close, 0.8), 0.5, places=5)

        # Without an equalize, the bias of a closed split is preserved by design
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        q.add_window(all_windows, Window(1))
        w2 = Window(2)
        q.add_window(all_windows, w2, location='vsplit')
        q.pairs_root.bias = 0.8
        q.remove_windows(all_windows.group_for_window(w2).id)
        all_windows.remove_window(w2)
        self.assertFalse(q.on_window_removed(all_windows))
        q.add_window(all_windows, Window(3), location='vsplit')
        self.assertAlmostEqual(q.pairs_root.bias, 0.8, places=5)

    def test_linear_constraint_cell_allocation(self):
        model = LinearConstraintModel()
        for num_windows in range(1, 17):
            sequence_biases = normalize_biases([float(i + 1) for i in range(num_windows)])
            biases: list[CellBias] = [None, sequence_biases]
            if num_windows > 1:
                biases.extend(({}, {0: 0.2, num_windows - 1: -0.1}))
            cell_counts = (1, num_windows * 5, num_windows * 6, num_windows * 17 + 3, 257)
            for number_of_cells in cell_counts:
                for bias in biases:
                    with self.subTest(num_windows=num_windows, number_of_cells=number_of_cells, bias=bias):
                        expected = calculate_cells_map(bias, num_windows, number_of_cells)
                        self.ae(model(bias, num_windows, number_of_cells), expected)

        model(None, 4, 100)
        solver = model.solver
        model(None, 4, 101)
        self.assertIs(model.solver, solver)
        model(None, 5, 101)
        self.assertIsNot(model.solver, solver)

        for num_windows in range(1, 17):
            decorations = tuple((i % 3, (i + 1) % 4) for i in range(num_windows))
            bias = normalize_biases([float(i + 1) for i in range(num_windows)])
            for cell_length in (1, 7, 13):
                for length in (0, num_windows * 2, num_windows * cell_length * 6 + sum(map(sum, decorations)), 511):
                    for alignment in (0, 1, 2):
                        args = (3, length, cell_length, decorations, alignment, bias)
                        expected = tuple(layout_dimension(*args))
                        actual = tuple(layout_dimension(*args, cell_allocator=model))
                        self.ae(actual, expected)

    def test_fixed_constraint_allocation(self):
        model = FixedConstraintModel()
        fixed = FixedSize
        self.ae(model(40, ()), ([], 40))
        self.ae(model(40, (fixed(10), fixed(20))), ([10, 20], 10))
        self.ae(model(25, (fixed(10), fixed(20))), ([10, 15], 0))
        self.ae(model(5, (fixed(10), fixed(20))), ([5, 0], 0))
        self.ae(model(200, (fixed(fraction=0.25), fixed(fraction=0.5))), ([50, 100], 50))
        self.ae(model(100, (fixed(fraction=0.75), fixed(fraction=0.75))), ([75, 25], 0))
        self.ae(model(100, (fixed(10), fixed(fraction=0.25))), ([10, 25], 65))
        model(40, (fixed(10), fixed(20)))
        solver = model.solver
        model(41, (fixed(10), fixed(20)))
        self.assertIs(model.solver, solver)
        model(200, (fixed(fraction=0.25),))
        solver = model.solver
        model(240, (fixed(fraction=0.25),))
        self.assertIs(model.solver, solver)

    def test_dock_metadata_serialization(self):
        layout = create_layout(Vertical)
        windows = create_windows(layout, 3)
        owner, dock = windows.all_windows[0], windows.all_windows[2]
        dock.dock_data = DockData('window', 'bottom', 2, owner.id, False)
        state = layout.serialize(windows)

        restored_layout = create_layout(Vertical)
        restored = create_windows(restored_layout, 3)
        for window in restored:
            window.serialized_id = window.id
        self.assertTrue(restored_layout.unserialize(state, restored))
        self.ae(len(tuple(restored.iter_main_groups())), 2)
        self.ae(len(tuple(restored.iter_dock_groups())), 1)
        self.ae(restored.all_windows[2].dock_data, DockData('window', 'bottom', 2, restored.all_windows[0].id, False))

        dock.dock_data = DockData('window', 'bottom', 25, owner.id, False, 'percent')
        state = layout.serialize(windows)
        restored_layout = create_layout(Vertical)
        restored = create_windows(restored_layout, 3)
        for window in restored:
            window.serialized_id = window.id
        self.assertTrue(restored_layout.unserialize(state, restored))
        self.ae(restored.all_windows[2].dock_data, DockData('window', 'bottom', 25.0, restored.all_windows[0].id, False, 'percent'))

    def test_dock_geometry(self):
        layout = create_layout(Vertical)
        windows = create_windows(layout, 1)
        owner = windows.active_window
        tab_dock, window_dock = Window(2), Window(3)
        tab_dock.dock_data = DockData('tab', 'top', 2)
        window_dock.dock_data = DockData('window', 'right', 3, owner.id)
        layout.add_window(windows, tab_dock)
        layout.add_window(windows, window_dock)

        lgd.cell_width = lgd.cell_height = 10
        layout._full_central = Region((0, 0, 299, 199, 300, 200))
        lgd.central = layout._calculate_tab_dock_regions(windows)
        layout.update_visibility(windows)
        layout.do_layout(windows)
        layout._layout_tab_docks(windows)
        layout._layout_window_docks(windows)

        def outer(window):
            geom = window.geometry
            return (
                geom.left - geom.spaces.left,
                geom.top - geom.spaces.top,
                geom.right + geom.spaces.right,
                geom.bottom + geom.spaces.bottom,
            )

        self.ae(outer(tab_dock), (0, 0, 300, 26))
        self.ae(tab_dock.geometry.ynum, 2)
        self.ae(outer(owner), (0, 26, 264, 200))
        self.ae(outer(window_dock), (264, 26, 300, 200))
        self.ae(window_dock.geometry.xnum, 3)
        owner_group = windows.group_for_window(owner)
        dock_group = windows.group_for_window(window_dock)
        windows.set_active_window_group_for(owner)
        self.ae(layout.neighbors(windows)['right'][0], dock_group.id)
        self.ae(layout.neighbors_for_window_with_docks(owner, windows)['right'][0], dock_group.id)
        windows.set_active_window_group_for(window_dock)
        self.ae(layout.neighbors(windows)['left'][0], owner_group.id)
        self.ae(layout.neighbors_for_window_with_docks(window_dock, windows)['left'][0], owner_group.id)

        tab_dock.dock_data = DockData('tab', 'top', 25, size_unit='percent')
        window_dock.dock_data = DockData('window', 'right', 20, owner.id, size_unit='percent')
        lgd.central = layout._calculate_tab_dock_regions(windows)
        layout.update_visibility(windows)
        layout.do_layout(windows)
        layout._layout_tab_docks(windows)
        layout._layout_window_docks(windows)
        self.ae(outer(tab_dock), (0, 0, 300, 50))
        self.ae(outer(owner), (0, 50, 240, 200))
        self.ae(outer(window_dock), (240, 50, 300, 200))

        from kitty.tabs import Tab as RealTab

        class ListingTab:
            active_window = owner
            current_layout = layout

            def __iter__(self):
                return iter(windows)

        listing_tab = ListingTab()
        listing_tab.windows = windows
        for window in windows:
            window.os_window_id = 1
            window.as_dict = lambda window=window, **kwargs: {'id': window.id, **kwargs}
        with patch('kitty.tabs.current_focused_os_window_id', return_value=1):
            listed = {item['id']: item for item in RealTab.list_windows(listing_tab)}
        self.ae(listed[window_dock.id]['neighbors_map']['left'][0], owner_group.id)

        tab_dock.dock_data = tab_dock.dock_data._replace(focusable=False)
        window_dock.dock_data = window_dock.dock_data._replace(focusable=False)
        self.ae(layout.neighbors_for_window_with_docks(window_dock, windows), {})

    def test_overlay_preserves_dock_group(self):
        layout = create_layout(Vertical)
        windows = create_windows(layout, 1)
        owner = windows.active_window
        dock = Window(2)
        dock.dock_data = DockData('window', 'bottom', owner_window_id=owner.id)
        layout.add_window(windows, dock)
        overlay = Window(3, overlay_for=dock.id)
        self.assertIs(layout.add_window(windows, overlay, overlay_for=dock.id), dock)
        dock_group = windows.group_for_window(dock)
        self.assertIs(dock_group, windows.group_for_window(overlay))
        self.ae(overlay.dock_data, dock.dock_data)

        for window in windows:
            window.serialized_id = window.id
        state = layout.serialize(windows)
        restored_layout = create_layout(Vertical)
        restored = create_windows(restored_layout, 0)
        restored_owner, restored_dock, restored_overlay = Window(10), Window(20), Window(30, overlay_for=20)
        for window, serialized_id in zip((restored_owner, restored_dock, restored_overlay), (1, 2, 3)):
            window.serialized_id = serialized_id
        restored.add_window(restored_owner)
        restored.add_window(restored_dock)
        restored.add_window(restored_overlay, group_of=restored_dock)
        self.assertTrue(restored_layout.unserialize(state, restored))
        self.ae(restored_dock.dock_data, restored_overlay.dock_data)
        self.ae(restored_dock.dock_data.owner_window_id, restored_owner.id)

        partial_layout = create_layout(Vertical)
        partial = create_windows(partial_layout, 0)
        partial_owner, partial_overlay = Window(100), Window(300)
        partial_owner.serialized_id, partial_overlay.serialized_id = 1, 3
        partial.add_window(partial_owner)
        partial.add_window(partial_overlay)
        self.assertTrue(partial_layout.unserialize(state, partial))
        self.ae(partial_overlay.dock_data.owner_window_id, partial_owner.id)

        windows.remove_window(dock)
        self.assertIs(dock_group, windows.group_for_window(overlay))
        self.ae(dock_group.dock_data, overlay.dock_data)
        self.ae(len(tuple(windows.iter_dock_groups())), 1)
        self.ae(len(tuple(windows.iter_main_groups())), 1)

    def test_docks_stay_out_of_splits_topology(self):
        layout = create_layout(Splits)
        windows = create_windows(layout, 0)
        for i in range(3):
            layout.add_window(windows, Window(i + 1))
        owner = windows.active_window
        dock = Window(4)
        dock.dock_data = DockData('window', 'bottom', owner_window_id=owner.id)
        layout.add_window(windows, dock)
        original_tree = layout.pairs_root.serialize()
        layout.insert_window_next_to(windows, dock, owner, True, True)
        self.ae(layout.pairs_root.serialize(), original_tree)
        self.assertFalse(layout.layout_action('move_to_screen_edge', ['left'], windows))
        self.ae(layout.pairs_root.serialize(), original_tree)

        layout.add_window(windows, Window(5))
        self.ae(set(layout.pairs_root.all_window_ids()), {group.id for group in windows.iter_main_groups()})

    def test_window_dock_owner_lifetime(self):
        from kitty.boss import Boss as RealBoss
        from kitty.tabs import Tab as RealTab

        class Boss:
            marked = []

            def mark_window_for_close(self, window):
                self.marked.append(window)

        layout = create_layout(Vertical)
        windows = create_windows(layout, 1)
        owner = windows.active_window
        dock = Window(2)
        dock.dock_data = DockData('window', 'bottom', owner_window_id=owner.id)
        layout.add_window(windows, dock)
        windows.set_active_window_group_for(owner)
        fake_tab = type('FakeTab', (), {'windows': windows})()
        self.assertIs(RealBoss._sole_window_of_tab(None, fake_tab), owner)
        tab = object.__new__(RealTab)
        tab.windows, tab.os_window_id, tab.id = windows, 1, 1
        boss = Boss()
        with patch('kitty.tabs.remove_window'), patch('kitty.tabs.get_boss', return_value=boss):
            RealTab.remove_window(tab, owner, do_post_removal_update=False)
        self.assertIsNone(windows.active_window)
        self.assertFalse(dock.is_visible_in_layout)
        self.ae(boss.marked, [dock])

        windows = create_windows(layout, 1)
        owner = windows.active_window
        overlay = Window(2, overlay_for=owner.id)
        windows.add_window(overlay, group_of=owner)
        dock = Window(3)
        dock.dock_data = DockData('window', 'bottom', owner_window_id=owner.id)
        layout.add_window(windows, dock)
        tab.windows = windows
        boss.marked = []
        with patch('kitty.tabs.remove_window'), patch('kitty.tabs.get_boss', return_value=boss):
            RealTab.remove_window(tab, owner, do_post_removal_update=False)
        self.ae(dock.dock_data.owner_window_id, overlay.id)
        self.ae(boss.marked, [])
        self.ae(RealTab.detach_window(tab, dock), ())
        self.assertIn(dock, windows)

    def test_docks_gracefully_consume_undersized_viewport(self):
        for layout_class in (Stack, Vertical, Horizontal, Tall, Grid, Splits):
            with self.subTest(layout=layout_class.name):
                layout = create_layout(layout_class)
                windows = create_windows(layout, 2)
                dock = Window(3)
                dock.dock_data = DockData('tab', 'top', 20)
                layout.add_window(windows, dock)
                lgd.cell_width = lgd.cell_height = 10
                layout._full_central = Region((0, 0, 19, 19, 20, 20))
                lgd.central = layout._calculate_tab_dock_regions(windows)
                layout.update_visibility(windows)
                layout.do_layout(windows)
                layout._layout_tab_docks(windows)
                for window in windows:
                    self.assertGreaterEqual(window.geometry.xnum, 0)
                    self.assertGreaterEqual(window.geometry.ynum, 0)

    def test_dock_visibility_and_focus(self):
        empty_layout = create_layout(Stack)
        empty_windows = create_windows(empty_layout, 0)
        status_only = Window(1)
        status_only.dock_data = DockData('tab', 'top', focusable=False)
        empty_layout.add_window(empty_windows, status_only)
        self.assertIsNone(empty_windows.active_window)

        layout = create_layout(Stack)
        windows = create_windows(layout, 2)
        first, second = windows.all_windows
        first_dock, second_dock, status = Window(3), Window(4), Window(5)
        first_dock.dock_data = DockData('window', 'bottom', 1, first.id)
        second_dock.dock_data = DockData('window', 'bottom', 1, second.id)
        status.dock_data = DockData('tab', 'top', 1, focusable=False)
        for dock in (first_dock, second_dock, status):
            layout.add_window(windows, dock)

        windows.set_active_window_group_for(first)
        layout.update_visibility(windows)
        self.assertTrue(first.is_visible_in_layout)
        self.assertTrue(first_dock.is_visible_in_layout)
        self.assertFalse(second.is_visible_in_layout)
        self.assertFalse(second_dock.is_visible_in_layout)
        self.assertTrue(status.is_visible_in_layout)

        status_idx = windows.group_idx_for_window(status)
        self.assertIsNotNone(status_idx)
        self.assertFalse(windows.set_active_group_idx(status_idx))
        self.assertIs(windows.active_window, first)
        windows.activate_next_window_group(1)
        self.assertIs(windows.active_window, second)
        layout.update_visibility(windows)
        windows.activate_next_window_group(1)
        self.assertIs(windows.active_window, second_dock)
        self.assertIs(windows.active_main_window, second)
        self.ae([window.id for _, window in windows.iter_windows_with_number()], [second.id, second_dock.id])
        self.ae(
            [window.id for _, window in windows.iter_windows_with_number(only_visible=False)],
            [first.id, second.id, first_dock.id, second_dock.id],
        )

    def test_split_constraint_allocation(self):
        model = SplitConstraintModel()
        self.ae(model(100, 0.5, 1, 10, 10), (49, 49))
        self.ae(model(100, 0.01, 1, 10, 10), (10, 88))
        self.ae(model(100, 0.99, 1, 10, 10), (88, 10))
        for length in range(20, 200):
            for bias in (0.1, 0.25, 0.5, 0.75, 0.9):
                for border in (0, 1, 2):
                    first = max(7, int(bias * length) - border)
                    second = length - first - 2 * border
                    if second >= 11:
                        self.ae(model(length, bias, border, 7, 11), (first, second))
        for length in range(20):
            first, second = model(length, 0.5, 1, 10, 10)
            self.assertGreaterEqual(first, 0)
            self.assertGreaterEqual(second, 0)
            self.ae(first + second, max(0, length - 2))
        model(100, 0.5, 1, 10, 10)
        solver = model.solver
        model(101, 0.5, 1, 10, 10)
        self.assertIs(model.solver, solver)

    def test_layout_dimension_no_negative_cells(self):
        # Regression test for issue #9946: when window padding exceeds the
        # available space (e.g. after maximize sets a window to minimum width),
        # layout_dimension must not produce a negative cells_per_window value
        # which would cause right < left in the resulting window geometry.
        for length, cell_length, decs in (
            (8, 8, [(5, 5)]),  # padding (10) > length (8) > cell_length (8)
            (6, 8, [(4, 4)]),  # length < cell_length
            (0, 8, [(4, 4)]),  # zero length
            (4, 8, [(3, 3)]),  # space_needed == length, no room for cells
        ):
            result = next(layout_dimension(0, length, cell_length, decs))
            self.assertGreaterEqual(
                result.cells_per_window, 0, f'cells_per_window={result.cells_per_window} < 0 for length={length}, cell_length={cell_length}, decs={decs}'
            )
            self.assertGreaterEqual(
                result.content_size, 0, f'content_size={result.content_size} < 0 for length={length}, cell_length={cell_length}, decs={decs}'
            )
            # content_pos must be within [0, length]: right edge = content_pos + content_size <= length
            self.assertGreaterEqual(result.content_pos, 0)
            self.assertLessEqual(
                result.content_pos + result.content_size,
                length,
                f'right ({result.content_pos + result.content_size}) > length ({length}) for cell_length={cell_length}, decs={decs}',
            )

    def test_drag_resize_target_windows(self):
        # Helper: call drag_resize_target_windows with given window and edge flags.
        def drtw(q, all_windows, window, edges):
            return q.drag_resize_target_windows(window, 0, 0, edges, all_windows)

        # --- 2-window horizontal split: A | B ---
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        wA = Window(1)
        q.add_window(all_windows, wA)
        wB = Window(2)
        q.add_window(all_windows, wB, location='vsplit')
        q(all_windows)
        root = q.pairs_root
        self.ae(root.horizontal, True)
        root_id = id(root)

        # Right edge of A (left of divider): divider belongs to root, A is on one-side
        d = drtw(q, all_windows, wA, RIGHT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # Left edge of B (right of divider): same divider, same direction
        d = drtw(q, all_windows, wB, LEFT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # Right edge of B (outer border): direction reversed
        d = drtw(q, all_windows, wB, RIGHT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, False)

        # --- 2-window vertical split: A / B ---
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        wA = Window(1)
        q.add_window(all_windows, wA)
        wB = Window(2)
        q.add_window(all_windows, wB, location='hsplit')
        q(all_windows)
        root = q.pairs_root
        self.ae(root.horizontal, False)
        root_id = id(root)

        # Bottom edge of A: divider belongs to root, A is in one-side
        d = drtw(q, all_windows, wA, BOTTOM_EDGE)
        self.ae(d.vertical_id, root_id)
        self.ae(d.height_increases_downwards, True)

        # Top edge of B: same divider
        d = drtw(q, all_windows, wB, TOP_EDGE)
        self.ae(d.vertical_id, root_id)
        self.ae(d.height_increases_downwards, True)

        # Bottom edge of B (outer border): direction reversed
        d = drtw(q, all_windows, wB, BOTTOM_EDGE)
        self.ae(d.vertical_id, root_id)
        self.ae(d.height_increases_downwards, False)

        # --- 3-window layout: top_pair(A | B) / C ---
        # root(vertical) -> one: top_pair(horizontal, one=A, two=B), two: C
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        wA = Window(1)
        q.add_window(all_windows, wA)
        wC = Window(3)
        q.add_window(all_windows, wC, location='hsplit')  # C below A (vertical root)
        all_windows.set_active_window_group_for(wA)
        wB = Window(2)
        q.add_window(all_windows, wB, location='vsplit')  # B right of A (horizontal top_pair)
        q(all_windows)
        root = q.pairs_root
        self.ae(root.horizontal, False)
        top_pair = root.one
        self.assertIsInstance(top_pair, Pair)
        self.ae(top_pair.horizontal, True)
        root_id = id(root)
        top_pair_id = id(top_pair)

        # Divider between A and B: belongs to top_pair
        d = drtw(q, all_windows, wA, RIGHT_EDGE)
        self.ae(d.horizontal_id, top_pair_id)
        self.ae(d.width_increases_rightwards, True)

        d = drtw(q, all_windows, wB, LEFT_EDGE)
        self.ae(d.horizontal_id, top_pair_id)
        self.ae(d.width_increases_rightwards, True)

        # Divider between top_pair and C: belongs to root
        d = drtw(q, all_windows, wA, BOTTOM_EDGE)
        self.ae(d.vertical_id, root_id)
        self.ae(d.height_increases_downwards, True)

        d = drtw(q, all_windows, wB, BOTTOM_EDGE)
        self.ae(d.vertical_id, root_id)
        self.ae(d.height_increases_downwards, True)

        d = drtw(q, all_windows, wC, TOP_EDGE)
        self.ae(d.vertical_id, root_id)
        self.ae(d.height_increases_downwards, True)

        # --- 3-window layout: A | right_pair(B / C) ---
        # root(horizontal) -> one: A, two: right_pair(vertical, one=B, two=C)
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        wA = Window(1)
        q.add_window(all_windows, wA)
        wB = Window(2)
        q.add_window(all_windows, wB, location='vsplit')  # B right of A (horizontal root)
        wC = Window(3)
        q.add_window(all_windows, wC, location='hsplit')  # C below B (vertical right_pair)
        q(all_windows)
        root = q.pairs_root
        self.ae(root.horizontal, True)
        right_pair = root.two
        self.assertIsInstance(right_pair, Pair)
        self.ae(right_pair.horizontal, False)
        root_id = id(root)
        right_pair_id = id(right_pair)

        # Divider between A and right_pair: A at RIGHT_EDGE -> root
        d = drtw(q, all_windows, wA, RIGHT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # B at LEFT_EDGE: B is on the leading side of right_pair, border belongs to root
        d = drtw(q, all_windows, wB, LEFT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # Divider between B and C: belongs to right_pair
        d = drtw(q, all_windows, wB, BOTTOM_EDGE)
        self.ae(d.vertical_id, right_pair_id)
        self.ae(d.height_increases_downwards, True)

        d = drtw(q, all_windows, wC, TOP_EDGE)
        self.ae(d.vertical_id, right_pair_id)
        self.ae(d.height_increases_downwards, True)

        # --- 4-window layout (bug scenario): left_pair(A/C) | right_pair(B/D) ---
        # root(horizontal) -> one: left_pair(vertical, one=A, two=C),
        #                      two: right_pair(vertical, one=B, two=D)
        q = create_layout(Splits)
        all_windows = create_windows(q, num=0)
        wA = Window(1)
        q.add_window(all_windows, wA)
        wB = Window(2)
        q.add_window(all_windows, wB, location='vsplit')  # B right of A
        all_windows.set_active_window_group_for(wA)
        wC = Window(3)
        q.add_window(all_windows, wC, location='hsplit')  # C below A
        all_windows.set_active_window_group_for(wB)
        wD = Window(4)
        q.add_window(all_windows, wD, location='hsplit')  # D below B
        q(all_windows)
        root = q.pairs_root
        self.ae(root.horizontal, True)
        left_pair = root.one
        right_pair = root.two
        self.assertIsInstance(left_pair, Pair)
        self.assertIsInstance(right_pair, Pair)
        self.ae(left_pair.horizontal, False)
        self.ae(right_pair.horizontal, False)
        root_id = id(root)
        left_pair_id = id(left_pair)
        right_pair_id = id(right_pair)

        # Bug #1: A at RIGHT_EDGE should give root with correct (rightward) direction
        d = drtw(q, all_windows, wA, RIGHT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # Bug #2: B at LEFT_EDGE should find root and give correct direction
        d = drtw(q, all_windows, wB, LEFT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # C at RIGHT_EDGE: same divider between left_pair and right_pair
        d = drtw(q, all_windows, wC, RIGHT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # D at LEFT_EDGE: same divider
        d = drtw(q, all_windows, wD, LEFT_EDGE)
        self.ae(d.horizontal_id, root_id)
        self.ae(d.width_increases_rightwards, True)

        # Vertical divider within left_pair (between A and C)
        d = drtw(q, all_windows, wA, BOTTOM_EDGE)
        self.ae(d.vertical_id, left_pair_id)
        self.ae(d.height_increases_downwards, True)

        d = drtw(q, all_windows, wC, TOP_EDGE)
        self.ae(d.vertical_id, left_pair_id)
        self.ae(d.height_increases_downwards, True)

        # Vertical divider within right_pair (between B and D)
        d = drtw(q, all_windows, wB, BOTTOM_EDGE)
        self.ae(d.vertical_id, right_pair_id)
        self.ae(d.height_increases_downwards, True)

        d = drtw(q, all_windows, wD, TOP_EDGE)
        self.ae(d.vertical_id, right_pair_id)
        self.ae(d.height_increases_downwards, True)


class BaseSplitGeometryTest(BaseTest):
    # These tests stub out Layout._set_dimensions, so they have to put back the lgd
    # singleton, which is global state shared with every other layout test.
    def setUp(self):
        super().setUp()
        self.set_options({'tab_bar_style': 'hidden'})
        saved = vars(lgd).copy()
        self.addCleanup(lambda: (vars(lgd).clear(), vars(lgd).update(saved)))

    def stub_dimensions(self, layout, central, minimal=True):
        def dimensions(all_windows):
            lgd.central = central
            lgd.cell_width, lgd.cell_height = 10, 20
            lgd.draw_minimal_borders = minimal

        layout._set_dimensions = dimensions

    def check_extents_fit(self, layout):
        # Every pair must divide its area exactly between its two halves and the
        # borders between them, otherwise windows overlap their neighbours.
        for p in layout.pairs_root.self_and_descendants():
            if p.is_redundant:
                continue
            with self.subTest(pair=repr(p)):
                if p.horizontal:
                    one = p.first_extent.right - p.first_extent.left
                    two = p.second_extent.right - p.second_extent.left
                    self.ae(one + two + 2 * p.border_width, p.width)
                    self.ae(p.second_extent.right, p.left + p.width)
                else:
                    one = p.first_extent.bottom - p.first_extent.top
                    two = p.second_extent.bottom - p.second_extent.top
                    self.ae(one + two + 2 * p.border_width, p.height)
                    self.ae(p.second_extent.bottom, p.top + p.height)


class TestSplitBorderResize(BaseSplitGeometryTest):
    def make_layout(self, shape):
        layout = create_layout(Splits)
        windows = create_windows(layout, num=0)
        for i in range(1, 5):
            layout.add_window(windows, Window(i))
        layout.pairs_root.unserialize(shape, lambda x: x)
        self.stub_dimensions(layout, Region((0, 0, 1499, 1099, 1500, 1100)))
        layout(windows)
        return layout, windows

    def test_left_center_stack_right_after_resize(self):
        layout, windows = self.make_layout(
            {
                'bias': 1 / 3,
                'one': 1,
                'two': {'one': {'horizontal': False, 'one': 2, 'two': 3}, 'two': 4},
            }
        )
        root = layout.pairs_root
        right_pair = root.two
        center = right_pair.one
        ws = {w.id: w for w in windows}
        # Resize right first, then alternate both sides of the left and right
        # dividers and both halves of the central horizontal divider.
        for _ in range(3):
            for wid, edge, expected in (
                (4, LEFT_EDGE, right_pair),
                (2, LEFT_EDGE, root),
                (3, LEFT_EDGE, root),
                (1, RIGHT_EDGE, root),
                (2, RIGHT_EDGE, right_pair),
                (3, RIGHT_EDGE, right_pair),
                (2, BOTTOM_EDGE, center),
                (3, TOP_EDGE, center),
            ):
                for increment in (3, -3):
                    with self.subTest(wid=wid, edge=edge, increment=increment):
                        data = layout.drag_resize_target_windows(ws[wid], 0, 0, edge, windows)
                        horizontal = bool(edge & (LEFT_EDGE | RIGHT_EDGE))
                        target = data.horizontal_id if horizontal else data.vertical_id
                        forwards = data.width_increases_rightwards if horizontal else data.height_increases_downwards
                        self.assertEqual(target, id(expected))
                        self.assertTrue(forwards)

                        def positions():
                            return {id(p): p.first_extent.right if p.horizontal else p.first_extent.bottom for p in root.self_and_descendants()}

                        before = positions()
                        self.assertTrue(layout.drag_resize_window(windows, target, increment, horizontal))
                        layout(windows)
                        cell = lgd.cell_width if horizontal else lgd.cell_height
                        for pid, position in positions().items():
                            self.ae(position - before[pid], increment * cell if pid == target else 0)

    def test_all_rendered_internal_borders(self):
        # All 5 binary tree shapes with 4 leaves, with every combination of
        # horizontal/vertical ancestors: 40 distinct arrangements.
        def shapes(ids):
            if len(ids) == 1:
                yield ids[0]
                return
            for n in range(1, len(ids)):
                for one in shapes(ids[:n]):
                    for two in shapes(ids[n:]):
                        for horizontal in (True, False):
                            yield {
                                'horizontal': horizontal,
                                'bias': 0.39,
                                'one': one,
                                'two': two,
                            }

        count = 0
        for shape in shapes((1, 2, 3, 4)):
            layout, windows = self.make_layout(shape)
            ws = {w.id: w for w in windows}
            for pair in layout.pairs_root.self_and_descendants():
                if pair.is_redundant:
                    continue
                for half in pair.between_borders:
                    for border in half:
                        trailing = border.window_id > 0
                        edge = (RIGHT_EDGE if trailing else LEFT_EDGE) if pair.horizontal else (BOTTOM_EDGE if trailing else TOP_EDGE)
                        with self.subTest(shape=shape, wid=border.window_id, edge=edge):
                            data = layout.drag_resize_target_windows(ws[abs(border.window_id)], 0, 0, edge, windows)
                            target = data.horizontal_id if pair.horizontal else data.vertical_id
                            forwards = data.width_increases_rightwards if pair.horizontal else data.height_increases_downwards
                            self.assertEqual(target, id(pair))
                            self.assertTrue(forwards)
                count += 1
        self.assertEqual(count, 120)

    def test_corner_axes_independent_and_single_pane(self):
        layout, windows = self.make_layout(
            {
                'one': 1,
                'two': {'one': {'horizontal': False, 'one': 2, 'two': 3}, 'two': 4},
            }
        )
        ws = {w.id: w for w in windows}
        data = layout.drag_resize_target_windows(ws[2], 0, 0, LEFT_EDGE | BOTTOM_EDGE, windows)
        self.assertEqual(data.horizontal_id, id(layout.pairs_root))
        self.assertEqual(data.vertical_id, id(layout.pairs_root.two.one))
        self.assertTrue(data.width_increases_rightwards)
        self.assertTrue(data.height_increases_downwards)
        layout.pairs_root = Pair()
        layout.pairs_root.one = 1
        data = layout.drag_resize_target_windows(ws[1], 0, 0, LEFT_EDGE | TOP_EDGE, windows)
        self.assertIsNone(data.horizontal_id)
        self.assertIsNone(data.vertical_id)


class TestReservedSpaces(BaseSplitGeometryTest):
    def test_reserved_spaces_do_not_overlap(self):
        # Custom shaders treat the space a layout reserves around the active
        # window (WindowGeometry.spaces) as part of it, so the reserved boxes
        # of visible windows must fit in the central area without overlapping.
        central = Region((19, 47, 1518, 1146, 1500, 1100))
        for cls in (Tall, Grid, Horizontal, Stack, Splits):
            for minimal in (True, False):
                for num in (1, 2, 3, 5):
                    layout = create_layout(cls)
                    windows = create_windows(layout, num=num)
                    self.stub_dimensions(layout, central, minimal)
                    layout(windows)
                    boxes = []
                    for w in windows:
                        if not w.is_visible_in_layout:
                            continue
                        g = w.geometry
                        boxes.append((g.left - g.spaces.left, g.top - g.spaces.top, g.right + g.spaces.right, g.bottom + g.spaces.bottom))
                    with self.subTest(layout=cls.name, minimal=minimal, num=num):
                        self.assertTrue(boxes)
                        for left, top, right, bottom in boxes:
                            self.assertGreaterEqual(left, central.left)
                            self.assertGreaterEqual(top, central.top)
                            self.assertLessEqual(right, central.left + central.width)
                            self.assertLessEqual(bottom, central.top + central.height)
                        for i, a in enumerate(boxes):
                            for b in boxes[i + 1 :]:
                                overlaps = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                                self.assertFalse(overlaps, f'{a} overlaps {b}')


class TestSplitDragGeometry(BaseSplitGeometryTest):
    def make_layout(self, shape, minimal=True, num=4):
        from types import SimpleNamespace

        from kitty.tabs import Tab as RealTab

        layout = create_layout(Splits)
        layout.layout_opts = SplitsLayoutOpts({'proportional': 'yes'})
        windows = create_windows(layout, num=num)
        layout.pairs_root.unserialize(shape, lambda x: x)
        self.stub_dimensions(layout, Region((19, 47, 1518, 1146, 1500, 1100)), minimal)
        tab = SimpleNamespace(current_layout=layout, windows=windows, relayout=lambda: layout(windows))
        tab.drag_resize_window = lambda *args: RealTab.drag_resize_window(tab, *args)
        tab.relayout()
        return layout, windows, tab

    def positions(self, layout):
        return {
            id(p): (p.first_extent.right if p.horizontal else p.first_extent.bottom) + p.border_width
            for p in layout.pairs_root.self_and_descendants()
            if not p.is_redundant
        }

    def fixed_dividers(self, pair):
        # The dividers move_divider() promises to leave alone: every divider outside
        # the dragged pair's region, plus the same-axis dividers inside it. Same-axis
        # dividers nested inside a perpendicular unit are excluded, that unit is
        # resized as a whole so they scale with it.
        inside = set()

        def walk(p):
            if not isinstance(p, Pair):
                return
            if p.is_redundant:
                return walk(p.one or p.two)
            if p.horizontal != pair.horizontal:
                return
            inside.add(id(p))
            walk(p.one)
            walk(p.two)

        walk(pair)
        descendants = {id(p) for p in pair.self_and_descendants()}
        return lambda pid: pid not in descendants or pid in inside

    def check_drags(self, layout, tab):
        for pair in layout.pairs_root.self_and_descendants():
            if pair.is_redundant:
                continue
            cell = lgd.cell_width if pair.horizontal else lgd.cell_height
            is_fixed = self.fixed_dividers(pair)
            for steps in (3, -5, 2):
                before = self.positions(layout)
                self.assertTrue(tab.drag_resize_window(id(pair), steps, pair.horizontal))
                after = self.positions(layout)
                self.check_extents_fit(layout)
                for pid, position in before.items():
                    if pid == id(pair):
                        self.ae(after[pid] - position, steps * cell)
                    elif is_fixed(pid):
                        self.ae(after[pid], position)

    def test_split_drag_adjacent_geometry(self):
        shapes = (
            {'bias': 0.3, 'one': 1, 'two': {'bias': 0.4, 'one': 2, 'two': {'one': 3, 'two': 4}}},
            {'one': {'bias': 0.6, 'one': 1, 'two': 2}, 'two': {'one': 3, 'two': 4}},
            {'one': {'one': {'one': 1, 'two': 2}, 'two': 3}, 'two': 4},
            {'horizontal': False, 'bias': 0.35, 'one': 4, 'two': {'one': 1, 'two': {'one': 2, 'two': 3}}},
            {'one': 1, 'two': {'one': {'horizontal': False, 'one': 2, 'two': 3}, 'two': 4}},
            # same-axis dividers nested inside a perpendicular unit
            {'one': 1, 'two': {'horizontal': False, 'one': {'bias': 0.6, 'one': 2, 'two': 3}, 'two': 4}},
            {'horizontal': False, 'bias': 0.5, 'one': {'one': {'horizontal': False, 'bias': 0.6, 'one': 1, 'two': 2}, 'two': 3}, 'two': 4},
        )

        def transpose(node):
            if isinstance(node, int):
                return node
            return {**node, 'horizontal': not node.get('horizontal', True), 'one': transpose(node['one']), 'two': transpose(node['two'])}

        for shape in shapes:
            for oriented in (shape, transpose(shape)):
                for minimal in (True, False):
                    with self.subTest(shape=oriented, minimal=minimal):
                        layout, windows, tab = self.make_layout(oriented, minimal)
                        self.check_drags(layout, tab)

    def test_split_drag_after_reposition_and_restore(self):
        shape = {'horizontal': False, 'one': 4, 'two': {'bias': 0.3, 'one': 1, 'two': {'bias': 0.6, 'one': 2, 'two': 3}}}
        layout, windows, tab = self.make_layout(shape)
        ws = {w.id: w for w in windows}
        self.check_drags(layout, tab)
        layout.insert_window_next_to(windows, ws[3], ws[1], True, False)
        tab.relayout()
        self.ae(list(layout.pairs_root.two.all_window_ids()), [3, 1, 2])
        self.check_drags(layout, tab)
        saved = {**layout.layout_state(), 'opts': layout.layout_opts.serialized()}
        self.assertTrue(layout.set_layout_state(saved, lambda x: x))
        tab.relayout()
        self.check_drags(layout, tab)

    def test_split_drag_minimum_size(self):
        layout, windows, tab = self.make_layout({'one': 1, 'two': {'one': 2, 'two': {'one': 3, 'two': 4}}})
        root = layout.pairs_root
        before = self.positions(layout)
        self.assertTrue(tab.drag_resize_window(id(root), 10000, True))
        after = self.positions(layout)
        for pid in before:
            if pid != id(root):
                self.ae(after[pid], before[pid])
        self.assertGreaterEqual(root.two.first_extent.right - root.two.first_extent.left, lgd.cell_width)
        self.assertFalse(tab.drag_resize_window(id(root), 1, True))
        self.assertTrue(tab.drag_resize_window(id(root), -1, True))
        self.ae(self.positions(layout)[id(root)], after[id(root)] - lgd.cell_width)

    def test_split_drag_nested_minimum_no_overlap(self):
        # Dragging a divider until a nested perpendicular unit is squeezed to its
        # minimum must not leave that unit's halves overflowing the area they were
        # given, which would overlap them with the neighbouring window.
        shape = {'horizontal': False, 'bias': 0.5, 'one': {'one': {'horizontal': False, 'bias': 0.6, 'one': 1, 'two': 2}, 'two': 3}, 'two': 4}
        for minimal in (True, False):
            with self.subTest(minimal=minimal):
                layout, windows, tab = self.make_layout(shape, minimal)
                root = layout.pairs_root
                tab.drag_resize_window(id(root), -1000, False)
                self.check_extents_fit(layout)
                inner = root.one.one
                self.ae(inner.second_extent.bottom, inner.top + inner.height)

    def test_split_drag_corner_and_subcell_motion(self):
        from types import SimpleNamespace

        from kitty.boss import Boss
        from kitty.types import WindowResizeDrag, WindowResizeDragData

        layout, windows, tab = self.make_layout({'one': 1, 'two': {'one': {'horizontal': False, 'one': 2, 'two': 3}, 'two': 4}})
        root = layout.pairs_root
        data = WindowResizeDragData(id(root), True, id(root.two.one), True)
        state = WindowResizeDrag(is_active=True, cell_width=10, cell_height=20, initial_x=300, initial_y=400, data=data)
        boss = SimpleNamespace(drag_resize_of_window=state, tab_for_id=lambda _: tab)
        before = self.positions(layout)
        for x, y in ((301, 401), (299, 399), (300, 400)):
            Boss.drag_resize_update(boss, x, y)
            self.ae(self.positions(layout), before)
        Boss.drag_resize_update(boss, 330, 440)
        moved = self.positions(layout)
        self.ae(moved[id(root)] - before[id(root)], 30)
        self.ae(moved[id(root.two.one)] - before[id(root.two.one)], 40)
        Boss.drag_resize_update(boss, 330, 440)
        self.ae(self.positions(layout), moved)
        Boss.drag_resize_update(boss, 300, 400)
        self.ae(self.positions(layout), before)

        # Overshooting a minimum size must not detach the divider from the
        # pointer when the pointer comes back into the allowed region.
        boss.drag_resize_of_window = state._replace(data=data._replace(vertical_id=None))
        Boss.drag_resize_update(boss, 10300, 400)
        limited = self.positions(layout)
        Boss.drag_resize_update(boss, 9300, 400)
        self.ae(self.positions(layout), limited)
        Boss.drag_resize_update(boss, 330, 400)
        self.ae(self.positions(layout)[id(root)], before[id(root)] + 30)
        Boss.drag_resize_update(boss, 300, 400)
        self.ae(self.positions(layout), before)


class TestProportionalSplits(BaseTest):
    def make_layout(self, shape=None, num=3, **options):
        q = create_layout(Splits)
        q.layout_opts = SplitsLayoutOpts({'proportional': 'yes', **options})
        windows = create_windows(q, num=0)
        for i in range(1, (num + 1) if shape else 2):
            q.add_window(windows, Window(i), location='vsplit')
        if shape:
            q.pairs_root.unserialize(shape, lambda x: x)
        return q, windows

    def check_weights(self, q, expected):
        # Observe the serialized layout, independently of the sizing helpers.
        actual = {}

        def walk(node, size):
            if isinstance(node, int):
                actual[node] = size
            elif 'two' not in node:
                walk(node['one'], size)
            else:
                bias = node.get('bias', 0.5)
                walk(node['one'], size * bias)
                walk(node['two'], size * (1 - bias))

        walk(q.pairs_root.serialize(), 1.0)
        self.ae(actual.keys(), expected.keys())
        for wid, size in expected.items():
            self.assertAlmostEqual(actual[wid], size)

    def test_proportional_add_equal_siblings(self):
        for location in ('vsplit', 'hsplit', None):
            for target in (1, 2):
                with self.subTest(location=location, target=target):
                    q, windows = self.make_layout()
                    q.add_window(windows, Window(2), location=location)
                    windows.set_active_window_group_for(windows.id_map[target])
                    q.add_window(windows, Window(3), location=location)
                    self.check_weights(q, {1: 1 / 3, 2: 1 / 3, 3: 1 / 3})
                    q.add_window(windows, Window(4), location=location)
                    self.check_weights(q, dict.fromkeys((1, 2, 3, 4), 0.25))

    def test_proportional_default_unchanged(self):
        q, windows = self.make_layout(proportional='no')
        q.add_window(windows, Window(2), location='vsplit')
        q.add_window(windows, Window(3), location='vsplit')
        self.check_weights(q, {1: 0.5, 2: 0.25, 3: 0.25})

    def test_proportional_add_preserves_adjusted_weights(self):
        q, windows = self.make_layout({'bias': 0.2, 'one': 1, 'two': {'bias': 0.375, 'one': 2, 'two': 3}})
        q.add_window(windows, Window(4), location='vsplit', next_to=windows.id_map[2])
        self.check_weights(q, {1: 2 / 13, 2: 3 / 13, 3: 5 / 13, 4: 3 / 13})

    def test_proportional_explicit_bias_wins(self):
        q, windows = self.make_layout()
        q.add_window(windows, Window(2), location='vsplit')
        q.add_window(windows, Window(3), location='vsplit', bias=80)
        self.check_weights(q, {1: 0.5, 2: 0.1, 3: 0.4})

    def test_proportional_close_preserves_survivors(self):
        for removed in (1, 2, 3):
            q, windows = self.make_layout({'bias': 0.2, 'one': 1, 'two': {'bias': 0.375, 'one': 2, 'two': 3}})
            sizes = {1: 0.2, 2: 0.3, 3: 0.5}
            sizes.pop(removed)
            total = sum(sizes.values())
            windows.remove_window(windows.id_map[removed])
            q.remove_windows(removed)
            self.check_weights(q, {k: v / total for k, v in sizes.items()})

    def test_proportional_close_multiple(self):
        q, windows = self.make_layout()
        for i in range(2, 6):
            q.add_window(windows, Window(i), location='vsplit')
        q.remove_windows(1, 3, 5)
        self.check_weights(q, {2: 0.5, 4: 0.5})

    def test_proportional_batch_close_mixed_axes(self):
        for horizontal in (True, False):
            shape = {
                'horizontal': horizontal,
                'one': 1,
                'two': {'horizontal': horizontal, 'one': {'horizontal': not horizontal, 'one': 2, 'two': 3}, 'two': 4},
            }
            q, windows = self.make_layout(shape, num=4)
            q.remove_windows(1, 2)
            # The surviving center pane keeps its column's width, even though
            # the other pane in that column was removed at the same time.
            self.check_weights(q, {3: 0.5, 4: 0.5})

    def test_proportional_mixed_axes(self):
        q, windows = self.make_layout({'bias': 0.4, 'one': 1, 'two': {'horizontal': False, 'bias': 0.25, 'one': 2, 'two': 3}})
        q.add_window(windows, Window(4), location='hsplit', next_to=windows.id_map[2])
        self.check_weights(q, {1: 0.4, 2: 0.12, 3: 0.36, 4: 0.12})
        q.remove_windows(2)
        self.check_weights(q, {1: 0.4, 3: 0.45, 4: 0.15})
        q.remove_windows(4)
        self.check_weights(q, {1: 0.4, 3: 0.6})

    def test_proportional_perpendicular_subtree_unchanged(self):
        q, windows = self.make_layout({'bias': 0.4, 'one': 1, 'two': {'horizontal': False, 'bias': 0.25, 'one': 2, 'two': 3}})
        q.add_window(windows, Window(4), location='vsplit', next_to=windows.id_map[1])
        self.check_weights(q, {1: 2 / 7, 4: 2 / 7, 2: 3 / 28, 3: 9 / 28})

    def test_proportional_reposition(self):
        q, windows = self.make_layout({'bias': 0.2, 'one': 1, 'two': {'bias': 0.375, 'one': 2, 'two': 3}})
        q.insert_window_next_to(windows, windows.id_map[3], windows.id_map[1], True, False)
        self.check_weights(q, {1: 2 / 7, 2: 3 / 7, 3: 2 / 7})
        self.ae(list(q.pairs_root.all_window_ids()), [3, 1, 2])
        before = q.layout_state()
        q.insert_window_next_to(windows, windows.id_map[1], windows.id_map[1], True, False)
        self.ae(q.layout_state(), before)

    def test_proportional_overlay_does_not_change_weights(self):
        q, windows = self.make_layout()
        q.add_window(windows, Window(2), location='vsplit')
        before = q.layout_state()
        q.add_window(windows, Window(10), overlay_for=2)
        self.ae(q.layout_state(), before)
        q.add_window(windows, Window(3), location='vsplit')
        self.check_weights(q, {1: 1 / 3, 2: 1 / 3, 3: 1 / 3})
        self.assertIs(windows.group_for_window(windows.id_map[10]), windows.group_for_window(windows.id_map[2]))

    def test_proportional_option_roundtrip_and_equalize(self):
        q, windows = self.make_layout({'bias': 0.2, 'one': 1, 'two': {'bias': 0.375, 'one': 2, 'two': 3}}, equalize_on_window_close='yes')
        options = SplitsLayoutOpts(q.layout_opts.serialized())
        self.assertTrue(options.proportional)
        self.assertTrue(options.equalize_on_close)
        windows.remove_window(windows.id_map[1])
        q.remove_windows(1)
        self.assertTrue(q.on_window_removed(windows))
        self.check_weights(q, {2: 0.5, 3: 0.5})

    def test_proportional_close_with_zero_sized_survivor(self):
        # Window 3 has been squeezed to nothing by maximize/bias, so it has zero
        # weight. Closing window 2 must not hand its column's space to windows 1
        # and 4, which are not in any sub-tree that lost a window.
        shape = {'one': 1, 'two': {'one': {'bias': 1.0, 'one': 2, 'two': 3}, 'two': 4}}
        q, windows = self.make_layout(shape, num=4)
        self.check_weights(q, {1: 0.5, 2: 0.25, 3: 0.0, 4: 0.25})
        q.remove_windows(2)
        self.check_weights(q, {1: 0.5, 3: 0.25, 4: 0.25})

    def test_proportional_batch_close_matches_sequential(self):
        # Pruning several windows in one pass (which happens when they are closed
        # while a different layout is active) must match closing them one by one.
        shape = {
            'bias': 0.4,
            'one': {'horizontal': False, 'one': 1, 'two': {'one': 2, 'two': 3}},
            'two': {'horizontal': False, 'one': 4, 'two': {'horizontal': False, 'one': 5, 'two': 6}},
        }
        removed = (6, 1, 3)
        q, windows = self.make_layout(shape, num=6)
        q.remove_windows(*removed)
        batch = q.pairs_root.window_weights()
        q, windows = self.make_layout(shape, num=6)
        for wid in removed:
            q.remove_windows(wid)
        sequential = q.pairs_root.window_weights()
        self.ae(batch.keys(), sequential.keys())
        for wid, weight in sequential.items():
            self.assertAlmostEqual(batch[wid], weight)

    def test_proportional_balanced_add(self):
        # A window that appears without being split off an existing one (it was
        # created while another layout was active) still gets a proportional share.
        q, windows = self.make_layout()
        q.add_window(windows, Window(2), location='vsplit')
        q.add_window(windows, Window(3), location='vsplit')
        self.check_weights(q, dict.fromkeys((1, 2, 3), 1 / 3))
        self.ae(q.balanced_add_window(4).horizontal, q.pairs_root.horizontal)
        self.check_weights(q, dict.fromkeys((1, 2, 3, 4), 0.25))
