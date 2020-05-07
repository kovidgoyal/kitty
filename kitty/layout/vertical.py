#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, Generator

from kitty.typing import WindowType
from kitty.window_list import WindowList

from .base import (
    Borders, Layout, LayoutDimension, NeighborsMap, all_borders, no_borders,
    variable_bias
)


class Vertical(Layout):

    name = 'vertical'
    main_is_horizontal = False
    only_between_border = Borders(False, False, False, True)
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout

    def variable_layout(self, all_windows: WindowList, biased_map: Dict[int, float]) -> LayoutDimension:
        num_windows = all_windows.num_groups
        bias = variable_bias(num_windows, biased_map) if num_windows else None
        return self.main_axis_layout(all_windows.iter_all_layoutable_groups(), bias=bias)

    def remove_all_biases(self) -> bool:
        self.biased_map: Dict[int, float] = {}
        return True

    def apply_bias(self, idx: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        if self.main_is_horizontal != is_horizontal:
            return False
        num_windows = all_windows.num_groups
        if num_windows < 2:
            return False
        before_layout = list(self.variable_layout(all_windows, self.biased_map))
        candidate = self.biased_map.copy()
        before = candidate.get(idx, 0)
        candidate[idx] = before + increment
        if before_layout == list(self.variable_layout(all_windows, candidate)):
            return False
        self.biased_map = candidate
        return True

    def do_layout(self, all_windows: WindowList) -> None:
        window_count = all_windows.num_groups
        if window_count == 1:
            self.layout_single_window_group(next(all_windows.iter_all_layoutable_groups()))
            return

        ylayout = self.variable_layout(all_windows, self.biased_map)
        for i, (wg, yl) in enumerate(zip(all_windows.iter_all_layoutable_groups(), ylayout)):
            xl = next(self.perp_axis_layout(iter((wg,))))
            if self.main_is_horizontal:
                xl, yl = yl, xl
            self.set_window_group_geometry(wg, xl, yl)

    def minimal_borders(self, all_windows: WindowList, needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        last_i = all_windows.num_groups - 1
        groups = tuple(all_windows.iter_all_layoutable_groups())
        for i, wg in enumerate(groups):
            if needs_borders_map[wg.id]:
                yield all_borders
                continue
            if i == last_i:
                yield no_borders
                break
            if needs_borders_map[groups[i+1].id]:
                yield no_borders
            else:
                yield self.only_between_border

    def neighbors_for_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        wg = all_windows.group_for_window(window)
        assert wg is not None
        groups = tuple(all_windows.iter_all_layoutable_groups())
        idx = groups.index(wg)
        before = [] if wg is groups[0] else [groups[idx-1].id]
        after = [] if wg is groups[-1] else [groups[idx+1].id]
        if self.main_is_horizontal:
            return {'left': before, 'right': after, 'top': [], 'bottom': []}
        return {'top': before, 'bottom': after, 'left': [], 'right': []}


class Horizontal(Vertical):

    name = 'horizontal'
    main_is_horizontal = True
    only_between_border = Borders(False, False, True, False)
    main_axis_layout = Layout.xlayout
    perp_axis_layout = Layout.ylayout
