#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from itertools import islice, repeat
from typing import Dict, Generator, List, Optional, Sequence, Tuple

from kitty.conf.utils import to_bool
from kitty.typing import EdgeLiteral, WindowType
from kitty.window_list import WindowList

from .base import (
    Borders, Layout, LayoutDimension, LayoutOpts, NeighborsMap, all_borders,
    lgd, no_borders, normalize_biases, safe_increment_bias, variable_bias
)


def neighbors_for_tall_window(
        num_full_size_windows: int,
        window: WindowType,
        all_windows: WindowList,
        mirrored: bool = False,
        main_is_horizontal: bool = True
) -> NeighborsMap:
    wg = all_windows.group_for_window(window)
    assert wg is not None
    groups = tuple(all_windows.iter_all_layoutable_groups())
    idx = groups.index(wg)
    prev = None if idx == 0 else groups[idx-1]
    nxt = None if idx == len(groups) - 1 else groups[idx+1]
    ans: NeighborsMap = {'left': [], 'right': [], 'top': [], 'bottom': []}
    main_before: EdgeLiteral = 'left' if main_is_horizontal else 'top'
    main_after: EdgeLiteral = 'right' if main_is_horizontal else 'bottom'
    cross_before: EdgeLiteral = 'top' if main_is_horizontal else 'left'
    cross_after: EdgeLiteral = 'bottom' if main_is_horizontal else 'right'
    if mirrored:
        main_before, main_after = main_after, main_before
    if prev is not None:
        ans[main_before] = [prev.id]
    if idx < num_full_size_windows - 1:
        if nxt is not None:
            ans[main_after] = [nxt.id]
    elif idx == num_full_size_windows - 1:
        ans[main_after] = [w.id for w in groups[idx+1:]]
    else:
        ans[main_before] = [groups[num_full_size_windows - 1].id]
        if idx > num_full_size_windows and prev is not None:
            ans[cross_before] = [prev.id]
        if nxt is not None:
            ans[cross_after] = [nxt.id]
    return ans


class TallLayoutOpts(LayoutOpts):
    bias: Tuple[float, ...] = ()
    full_size: int = 1
    mirrored: bool = False

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
        self.mirrored = to_bool(data.get('mirrored', 'false'))


class Tall(Layout):

    name = 'tall'
    main_is_horizontal = True
    only_between_border = Borders(False, False, False, True)
    only_main_border = Borders(False, False, True, False)
    only_main_border_mirrored = Borders(True, False, False, False)
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
        mirrored = self.layout_opts.mirrored
        groups = tuple(all_windows.iter_all_layoutable_groups())
        main_bias = self.main_bias[::-1] if mirrored else self.main_bias
        if num <= self.num_full_size_windows + 1:
            if mirrored:
                groups = tuple(reversed(groups))
            if num < self.num_full_size_windows + 1:
                main_bias = normalize_biases(main_bias[:num])
            xlayout = self.main_axis_layout(iter(groups), bias=main_bias)
            for wg, xl in zip(groups, xlayout):
                yl = next(self.perp_axis_layout(iter((wg,))))
                if is_fat:
                    xl, yl = yl, xl
                self.set_window_group_geometry(wg, xl, yl)
            return

        start = lgd.central.top if is_fat else lgd.central.left
        size = 0
        if mirrored:
            fsg = groups[:self.num_full_size_windows + 1]
            xlayout = self.main_axis_layout(reversed(fsg), bias=main_bias)
            for i, wg in enumerate(reversed(fsg)):
                xl = next(xlayout)
                if i == 0:
                    size = xl.content_size + xl.space_before + xl.space_after
                    continue
                yl = next(self.perp_axis_layout(iter((wg,))))
                if is_fat:
                    xl, yl = yl, xl
                self.set_window_group_geometry(wg, xl, yl)
        else:
            xlayout = self.main_axis_layout(islice(groups, self.num_full_size_windows + 1), bias=main_bias)
            attr: EdgeLiteral = 'bottom' if is_fat else 'right'
            for i, wg in enumerate(groups):
                if i >= self.num_full_size_windows:
                    break
                xl = next(xlayout)
                yl = next(self.perp_axis_layout(iter((wg,))))
                if is_fat:
                    xl, yl = yl, xl
                geom = self.set_window_group_geometry(wg, xl, yl)
                start = getattr(geom, attr) + wg.decoration(attr)
            size = (lgd.central.height if is_fat else lgd.central.width) - start

        ylayout = self.variable_layout(all_windows, self.biased_map)
        for i, wg in enumerate(all_windows.iter_all_layoutable_groups()):
            if i < self.num_full_size_windows:
                continue
            yl = next(ylayout)
            xl = next(self.main_axis_layout(iter((wg,)), start=start, size=size))
            if is_fat:
                xl, yl = yl, xl
            self.set_window_group_geometry(wg, xl, yl)

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        return neighbors_for_tall_window(self.num_full_size_windows, window, windows, self.layout_opts.mirrored, self.main_is_horizontal)

    def minimal_borders(self, all_windows: WindowList, needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        mirrored = self.layout_opts.mirrored
        only_main_border = self.only_main_border_mirrored if mirrored else self.only_main_border
        num = all_windows.num_groups
        last_i = num - 1
        groups = tuple(all_windows.iter_all_layoutable_groups())
        for i, wg in enumerate(groups):
            if needs_borders_map[wg.id]:
                yield all_borders
                continue
            if i < self.num_full_size_windows:
                next_window_is_full_sized = last_i == i+1 or i+1 < self.num_full_size_windows
                if next_window_is_full_sized and needs_borders_map[groups[i+1].id]:
                    yield no_borders
                else:
                    yield no_borders if i == last_i else only_main_border
                continue
            if i == last_i:
                yield no_borders
                break
            if needs_borders_map[groups[i+1].id]:
                yield no_borders
            else:
                yield self.only_between_border

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> Optional[bool]:
        if action_name == 'increase_num_full_size_windows':
            self.layout_opts.full_size += 1
            return True
        if action_name == 'decrease_num_full_size_windows':
            if self.layout_opts.full_size > 1:
                self.layout_opts.full_size -= 1
                return True


class Fat(Tall):

    name = 'fat'
    main_is_horizontal = False
    only_between_border = Borders(False, False, True, False)
    only_main_border = Borders(False, False, False, True)
    only_main_border_mirrored = Borders(False, True, False, False)
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout
