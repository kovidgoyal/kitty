#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, Generator, List, Tuple

from kitty.borders import BorderColor
from kitty.constants import Edges
from kitty.typing import WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import (
    BorderLine, Borders, Layout, LayoutData, LayoutDimension, NeighborsMap,
    lgd, variable_bias
)


class Vertical(Layout):

    name = 'vertical'
    main_is_horizontal = False
    only_between_border = Borders(False, False, False, True)
    no_minimal_window_borders = True
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout

    def variable_layout(self, all_windows: WindowList, biased_map: Dict[int, float]) -> LayoutDimension:
        num_windows = all_windows.num_groups
        bias = variable_bias(num_windows, biased_map) if num_windows else None
        return self.main_axis_layout(all_windows.iter_all_layoutable_groups(), bias=bias)

    def fixed_layout(self, wg: WindowGroup) -> LayoutDimension:
        return self.perp_axis_layout(iter((wg,)), border_mult=0 if lgd.draw_minimal_borders else 1)

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

    def generate_layout_data(self, all_windows: WindowList) -> Generator[Tuple[WindowGroup, LayoutData, LayoutData], None, None]:
        ylayout = self.variable_layout(all_windows, self.biased_map)
        for wg, yl in zip(all_windows.iter_all_layoutable_groups(), ylayout):
            xl = next(self.fixed_layout(wg))
            if self.main_is_horizontal:
                xl, yl = yl, xl
            yield wg, xl, yl

    def do_layout(self, all_windows: WindowList) -> None:
        window_count = all_windows.num_groups
        if window_count == 1:
            self.layout_single_window_group(next(all_windows.iter_all_layoutable_groups()))
            return
        for wg, xl, yl in self.generate_layout_data(all_windows):
            self.set_window_group_geometry(wg, xl, yl)

    def window_independent_borders(self, all_windows: WindowList) -> Generator[BorderLine, None, None]:
        window_count = all_windows.num_groups
        if window_count == 1 or not lgd.draw_minimal_borders:
            return
        groups = tuple(all_windows.iter_all_layoutable_groups())
        needs_borders_map = all_windows.compute_needs_borders_map(lgd.draw_active_borders)
        bw = groups[0].effective_border()
        if not bw:
            return
        borders: List[BorderLine] = []
        active_group = all_windows.active_group

        for wg, xl, yl in self.generate_layout_data(all_windows):
            if self.main_is_horizontal:
                e1 = Edges(
                    xl.content_pos - xl.space_before, yl.content_pos - yl.space_before,
                    xl.content_pos - xl.space_before + bw, yl.content_pos + yl.content_size + yl.space_after
                )
                e2 = Edges(
                    xl.content_pos + xl.content_size + xl.space_after - bw, yl.content_pos - yl.space_before,
                    xl.content_pos + xl.content_size + xl.space_after, yl.content_pos + yl.content_size + yl.space_after
                )
            else:
                e1 = Edges(
                    xl.content_pos - xl.space_before, yl.content_pos - yl.space_before,
                    xl.content_pos + xl.content_size + xl.space_after, yl.content_pos - yl.space_before + bw
                )
                e2 = Edges(
                    xl.content_pos - xl.space_before, yl.content_pos + yl.content_size + yl.space_after - bw,
                    xl.content_pos + xl.content_size + xl.space_after, yl.content_pos + yl.content_size + yl.space_after
                )
            color = BorderColor.inactive
            if needs_borders_map.get(wg.id):
                color = BorderColor.active if wg is active_group else BorderColor.bell
            borders.append(BorderLine(e1, color))
            borders.append(BorderLine(e2, color))
        for x in borders[1:-1]:
            yield x

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
