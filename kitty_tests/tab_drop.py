#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.boss import Boss
from kitty.layout.splits import Splits
from kitty.tabs import Tab

from .base import BaseTest
from .layout import Window, create_layout, create_windows


class TestTabDrop(BaseTest):
    def setUp(self):
        super().setUp()
        self.source = SimpleNamespace(id=1, os_window_id=1, windows=SimpleNamespace(num_groups=1), active_window=SimpleNamespace(id=10))
        self.destination = SimpleNamespace(id=2)
        self.tm = SimpleNamespace(
            os_window_id=1,
            active_tab=self.destination,
            on_tab_drop_move=Mock(),
            on_window_drop_move=Mock(),
            on_window_drop=Mock(),
            on_tab_drop=Mock(),
            layout_tab_bar=Mock(),
            tab_being_dropped=None,
            window_being_dropped=None,
        )
        self.boss = SimpleNamespace(
            os_window_map={1: self.tm},
            all_tab_managers=[self.tm],
            tab_for_id=lambda tid: self.source if tid == 1 else None,
            _move_tab_to=Mock(),
            _move_window_to=Mock(),
            _insert_window_in_direction=Mock(),
            window_id_map={},
        )
        self.data = {f'application/net.kovidgoyal.kitty-tab-{os.getpid()}': b'1'}
        self.region = SimpleNamespace(left=0, right=1000, top=30, bottom=1000)
        bar = SimpleNamespace(left=0, right=1000, top=0, bottom=30)
        for name, value in (
            ('viewport_for_window', Mock(return_value=(self.region, bar))),
            ('get_tab_being_dragged', Mock(return_value=(1, True))),
            ('get_window_being_dragged', Mock(return_value=(0, False))),
            ('set_tab_being_dragged', Mock()),
            ('change_drag_thumbnail', Mock()),
        ):
            patcher = patch('kitty.boss.' + name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name, value)

    def test_single_window_tab_preview_and_drop(self):
        Boss.on_drop_move(self.boss, 1, 600, 400, True, False)
        self.tm.on_window_drop_move.assert_called_with(10, True, 600, 400)
        self.tm.on_tab_drop_move.assert_called_with(1, False, 600, 400)
        Boss.on_drop(self.boss, 1, self.data, True, 600, 400)
        self.tm.on_window_drop.assert_called_once_with(600, 400, 10)
        self.boss._move_tab_to.assert_not_called()
        self.tm.on_window_drop_move.assert_called_with()
        self.set_tab_being_dragged.assert_called_once_with()

    def test_single_window_tab_cross_os_window(self):
        self.source.os_window_id = 9
        Boss.on_drop_move(self.boss, 1, 600, 400, True, False)
        self.tm.on_window_drop_move.assert_called_with(10, True, 600, 400)
        Boss.on_drop(self.boss, 1, self.data, True, 600, 400)
        self.tm.on_window_drop.assert_called_once_with(600, 400, 10)
        self.tm.on_tab_drop.assert_not_called()

    def test_tab_bar_drop_keeps_tab_behavior(self):
        Boss.on_drop_move(self.boss, 1, 600, 10, True, False)
        self.tm.on_window_drop_move.assert_called_with(0, False, 600, 10)
        self.tm.on_tab_drop_move.assert_called_with(1, True, 600, 10)
        Boss.on_drop(self.boss, 1, self.data, True, 600, 10)
        self.tm.on_tab_drop.assert_called_once_with(600, 10)
        self.tm.on_window_drop.assert_not_called()

    def test_multi_window_tab_keeps_tab_behavior(self):
        self.source.windows.num_groups = 2
        Boss.on_drop_move(self.boss, 1, 600, 400, True, False)
        self.tm.on_window_drop_move.assert_called_with(0, False, 600, 400)
        Boss.on_drop(self.boss, 1, self.data, True, 600, 400)
        self.boss._move_tab_to.assert_called_once_with(self.source)
        self.tm.on_window_drop.assert_not_called()
        self.source.os_window_id = 9
        Boss.on_drop(self.boss, 1, self.data, True, 600, 400)
        self.tm.on_tab_drop.assert_called_once_with(600, 400)

    def test_tab_drop_into_self_keeps_tab_behavior(self):
        self.tm.active_tab = self.source
        Boss.on_drop_move(self.boss, 1, 600, 400, True, False)
        self.tm.on_window_drop_move.assert_called_with(0, False, 600, 400)
        Boss.on_drop(self.boss, 1, self.data, True, 600, 400)
        self.boss._move_tab_to.assert_called_once_with(self.source)
        self.tm.on_window_drop.assert_not_called()

    def test_leaving_clears_window_preview(self):
        Boss.on_drop_move(self.boss, 1, 600, 400, True, True)
        self.tm.on_window_drop_move.assert_called_with(0, False, 600, 400)
        self.tm.on_tab_drop_move.assert_called_with(1, False, 600, 400)

    def test_cancel_clears_preview_without_detaching(self):
        for reported_drop in (True, False):
            Boss.on_drag_source_finished(self.boss, reported_drop, True, '', 0, self.data, True)
            self.tm.on_window_drop_move.assert_called_with()
            self.boss._move_tab_to.assert_not_called()
            self.boss._insert_window_in_direction.assert_not_called()

    def test_wayland_finish_uses_pending_window_target(self):
        target = SimpleNamespace(id=20, tab_id=2)
        self.boss.window_id_map[20] = target
        for quadrant, direction in enumerate(('left', 'right', 'top', 'bottom'), 1):
            self.tm.window_being_dropped = SimpleNamespace(window_id=20, quadrant=quadrant)
            Boss.on_drag_source_finished(self.boss, True, False, '', 0, self.data, True)
            self.boss._insert_window_in_direction.assert_called_with(self.source.active_window, target, direction)
            self.tm.on_window_drop_move.assert_called_with()
            self.boss._move_tab_to.assert_not_called()
        self.tm.window_being_dropped.quadrant = 5
        Boss.on_drag_source_finished(self.boss, True, False, '', 0, self.data, True)
        self.boss._move_window_to.assert_called_once_with(self.source.active_window, target_tab_id=2)

    def test_completed_drop_is_not_detached_again(self):
        self.get_tab_being_dragged.return_value = (0, False)
        Boss.on_drag_source_finished(self.boss, True, False, '', 0, self.data, True)
        self.boss._move_tab_to.assert_not_called()

    def test_directional_attach_preserves_other_split_weights_and_overlays(self):
        for horizontal in (True, False):
            for after in (True, False):
                with self.subTest(horizontal=horizontal, after=after):
                    layout = create_layout(Splits)
                    windows = create_windows(layout, num=0)
                    for wid in (1, 2, 3):
                        layout.add_window(windows, Window(wid), location='vsplit')
                    layout.pairs_root.unserialize({'bias': 0.2, 'one': 1, 'two': {'bias': 0.375, 'one': 2, 'two': 3}}, lambda x: x)
                    tab = SimpleNamespace(id=2, os_window_id=1, current_layout=layout, windows=windows, mark_tab_bar_dirty=Mock(), relayout=Mock())
                    pane, overlay = Window(4), Window(5)
                    for window in (pane, overlay):
                        window.change_tab = Mock()
                    tab._add_window = lambda window, overlay_for: layout.add_window(windows, window, overlay_for=overlay_for)
                    tab.attach_window = lambda window, overlay_for: Tab.attach_window(tab, window, overlay_for)
                    with patch('kitty.tabs.attach_window') as native_attach:
                        Tab.attach_windows(tab, (pane, overlay), next_to=windows.id_map[2], horizontal=horizontal, after=after)
                    self.ae(native_attach.call_count, 2)
                    root = layout.pairs_root
                    self.assertAlmostEqual(root.bias, 0.2)
                    self.assertAlmostEqual(root.two.bias, 0.375)
                    split = root.two.one
                    self.ae(split.horizontal, horizontal)
                    self.ae((split.one, split.two), (2, 4) if after else (4, 2))
                    self.assertAlmostEqual(split.bias, 0.5)
                    self.assertIs(windows.group_for_window(pane), windows.group_for_window(overlay))

    def test_cross_tab_directional_insert_uses_direct_attachment(self):
        source = SimpleNamespace(detach_window=Mock(return_value=('pane', 'overlay')))
        dest = SimpleNamespace(attach_windows=Mock(), make_active=Mock())
        pane = SimpleNamespace(tabref=lambda: source)
        target = SimpleNamespace(tabref=lambda: dest)
        boss = SimpleNamespace(suppress_focus_change_events=nullcontext, _cleanup_tab_after_window_removal=Mock())
        for direction, horizontal, after in (('left', True, False), ('right', True, True), ('top', False, False), ('bottom', False, True)):
            Boss._insert_window_in_direction(boss, pane, target, direction)
            dest.attach_windows.assert_called_with(('pane', 'overlay'), next_to=target, horizontal=horizontal, after=after)
            boss._cleanup_tab_after_window_removal.assert_called_with(source)
            dest.make_active.assert_called_with()
