#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

import os
from contextlib import nullcontext
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from kitty.boss import Boss
from kitty.layout.interface import Splits, Stack, Tall
from kitty.tabs import DragOverlayMode, Tab, TabManager

from .base import BaseTest
from .layout import Window, create_layout, create_windows


def tab_mime() -> str:
    # Must be computed at run time, the test runner may fork after importing this module
    return f'application/net.kovidgoyal.kitty-tab-{os.getpid()}'


def region(left: int, top: int, right: int, bottom: int) -> SimpleNamespace:
    return SimpleNamespace(left=left, top=top, right=right, bottom=bottom)


class Viewport:
    """Models the coupling between tab bar visibility and the size of the central region.

    The real viewport_for_window() shrinks the central region as soon as the tab bar becomes
    visible, and a drag hovering over an OS Window forces the tab bar visible. Drop classification
    therefore feeds back into the geometry it is based on, so tests need a viewport that reproduces
    it rather than a fixed pair of regions."""

    tab_bar_height = 30
    cell_width, cell_height = 10, 20

    def __init__(self, num_tabs: int = 1, min_tabs: int = 2, width: int = 1000, height: int = 800):
        self.num_tabs, self.min_tabs = num_tabs, min_tabs
        self.width, self.height = width, height
        self.drag_over = False

    @property
    def tab_bar_visible(self) -> bool:
        return self.drag_over or self.num_tabs >= self.min_tabs

    def regions(self) -> tuple[SimpleNamespace, ...]:
        top = self.tab_bar_height if self.tab_bar_visible else 0
        tab_bar = region(0, 0, self.width, top) if top else region(0, 0, 0, 0)
        return region(0, top, self.width, self.height), tab_bar, self.width, self.height, self.cell_width, self.cell_height


class FakeTabManager:
    "The parts of TabManager that Boss touches while classifying a drop"

    def __init__(self, viewport: Viewport, os_window_id: int = 1, active_tab: object = None):
        self.viewport, self.os_window_id, self.active_tab = viewport, os_window_id, active_tab
        self.tab_being_dropped: object = None
        self.window_being_dropped: object = None
        for name in ('on_tab_drop_move', 'on_window_drop_move', 'on_window_drop', 'on_tab_drop', 'layout_tab_bar'):
            setattr(self, name, Mock(name=name))

    def set_drag_over_me(self, over: bool) -> None:
        self.viewport.drag_over = over


class BossDropTest(BaseTest):
    "Drives the real Boss drop handlers against fake tab managers and a viewport model"

    num_tabs_in_destination = 2

    def setUp(self):
        super().setUp()
        self.viewport = Viewport(num_tabs=self.num_tabs_in_destination)
        self.viewports = {1: self.viewport}
        self.window = SimpleNamespace(id=10)
        self.source = SimpleNamespace(id=1, os_window_id=1, windows=SimpleNamespace(num_groups=1), active_window=self.window)
        self.destination = SimpleNamespace(id=2)
        self.tm = FakeTabManager(self.viewport, active_tab=self.destination)
        self.boss = SimpleNamespace(
            os_window_map={1: self.tm},
            all_tab_managers=[self.tm],
            tab_for_id=lambda tid: self.source if tid == 1 else None,
            _move_tab_to=Mock(),
            _move_window_to=Mock(),
            _insert_window_in_direction=Mock(),
            window_id_map={},
        )
        for name in ('_update_drag_over', '_reset_drop_previews', '_sole_window_of_tab', '_tab_merge_target'):
            setattr(self.boss, name, partial(getattr(Boss, name), self.boss))
        self.data = {tab_mime(): b'1'}
        for name, value in (
            ('viewport_for_window', lambda os_window_id: self.viewports[os_window_id].regions()),
            ('get_tab_being_dragged', Mock(return_value=(1, True))),
            ('get_window_being_dragged', Mock(return_value=(0, False))),
            ('set_tab_being_dragged', Mock()),
            ('change_drag_thumbnail', Mock()),
        ):
            patcher = patch('kitty.boss.' + name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name, value)

    def drag_move(self, x: int, y: int, is_leave: bool = False) -> tuple[tuple[object, ...], tuple[object, ...]]:
        "Deliver a drag move and return the (window preview, tab preview) arguments it produced"
        self.tm.on_window_drop_move.reset_mock()
        self.tm.on_tab_drop_move.reset_mock()
        Boss.on_drop_move(self.boss, 1, x, y, True, is_leave)
        return self.tm.on_window_drop_move.call_args.args, self.tm.on_tab_drop_move.call_args.args

    def drop(self, x: int, y: int) -> str:
        "Deliver a drop and return the name of the action it performed"
        Boss.on_drop(self.boss, 1, self.data, True, x, y)
        if self.tm.on_window_drop.called:
            return 'merge'
        if self.tm.on_tab_drop.called:
            return 'tab_drop'
        if self.boss._move_tab_to.called:
            return 'reorder'
        return 'nothing'


class TestTabDropClassification(BossDropTest):
    def test_single_window_tab_merges_into_destination_layout(self):
        self.ae(self.drag_move(600, 400), ((10, True, 600, 400), (1, False, 600, 400)))
        self.ae(self.drop(600, 400), 'merge')
        self.tm.on_window_drop.assert_called_once_with(600, 400, 10)
        self.boss._move_tab_to.assert_not_called()
        self.set_tab_being_dragged.assert_called_once_with()

    def test_merge_works_across_os_windows(self):
        self.source.os_window_id = 9
        self.viewports[9] = Viewport(num_tabs=1)
        self.ae(self.drag_move(600, 400)[0], (10, True, 600, 400))
        self.ae(self.drop(600, 400), 'merge')
        self.tm.on_window_drop.assert_called_once_with(600, 400, 10)

    def test_tab_bar_drop_keeps_tab_behavior(self):
        self.ae(self.drag_move(600, 10), ((0, False, 600, 10), (1, True, 600, 10)))
        self.ae(self.drop(600, 10), 'tab_drop')
        self.tm.on_tab_drop.assert_called_once_with(600, 10)

    def test_multi_window_tab_keeps_tab_behavior(self):
        self.source.windows.num_groups = 2
        self.ae(self.drag_move(600, 400)[0], (0, False, 600, 400))
        self.ae(self.drop(600, 400), 'reorder')
        self.boss._move_tab_to.assert_called_once_with(self.source)
        self.source.os_window_id = 9
        self.viewports[9] = Viewport(num_tabs=1)
        self.ae(self.drop(600, 400), 'tab_drop')
        self.tm.on_tab_drop.assert_called_once_with(600, 400)

    def test_tab_drop_into_self_keeps_tab_behavior(self):
        self.tm.active_tab = self.source
        self.ae(self.drag_move(600, 400)[0], (0, False, 600, 400))
        self.ae(self.drop(600, 400), 'reorder')
        self.boss._move_tab_to.assert_called_once_with(self.source)

    def test_leaving_clears_previews(self):
        self.drag_move(600, 400)
        self.assertTrue(self.viewport.drag_over)
        self.ae(self.drag_move(600, 400, is_leave=True), ((0, False, 600, 400), (1, False, 600, 400)))
        self.assertFalse(self.viewport.drag_over, 'leaving must release the forced tab bar')


class TestTabDropClassificationStability(BossDropTest):
    # A destination OS Window with a single tab has its tab bar hidden until the drag forces it
    # visible, which is what makes the classification feed back into the geometry.
    num_tabs_in_destination = 1

    def setUp(self):
        super().setUp()
        self.source.os_window_id = 9
        self.viewports[9] = Viewport(num_tabs=1)
        self.assertFalse(self.viewport.tab_bar_visible)

    def test_classification_does_not_oscillate_over_the_tab_bar(self):
        # y is inside the strip the tab bar occupies once the drag forces it visible
        y = Viewport.tab_bar_height // 2
        first = self.drag_move(600, y)
        self.assertTrue(self.viewport.drag_over, 'the drag must force the destination tab bar visible')
        for _ in range(3):
            self.ae(self.drag_move(600, y), first, 'classification changed while the pointer stood still')
        self.ae(first, ((0, False, 600, y), (1, True, 600, y)))
        self.ae(self.drop(600, y), 'tab_drop', 'the drop disagreed with the preview')

    def test_classification_is_stable_over_the_content_area(self):
        first = self.drag_move(600, 400)
        for _ in range(3):
            self.ae(self.drag_move(600, 400), first)
        self.ae(first, ((10, True, 600, 400), (1, False, 600, 400)))
        self.ae(self.drop(600, 400), 'merge')

    def test_drop_matches_preview_at_every_height(self):
        for y in range(0, self.viewport.height, 7):
            with self.subTest(y=y):
                previewed_merge = self.drag_move(600, y)[0][1]
                self.tm.on_window_drop.reset_mock(), self.tm.on_tab_drop.reset_mock()
                self.boss._move_tab_to.reset_mock()
                action = self.drop(600, y)
                self.ae(action, 'merge' if previewed_merge else 'tab_drop')


class TestWaylandDragFinish(BossDropTest):
    def finish(self, was_dropped: bool = True, was_canceled: bool = False) -> None:
        Boss.on_drag_source_finished(self.boss, was_dropped, was_canceled, '', 0, self.data, True)

    def set_pending_target(self, quadrant: int, direction: str | None) -> SimpleNamespace:
        target = SimpleNamespace(id=20, tab_id=2)
        self.boss.window_id_map[20] = target
        self.tm.window_being_dropped = SimpleNamespace(window_id=20, quadrant=quadrant, direction=direction)
        return target

    def test_cancel_clears_preview_without_detaching(self):
        self.set_pending_target(1, 'left')
        for reported_drop in (True, False):
            with self.subTest(was_dropped=reported_drop):
                self.finish(reported_drop, was_canceled=True)
                self.tm.on_window_drop_move.assert_called_with()
                self.boss._move_tab_to.assert_not_called()
                self.boss._insert_window_in_direction.assert_not_called()
                self.boss._move_window_to.assert_not_called()

    def test_finish_inserts_at_the_previewed_edge(self):
        for quadrant, direction in enumerate(('left', 'right', 'top', 'bottom'), 1):
            with self.subTest(quadrant=quadrant):
                target = self.set_pending_target(quadrant, direction)
                self.finish()
                self.boss._insert_window_in_direction.assert_called_with(self.window, target, direction)
                self.tm.on_window_drop_move.assert_called_with()
                self.boss._move_tab_to.assert_not_called()

    def test_finish_uses_recorded_direction_for_whole_window_highlight(self):
        # Quadrant 6 highlights the whole window (Stack and friends) but still inserts
        # directionally, so the direction resolved when previewing must be the one used.
        for direction in ('left', 'right', 'top', 'bottom'):
            with self.subTest(direction=direction):
                target = self.set_pending_target(6, direction)
                self.finish()
                self.boss._insert_window_in_direction.assert_called_with(self.window, target, direction)

    def test_finish_moves_window_for_title_bar_target(self):
        self.set_pending_target(5, None)
        self.finish()
        self.boss._move_window_to.assert_called_once_with(self.window, target_tab_id=2)
        self.boss._insert_window_in_direction.assert_not_called()

    def test_multi_window_tab_is_not_merged(self):
        self.source.windows.num_groups = 2
        self.set_pending_target(1, 'left')
        self.finish()
        self.boss._insert_window_in_direction.assert_not_called()
        self.boss._move_window_to.assert_not_called()

    def test_internal_drop_finishes_before_data_arrives(self):
        # glfw.c reports was_dropped=False while an internal drop destination exists, even for a
        # successful drop, and the data can arrive after this callback.
        target = self.set_pending_target(1, 'left')
        self.finish(was_dropped=False)
        self.boss._insert_window_in_direction.assert_called_once_with(self.window, target, 'left')
        self.boss._move_tab_to.assert_not_called()

    def test_internal_tab_reordering_is_preserved(self):
        self.tm.tab_being_dropped = SimpleNamespace()
        self.finish(was_dropped=False)
        self.tm.on_tab_drop.assert_called_once_with(0, 0, bypass_move=True)
        self.boss._move_tab_to.assert_not_called()

    def test_completed_drop_is_not_detached_again(self):
        self.get_tab_being_dragged.return_value = (0, False)
        self.finish()
        self.boss._move_tab_to.assert_not_called()

    def test_drop_outside_kitty_detaches_into_new_os_window(self):
        self.finish()
        self.boss._move_tab_to.assert_called_once_with(self.source)


class TestFileDrop(BossDropTest):
    def test_hit_test_accounts_for_an_offset_tab_bar(self):
        central = self.viewport.regions()[0]
        mid = (central.top + central.bottom) // 2
        top = SimpleNamespace(id=1, is_visible_in_layout=True, geometry=region(0, central.top, central.right, mid), on_drop=Mock())
        bottom = SimpleNamespace(id=2, is_visible_in_layout=True, geometry=region(0, mid, central.right, central.bottom), on_drop=Mock())
        hidden = SimpleNamespace(id=3, is_visible_in_layout=False, geometry=top.geometry, on_drop=Mock())
        tab = MagicMock()
        tab.__iter__.return_value = [hidden, top, bottom]
        self.tm.active_tab = tab
        drop = {'text/plain': b'hello'}
        for expected, y in ((top, central.top + 2), (top, mid - 2), (bottom, mid + 2), (bottom, central.bottom - 2)):
            with self.subTest(y=y):
                for w in (top, bottom, hidden):
                    w.on_drop.reset_mock()
                tab.__iter__.return_value = [hidden, top, bottom]
                Boss.on_drop(self.boss, 1, drop, False, 500, y)
                expected.on_drop.assert_called_once_with(drop)
                hidden.on_drop.assert_not_called()


class TestWindowDropTargets(BaseTest):
    "Drives the real TabManager drop handlers, whose hit testing is in OS Window coordinates"

    def make_window(self, win_id, geometry, show_title_bar=False, is_visible_in_layout=True, tab=None):
        return SimpleNamespace(
            id=win_id,
            geometry=geometry,
            show_title_bar=show_title_bar,
            is_visible_in_layout=is_visible_in_layout,
            tab_id=7,
            tabref=lambda: tab,
            is_drag_target=False,
            _title_bar_screen=None,
            update_title_bar=Mock(),
        )

    def make_boss(self, *windows):
        return SimpleNamespace(window_id_map={w.id: w for w in windows}, _insert_window_in_direction=Mock(), _move_window_to=Mock())

    def make_tab_manager(self, windows, central, tab_bar, mode=DragOverlayMode.free):
        tab = MagicMock(current_layout=SimpleNamespace(drag_overlay_mode=mode))
        tab.__iter__.side_effect = lambda: iter(windows)
        tm = SimpleNamespace(
            os_window_id=1,
            active_tab=tab,
            window_being_dropped=None,
            window_drag_over_me=True,
            tab_bar_hidden=False,
            _set_drag_target_tab=Mock(),
            _clear_force_show_title_bars=Mock(),
            mark_tab_bar_dirty=Mock(),
            layout_tab_bar=Mock(),
            resize=Mock(),
            set_drag_over_me=Mock(),
        )
        for name in ('_find_window_at', '_pointer_in_title_bar_of', '_drop_direction_for', '_set_drag_target_window', 'on_window_drop_move'):
            setattr(tm, name, partial(getattr(TabManager, name), tm))
        return tm, (central, tab_bar, central.right, central.bottom, 10, 20)

    def drop_window(self, tm, regions, boss, x, y, window_id):
        with (
            patch('kitty.fast_data_types.viewport_for_window', return_value=regions),
            patch('kitty.fast_data_types.cell_size_for_window', return_value=(10, 20)),
            patch('kitty.fast_data_types.set_window_drag_overlay'),
            patch('kitty.tabs.get_options', return_value=SimpleNamespace(window_title_bar='top')),
            patch('kitty.tabs.get_boss', return_value=boss),
            patch('kitty.tabs.set_window_being_dragged'),
        ):
            tm.on_window_drop_move(window_id, True, x, y)
            preview = tm.window_being_dropped
            TabManager.on_window_drop(tm, x, y, window_id)
        return preview

    def edge_points(self, g):
        return {
            'left': (g.left + 2, (g.top + g.bottom) // 2),
            'right': (g.right - 2, (g.top + g.bottom) // 2),
            'top': ((g.left + g.right) // 2, g.top + 2),
            'bottom': ((g.left + g.right) // 2, g.bottom - 2),
        }

    def test_drop_with_offset_tab_bar(self):
        for left, top in ((0, 30), (80, 0), (80, 30)):
            central = region(left, top, 1000, 800)
            tab_bar = region(0, 0, left or 1000, top or 800)
            g = region(left + 5, top + 5, 995, 795)
            dest = self.make_window(20, g)
            src = self.make_window(10, g)
            tm, regions = self.make_tab_manager([dest], central, tab_bar)
            boss = self.make_boss(src, dest)
            for direction, (x, y) in self.edge_points(g).items():
                with self.subTest(left=left, top=top, direction=direction):
                    boss._insert_window_in_direction.reset_mock()
                    tm.window_being_dropped = None
                    preview = self.drop_window(tm, regions, boss, x, y, 10)
                    self.ae((preview.window_id, preview.direction), (20, direction))
                    boss._insert_window_in_direction.assert_called_once_with(src, dest, direction)
                    boss._move_window_to.assert_not_called()

    def test_hidden_windows_are_not_drop_targets(self):
        # In a Stack layout every group has the same geometry and only one window is visible, so
        # without a visibility check the hit test would depend on iteration order.
        central = region(0, 30, 1000, 800)
        g = region(5, 35, 995, 795)
        hidden = self.make_window(30, g, is_visible_in_layout=False)
        visible = self.make_window(20, g)
        src = self.make_window(10, g)
        tm, regions = self.make_tab_manager([hidden, visible], central, region(0, 0, 1000, 30))
        boss = self.make_boss(src, visible, hidden)
        with patch('kitty.fast_data_types.viewport_for_window', return_value=regions):
            self.assertIs(TabManager._find_window_at(tm, 500, 400), visible)
        preview = self.drop_window(tm, regions, boss, 500, 400, 10)
        self.ae(preview.window_id, 20)
        boss._insert_window_in_direction.assert_called_once()
        self.assertIs(boss._insert_window_in_direction.call_args.args[1], visible)

    def test_whole_window_highlight_still_records_a_direction(self):
        central = region(0, 30, 1000, 800)
        g = region(5, 35, 995, 795)
        dest = self.make_window(20, g)
        src = self.make_window(10, g)
        tm, regions = self.make_tab_manager([dest], central, region(0, 0, 1000, 30), mode=DragOverlayMode.full)
        boss = self.make_boss(src, dest)
        for direction, (x, y) in self.edge_points(g).items():
            with self.subTest(direction=direction):
                boss._insert_window_in_direction.reset_mock()
                tm.window_being_dropped = None
                preview = self.drop_window(tm, regions, boss, x, y, 10)
                self.ae((preview.quadrant, preview.direction), (6, direction))
                boss._insert_window_in_direction.assert_called_once_with(src, dest, direction)

    def test_axis_layouts_restrict_the_direction(self):
        central = region(0, 30, 1000, 800)
        g = region(5, 35, 995, 795)
        dest = self.make_window(20, g)
        for mode, expected in (
            (DragOverlayMode.axis_x, {'left': 'left', 'right': 'right', 'top': 'left', 'bottom': 'right'}),
            (DragOverlayMode.axis_y, {'left': 'top', 'right': 'bottom', 'top': 'top', 'bottom': 'bottom'}),
        ):
            tm, _ = self.make_tab_manager([dest], central, region(0, 0, 1000, 30), mode=mode)
            for edge, (x, y) in self.edge_points(g).items():
                with self.subTest(mode=mode, edge=edge):
                    # the pointer is exactly centred on the off-axis, so ties resolve to the
                    # second half of the axis; only the on-axis edges are interesting
                    if edge in ('left', 'right') and mode is DragOverlayMode.axis_y:
                        continue
                    if edge in ('top', 'bottom') and mode is DragOverlayMode.axis_x:
                        continue
                    self.ae(TabManager._drop_direction_for(tm, dest, x, y), expected[edge])

    def test_title_bar_hover_targets_the_whole_window(self):
        central = region(0, 30, 1000, 800)
        g = region(5, 35, 995, 795)
        dest = self.make_window(20, g, show_title_bar=True, tab=object())
        src = self.make_window(10, g, tab=object())
        tm, regions = self.make_tab_manager([dest], central, region(0, 0, 1000, 30))
        tm.active_tab.id = 7
        boss = self.make_boss(src, dest)
        preview = self.drop_window(tm, regions, boss, 500, g.top + 5, 10)
        self.ae((preview.quadrant, preview.direction), (5, None))
        boss._move_window_to.assert_called_once_with(src, target_tab_id=7)
        boss._insert_window_in_direction.assert_not_called()


def make_tab(layout, windows):
    "A stand-in for Tab that uses the real window attaching implementation"
    tab = SimpleNamespace(id=2, os_window_id=1, current_layout=layout, windows=windows, mark_tab_bar_dirty=Mock(), relayout=Mock())
    tab._add_window = lambda window, overlay_for=None: layout.add_window(windows, window, overlay_for=overlay_for)
    for name in ('_take_ownership_of_window', 'attach_window', 'attach_window_at_edge', 'attach_windows'):
        setattr(tab, name, partial(getattr(Tab, name), tab))
    return tab


def new_window(win_id):
    w = Window(win_id)
    w.change_tab = Mock()
    return w


class TestWindowAttach(BaseTest):
    def test_attach_at_edge_preserves_split_weights_and_overlays(self):
        for horizontal in (True, False):
            for after in (True, False):
                with self.subTest(horizontal=horizontal, after=after):
                    layout = create_layout(Splits)
                    windows = create_windows(layout, num=0)
                    for wid in (1, 2, 3):
                        layout.add_window(windows, Window(wid), location='vsplit')
                    layout.pairs_root.unserialize({'bias': 0.2, 'one': 1, 'two': {'bias': 0.375, 'one': 2, 'two': 3}}, lambda x: x)
                    tab = make_tab(layout, windows)
                    pane, overlay = new_window(4), new_window(5)
                    with patch('kitty.tabs.attach_window') as native_attach:
                        tab.attach_windows((pane, overlay), next_to=windows.id_map[2], horizontal=horizontal, after=after)
                    self.ae(native_attach.call_count, 2, 'every window must be handed over to the tab natively')
                    for w in (pane, overlay):
                        w.change_tab.assert_called_once_with(tab)
                    root = layout.pairs_root
                    self.assertAlmostEqual(root.bias, 0.2)
                    self.assertAlmostEqual(root.two.bias, 0.375)
                    split = root.two.one
                    self.ae(split.horizontal, horizontal)
                    self.ae((split.one, split.two), (2, 4) if after else (4, 2))
                    self.assertAlmostEqual(split.bias, 0.5)
                    self.assertIs(windows.group_for_window(pane), windows.group_for_window(overlay))
                    self.assertIs(windows.active_window, overlay)

    def test_attach_at_edge_keeps_the_new_group_beside_its_target(self):
        # For layouts where group order is the layout, the new group must land next to the drop
        # target rather than being appended and then swapped with an unrelated group.
        for after in (True, False):
            with self.subTest(after=after):
                layout = create_layout(Stack)
                windows = create_windows(layout, num=3)
                tab = make_tab(layout, windows)
                target = windows.id_map[2]
                target_gid = windows.group_for_window(target).id
                others = [g.id for g in windows.groups if g.id != target_gid]
                pane = new_window(4)
                with patch('kitty.tabs.attach_window'):
                    tab.attach_windows((pane,), next_to=target, horizontal=True, after=after)
                order = [g.id for g in windows.groups]
                new_gid = windows.group_for_window(pane).id
                self.ae(abs(order.index(new_gid) - order.index(target_gid)), 1, f'new group is not beside its target: {order}')
                self.ae([gid for gid in order if gid not in (new_gid, target_gid)], others, 'an unrelated group was moved')

    def test_attach_without_a_target_is_unchanged(self):
        layout = create_layout(Tall)
        windows = create_windows(layout, num=2)
        tab = make_tab(layout, windows)
        pane, overlay = new_window(4), new_window(5)
        with patch('kitty.tabs.attach_window') as native_attach:
            tab.attach_windows((pane, overlay))
        self.ae(native_attach.call_count, 2)
        self.ae(len(windows.groups), 3)
        self.assertIs(windows.group_for_window(pane), windows.group_for_window(overlay))

    def test_cross_tab_directional_insert_uses_direct_attachment(self):
        source = SimpleNamespace(detach_window=Mock(return_value=('pane', 'overlay')))
        dest = SimpleNamespace(attach_windows=Mock(), make_active=Mock())
        pane = SimpleNamespace(tabref=lambda: source)
        target = SimpleNamespace(tabref=lambda: dest)
        boss = SimpleNamespace(suppress_focus_change_events=nullcontext, _cleanup_tab_after_window_removal=Mock())
        for direction, horizontal, after in (('left', True, False), ('right', True, True), ('top', False, False), ('bottom', False, True)):
            with self.subTest(direction=direction):
                Boss._insert_window_in_direction(boss, pane, target, direction)
                dest.attach_windows.assert_called_with(('pane', 'overlay'), next_to=target, horizontal=horizontal, after=after)
                boss._cleanup_tab_after_window_removal.assert_called_with(source)
                dest.make_active.assert_called_with()

    def test_same_tab_directional_insert_repositions_in_place(self):
        layout = create_layout(Splits)
        windows = create_windows(layout, num=0)
        for wid in (1, 2, 3):
            layout.add_window(windows, Window(wid), location='vsplit')
        tab = SimpleNamespace(current_layout=layout, windows=windows, relayout=Mock())
        window, dest_window = windows.id_map[3], windows.id_map[1]
        window.tabref = dest_window.tabref = lambda: tab
        boss = SimpleNamespace(suppress_focus_change_events=nullcontext)
        Boss._insert_window_in_direction(boss, window, dest_window, 'top')
        src_gid = windows.group_for_window(window).id
        pair = layout.pairs_root.pair_for_window(src_gid)
        self.ae(sorted(pair.all_window_ids()), sorted((src_gid, windows.group_for_window(dest_window).id)))
        self.assertFalse(pair.horizontal, "'top' must split along the vertical axis")
        self.ae(pair.one, src_gid, "'top' must put the moved window before its target")
        tab.relayout.assert_called_with()
