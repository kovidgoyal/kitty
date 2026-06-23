#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Generator, Iterable, Sequence
from typing import Any

from kitty.borders import BorderColor
from kitty.types import Edges, NeighborsMap, WindowMapper
from kitty.typing_compat import EdgeLiteral, WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import BorderLine, DragOverlayMode, Layout, LayoutData, LayoutDimension, LayoutOpts, lgd


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
        borders.append(BorderLine(e1, color, -wg.active_window_id, not is_horizontal))
        borders.append(BorderLine(e2, color, wg.active_window_id, not is_horizontal))

    last_idx = len(borders) - 1 - end_offset
    for i, x in enumerate(borders):
        if start_offset <= i <= last_idx:
            yield x


class Vertical(Layout):

    name = 'vertical'
    main_is_horizontal = False
    no_minimal_window_borders = True
    drag_overlay_mode = DragOverlayMode.axis_y
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

    def apply_bias(self, window_id: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        if self.main_is_horizontal != is_horizontal:
            return False
        num_windows = all_windows.num_groups
        if num_windows < 2:
            return False
        before_layout = list(self.variable_layout(all_windows, self.biased_map))
        candidate = self.biased_map.copy()
        before = candidate.get(window_id, 0)
        candidate[window_id] = before + increment
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

    def do_layout(self, windows: WindowList) -> None:
        window_count = windows.num_groups
        if window_count == 1:
            self.layout_single_window_group(next(windows.iter_all_layoutable_groups()))
            return
        for wg, xl, yl in self.generate_layout_data(windows):
            self.set_window_group_geometry(wg, xl, yl)

    def minimal_borders(self, windows: WindowList) -> Generator[BorderLine, None, None]:
        window_count = windows.num_groups
        if window_count < 2 or not lgd.draw_minimal_borders:
            return
        yield from borders(self.generate_layout_data(windows), self.main_is_horizontal, windows)

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        wg = windows.group_for_window(window)
        assert wg is not None
        groups = tuple(windows.iter_all_layoutable_groups())
        idx = groups.index(wg)
        lg = len(groups)
        if lg > 1:
            after = [groups[(idx - 1 + lg) % lg].id]
            before = [groups[(idx + 1) % lg].id]
        else:
            before, after = [], []
        ans: NeighborsMap = {}
        akey: EdgeLiteral = 'top'
        bkey: EdgeLiteral = 'bottom'
        if self.main_is_horizontal:
            akey, bkey = 'left', 'right'
        if before:
            ans[bkey] = before
        if after:
            ans[akey] = after
        return ans

    def layout_state(self) -> dict[str, Any]:
        return {'biased_map': self.biased_map}

    def set_layout_state(self, layout_state: dict[str, Any], map_group_id: WindowMapper) -> bool:
        self.biased_map = {int(k): v for k, v in layout_state['biased_map'].items()}
        return True

class Horizontal(Vertical):

    name = 'horizontal'
    main_is_horizontal = True
    drag_overlay_mode = DragOverlayMode.axis_x
    main_axis_layout = Layout.xlayout
    perp_axis_layout = Layout.ylayout


class FocusLayoutOpts(LayoutOpts):
    bias: int = 60

    def __init__(self, data: dict[str, str]):
        try:
            self.bias = int(data.get('bias', 60))
        except Exception:
            self.bias = 60
        self.bias = max(10, min(self.bias, 90))

    def serialized(self) -> dict[str, Any]:
        return {'bias': self.bias}


class VerticalFocus(Vertical):

    name = 'verticalfocus'
    layout_opts = FocusLayoutOpts({})
    needs_relayout_on_focus_change = True

    def focused_bias(self, all_windows: WindowList) -> Sequence[float] | None:
        groups = tuple(all_windows.iter_all_layoutable_groups())
        if len(groups) <= 1:
            return None
        active_group = all_windows.active_group
        if active_group is None:
            return None
        try:
            active_idx = groups.index(active_group)
        except ValueError:
            return None
        focused = self.layout_opts.bias / 100.0
        other = (1.0 - focused) / (len(groups) - 1)
        return tuple(focused if i == active_idx else other for i in range(len(groups)))

    def variable_layout(self, all_windows: WindowList, biased_map: dict[int, float]) -> LayoutDimension:
        return self.main_axis_layout(all_windows.iter_all_layoutable_groups(), bias=self.focused_bias(all_windows))

    def apply_bias(self, idx: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        return False

    def bias_slot(self, all_windows: WindowList, idx: int, fractional_bias: float, cell_increment_bias_h: float, cell_increment_bias_v: float) -> bool:
        return False

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> bool | None:
        if action_name == 'bias':
            if len(args) == 0:
                raise ValueError('layout_action bias must contain at least one number between 10 and 90')
            biases = args[0].split()
            if len(biases) == 1:
                biases.append('60')
            try:
                i = biases.index(str(self.layout_opts.bias)) + 1
            except ValueError:
                i = 0
            try:
                self.layout_opts.bias = max(10, min(int(biases[i % len(biases)]), 90))
                return True
            except Exception:
                return False
        return None

    def set_layout_state(self, layout_state: dict[str, Any], map_group_id: WindowMapper) -> bool:
        self.layout_opts = FocusLayoutOpts(layout_state['opts'])
        return True
