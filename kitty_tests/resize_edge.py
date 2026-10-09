#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

import json
from math import ceil
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.layout.base import lgd
from kitty.rc.base import PayloadGetter
from kitty.rc.resize_window import resize_window
from kitty.rc.resize_window_edge import ResizeWindowEdge

from . import layout as geometry_tests


class TestResizeEntry(geometry_tests.BaseTest):
    def test_reenter_resize_replaces_existing_overlay(self):
        from kitty.boss import Boss

        launched = []

        def create_kitten_handler(kitten, args):
            launched.append(args)
            raise AssertionError('Launched')

        for name in ('resize_window', 'resize-window'):
            cmd = ResizeWindowEdge()
            base = Mock(is_resize_overlay=False)
            resize = Mock(is_resize_overlay=True)
            # Another overlay can temporarily cover the resize UI.
            other = Mock(is_resize_overlay=False)
            group = SimpleNamespace(windows=[base, resize, other])
            tab = SimpleNamespace(windows=SimpleNamespace(group_for_window=lambda w: group), set_active_window=Mock())
            base.tabref = other.tabref = lambda: tab
            session = cmd.start_session(resize, None)
            boss = SimpleNamespace(active_window=other, active_tab=tab, mark_window_for_close=Mock())
            with patch('kitty.rc.resize_window_edge.resize_window_edge', cmd), patch('kittens.runner.create_kitten_handler', create_kitten_handler):
                with self.assertRaisesRegex(AssertionError, 'Launched'):
                    Boss.run_kitten_with_metadata(boss, name, args=['--strategy=edge'])
            # The new options are used, the old UI is closed and its snapshot is handed over
            self.ae(launched.pop(), ['--strategy=edge'])
            boss.mark_window_for_close.assert_called_once_with(resize)
            self.assertNotIn(resize, cmd.sessions)
            new_overlay = Mock()
            self.assertIs(cmd.start_session(new_overlay, None, session), session)
            self.assertIs(cmd.sessions[new_overlay], session)
            tab.set_active_window.assert_not_called()

    def test_resize_reentry_is_scoped_to_kitten_and_pane(self):
        from kitty.boss import Boss

        shell = SimpleNamespace(is_resize_overlay=False)
        resize = SimpleNamespace(is_resize_overlay=True)
        group = SimpleNamespace(windows=[shell])
        tab = SimpleNamespace(windows=SimpleNamespace(group_for_window=lambda w: group), set_active_window=Mock())
        window = SimpleNamespace(tabref=lambda: tab)
        boss = SimpleNamespace(active_window=window, active_tab=tab, mark_window_for_close=Mock())
        with patch('kittens.runner.create_kitten_handler', side_effect=AssertionError('Normal launch')):
            with self.assertRaisesRegex(AssertionError, 'Normal launch'):
                Boss.run_kitten_with_metadata(boss, 'resize_window')
            group.windows.append(resize)
            with self.assertRaisesRegex(AssertionError, 'Normal launch'):
                Boss.run_kitten_with_metadata(boss, 'hints')
        tab.set_active_window.assert_not_called()
        boss.mark_window_for_close.assert_not_called()


class TestEdgeResize(geometry_tests.BaseSplitGeometryTest):
    make_layout = geometry_tests.TestSplitDragGeometry.make_layout
    positions = geometry_tests.TestSplitDragGeometry.positions
    fixed_dividers = geometry_tests.TestSplitDragGeometry.fixed_dividers

    def resize(self, tab, window_id, edge, increment, fraction=0):
        changed = tab.current_layout.modify_size_of_window_edge(tab.windows, window_id, edge, increment, fraction)
        if changed:
            tab.relayout()
        return changed

    def test_nested_edge_selection(self):
        shape = {'one': 1, 'two': {'one': 2, 'two': {'one': 3, 'two': 4}}}
        layout, windows, tab = self.make_layout(shape)
        expected = {1: {'right'}, 2: {'left', 'right'}, 3: {'left', 'right'}, 4: {'left'}}
        before = self.positions(layout)
        for window_id, edges in expected.items():
            found = {edge for edge in ('left', 'right', 'top', 'bottom') if layout.pair_for_window_edge(windows, window_id, edge)}
            self.ae(found, edges)
        self.assertIs(layout.pair_for_window_edge(windows, 2, 'left'), layout.pairs_root)
        self.assertIs(layout.pair_for_window_edge(windows, 2, 'right'), layout.pairs_root.two)
        self.assertIs(layout.pair_for_window_edge(windows, 3, 'left'), layout.pairs_root.two)
        self.assertIsNone(layout.pair_for_window_edge(windows, 999, 'left'))
        self.ae(self.positions(layout), before)
        shape = {'one': {'horizontal': False, 'one': 1, 'two': 2}, 'two': {'horizontal': False, 'one': 3, 'two': 4}}
        layout, windows, tab = self.make_layout(shape)
        for window_id, expected in ((1, {'right', 'bottom'}), (2, {'right', 'top'}), (3, {'left', 'bottom'}), (4, {'left', 'top'})):
            self.ae({edge for edge in ('left', 'right', 'top', 'bottom') if layout.pair_for_window_edge(windows, window_id, edge)}, expected)

    def test_only_selected_same_axis_divider_moves(self):
        shapes = (
            {'one': 1, 'two': {'one': 2, 'two': {'one': 3, 'two': 4}}},
            {'one': {'one': 1, 'two': 2}, 'two': {'one': 3, 'two': 4}},
            {'one': 1, 'two': {'one': {'horizontal': False, 'one': 2, 'two': 3}, 'two': 4}},
            {'horizontal': False, 'one': 1, 'two': {'horizontal': False, 'one': 2, 'two': {'horizontal': False, 'one': 3, 'two': 4}}},
        )
        for shape in shapes:
            for minimal in (True, False):
                layout, windows, tab = self.make_layout(shape, minimal)
                for window_id in (1, 2, 3, 4):
                    for edge in ('left', 'right', 'top', 'bottom'):
                        pair = layout.pair_for_window_edge(windows, window_id, edge)
                        if pair is None:
                            continue
                        fixed = self.fixed_dividers(pair)
                        cell = lgd.cell_width if pair.horizontal else lgd.cell_height
                        for increment in (2, -2):
                            before = self.positions(layout)
                            self.assertTrue(self.resize(tab, window_id, edge, increment))
                            after = self.positions(layout)
                            self.ae(after[id(pair)] - before[id(pair)], increment * cell)
                            for pid, position in before.items():
                                if pid != id(pair) and fixed(pid):
                                    self.ae(after[pid], position)
                            self.check_extents_fit(layout)

    def test_fractional_steps_limits_and_custom_fraction(self):
        for horizontal in (True, False):
            for window_id in (1, 2):
                for sign in (-1, 1):
                    for remaining in (0, 1, 2, 3, 4, 5, 6, 10):
                        for fraction in (1 / 3, 1 / 4, 1 / 2, 1):
                            layout, windows, tab = self.make_layout({'horizontal': horizontal, 'one': 1, 'two': 2}, num=2)
                            pair = layout.pairs_root
                            edge = ('right' if window_id == 1 else 'left') if horizontal else ('bottom' if window_id == 1 else 'top')
                            step = 2 * (lgd.cell_width if horizontal else lgd.cell_height)
                            pair.move_divider(sign * (pair.width if horizontal else pair.height))
                            tab.relayout()
                            pair.move_divider(-sign * step * remaining)
                            tab.relayout()
                            before = self.positions(layout)[id(pair)]
                            self.ae(self.resize(tab, window_id, edge, sign * 2, fraction), bool(remaining))
                            self.ae(self.positions(layout)[id(pair)] - before, sign * step * ceil(remaining * fraction - 1e-9))
                            while self.resize(tab, window_id, edge, sign * 2, fraction):
                                self.check_extents_fit(layout)
                            before = self.positions(layout)
                            self.assertFalse(self.resize(tab, window_id, edge, sign * 2, fraction))
                            self.ae(self.positions(layout), before)
                            self.assertTrue(self.resize(tab, window_id, edge, -sign * 2, fraction))
                            self.check_extents_fit(layout)

    def test_partial_step_and_invalid_requests(self):
        layout, windows, tab = self.make_layout({'one': 1, 'two': 2}, num=2)
        pair = layout.pairs_root
        pair.move_divider(pair.width)
        tab.relayout()
        partial = lgd.cell_width - 1
        pair.move_divider(-partial)
        tab.relayout()
        before = self.positions(layout)
        self.assertTrue(self.resize(tab, 1, 'right', 2, 0.25))
        self.ae(self.positions(layout)[id(pair)] - before[id(pair)], partial)
        for edge, window_id, increment, fraction in (
            ('left', 1, 2, 0),
            ('right', 999, 2, 0),
            ('right', 1, 0, 0),
            ('right', 1, 2, -1),
            ('right', 1, 2, float('nan')),
        ):
            before = self.positions(layout)
            self.assertFalse(self.resize(tab, window_id, edge, increment, fraction))
            self.ae(self.positions(layout), before)

    def command(self, cmd, tab, window_id, operation, **payload):
        window = tab.windows.id_map[window_id]
        window.tabref = lambda: tab
        boss = SimpleNamespace(active_window=window)
        return json.loads(cmd.response_from_kitty(boss, window, PayloadGetter(cmd, {'self': True, 'operation': operation, **payload})))

    def test_session_reset_restores_entry_geometry(self):
        layout, windows, tab = self.make_layout({'bias': 0.3, 'one': 1, 'two': {'bias': 0.4, 'one': 2, 'two': 3}}, num=3)
        cmd = ResizeWindowEdge()
        before = self.positions(layout)
        self.command(cmd, tab, 2, 'start')
        for edge, increment in (('left', 3), ('right', -2)):
            selected = self.command(cmd, tab, 2, 'select', edge=edge)
            self.ae(selected['selected'], edge)
            self.command(cmd, tab, 2, 'move', edge=edge, increment=increment, divider=selected['divider'])
        self.assertNotEqual(self.positions(layout), before)
        restored = self.command(cmd, tab, 2, 'reset')
        self.ae(self.positions(layout), before)
        self.ae(restored['selected'], '')
        self.assertIn('Restored', restored['status'])
        self.ae(layout.pairs_root.bias, 0.3)
        self.ae(layout.pairs_root.two.bias, 0.4)
        self.command(cmd, tab, 2, 'reset')
        self.ae(self.positions(layout), before)

    def test_entry_selection_and_snapshot_survive_strategy_activation(self):
        for horizontal in (True, False):
            layout, windows, tab = self.make_layout({'horizontal': horizontal, 'bias': 0.3, 'one': 1, 'two': 2}, num=2)
            cmd = ResizeWindowEdge()
            before = self.positions(layout)
            # Boss takes the snapshot before either strategy has resized anything.
            cmd.start_session(windows.id_map[1], layout)
            layout.pairs_root.bias = 0.6
            tab.relayout()
            started = self.command(cmd, tab, 1, 'start')
            self.ae(started['selected'], 'right' if horizontal else 'bottom')
            self.assertTrue(started['divider'])
            self.command(cmd, tab, 1, 'start')
            self.command(cmd, tab, 1, 'reset')
            self.ae(self.positions(layout), before)
        layout, windows, tab = self.make_layout({'one': 1, 'two': {'one': 2, 'two': 3}}, num=3)
        started = self.command(ResizeWindowEdge(), tab, 2, 'start')
        self.ae(started['edges'], ['left', 'right'])
        self.ae(started['selected'], '')

    def test_no_internal_edge_and_unsupported_layout(self):
        layout, windows, tab = self.make_layout({'one': 1}, num=1)
        cmd = ResizeWindowEdge()
        before = self.positions(layout)
        started = self.command(cmd, tab, 1, 'start')
        self.ae(started['edges'], [])
        self.ae(started['selected'], '')
        self.command(cmd, tab, 1, 'move', edge='right', increment=2)
        self.ae(self.positions(layout), before)
        tab.current_layout = geometry_tests.create_layout(geometry_tests.Tall)
        unavailable = self.command(cmd, tab, 1, 'start')
        self.ae(unavailable['edges'], [])
        self.assertIn('requires the Splits layout', unavailable['status'])

    def test_session_selection_stale_identity_and_structure_change(self):
        layout, windows, tab = self.make_layout({'one': 1, 'two': 2}, num=2)
        cmd = ResizeWindowEdge()
        before = self.positions(layout)
        self.command(cmd, tab, 1, 'start')
        outside = self.command(cmd, tab, 1, 'select', edge='left')
        self.ae(outside['selected'], '')
        selected = self.command(cmd, tab, 1, 'select', edge='right')
        self.ae(selected['selected'], 'right')
        self.ae(self.positions(layout), before)
        stale = self.command(cmd, tab, 1, 'move', edge='right', divider='invalid', increment=2)
        self.ae(stale['selected'], '')
        self.ae(self.positions(layout), before)
        layout.pairs_root.horizontal = False
        tab.relayout()
        changed = self.positions(layout)
        refused = self.command(cmd, tab, 1, 'reset')
        self.assertIn('structure changed', refused['status'])
        self.ae(self.positions(layout), changed)

    def test_window_reset_restores_same_entry_snapshot(self):
        layout, windows, tab = self.make_layout({'bias': 0.31, 'one': 1, 'two': {'bias': 0.43, 'one': 2, 'two': 3}}, num=3)
        window = windows.id_map[2]
        window.tabref = lambda: tab
        cmd = ResizeWindowEdge()
        cmd.start_session(window, layout)
        before = self.positions(layout)
        boss = SimpleNamespace(active_window=window, resize_layout_window=Mock())
        payload = PayloadGetter(resize_window, {'self': True, 'axis': 'reset', 'restore_entry_layout': True})
        with patch('kitty.rc.resize_window_edge.resize_window_edge', cmd):
            self.assertTrue(self.resize(tab, 2, 'left', 3))
            self.assertTrue(self.resize(tab, 2, 'right', -2))
            self.assertIsNone(resize_window.response_from_kitty(boss, window, payload))
            self.ae(self.positions(layout), before)
            boss.resize_layout_window.assert_not_called()
            layout.pairs_root.horizontal = False
            tab.relayout()
            changed = self.positions(layout)
            result = resize_window.response_from_kitty(boss, window, payload)
            self.assertIn('structure changed', result)
            self.ae(self.positions(layout), changed)

    def test_reset_after_leaving_entry_layout_uses_default_reset(self):
        layout, windows, tab = self.make_layout({'bias': 0.3, 'one': 1, 'two': 2}, num=2)
        window = windows.id_map[1]
        window.tabref = lambda: tab
        cmd = ResizeWindowEdge()
        cmd.start_session(window, layout)
        boss = SimpleNamespace(active_window=window, resize_layout_window=Mock(return_value=None))
        payload = PayloadGetter(resize_window, {'self': True, 'axis': 'reset', 'increment': 2, 'restore_entry_layout': True})
        with patch('kitty.rc.resize_window_edge.resize_window_edge', cmd):
            tab.current_layout = geometry_tests.create_layout(geometry_tests.Tall)
            self.assertIsNone(resize_window.response_from_kitty(boss, window, payload))
            self.assertTrue(boss.resize_layout_window.call_args.kwargs['reset'])
            # Returning to the entry layout restores its snapshot again
            tab.current_layout = layout
            layout.pairs_root.bias = 0.6
            boss.resize_layout_window.reset_mock()
            self.assertIsNone(resize_window.response_from_kitty(boss, window, payload))
            boss.resize_layout_window.assert_not_called()
            self.ae(layout.pairs_root.bias, 0.3)

    def test_no_snapshot_when_entered_in_other_layout(self):
        layout, windows, tab = self.make_layout({'bias': 0.3, 'one': 1, 'two': 2}, num=2)
        window = windows.id_map[1]
        window.tabref = lambda: tab
        tab.reset_window_sizes = Mock()
        cmd = ResizeWindowEdge()
        cmd.start_session(window, geometry_tests.create_layout(geometry_tests.Tall))
        layout.pairs_root.bias = 0.6
        started = self.command(cmd, tab, 1, 'start')
        self.assertTrue(started['divider'])
        moved = self.command(cmd, tab, 1, 'move', edge='right', increment=2, divider=started['divider'])
        self.ae(moved['status'], '')
        self.assertFalse(moved['failed'])
        # Sizes changed after entry must not be treated as the original sizes
        reset = self.command(cmd, tab, 1, 'reset')
        tab.reset_window_sizes.assert_called_once_with()
        self.assertNotIn('Restored', reset['status'])
        self.assertFalse(reset['failed'])

    def test_failure_flag(self):
        layout, windows, tab = self.make_layout({'one': 1, 'two': 2}, num=2)
        cmd = ResizeWindowEdge()
        self.command(cmd, tab, 1, 'start')
        self.assertTrue(self.command(cmd, tab, 1, 'select', edge='left')['failed'])
        selected = self.command(cmd, tab, 1, 'select', edge='right')
        self.assertFalse(selected['failed'])
        while not (moved := self.command(cmd, tab, 1, 'move', edge='right', increment=2, divider=selected['divider']))['failed']:
            pass
        self.assertIn('size limit', moved['status'])
        restored = self.command(cmd, tab, 1, 'reset')
        self.assertIn('Restored', restored['status'])
        self.assertFalse(restored['failed'])

    def test_window_reset_without_session_keeps_default_behavior(self):
        layout, windows, tab = self.make_layout({'one': 1, 'two': 2}, num=2)
        window = windows.id_map[1]
        window.tabref = lambda: tab
        boss = SimpleNamespace(active_window=window, resize_layout_window=Mock(return_value=None))
        cmd = ResizeWindowEdge()
        with patch('kitty.rc.resize_window_edge.resize_window_edge', cmd):
            for restore in (False, True):
                payload = PayloadGetter(resize_window, {'self': True, 'axis': 'reset', 'increment': 2, 'restore_entry_layout': restore})
                self.assertIsNone(resize_window.response_from_kitty(boss, window, payload))
                self.assertTrue(boss.resize_layout_window.call_args.kwargs['reset'])
            cmd.start_session(window, layout)
            before = boss.resize_layout_window.call_count
            # An ordinary remote-control reset always retains default-size reset.
            payload = PayloadGetter(resize_window, {'self': True, 'axis': 'reset', 'increment': 2})
            resize_window.response_from_kitty(boss, window, payload)
            self.ae(boss.resize_layout_window.call_count, before + 1)
        for fraction in (-1, 1.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.command(cmd, tab, 1, 'move', edge='bottom', fraction=fraction)
