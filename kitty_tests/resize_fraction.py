#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from copy import deepcopy
from math import ceil
from types import SimpleNamespace

from kitty.fast_data_types import Region
from kitty.layout.base import lgd
from kitty.layout.interface import Fat, Grid, Horizontal, Stack, Tall, Vertical
from kitty.rc.base import PayloadGetter
from kitty.rc.resize_window import resize_window
from kitty.tabs import Tab

from . import layout as geometry_tests


class TestFractionalResize(geometry_tests.BaseSplitGeometryTest):
    make_layout = geometry_tests.TestSplitDragGeometry.make_layout

    def resize(self, tab, window_id, increment, horizontal, fraction=1 / 3):
        return Tab.resize_window_by(tab, window_id, increment, horizontal, fraction) is None

    def test_fractional_splits_steps(self):
        for horizontal in (True, False):
            for window_id in (1, 2):
                for increment in (-2, 2):
                    for remaining in (0, 1, 2, 3, 4, 5, 6, 10):
                        with self.subTest(axis=horizontal, window=window_id, increment=increment, remaining=remaining):
                            layout, windows, tab = self.make_layout({'horizontal': horizontal, 'one': 1, 'two': 2}, num=2)
                            pair = layout.pairs_root
                            size = pair.width if horizontal else pair.height
                            cell = lgd.cell_width if horizontal else lgd.cell_height
                            low = (cell + pair.border_width + 0.5) / size
                            high = (size - cell - pair.border_width + 0.5) / size
                            delta = layout.bias_increment_for_cell(windows, horizontal) * increment * (1 if window_id == 1 else -1)
                            pair.bias = (high if delta > 0 else low) - remaining * delta
                            tab.relayout()
                            before = pair.bias
                            self.ae(self.resize(tab, window_id, increment, horizontal), bool(remaining))
                            self.assertAlmostEqual(pair.bias, before + delta * ((remaining + 2) // 3))
                            self.check_extents_fit(layout)
                            while self.resize(tab, window_id, increment, horizontal):
                                self.check_extents_fit(layout)
                            at_limit = pair.bias
                            for _ in range(3):
                                self.assertFalse(self.resize(tab, window_id, increment, horizontal))
                                self.ae(pair.bias, at_limit)
                            self.assertTrue(self.resize(tab, window_id, -increment, horizontal))
                            self.check_extents_fit(layout)

    def test_fractional_splits_partial_step_and_options(self):
        for fraction in (1 / 4, 1 / 3, 1 / 2, 1):
            for increment in (-2, 2):
                layout, windows, tab = self.make_layout({'one': 1, 'two': 2}, num=2)
                pair = layout.pairs_root
                delta = layout.bias_increment_for_cell(windows, True) * increment
                limit = (
                    (pair.width - lgd.cell_width - pair.border_width + 0.5) / pair.width
                    if delta > 0
                    else (lgd.cell_width + pair.border_width + 0.5) / pair.width
                )
                pair.bias = limit - 9.75 * delta
                tab.relayout()
                before = pair.bias
                self.assertTrue(self.resize(tab, 1, increment, True, fraction))
                expected = before + ceil(10 * fraction) * delta
                self.assertAlmostEqual(pair.bias, min(expected, limit) if delta > 0 else max(expected, limit))
                pair.bias = limit - 0.25 * delta
                tab.relayout()
                self.assertTrue(self.resize(tab, 1, increment, True, fraction))
                self.assertAlmostEqual(pair.bias, limit)
                self.assertFalse(self.resize(tab, 1, increment, True, fraction))
                self.check_extents_fit(layout)

    def test_fractional_splits_nested_and_saturated(self):
        shape = {'one': 1, 'two': {'horizontal': False, 'one': 2, 'two': {'one': 3, 'two': 4}}}
        for minimal in (True, False):
            for increment in (-2, 2):
                layout, _windows, tab = self.make_layout(shape, minimal)
                pair = layout.pairs_root
                others = {id(p): p.bias for p in pair.self_and_descendants() if p is not pair}
                pair.bias = 0 if increment > 0 else 1
                tab.relayout()
                self.assertTrue(self.resize(tab, 2, -increment, True))
                self.assertGreater(pair.bias, 0.1)
                self.assertLess(pair.bias, 0.9)
                self.ae({id(p): p.bias for p in pair.self_and_descendants() if p is not pair}, others)
                self.check_extents_fit(layout)

    def other_layout(self, cls, num, opts=''):
        layout = geometry_tests.create_layout(cls)
        if opts:
            layout.layout_opts = layout.parse_layout_opts(opts)
            layout.remove_all_biases()
        windows = geometry_tests.create_windows(layout, num)
        self.stub_dimensions(layout, Region((0, 0, 1499, 1099, 1500, 1100)))
        layout(windows)
        return layout, windows

    def test_fractional_all_layouts(self):
        # Compare with actual ordinary resizing and rendered geometries. This
        # catches incorrect counts and accidental mutation during the probe.
        for cls in (Tall, Fat, Grid, Vertical, Horizontal):
            for num in (2, 5):
                for horizontal in (True, False):
                    for increment in (-2, 2):
                        for window_id in (1, num):
                            with self.subTest(layout=cls.name, windows=num, axis=horizontal, increment=increment, window=window_id):
                                reference, ref_windows = self.other_layout(cls, num)
                                step = reference.bias_increment_for_cell(ref_windows, horizontal) * increment
                                states = []
                                for _ in range(500):
                                    before = tuple(w.geometry for w in ref_windows)
                                    if not reference.modify_size_of_window(ref_windows, window_id, step, horizontal):
                                        break
                                    reference(ref_windows)
                                    if tuple(w.geometry for w in ref_windows) == before:
                                        break
                                    states.append(deepcopy(reference.layout_state()))
                                else:
                                    self.fail('Ordinary resizing did not stop')
                                layout, windows = self.other_layout(cls, num)
                                before = deepcopy(layout.layout_state())
                                changed = layout.modify_size_of_window_by_fraction(windows, window_id, step, horizontal, 1 / 3)
                                self.ae(changed, bool(states))
                                self.ae(layout.layout_state(), states[(len(states) + 2) // 3 - 1] if states else before)

    def test_fractional_tall_full_size_and_mirrored(self):
        for cls in (Tall, Fat):
            for opts in ('full_size=2', 'full_size=3;mirrored=yes'):
                for window_id in (1, 5):
                    layout, windows = self.other_layout(cls, 5, opts)
                    step = layout.bias_increment_for_cell(windows, cls.main_is_horizontal) * 2
                    self.assertTrue(layout.modify_size_of_window_by_fraction(windows, window_id, step, cls.main_is_horizontal, 1 / 3))
                    layout(windows)
                    self.assertTrue(all(w.geometry.xnum > 0 and w.geometry.ynum > 0 for w in windows))

    def test_fractional_unavailable_and_invalid(self):
        for cls in (Stack, Tall, Fat, Grid, Vertical, Horizontal):
            layout, windows = self.other_layout(cls, 1)
            before = deepcopy(layout.layout_state())
            self.assertFalse(layout.modify_size_of_window_by_fraction(windows, 1, 0.1, True, 1 / 3))
            self.ae(layout.layout_state(), before)
        layout, windows, tab = self.make_layout({'one': 1, 'two': 2}, num=2)
        for window_id, increment, horizontal in ((999, 2, True), (1, 0, True), (1, 2, False)):
            self.assertFalse(self.resize(tab, window_id, increment, horizontal))
        for fraction in (0, -1, 1.1, float('nan'), float('inf')):
            self.assertFalse(layout.modify_size_of_window_by_fraction(windows, 1, 0.1, True, fraction))

    def test_fractional_remote_validation_and_compatibility(self):
        calls = []
        boss = SimpleNamespace(resize_layout_window=lambda *a, **kw: calls.append(kw))
        window = SimpleNamespace(id=1)
        original = resize_window.windows_for_match_payload
        resize_window.windows_for_match_payload = lambda *a: [window]
        self.addCleanup(lambda: setattr(resize_window, 'windows_for_match_payload', original))
        for fraction in (None, 0, 1 / 3, 1):
            payload = {'increment': 2, 'axis': 'horizontal'}
            if fraction is not None:
                payload['fraction'] = fraction
            resize_window.response_from_kitty(boss, window, PayloadGetter(resize_window, payload))
            self.ae(calls[-1]['fraction'], fraction or 0)
        for fraction in (-1, 1.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                resize_window.response_from_kitty(boss, window, PayloadGetter(resize_window, {'fraction': fraction}))
