#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.types import NeighborsMap
from kitty.typing_compat import WindowType
from kitty.window_list import WindowList

from .base import Layout
from .constraints import LinearConstraintModel


class Stack(Layout):
    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def __init__(self, os_window_id: int, tab_id: int, layout_opts: str = '') -> None:
        super().__init__(os_window_id, tab_id, layout_opts)
        self._x_constraint_model = LinearConstraintModel()
        self._y_constraint_model = LinearConstraintModel()

    def do_layout(self, windows: WindowList) -> None:
        active_group = windows.active_group
        for group in windows.iter_all_layoutable_groups():
            self.layout_single_window_group(
                group,
                add_blank_rects=group is active_group,
                x_cell_allocator=self._x_constraint_model,
                y_cell_allocator=self._y_constraint_model,
            )

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        wg = windows.group_for_window(window)
        assert wg is not None
        groups = tuple(windows.iter_all_layoutable_groups())
        idx = groups.index(wg)
        before = [] if wg is groups[0] else [groups[idx - 1].id]
        after = [] if wg is groups[-1] else [groups[idx + 1].id]
        return {'top': before, 'left': before, 'right': after, 'bottom': after}
