#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Generator, Iterable
from typing import Any

from kitty.borders import BorderColor
from kitty.types import Edges
from kitty.typing_compat import WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import BorderLine, Layout, LayoutData, LayoutDimension, NeighborsMap, lgd


def borders(
    data: Iterable[tuple[WindowGroup, LayoutData, LayoutData]],
    is_horizontal: bool,
    all_windows: WindowList,
    start_offset: int = 1, end_offset: int = 1
) -> Generator[BorderLine, None, None]:
    borders: list[BorderLine] = []
    active_group = all_windows.active_group
    needs_borders_map = all_windows.compute_needs_borders_map(lgd.draw_active_borders)
    try:
        bw = next(all_windows.iter_all_layoutable_groups()).effective_border()
    except StopIteration:
        bw = 0
    if not bw:
        return

    for wg, xl, yl in data:
        if is_horizontal:
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

    last_idx = len(borders) - 1 - end_offset
    for i, x in enumerate(borders):
        if start_offset <= i <= last_idx:
            yield x


class Vertical(Layout):

    name = 'vertical'
    main_is_horizontal = False
    no_minimal_window_borders = True
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout

    def variable_layout(self, all_windows: WindowList, biased_map: dict[int, float]) -> LayoutDimension:
        num_windows = all_windows.num_groups
        bias = biased_map if num_windows > 1 else None
        return self.main_axis_layout(all_windows.iter_all_layoutable_groups(), bias=bias)

    def fixed_layout(self, wg: WindowGroup) -> LayoutDimension:
        return self.perp_axis_layout(iter((wg,)), border_mult=0 if lgd.draw_minimal_borders else 1)

    def remove_all_biases(self) -> bool:
        self.biased_map: dict[int, float] = {}
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

    def bias_slot(self, all_windows: WindowList, idx: int, fractional_bias: float, cell_increment_bias_h: float, cell_increment_bias_v: float) -> bool:
        before_layout = tuple(self.variable_layout(all_windows, self.biased_map))
        self.biased_map[idx] = cell_increment_bias_h if self.main_is_horizontal else cell_increment_bias_v
        after_layout = tuple(self.variable_layout(all_windows, self.biased_map))
        return before_layout == after_layout

    def generate_layout_data(self, all_windows: WindowList) -> Generator[tuple[WindowGroup, LayoutData, LayoutData], None, None]:
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

    def minimal_borders(self, all_windows: WindowList) -> Generator[BorderLine, None, None]:
        window_count = all_windows.num_groups
        if window_count < 2 or not lgd.draw_minimal_borders:
            return
        yield from borders(self.generate_layout_data(all_windows), self.main_is_horizontal, all_windows)

    def neighbors_for_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        wg = all_windows.group_for_window(window)
        assert wg is not None
        groups = tuple(all_windows.iter_all_layoutable_groups())
        idx = groups.index(wg)
        lg = len(groups)
        if lg > 1:
            before = [groups[(idx - 1 + lg) % lg].id]
            after = [groups[(idx + 1) % lg].id]
        else:
            before, after = [], []
        if self.main_is_horizontal:
            return {'left': before, 'right': after, 'top': [], 'bottom': []}
        return {'top': before, 'bottom': after, 'left': [], 'right': []}

    def layout_state(self) -> dict[str, Any]:
        return {'biased_map': self.biased_map}


class Horizontal(Vertical):

    name = 'horizontal'
    main_is_horizontal = True
    main_axis_layout = Layout.xlayout
    perp_axis_layout = Layout.ylayout
