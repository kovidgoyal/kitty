#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal, <kovid at kovidgoyal.net>

import json
from math import ceil
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.layout.base import lgd
from kitty.rc.base import PayloadGetter
from kitty.rc.resize_window_edge import ResizeWindowEdge

from . import layout as geometry_tests


class TestResizeEntry(geometry_tests.BaseTest):
    def test_reenter_resize_reuses_existing_overlay(self):
        from kitty.boss import Boss
        resize = SimpleNamespace(is_resize_overlay=True)
        shell = SimpleNamespace(is_resize_overlay=False)
        # Another overlay can temporarily cover the resize UI.
        group = SimpleNamespace(windows=[shell, resize, shell])
        tab = SimpleNamespace(windows=SimpleNamespace(group_for_window=lambda w: group), set_active_window=Mock())
        window = SimpleNamespace(tabref=lambda: tab)
        boss = SimpleNamespace(active_window=window, active_tab=tab)
        with patch('kittens.runner.create_kitten_handler', side_effect=AssertionError('Created another resize UI')):
            for name in ('resize_window', 'resize-window'):
                self.assertIs(Boss.run_kitten_with_metadata(boss, name, args=['--strategy=edge']), resize)
                self.assertIs(Boss.run_kitten_with_metadata(boss, name, window=window), resize)
        self.ae(tab.set_active_window.call_count, 4)
        tab.set_active_window.assert_called_with(resize)

    def test_resize_reentry_is_scoped_to_kitten_and_pane(self):
        from kitty.boss import Boss
        shell = SimpleNamespace(is_resize_overlay=False)
        resize = SimpleNamespace(is_resize_overlay=True)
        group = SimpleNamespace(windows=[shell])
        tab = SimpleNamespace(windows=SimpleNamespace(group_for_window=lambda w: group), set_active_window=Mock())
        window = SimpleNamespace(tabref=lambda: tab)
        boss = SimpleNamespace(active_window=window, active_tab=tab)
        with patch('kittens.runner.create_kitten_handler', side_effect=AssertionError('Normal launch')):
            with self.assertRaisesRegex(AssertionError, 'Normal launch'):
                Boss.run_kitten_with_metadata(boss, 'resize_window')
            group.windows.append(resize)
            with self.assertRaisesRegex(AssertionError, 'Normal launch'):
                Boss.run_kitten_with_metadata(boss, 'hints')
        tab.set_active_window.assert_not_called()


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
        for fraction in (-1, 1.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.command(cmd, tab, 1, 'move', edge='bottom', fraction=fraction)
