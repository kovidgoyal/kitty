#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.fast_data_types import Region
from kitty.layout.base import carve_docks, lgd, outer_region_of
from kitty.layout.interface import Splits, Stack, Tall
from kitty.tabs import DetachedGroup
from kitty.tabs import Tab as RealTab
from kitty.types import DockSpec, parse_dock_spec
from kitty.window_list import WindowGroup, WindowList, reset_group_id_counter

from .base import BaseTest
from .layout import Tab, Window

VIEWPORT = Region((0, 0, 999, 599, 1000, 600))
CELL_WIDTH, CELL_HEIGHT = 10, 20
# The test windows have a margin, border and padding of one pixel on every edge
DECORATION = 3


class CountingWindow(Window):
    def __init__(self, win_id: int) -> None:
        super().__init__(win_id)
        self.set_geometry_calls = 0

    def set_geometry(self, geometry):
        self.set_geometry_calls += 1
        super().set_geometry(geometry)


def make_layout(cls):
    ans = cls(1, 1)
    ans.set_active_window_in_os_window = lambda idx: None
    ans.swap_windows_in_os_window = lambda a, b: None
    return ans


def make_windows(layout, num=2):
    t = Tab()
    t.current_layout = layout
    t.windows = ans = WindowList(t)
    reset_group_id_counter()
    for i in range(num):
        layout.add_window(ans, CountingWindow(i + 1))
    ans.set_active_group_idx(0)
    return ans


def add_dock(layout, windows, win_id, edge='bottom', size='1', focusable=True, owner=None):
    w = CountingWindow(win_id)
    layout.add_window(windows, w, dock=parse_dock_spec(edge, size, focusable), dock_owner=owner)
    return w


def rect(r):
    return r.left, r.top, r.left + r.width, r.top + r.height


def overlaps(a, b):
    al, at, ar, ab = rect(a)
    bl, bt, br, bb = rect(b)
    return al < br and bl < ar and at < bb and bt < ab


class TestDocks(BaseTest):
    def setUp(self):
        super().setUp()
        self.set_options({'tab_bar_style': 'hidden'})
        self.viewport_patch = patch('kitty.layout.base.viewport_for_window', return_value=(VIEWPORT, VIEWPORT, 1000, 600, CELL_WIDTH, CELL_HEIGHT))
        self.viewport_patch.start()

    def tearDown(self):
        self.viewport_patch.stop()
        super().tearDown()

    def check_no_overlaps(self, windows):
        regions = [(g.id, outer_region_of(g.geometry)) for g in windows.iter_visible_groups()]
        for i, (gid, r) in enumerate(regions):
            left, top, right, bottom = rect(r)
            self.assertTrue(0 <= left and 0 <= top and right <= 1000 and bottom <= 600, f'group {gid} is outside the viewport: {r}')
            for oid, o in regions[i + 1 :]:
                self.assertFalse(overlaps(r, o), f'groups {gid} and {oid} overlap: {r} {o}')

    def test_dock_spec_parsing(self):
        self.ae(parse_dock_spec('left', '3'), DockSpec('left', 3, False, True))
        self.ae(parse_dock_spec('top', ' 12.5% ', False), DockSpec('top', 12.5, True, False))
        self.ae(parse_dock_spec('top', '100%').size_as_string, '100%')
        for edge, size in (('middle', '1'), ('top', '0'), ('top', '-1'), ('top', '0%'), ('top', '101%'), ('top', 'x'), ('top', '1.5'), ('top', 'nan%')):
            with self.subTest(edge=edge, size=size), self.assertRaises(ValueError):
                parse_dock_spec(edge, size)
        spec = parse_dock_spec('right', '30%', False)
        self.ae(spec.as_launch_args('window'), ['--type=window-dock', '--dock-edge=right', '--dock-size=30%', '--dock-skip-focus'])
        self.ae(parse_dock_spec('top', '2').as_launch_args('tab'), ['--type=tab-dock', '--dock-edge=top', '--dock-size=2'])

    def test_carving(self):
        def dock(edge, size):
            g = WindowGroup(parse_dock_spec(edge, size))
            g.add_window(Window(len(groups) + 1))
            groups.append(g)
            return g

        groups: list[WindowGroup] = []
        top, left, bottom = dock('top', '2'), dock('left', '10%'), dock('bottom', '1')
        content, placements = carve_docks(VIEWPORT, groups, CELL_WIDTH, CELL_HEIGHT)
        self.ae([g for g, r in placements], groups)
        regions = {g.id: rect(r) for g, r in placements}
        # earlier docks span the full extent, later docks fit into what remains
        self.ae(regions[top.id], (0, 0, 1000, 2 * CELL_HEIGHT + 2 * DECORATION))
        self.ae(regions[left.id], (0, 46, 100, 600))
        self.ae(regions[bottom.id], (100, 600 - CELL_HEIGHT - 2 * DECORATION, 1000, 600))
        self.ae(rect(content), (100, 46, 1000, 574))

        # When space runs out, later docks shrink first and the content can be squeezed to nothing
        groups = []
        dock('top', '90%'), dock('bottom', '20%')
        content, placements = carve_docks(VIEWPORT, groups, CELL_WIDTH, CELL_HEIGHT)
        self.ae([r.height for g, r in placements], [540, 60])
        self.ae(content.height, 0)
        groups = []
        dock('top', '90%'), dock('bottom', '50%')
        content, placements = carve_docks(VIEWPORT, groups, CELL_WIDTH, CELL_HEIGHT)
        self.ae([r.height for g, r in placements], [540, 60])
        content, placements = carve_docks(Region((0, 0, -1, -1, 0, 0)), groups, CELL_WIDTH, CELL_HEIGHT)
        self.ae([r.height for g, r in placements], [0, 0])

    def test_tab_docks(self):
        q = make_layout(Tall)
        windows = make_windows(q, 2)
        status = add_dock(q, windows, 10, 'bottom', '1', focusable=False)
        side = add_dock(q, windows, 11, 'left', '20%')
        # docks are not part of the layout
        self.ae(windows.num_groups, 2)
        self.ae(len(windows), 4)
        # the non focusable dock did not take focus, the other one did
        self.assertIs(windows.active_window, side)
        self.assertIs(windows.active_main_window, windows.id_map[1])
        q(windows)
        self.ae(rect(outer_region_of(status.geometry)), (0, 600 - CELL_HEIGHT - 2 * DECORATION, 1000, 600))
        self.ae(rect(outer_region_of(side.geometry)), (0, 0, 200, 574))
        self.ae(status.geometry.ynum, 1)
        self.ae(rect(lgd.central), (200, 0, 1000, 574))
        self.assertTrue(all(w.is_visible_in_layout for w in windows))
        self.check_no_overlaps(windows)
        # cannot focus a dock that skips focus
        self.assertFalse(windows.set_active_group(windows.group_for_window(status).id))
        windows.set_active_window_group_for(status)
        self.assertIs(windows.active_window, side)
        # normal window operations do not apply to docks
        self.assertFalse(q.move_window(windows, 1))
        self.assertIsNone(windows.group_idx_for_window(side))
        # going back to the layout
        windows.activate_next_window_group(1)
        self.assertIs(windows.active_window, windows.id_map[2])
        windows.make_previous_group_active()
        self.assertIs(windows.active_window, side)
        # closing the dock returns focus to the layout
        windows.remove_window(side)
        self.assertIs(windows.active_window, windows.id_map[2])
        q(windows)
        self.ae(rect(lgd.central), (0, 0, 1000, 574))

    def test_window_docks(self):
        q = make_layout(Tall)
        windows = make_windows(q, 2)
        owner = windows.groups[1]
        main = windows.id_map[2]
        bottom = add_dock(q, windows, 10, 'bottom', '2', owner=owner)
        right = add_dock(q, windows, 11, 'right', '25%', owner=owner)
        self.ae(owner.docks, [windows.group_for_window(bottom), windows.group_for_window(right)])
        self.assertIs(windows.active_window, right)
        # Focusing a dock makes its owner the active normal group
        self.assertIs(windows.active_main_group, owner)
        q(windows)
        allocated = outer_region_of(owner.allocated_geometry)
        content = outer_region_of(main.geometry)
        dock_regions = [outer_region_of(w.geometry) for w in (bottom, right)]
        # The owner and its docks exactly share the area the layout gave the owner
        self.ae(sum(r.width * r.height for r in [content] + dock_regions), allocated.width * allocated.height)
        for r in [content] + dock_regions:
            self.assertTrue(rect(r)[0] >= allocated.left and rect(r)[2] <= allocated.left + allocated.width)
        self.ae(rect(dock_regions[0])[1], allocated.top + allocated.height - 2 * CELL_HEIGHT - 2 * DECORATION)
        self.ae(dock_regions[1].width, allocated.width // 4)
        self.check_no_overlaps(windows)
        # The decorations chosen by the layout for the owner are preserved
        self.ae(main.geometry.spaces.left - main.geometry.compensatory.left, DECORATION)

        # Relayouts resize the owner's windows only once
        for w in windows:
            w.set_geometry_calls = 0
        q(windows)
        self.ae({w.id: w.set_geometry_calls for w in windows}, {1: 1, 2: 1, 10: 1, 11: 1})

        # Closing the owner orphans its docks, they are hidden and closed by the tab
        windows.remove_window(main)
        self.ae(windows.num_groups, 1)
        self.ae([list(d) for d in windows.orphaned_docks], [[bottom], [right]])
        self.assertIs(windows.active_window, windows.id_map[1])
        q(windows)
        self.assertFalse(bottom.is_visible_in_layout or right.is_visible_in_layout)
        windows.remove_window(bottom)
        windows.remove_window(right)
        self.ae(windows.orphaned_docks, [])
        self.ae(len(windows), 1)

    def test_docks_follow_owner_visibility(self):
        q = make_layout(Stack)
        windows = make_windows(q, 2)
        dock = add_dock(q, windows, 10, 'top', '1', owner=windows.groups[0])
        overlay = CountingWindow(11)
        q.add_window(windows, overlay, overlay_for=dock.id)
        self.assertIs(windows.group_for_window(overlay), windows.group_for_window(dock))
        self.assertIs(windows.active_window, overlay)
        q(windows)
        self.ae((dock.is_visible_in_layout, overlay.is_visible_in_layout), (False, True))
        self.assertTrue(windows.id_map[1].is_visible_in_layout)
        windows.set_active_group_idx(1)
        q(windows)
        self.assertFalse(windows.id_map[1].is_visible_in_layout or overlay.is_visible_in_layout)
        self.assertTrue(windows.id_map[2].is_visible_in_layout)
        self.check_no_overlaps(windows)

    def test_removing_earlier_group_keeps_dock_owner_active(self):
        q = make_layout(Tall)
        windows = make_windows(q, 3)
        dock = add_dock(q, windows, 10, owner=windows.groups[2])
        self.assertIs(windows.active_window, dock)
        windows.remove_window(windows.id_map[1])
        self.assertIs(windows.active_window, dock)
        self.assertIs(windows.active_main_window, windows.id_map[3])

    def test_dock_neighbors(self):
        q = make_layout(Tall)
        windows = make_windows(q, 2)
        g1, g2 = windows.groups
        outer = add_dock(q, windows, 10, 'bottom', owner=g2)
        inner = add_dock(q, windows, 11, 'bottom', owner=g2)
        add_dock(q, windows, 12, 'right', owner=g2, focusable=False)
        tab_dock = add_dock(q, windows, 13, 'top')
        q(windows)
        gid = {w.id: windows.group_for_window(w).id for w in windows}

        def neighbors(wid):
            return {k: v for k, v in q.neighbors_for_any_window(windows.id_map[wid], windows).items() if v}

        # the innermost dock is next to its owner, docks that skip focus are skipped
        self.ae(neighbors(2), {'left': [g1.id], 'bottom': [gid[11]], 'top': [gid[13]]})
        self.ae(neighbors(11), {'left': [g1.id], 'top': [g2.id], 'bottom': [gid[10]]})
        self.ae(neighbors(10), {'left': [g1.id], 'top': [gid[11]]})
        self.ae(neighbors(1), {'right': [g2.id], 'top': [gid[13]]})
        windows.set_active_group_idx(1)
        self.ae(neighbors(13), {'bottom': [g2.id]})
        # neighbors for windows in the layout are unchanged when there are no docks
        windows.remove_window(tab_dock)
        windows.remove_window(outer)
        windows.remove_window(inner)
        self.ae(neighbors(1), {'right': [g2.id]})

    def test_splits_ignore_docks(self):
        q = make_layout(Splits)
        windows = make_windows(q, 0)
        for wid in (1, 2):
            q.add_window(windows, CountingWindow(wid), location='vsplit')
        add_dock(q, windows, 10, 'left', '5', owner=windows.groups[0])
        add_dock(q, windows, 11, 'top', '2')
        # new windows are never split off a docked window
        q.add_window(windows, CountingWindow(3), location='hsplit')
        q(windows)
        self.ae(set(q.pairs_root.all_window_ids()), {g.id for g in windows.groups})
        self.assertIsNone(q.layout_action('rotate', (), windows) if windows.active_dock else None)
        self.check_no_overlaps(windows)
        windows.set_active_window_group_for(windows.id_map[10])
        q.insert_window_next_to(windows, windows.id_map[10], windows.id_map[2], True, True)
        self.ae(set(q.pairs_root.all_window_ids()), {g.id for g in windows.groups})

    def test_layout_state_ignores_docks(self):
        q = make_layout(Tall)
        windows = make_windows(q, 2)
        add_dock(q, windows, 10, owner=windows.groups[0])
        add_dock(q, windows, 11, 'top')
        state = windows.serialize_layout_state()
        window_id_map = {w.id: w.id for w in windows}
        self.assertIsNotNone(windows.unserialize_layout_state(state, window_id_map))
        del window_id_map[10], window_id_map[11]
        self.assertIsNotNone(windows.unserialize_layout_state(state, window_id_map))

    def test_detach_and_attach_carry_docks(self):
        q = make_layout(Tall)
        windows = make_windows(q, 2)
        owner = windows.groups[0]
        dock = add_dock(q, windows, 10, 'right', '3', owner=owner)
        dock_overlay = CountingWindow(11)
        q.add_window(windows, dock_overlay, overlay_for=dock.id)
        boss = SimpleNamespace(mark_window_for_close=Mock())

        def make_tab(windows):
            tab = SimpleNamespace(id=2, os_window_id=1, current_layout=q, windows=windows, mark_tab_bar_dirty=Mock(), relayout=Mock())
            tab.post_window_removal_update = Mock()
            for name in ('remove_window', 'detach_window', '_add_window', '_take_ownership_of_window', 'attach_window', 'attach_windows', 'set_active_window'):
                setattr(tab, name, getattr(RealTab, name).__get__(tab))
            return tab

        src = make_tab(windows)
        for w in windows:
            w.change_tab = Mock()
        with patch('kitty.tabs.detach_window'), patch('kitty.tabs.get_boss', return_value=boss):
            detached = src.detach_window(windows.id_map[1])
        self.assertIsInstance(detached, DetachedGroup)
        self.ae([w.id for w in detached.windows], [1])
        self.ae([(spec.edge, [w.id for w in ws]) for spec, ws in detached.docks], [('right', [10, 11])])
        self.ae([w.id for w in windows], [2])
        self.ae(windows.orphaned_docks, [])
        boss.mark_window_for_close.assert_not_called()

        dest_windows = make_windows(q, 0)
        dest_windows.add_window(CountingWindow(5))
        dest = make_tab(dest_windows)
        with patch('kitty.tabs.attach_window'):
            dest.attach_windows(detached)
        new_owner = dest_windows.group_for_window(detached.windows[0])
        self.ae([[w.id for w in d] for d in new_owner.docks], [[10, 11]])
        self.ae(new_owner.docks[0].dock, parse_dock_spec('right', '3'))
        self.assertIs(dest_windows.active_window, detached.windows[0])

    def test_closing_last_window_closes_docks(self):
        q = make_layout(Tall)
        windows = make_windows(q, 2)
        tab_dock = add_dock(q, windows, 10, 'top')
        owned = add_dock(q, windows, 11, owner=windows.groups[1])
        boss = SimpleNamespace(mark_window_for_close=Mock())
        tab = SimpleNamespace(id=2, os_window_id=1, windows=windows, post_window_removal_update=Mock())
        remove = RealTab.remove_window.__get__(tab)
        with patch('kitty.tabs.remove_window'), patch('kitty.tabs.get_boss', return_value=boss):
            remove(windows.id_map[2])
            self.ae([c.args[0] for c in boss.mark_window_for_close.call_args_list], [owned])
            boss.mark_window_for_close.reset_mock()
            remove(owned)
            boss.mark_window_for_close.assert_not_called()
            remove(windows.id_map[1])
            self.ae([c.args[0] for c in boss.mark_window_for_close.call_args_list], [tab_dock])
