#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from enum import IntFlag
from itertools import chain
from typing import List, Optional, Sequence, Tuple

from .fast_data_types import (
    BORDERS_PROGRAM, add_borders_rect, compile_program, init_borders_program,
    os_window_has_background_image
)
from .options_stub import Options
from .utils import load_shaders
from .typing import WindowType, LayoutType


class BorderColor(IntFlag):
    # See the border vertex shader for how these flags become actual colors
    default_bg, active, inactive, window_bg, bell = ((1 << i) for i in range(5))


def vertical_edge(os_window_id: int, tab_id: int, color: int, width: int, top: int, bottom: int, left: int) -> None:
    if width > 0:
        add_borders_rect(os_window_id, tab_id, left, top, left + width, bottom, color)


def horizontal_edge(os_window_id: int, tab_id: int, color: int, height: int, left: int, right: int, top: int) -> None:
    if height > 0:
        add_borders_rect(os_window_id, tab_id, left, top, right, top + height, color)


def draw_edges(os_window_id: int, tab_id: int, colors: Sequence[int], window: WindowType, borders: bool = False) -> None:
    geometry = window.geometry
    pl, pt = window.effective_padding('left'), window.effective_padding('top')
    pr, pb = window.effective_padding('right'), window.effective_padding('bottom')
    left = geometry.left - pl
    top = geometry.top - pt
    lr = geometry.right
    right = lr + pr
    bt = geometry.bottom
    bottom = bt + pb
    if borders:
        width = window.effective_border()
        bt = bottom
        lr = right
        left -= width
        top -= width
        right += width
        bottom += width
        pl = pr = pb = pt = width
    horizontal_edge(os_window_id, tab_id, colors[1], pt, left, right, top)
    horizontal_edge(os_window_id, tab_id, colors[3], pb, left, right, bt)
    vertical_edge(os_window_id, tab_id, colors[0], pl, top, bottom, left)
    vertical_edge(os_window_id, tab_id, colors[2], pr, top, bottom, lr)


def load_borders_program() -> None:
    compile_program(BORDERS_PROGRAM, *load_shaders('border'))
    init_borders_program()


class Borders:

    def __init__(self, os_window_id: int, tab_id: int, opts: Options):
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.draw_active_borders = opts.active_border_color is not None

    def __call__(
        self,
        windows: List[WindowType],
        active_window: Optional[WindowType],
        current_layout: LayoutType,
        extra_blank_rects: Sequence[Tuple[int, int, int, int]],
        draw_window_borders: bool = True,
    ) -> None:
        add_borders_rect(self.os_window_id, self.tab_id, 0, 0, 0, 0, BorderColor.default_bg)
        has_background_image = os_window_has_background_image(self.os_window_id)
        if not has_background_image:
            for br in chain(current_layout.blank_rects, extra_blank_rects):
                left, top, right, bottom = br
                add_borders_rect(self.os_window_id, self.tab_id, left, top, right, bottom, BorderColor.default_bg)
        bw = 0
        if windows:
            bw = windows[0].effective_border()
        draw_borders = bw > 0 and draw_window_borders
        if draw_borders:
            border_data = current_layout.resolve_borders(windows, active_window)

        for i, w in enumerate(windows):
            window_bg = w.screen.color_profile.default_bg
            window_bg = (window_bg << 8) | BorderColor.window_bg
            if draw_borders:
                # Draw the border rectangles
                if w is active_window and self.draw_active_borders:
                    color = BorderColor.active
                else:
                    color = BorderColor.bell if w.needs_attention else BorderColor.inactive
                try:
                    colors = tuple(color if needed else window_bg for needed in next(border_data))
                    draw_edges(self.os_window_id, self.tab_id, colors, w, borders=True)
                except StopIteration:
                    pass
            if not has_background_image:
                # Draw the background rectangles over the padding region
                colors = window_bg, window_bg, window_bg, window_bg
                draw_edges(self.os_window_id, self.tab_id, colors, w)

        color = BorderColor.inactive
        for (left, top, right, bottom) in current_layout.window_independent_borders(windows, active_window):
            add_borders_rect(self.os_window_id, self.tab_id, left, top, right, bottom, color)
