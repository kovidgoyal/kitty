#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.typing_compat import WindowType
from kitty.window_list import WindowList

from .base import Layout, NeighborsMap


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def do_layout(self, all_windows: WindowList) -> None:
        active_group = all_windows.active_group
        for group in all_windows.iter_all_layoutable_groups():
            self.layout_single_window_group(group, add_blank_rects=group is active_group)

    def neighbors_for_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        wg = all_windows.group_for_window(window)
        assert wg is not None
        groups = tuple(all_windows.iter_all_layoutable_groups())
        idx = groups.index(wg)
        before = [] if wg is groups[0] else [groups[idx-1].id]
        after = [] if wg is groups[-1] else [groups[idx+1].id]
        return {'top': before, 'left': before, 'right': after, 'bottom': after}
