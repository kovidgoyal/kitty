#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.window_list import WindowList

from .base import Layout


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def do_layout(self, all_windows: WindowList) -> None:
        active_group = all_windows.active_group
        for group in all_windows.iter_all_layoutable_groups():
            self.layout_single_window_group(group, add_blank_rects=group is active_group)
