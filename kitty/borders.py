#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from itertools import chain

from .fast_data_types import (
    BORDERS_PROGRAM, add_borders_rect, compile_program, init_borders_program
)
from .utils import load_shaders

try:
    from enum import IntFlag
except Exception:
    from enum import IntEnum as IntFlag


class BorderColor(IntFlag):
    # See the border vertex shader for how these flags become actual colors
    default_bg, active, inactive, window_bg, bell = ((1 << i) for i in range(5))


def vertical_edge(os_window_id, tab_id, color, width, top, bottom, left):
    add_borders_rect(os_window_id, tab_id, left, top, left + width, bottom, color)


def horizontal_edge(os_window_id, tab_id, color, height, left, right, top):
    add_borders_rect(os_window_id, tab_id, left, top, right, top + height, color)


def draw_edges(os_window_id, tab_id, colors, width, geometry, base_width=0):
    left = geometry.left - (width + base_width)
    top = geometry.top - (width + base_width)
    right = geometry.right + (width + base_width)
    bottom = geometry.bottom + (width + base_width)
    horizontal_edge(os_window_id, tab_id, colors[1], width, left, right, top)
    horizontal_edge(os_window_id, tab_id, colors[3], width, left, right, geometry.bottom + base_width)
    vertical_edge(os_window_id, tab_id, colors[0], width, top, bottom, left)
    vertical_edge(os_window_id, tab_id, colors[2], width, top, bottom, geometry.right + base_width)


def load_borders_program():
    compile_program(BORDERS_PROGRAM, *load_shaders('border'))
    init_borders_program()
    Borders.program_initialized = True


class Borders:

    def __init__(self, os_window_id, tab_id, opts, border_width, padding_width):
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.border_width = border_width
        self.padding_width = padding_width
        self.draw_active_borders = opts.active_border_color is not None

    def __call__(
        self,
        windows,
        active_window,
        current_layout,
        extra_blank_rects,
        draw_window_borders=True
    ):
        add_borders_rect(self.os_window_id, self.tab_id, 0, 0, 0, 0, BorderColor.default_bg)
        for br in chain(current_layout.blank_rects, extra_blank_rects):
            add_borders_rect(self.os_window_id, self.tab_id, *br, BorderColor.default_bg)
        bw, pw = self.border_width, self.padding_width
        if bw + pw <= 0:
            return
        draw_borders = bw > 0 and draw_window_borders and len(windows) > 1
        if draw_borders:
            border_data = current_layout.resolve_borders(windows, active_window)

        for i, w in enumerate(windows):
            g = w.geometry
            window_bg = w.screen.color_profile.default_bg
            window_bg = (window_bg << 8) | BorderColor.window_bg
            if draw_borders:
                # Draw the border rectangles
                if w is active_window and self.draw_active_borders:
                    color = BorderColor.active
                else:
                    color = BorderColor.bell if w.needs_attention else BorderColor.inactive
                colors = tuple(color if needed else window_bg for needed in next(border_data))
                draw_edges(
                    self.os_window_id, self.tab_id, colors, bw, g, base_width=pw)
            if pw > 0:
                # Draw the background rectangles over the padding region
                colors = (window_bg, window_bg, window_bg, window_bg)
                draw_edges(
                    self.os_window_id, self.tab_id, colors, pw, g)
