#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.boss import Boss
from kitty.fast_data_types import Region
from kitty.layout.base import carve_docks, lgd, outer_region_of
from kitty.layout.interface import Splits, Stack, Tall
from kitty.tabs import DetachedGroup
from kitty.tabs import Tab as RealTab
from kitty.tabs import TabManager as RealTabManager
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
        self.tab = None

    def set_geometry(self, geometry):
        self.set_geometry_calls += 1
        super().set_geometry(geometry)

    def change_tab(self, tab):
        self.tab = tab


class OSWindowTab:
    "A tab in an OS window that can host the OS window docks"

    def __init__(self, tm, tab_id, *window_ids):
        self.id = tab_id
        self.tm = tm
        self.os_window_id = tm.os_window_id
        self.current_layout = make_layout(Tall)
        self.windows = WindowList(self, tm.os_window_docks)
        for wid in window_ids:
            self.current_layout.add_window(self.windows, CountingWindow(wid))
        tm.tabs.append(self)

    def __len__(self):
        return len(self.windows)

    def __iter__(self):
        return iter(self.windows)

    def tab_manager_ref(self):
        return self.tm

    name = cwd = created_in_session_name = ''
    enabled_layouts = ('tall',)
    _last_used_layout = None
    _current_layout_name = ''
    take_over_from = RealTab.take_over_from

    def mark_tab_bar_dirty(self):
        pass

    def active_window_changed(self):
        pass

    @property
    def active_window(self):
        return self.windows.active_window

    def relayout(self):
        self.current_layout(self.windows)


class OSWindowTabManager:
    os_window_docks_host = RealTabManager.os_window_docks_host
    host_os_window_docks_in = RealTabManager.host_os_window_docks_in
    park_os_window_docks = RealTabManager.park_os_window_docks
    sync_os_window_docks = RealTabManager.sync_os_window_docks

    def __init__(self, os_window_id=1):
        self.os_window_id = os_window_id
        self.os_window_docks = []
        self._os_window_docks_host = None
        self._os_window_docks_parked = False
        self.tabs = []
        self.active_tab = None
        self.remove = Mock(side_effect=self.tabs.remove)

    def __len__(self):
        return len(self.tabs)


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


def add_os_window_dock(tab, win_id, edge='left', size='1', focusable=True):
    w = CountingWindow(win_id)
    tab.current_layout.add_window(tab.windows, w, dock=parse_dock_spec(edge, size, focusable), os_window_dock=True)
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
        self.ae(parse_dock_spec('left', '20%').as_launch_args('os-window'), ['--type=os-window-dock', '--dock-edge=left', '--dock-size=20%'])

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

    def test_os_window_docks(self):
        reset_group_id_counter()
        tm = OSWindowTabManager()
        t1, t2 = OSWindowTab(tm, 101, 1, 2), OSWindowTab(tm, 102, 3)
        c_calls = self.patch_c_calls()

        def switch_to(tab):
            tm.active_tab = tab
            tm.sync_os_window_docks()

        def region(w):
            return rect(outer_region_of(w.geometry))

        switch_to(t1)
        self.assertTrue(t1.windows.hosts_os_window_docks)
        self.assertFalse(t2.windows.hosts_os_window_docks)
        with self.assertRaises(ValueError):
            t2.current_layout.add_window(t2.windows, CountingWindow(99), dock=parse_dock_spec('left', '10%'), os_window_dock=True)
        side = add_dock(t1.current_layout, t1.windows, 10, 'left', '10%')
        t1.windows.remove_window(side)
        side = CountingWindow(10)
        t1.current_layout.add_window(t1.windows, side, dock=parse_dock_spec('left', '10%'), os_window_dock=True)
        tab_dock = add_dock(t1.current_layout, t1.windows, 11, 'left', '3')
        group = t1.windows.group_for_window(side)
        self.ae(tm.os_window_docks, [group])
        self.ae(group.as_simple_dict()['dock'], {'edge': 'left', 'size': '10%', 'focusable': True, 'scope': 'os-window'})
        self.ae(t1.windows.group_for_window(tab_dock).as_simple_dict()['dock']['scope'], 'tab')
        self.assertTrue(t1.windows.is_in_os_window_dock(side))
        self.assertFalse(t1.windows.is_in_os_window_dock(tab_dock))
        self.ae([w.id for w in t1.windows.iter_tab_windows()], [1, 2, 11])
        # The OS window dock is outside the tab dock
        t1.relayout()
        self.ae(region(side), (0, 0, 100, 600))
        self.ae(region(tab_dock), (100, 0, 100 + 3 * CELL_WIDTH + 2 * DECORATION, 600))
        self.check_no_overlaps(t1.windows)
        dock_geometry = side.geometry
        # Every tab reserves the space for the OS window docks
        t2.relayout()
        self.ae(rect(lgd.central), (100, 0, 1000, 600))
        self.assertNotIn(side, t2.windows)

        # Neighbors
        gid = {w.id: t1.windows.group_for_window(w).id for w in t1.windows}

        def neighbors(tab, wid):
            return {k: v for k, v in tab.current_layout.neighbors_for_any_window(tab.windows.id_map[wid], tab.windows).items() if v}

        self.ae(neighbors(t1, 10), {'right': [gid[11]]})
        self.ae(neighbors(t1, 11)['left'], [gid[10]])

        # Focus the OS window dock and switch tabs, it moves to the new tab
        t1.windows.set_active_window_group_for(side)
        self.assertIs(t1.active_window, side)
        switch_to(t2)
        c_calls['move_window_to_tab'].assert_called_once_with(1, 101, 102, 10)
        c_calls['set_active_window'].assert_called_once_with(1, 101, 2)
        self.assertIs(side.tab, t2)
        self.assertNotIn(side, t1.windows)
        self.assertIn(side, t2.windows)
        self.assertIs(t1.active_window, t1.windows.id_map[2])
        # It does not take the focus in the new tab
        self.assertIs(t2.active_window, t2.windows.id_map[3])
        self.ae(side.geometry, dock_geometry)
        self.assertTrue(side.is_visible_in_layout)
        self.ae(neighbors(t2, 3)['left'], [t2.windows.group_for_window(side).id])
        self.check_no_overlaps(t2.windows)
        # The tab dock stays in its tab
        self.assertIn(tab_dock, t1.windows)
        self.ae([w.id for w in t2.windows], [3, 10])
        self.ae([w.id for w in t2.windows.iter_tab_windows()], [3])
        self.ae(list(t2.windows.hosted_os_window_docks()), tm.os_window_docks)
        self.ae(list(t1.windows.hosted_os_window_docks()), [])

        # A tab with only the OS window docks has no windows of its own
        t2.windows.remove_window(t2.windows.id_map[3])
        self.assertFalse(t2.windows.has_tab_windows)
        self.assertTrue(t1.windows.has_tab_windows)

        # Parking takes the docks out of all tabs, syncing puts them in the active tab
        tm.park_os_window_docks(t1)
        c_calls['detach_window'].assert_not_called()
        tm.park_os_window_docks(t2)
        c_calls['detach_window'].assert_called_once_with(1, 102, 10)
        self.assertIsNone(tm.os_window_docks_host)
        self.assertNotIn(side, t2.windows)
        tm.active_tab = t1
        tm.sync_os_window_docks()
        c_calls['attach_window'].assert_called_once_with(1, 101, 10)
        self.assertIs(side.tab, t1)
        self.assertIn(side, t1.windows)
        self.ae(side.geometry, dock_geometry)

        # Closing the dock removes it from every tab
        t1.windows.remove_window(side)
        self.ae(tm.os_window_docks, [])
        t2.relayout()
        self.ae(rect(lgd.central), (0, 0, 1000, 600))

    def test_cleanup_of_tab_with_only_os_window_docks(self):
        reset_group_id_counter()
        tm = OSWindowTabManager()
        with patch('kitty.tabs.move_window_to_tab', return_value=True), patch('kitty.tabs.set_active_window'):
            t1, t2 = OSWindowTab(tm, 101, 1), OSWindowTab(tm, 102, 2)
            tm.active_tab = t1
            tm.sync_os_window_docks()
            dock = CountingWindow(10)
            t1.current_layout.add_window(t1.windows, dock, dock=parse_dock_spec('top', '1'), os_window_dock=True)
            boss = SimpleNamespace(shutting_down=False, mark_window_for_close=Mock(), mark_os_window_for_close=Mock())
            cleanup = Boss._cleanup_tab_after_window_removal.__get__(boss)
            t1.windows.remove_window(t1.windows.id_map[1])
            t1.destroy = Mock()
            # With other tabs present, the tab is removed and the docks move on
            cleanup(t1)
            tm.remove.assert_called_once_with(t1)
            boss.mark_window_for_close.assert_not_called()
            # In the last tab, the docks are closed first
            tm.remove.reset_mock()
            tm.active_tab = t2
            tm.sync_os_window_docks()
            t2.windows.remove_window(t2.windows.id_map[2])
            cleanup(t2)
            tm.remove.assert_not_called()
            self.ae([c.args[0] for c in boss.mark_window_for_close.call_args_list], [dock])
            t2.windows.remove_window(dock)
            t2.destroy = Mock()
            cleanup(t2)
            tm.remove.assert_called_once_with(t2)
            boss.mark_os_window_for_close.assert_called_once_with(1)

    def test_moving_tab_to_other_os_window_keeps_docks(self):
        reset_group_id_counter()
        src, dest = OSWindowTabManager(1), OSWindowTabManager(2)
        self.patch_c_calls()
        moved, staying, target = OSWindowTab(src, 101, 1), OSWindowTab(src, 102, 2), OSWindowTab(dest, 201)
        for tm, tab, wid in ((src, moved, 10), (dest, target, 20)):
            tm.active_tab = tab
            tm.sync_os_window_docks()
            tab.current_layout.add_window(tab.windows, CountingWindow(wid), dock=parse_dock_spec('left', '5'), os_window_dock=True)
        src_dock, dest_dock = src.os_window_docks[0], dest.os_window_docks[0]
        # The source tab will be removed, so the docks go to the other tab
        src.active_tab = staying
        target.take_over_from(moved)
        self.assertIs(target.windows.os_window_docks, dest.os_window_docks)
        self.assertIs(moved.windows.os_window_docks, src.os_window_docks)
        self.assertIs(staying.windows.os_window_docks, src.os_window_docks)
        self.ae(src.os_window_docks, [src_dock])
        self.ae(dest.os_window_docks, [dest_dock])
        self.ae([w.id for w in target.windows], [1, 20])
        self.ae([w.id for w in staying.windows], [2, 10])
        self.ae([w.id for w in moved.windows], [])
        self.assertIs(src.os_window_docks_host, staying)
        self.assertIs(dest.os_window_docks_host, target)

    def patch_c_calls(self):
        c_calls = {name: Mock(return_value=True) for name in ('move_window_to_tab', 'attach_window', 'detach_window', 'set_active_window')}
        patches = [patch(f'kitty.tabs.{name}', m) for name, m in c_calls.items()]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return c_calls

    def test_multiple_os_window_docks(self):
        reset_group_id_counter()
        tm = OSWindowTabManager()
        c_calls = self.patch_c_calls()
        t1, t2 = OSWindowTab(tm, 101, 1, 2), OSWindowTab(tm, 102, 3)
        tm.active_tab = t1
        tm.sync_os_window_docks()
        outer_left = add_os_window_dock(t1, 10, 'left', '10%', focusable=False)
        inner_left = add_os_window_dock(t1, 11, 'left', '5')
        bottom = add_os_window_dock(t1, 12, 'bottom', '1')
        tab_dock = add_dock(t1.current_layout, t1.windows, 13, 'left', '3')
        dock_ids = [10, 11, 12]
        self.ae([[w.id for w in g] for g in tm.os_window_docks], [[10], [11], [12]])
        self.ae([g.dock_as_dict()['scope'] for g in t1.windows.iter_dock_groups()], ['tab', 'os-window', 'os-window', 'os-window'])

        def region(w):
            return rect(outer_region_of(w.geometry))

        def neighbors(tab, wid):
            return {k: v for k, v in tab.current_layout.neighbors_for_any_window(tab.windows.id_map[wid], tab.windows).items() if v}

        def gid(tab, w):
            return tab.windows.group_for_window(w).id

        # Later docks at the same edge are inside earlier ones, the earlier
        # docks span the full extent of their edge, the tab docks are inside all
        # the OS window docks
        t1.relayout()
        self.ae(region(outer_left), (0, 0, 100, 600))
        self.ae(region(inner_left), (100, 0, 100 + 5 * CELL_WIDTH + 2 * DECORATION, 600))
        self.ae(region(bottom), (156, 600 - CELL_HEIGHT - 2 * DECORATION, 1000, 600))
        self.ae(region(tab_dock), (156, 0, 156 + 3 * CELL_WIDTH + 2 * DECORATION, 574))
        self.ae(rect(lgd.central), (192, 0, 1000, 574))
        self.check_no_overlaps(t1.windows)
        geometries = {wid: t1.windows.id_map[wid].geometry for wid in dock_ids}

        # Neighbors chain from the OS window docks through the tab docks to
        # the layout, skipping docks that cannot be focused
        self.ae(neighbors(t1, 11), {'right': [gid(t1, tab_dock)]})
        self.ae(neighbors(t1, 13)['left'], [gid(t1, inner_left)])
        self.ae(neighbors(t1, 12), {'top': [t1.windows.active_main_group.id]})
        self.ae(neighbors(t1, 1), {'right': [t1.windows.groups[1].id], 'left': [gid(t1, tab_dock)], 'bottom': [gid(t1, bottom)]})
        # Focusable docks are numbered after the normal windows, the tab docks first
        self.ae([w.id for n, w in t1.windows.iter_windows_with_number(only_visible=False)], [1, 2, 13, 11, 12])

        # All the OS window docks move together, in order, and keep their geometry
        tm.active_tab = t2
        tm.sync_os_window_docks()
        self.ae([c.args for c in c_calls['move_window_to_tab'].call_args_list], [(1, 101, 102, wid) for wid in dock_ids])
        self.ae([w.id for w in t2.windows], [3] + dock_ids)
        self.ae([w.id for w in t1.windows], [1, 2, 13])
        self.ae({wid: t2.windows.id_map[wid].geometry for wid in dock_ids}, geometries)
        self.assertTrue(all(t2.windows.id_map[wid].is_visible_in_layout for wid in dock_ids))
        self.ae(rect(lgd.central), (156, 0, 1000, 574))
        self.check_no_overlaps(t2.windows)
        self.ae(neighbors(t2, 3), {'left': [gid(t2, inner_left)], 'bottom': [gid(t2, bottom)]})
        self.ae(neighbors(t2, 11), {'right': [t2.windows.active_main_group.id]})

        # Closing one of them gives its space to the others, in every tab
        t2.windows.remove_window(inner_left)
        self.ae([[w.id for w in g] for g in tm.os_window_docks], [[10], [12]])
        t2.relayout()
        self.ae(region(outer_left), (0, 0, 100, 600))
        self.ae(region(bottom), (100, 574, 1000, 600))
        self.ae(rect(lgd.central), (100, 0, 1000, 574))
        t1.relayout()
        self.ae(region(tab_dock), (100, 0, 136, 574))
        self.ae(rect(lgd.central), (136, 0, 1000, 574))
        self.check_no_overlaps(t1.windows)

        # Moving back to the first tab moves the remaining docks
        tm.active_tab = t1
        tm.sync_os_window_docks()
        self.ae([w.id for w in t1.windows], [1, 2, 13, 10, 12])
        self.ae([w.id for w in t2.windows], [3])

    def test_multiple_os_window_docks_shrink(self):
        reset_group_id_counter()
        tm = OSWindowTabManager()
        self.patch_c_calls()
        t1, t2 = OSWindowTab(tm, 101, 1), OSWindowTab(tm, 102, 2)
        tm.active_tab = t1
        tm.sync_os_window_docks()
        top = add_os_window_dock(t1, 10, 'top', '90%')
        bottom = add_os_window_dock(t1, 11, 'bottom', '50%')
        tab_dock = add_dock(t1.current_layout, t1.windows, 12, 'top', '1')
        t1.relayout()
        # The docks created last are made smaller first, down to nothing for the
        # tab docks and the layout
        self.ae([outer_region_of(w.geometry).height for w in (top, bottom, tab_dock)], [540, 60, 0])
        self.ae(lgd.central.height, 0)
        # The same space is reserved in the other tab
        t2.relayout()
        self.ae(lgd.central.height, 0)
        t1.windows.remove_window(top)
        t2.relayout()
        self.ae(rect(lgd.central), (0, 0, 1000, 300))
