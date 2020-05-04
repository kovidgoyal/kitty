#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, Generator, Optional

from kitty.typing import WindowType
from kitty.window_list import WindowList

from .base import (
    Borders, InternalNeighborsMap, Layout, LayoutDimension, ListOfWindows,
    all_borders, no_borders, variable_bias
)


class Vertical(Layout):

    name = 'vertical'
    main_is_horizontal = False
    only_between_border = Borders(False, False, False, True)
    main_axis_layout = Layout.ylayout
    perp_axis_layout = Layout.xlayout

    def variable_layout(self, windows: ListOfWindows, biased_map: Dict[int, float]) -> LayoutDimension:
        num_windows = len(windows)
        bias = variable_bias(num_windows, biased_map) if num_windows else None
        return self.main_axis_layout(windows, bias=bias)

    def remove_all_biases(self) -> bool:
        self.biased_map: Dict[int, float] = {}
        return True

    def apply_bias(self, idx: int, increment: float, top_level_windows: ListOfWindows, is_horizontal: bool = True) -> bool:
        if self.main_is_horizontal != is_horizontal:
            return False
        num_windows = len(top_level_windows)
        if num_windows < 2:
            return False
        before_layout = list(self.variable_layout(top_level_windows, self.biased_map))
        candidate = self.biased_map.copy()
        before = candidate.get(idx, 0)
        candidate[idx] = before + increment
        if before_layout == list(self.variable_layout(top_level_windows, candidate)):
            return False
        self.biased_map = candidate
        return True

    def do_layout(self, windows: WindowList, active_window_idx: int) -> None:
        window_count = len(windows)
        if window_count == 1:
            self.layout_single_window(windows[0])
            return

        ylayout = self.variable_layout(windows, self.biased_map)
        for i, (w, yl) in enumerate(zip(windows, ylayout)):
            xl = next(self.perp_axis_layout([w]))
            if self.main_is_horizontal:
                xl, yl = yl, xl
            self.set_window_geometry(w, i, xl, yl)

    def minimal_borders(self, windows: WindowList, active_window: Optional[WindowType], needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        last_i = len(windows) - 1
        for i, w in enumerate(windows):
            if needs_borders_map[w.id]:
                yield all_borders
                continue
            if i == last_i:
                yield no_borders
                break
            if needs_borders_map[windows[i+1].id]:
                yield no_borders
            else:
                yield self.only_between_border

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> InternalNeighborsMap:
        idx = windows.index(window)
        before = [] if window is windows[0] else [windows[idx-1].id]
        after = [] if window is windows[-1] else [windows[idx+1].id]
        if self.main_is_horizontal:
            return {'left': before, 'right': after, 'top': [], 'bottom': []}
        return {'top': before, 'bottom': after, 'left': [], 'right': []}


class Horizontal(Vertical):

    name = 'horizontal'
    main_is_horizontal = True
    only_between_border = Borders(False, False, True, False)
    main_axis_layout = Layout.xlayout
    perp_axis_layout = Layout.ylayout
