#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from itertools import repeat
from typing import Dict, Generator, List, Tuple

from kitty.typing import EdgeLiteral, WindowType
from kitty.window_list import WindowList

from .base import (
    Borders, Layout, LayoutDimension, LayoutOpts, NeighborsMap, all_borders,
    lgd, no_borders, normalize_biases, safe_increment_bias, variable_bias
)


def neighbors_for_tall_window(num_full_size_windows: int, window: WindowType, all_windows: WindowList) -> NeighborsMap:
    wg = all_windows.group_for_window(window)
    assert wg is not None
    groups = tuple(all_windows.iter_all_layoutable_groups())
    idx = groups.index(wg)
    prev = None if idx == 0 else groups[idx-1]
    nxt = None if idx == len(groups) - 1 else groups[idx+1]
    ans: NeighborsMap = {'left': [prev.id] if prev is not None else [], 'right': [], 'top': [], 'bottom': []}
    if idx < num_full_size_windows - 1:
        if nxt is not None:
            ans['right'] = [nxt.id]
    elif idx == num_full_size_windows - 1:
        ans['right'] = [w.id for w in groups[idx+1:]]
    else:
        ans['left'] = [groups[num_full_size_windows - 1].id]
        if idx > num_full_size_windows and prev is not None:
            ans['top'] = [prev.id]
        if nxt is not None:
            ans['bottom'] = [nxt.id]
    return ans


class TallLayoutOpts(LayoutOpts):
    bias: Tuple[float, ...] = ()
    full_size: int = 1

    def __init__(self, data: Dict[str, str]):

        try:
            self.full_size = int(data.get('full_size', 1))
        except Exception:
            self.full_size = 1
        self.full_size = fs = max(1, min(self.full_size, 100))
        try:
            b = int(data.get('bias', 50)) / 100
        except Exception:
            b = 0.5
        b = max(0.1, min(b, 0.9))
        self.bias = tuple(repeat(b / fs, fs)) + (1.0 - b,)


class Tall(Layout):

    name = 'tall'
    main_is_horizontal = True
    only_between_border = Borders(False, False, False, True)
    only_main_border = Borders(False, False, True, False)
    layout_opts = TallLayoutOpts({})
    main_axis_layout = Layout.xlayout
    perp_axis_layout = Layout.ylayout

    @property
    def num_full_size_windows(self) -> int:
        return self.layout_opts.full_size

    def remove_all_biases(self) -> bool:
        self.main_bias: List[float] = list(self.layout_opts.bias)
        self.biased_map: Dict[int, float] = {}
        return True

    def variable_layout(self, all_windows: WindowList, biased_map: Dict[int, float]) -> LayoutDimension:
        num = all_windows.num_groups - self.num_full_size_windows
        bias = variable_bias(num, biased_map) if num > 1 else None
        return self.perp_axis_layout(all_windows.iter_all_layoutable_groups(), bias=bias, offset=self.num_full_size_windows)

    def apply_bias(self, idx: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        num_windows = all_windows.num_groups
        if self.main_is_horizontal == is_horizontal:
            before_main_bias = self.main_bias
            ncols = self.num_full_size_windows + 1
            biased_col = idx if idx < self.num_full_size_windows else (ncols - 1)
            self.main_bias = [
                safe_increment_bias(self.main_bias[i], increment * (1 if i == biased_col else -1)) for i in range(ncols)
            ]
            self.main_bias = normalize_biases(self.main_bias)
            return self.main_bias != before_main_bias

        num_of_short_windows = num_windows - self.num_full_size_windows
        if idx < self.num_full_size_windows or num_of_short_windows < 2:
            return False
        idx -= self.num_full_size_windows
        before_layout = list(self.variable_layout(all_windows, self.biased_map))
        before = self.biased_map.get(idx, 0.)
        candidate = self.biased_map.copy()
        candidate[idx] = after = before + increment
        if before_layout == list(self.variable_layout(all_windows, candidate)):
            return False
        self.biased_map = candidate
        return before != after

    def do_layout(self, all_windows: WindowList) -> None:
        num = all_windows.num_groups
        if num == 1:
            self.layout_single_window_group(next(all_windows.iter_all_layoutable_groups()))
            return
        is_fat = not self.main_is_horizontal
        if num <= self.num_full_size_windows + 1:
            xlayout = self.main_axis_layout(all_windows.iter_all_layoutable_groups(), bias=self.main_bias)
            for i, (wg, xl) in enumerate(zip(all_windows.iter_all_layoutable_groups(), xlayout)):
                yl = next(self.perp_axis_layout(iter((wg,))))
                if is_fat:
                    xl, yl = yl, xl
                self.set_window_group_geometry(wg, xl, yl)
            return

        main_axis_groups = (gr for i, gr in enumerate(all_windows.iter_all_layoutable_groups()) if i <= self.num_full_size_windows)
        xlayout = self.main_axis_layout(main_axis_groups, bias=self.main_bias)
        attr: EdgeLiteral = 'bottom' if is_fat else 'right'
        start = lgd.central.top if is_fat else lgd.central.left
        for i, wg in enumerate(all_windows.iter_all_layoutable_groups()):
            if i >= self.num_full_size_windows:
                break
            xl = next(xlayout)
            yl = next(self.perp_axis_layout(iter((wg,))))
            if is_fat:
                xl, yl = yl, xl
            geom = self.set_window_group_geometry(wg, xl, yl)
            start = getattr(geom, attr) + wg.decoration(attr)
        ylayout = self.variable_layout(all_windows, self.biased_map)
        size = (lgd.central.height if is_fat else lgd.central.width) - start
        for i, wg in enumerate(all_windows.iter_all_layoutable_groups()):
            if i < self.num_full_size_windows:
                continue
            yl = next(ylayout)
            xl = next(self.main_axis_layout(iter((wg,)), start=start, size=size))
            if is_fat:
                xl, yl = yl, xl
            self.set_window_group_geometry(wg, xl, yl)

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        return neighbors_for_tall_window(self.num_full_size_windows, window, windows)

    def minimal_borders(self, all_windows: WindowList, needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        num = all_windows.num_groups
        last_i = num - 1
        groups = tuple(all_windows.iter_all_layoutable_groups())
        for i, wg in enumerate(groups):
            if needs_borders_map[wg.id]:
                yield all_borders
                continue
            if i < self.num_full_size_windows:
                if (last_i == i+1 or i+1 < self.num_full_size_windows) and needs_borders_map[groups[i+1].id]:
                    yield no_borders
                else:
                    yield no_borders if i == last_i else self.only_main_border
                continue
            if i == last_i:
                yield no_borders
                break
            if needs_borders_map[groups[i+1].id]:
                yield no_borders
            else:
                yield self.only_between_border


class Fat(Tall):

    name = 'fat'
    main_is_horizontal = False
    only_between_border = Borders(False, False, True, False)
    only_main_border = Borders(False, False, False, True)
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout

    def neighbors_for_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        wg = all_windows.group_for_window(window)
        assert wg is not None
        groups = tuple(all_windows.iter_all_layoutable_groups())
        idx = groups.index(wg)
        prev = None if idx == 0 else groups[idx-1]
        nxt = None if idx == len(groups) - 1 else groups[idx+1]
        ans: NeighborsMap = {'left': [], 'right': [], 'top': [] if prev is None else [prev.id], 'bottom': []}
        if idx < self.num_full_size_windows - 1:
            if nxt is not None:
                ans['bottom'] = [nxt.id]
        elif idx == self.num_full_size_windows - 1:
            ans['bottom'] = [w.id for w in groups[idx+1:]]
        else:
            ans['top'] = [groups[self.num_full_size_windows - 1].id]
            if idx > self.num_full_size_windows and prev is not None:
                ans['left'] = [prev.id]
            if nxt is not None:
                ans['right'] = [nxt.id]
        return ans
