#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Generator, Sequence
from itertools import islice, repeat
from typing import Any

from kitty.borders import BorderColor
from kitty.conf.utils import to_bool
from kitty.types import Edges
from kitty.typing_compat import EdgeLiteral, WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import (
    BorderLine,
    Layout,
    LayoutData,
    LayoutDimension,
    LayoutOpts,
    NeighborsMap,
    lgd,
    normalize_biases,
    safe_increment_bias,
)
from .vertical import borders


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
    bias: int = 50
    full_size: int = 1
    mirrored: bool = False

    def __init__(self, data: dict[str, str]):
        try:
            self.full_size = int(data.get('full_size', 1))
        except Exception:
            self.full_size = 1
        self.full_size = max(1, min(self.full_size, 100))
        try:
            self.bias = int(data.get('bias', 50))
        except Exception:
            self.bias = 50
        self.mirrored = to_bool(data.get('mirrored', 'false'))

    def serialized(self) -> dict[str, Any]:
        return {'full_size': self.full_size, 'bias': self.bias, 'mirrored': self.mirrored}

    def build_bias_list(self) -> tuple[float, ...]:
        b = self.bias / 100
        b = max(0.1, min(b, 0.9))
        return tuple(repeat(b / self.full_size, self.full_size)) + (1.0 - b,)


def set_bias(biases: Sequence[float], idx: int, target: float) -> list[float]:
    remainder = 1 - target
    previous_remainder = sum(x for i, x in enumerate(biases) if i != idx)
    ans = [1. for i in range(len(biases))]
    for i in range(len(biases)):
        if i == idx:
            ans[i] = target
        else:
            ans[i] = remainder * biases[i] / previous_remainder
    return ans


class Tall(Layout):

    name = 'tall'
    main_is_horizontal = True
    no_minimal_window_borders = True
    layout_opts = TallLayoutOpts({})
    main_axis_layout = Layout.xlayout
    perp_axis_layout = Layout.ylayout

    @property
    def num_full_size_windows(self) -> int:
        return self.layout_opts.full_size

    def remove_all_biases(self) -> bool:
        self.main_bias: list[float] = list(self.layout_opts.build_bias_list())
        self.biased_map: dict[int, float] = {}
        return True

    def variable_layout(self, all_windows: WindowList, biased_map: dict[int, float]) -> LayoutDimension:
        num = all_windows.num_groups - self.num_full_size_windows
        bias = biased_map if num > 1 else None
        return self.perp_axis_layout(all_windows.iter_all_layoutable_groups(), bias=bias, offset=self.num_full_size_windows)

    def bias_slot(self, all_windows: WindowList, idx: int, fractional_bias: float, cell_increment_bias_h: float, cell_increment_bias_v: float) -> bool:
        if idx < len(self.main_bias):
            before_main_bias = self.main_bias
            self.main_bias = set_bias(self.main_bias, idx, fractional_bias)
            return self.main_bias != before_main_bias

        before_layout = tuple(self.variable_layout(all_windows, self.biased_map))
        self.biased_map[idx - self.num_full_size_windows] = cell_increment_bias_v if self.main_is_horizontal else cell_increment_bias_h
        after_layout = tuple(self.variable_layout(all_windows, self.biased_map))
        return before_layout == after_layout

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
        before_layout = tuple(self.variable_layout(all_windows, self.biased_map))
        before = self.biased_map.get(idx, 0.)
        candidate = self.biased_map.copy()
        candidate[idx] = after = before + increment
        if before_layout == tuple(self.variable_layout(all_windows, candidate)):
            return False
        self.biased_map = candidate
        return before != after

    def simple_layout(self, all_windows: WindowList) -> Generator[tuple[WindowGroup, LayoutData, LayoutData, bool], None, None]:
        num = all_windows.num_groups
        is_fat = not self.main_is_horizontal
        mirrored = self.layout_opts.mirrored
        groups = tuple(all_windows.iter_all_layoutable_groups())
        main_bias = self.main_bias[::-1] if mirrored else self.main_bias
        if mirrored:
            groups = tuple(reversed(groups))
        main_bias = normalize_biases(main_bias[:num])
        xlayout = self.main_axis_layout(iter(groups), bias=main_bias)
        for wg, xl in zip(groups, xlayout):
            yl = next(self.perp_axis_layout(iter((wg,))))
            if is_fat:
                xl, yl = yl, xl
            yield wg, xl, yl, True

    def full_layout(self, all_windows: WindowList) -> Generator[tuple[WindowGroup, LayoutData, LayoutData, bool], None, None]:
        is_fat = not self.main_is_horizontal
        mirrored = self.layout_opts.mirrored
        groups = tuple(all_windows.iter_all_layoutable_groups())
        main_bias = self.main_bias[::-1] if mirrored else self.main_bias

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
                yield wg, xl, yl, True
        else:
            xlayout = self.main_axis_layout(islice(groups, self.num_full_size_windows + 1), bias=main_bias)
            for i, wg in enumerate(groups):
                if i >= self.num_full_size_windows:
                    break
                xl = next(xlayout)
                yl = next(self.perp_axis_layout(iter((wg,))))
                start = xl.content_pos + xl.content_size + xl.space_after
                if is_fat:
                    xl, yl = yl, xl
                yield wg, xl, yl, True
            size = 1 + (lgd.central.bottom if is_fat else lgd.central.right) - start

        ylayout = self.variable_layout(all_windows, self.biased_map)
        for i, wg in enumerate(all_windows.iter_all_layoutable_groups()):
            if i < self.num_full_size_windows:
                continue
            yl = next(ylayout)
            xl = next(self.main_axis_layout(iter((wg,)), start=start, size=size))
            if is_fat:
                xl, yl = yl, xl
            yield wg, xl, yl, False

    def do_layout(self, all_windows: WindowList) -> None:
        num = all_windows.num_groups
        if num == 1:
            self.layout_single_window_group(next(all_windows.iter_all_layoutable_groups()))
            return
        layouts = (self.simple_layout if num <= self.num_full_size_windows + 1 else self.full_layout)(all_windows)
        for wg, xl, yl, is_full_size in layouts:
            self.set_window_group_geometry(wg, xl, yl)

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        return neighbors_for_tall_window(self.num_full_size_windows, window, windows, self.layout_opts.mirrored, self.main_is_horizontal)

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> bool | None:
        if action_name == 'increase_num_full_size_windows':
            self.layout_opts.full_size += 1
            self.main_bias = list(self.layout_opts.build_bias_list())
            return True
        if action_name == 'decrease_num_full_size_windows':
            if self.layout_opts.full_size > 1:
                self.layout_opts.full_size -= 1
                self.main_bias = list(self.layout_opts.build_bias_list())
                return True
        if action_name == 'mirror':
            action = (args or ('toggle',))[0]
            ok = False
            if action == 'toggle':
                self.layout_opts.mirrored = not self.layout_opts.mirrored
                ok = True
            else:
                new_val = to_bool(action)
                if new_val != self.layout_opts.mirrored:
                    self.layout_opts.mirrored = new_val
                    ok = True
            return ok
        if action_name == 'bias':
            if len(args) == 0:
                raise ValueError('layout_action bias must contain at least one number between 10 and 90')
            biases = args[0].split()
            if len(biases) == 1:
                biases.append("50")
            try:
                i = biases.index(str(self.layout_opts.bias)) + 1
            except ValueError:
                i = 0
            try:
                self.layout_opts.bias = int(biases[i % len(biases)])
                self.remove_all_biases()
                return True
            except Exception:
                return False
        return None

    def minimal_borders(self, all_windows: WindowList) -> Generator[BorderLine, None, None]:
        num = all_windows.num_groups
        if num < 2 or not lgd.draw_minimal_borders:
            return
        try:
            bw = next(all_windows.iter_all_layoutable_groups()).effective_border()
        except StopIteration:
            bw = 0
        if not bw:
            return
        if num <= self.num_full_size_windows + 1:
            layout = (x[:3] for x in self.simple_layout(all_windows))
            yield from borders(layout, self.main_is_horizontal, all_windows)
            return
        main_layouts: list[tuple[WindowGroup, LayoutData, LayoutData]] = []
        perp_borders: list[BorderLine] = []
        layouts = (self.simple_layout if num <= self.num_full_size_windows else self.full_layout)(all_windows)
        needs_borders_map = all_windows.compute_needs_borders_map(lgd.draw_active_borders)
        active_group = all_windows.active_group
        mirrored = self.layout_opts.mirrored
        for wg, xl, yl, is_full_size in layouts:
            if is_full_size:
                main_layouts.append((wg, xl, yl))
            else:
                color = BorderColor.inactive
                if needs_borders_map.get(wg.id):
                    color = BorderColor.active if wg is active_group else BorderColor.bell
                if self.main_is_horizontal:
                    e1 = Edges(
                        xl.content_pos - xl.space_before,
                        yl.content_pos - yl.space_before,
                        xl.content_pos + xl.content_size + xl.space_after,
                        yl.content_pos - yl.space_before + bw
                    )
                    e3 = Edges(
                        xl.content_pos - xl.space_before,
                        yl.content_pos + yl.content_size + yl.space_after - bw,
                        xl.content_pos + xl.content_size + xl.space_after,
                        yl.content_pos + yl.content_size + yl.space_after,
                    )
                    e2 = Edges(
                        xl.content_pos + ((xl.content_size + xl.space_after - bw) if mirrored else -xl.space_before),
                        yl.content_pos - yl.space_before,
                        xl.content_pos + ((xl.content_size + xl.space_after) if mirrored else (bw - xl.space_before)),
                        yl.content_pos + yl.content_size + yl.space_after,
                    )
                else:
                    e1 = Edges(
                        xl.content_pos - xl.space_before,
                        yl.content_pos - yl.space_before,
                        xl.content_pos - xl.space_before + bw,
                        yl.content_pos + yl.content_size + yl.space_after,
                    )
                    e3 = Edges(
                        xl.content_pos + xl.content_size + xl.space_after - bw,
                        yl.content_pos - yl.space_before,
                        xl.content_pos + xl.content_size + xl.space_after,
                        yl.content_pos + yl.content_size + yl.space_after,
                    )
                    e2 = Edges(
                        xl.content_pos - xl.space_before,
                        yl.content_pos + ((yl.content_size + yl.space_after - bw) if mirrored else -yl.space_before),
                        xl.content_pos + xl.content_size + xl.space_after,
                        yl.content_pos + ((yl.content_size + yl.space_after) if mirrored else (bw - yl.space_before)),
                    )
                perp_borders.append(BorderLine(e1, color))
                perp_borders.append(BorderLine(e2, color))
                perp_borders.append(BorderLine(e3, color))

        mirrored = self.layout_opts.mirrored
        yield from borders(
            main_layouts, self.main_is_horizontal, all_windows,
            start_offset=int(not mirrored), end_offset=int(mirrored)
        )
        yield from perp_borders[1:-1]

    def layout_state(self) -> dict[str, Any]:
        return {
            'num_full_size_windows': self.num_full_size_windows,
            'main_bias': self.main_bias,
            'biased_map': self.biased_map
        }


class Fat(Tall):

    name = 'fat'
    main_is_horizontal = False
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout
