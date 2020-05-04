#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.window_list import WindowList

from .base import Layout, blank_rects_for_window, lgd


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def do_layout(self, windows: WindowList, active_window_idx: int) -> None:
        for i, w in enumerate(windows):
            wg = self.layout_single_window(w, left_align=lgd.align_top_left, return_geometry=True)
            if wg is not None:
                w.set_geometry(i, wg)
                if w.is_visible_in_layout:
                    self.blank_rects = list(blank_rects_for_window(wg))
