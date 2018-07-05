#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial
from itertools import chain

from .fast_data_types import (
    BORDERS_PROGRAM, add_borders_rect, compile_program, init_borders_program
)
from .utils import load_shaders
from .window import Widths

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


def edge(func, os_window_id, tab_id, color, sz, a, b):
    return partial(func, os_window_id, tab_id, color, sz, a, b)


def border(os_window_id, tab_id, color, widths, geometry, base_width=0):
    left = geometry.left - (widths.left + base_width)
    top = geometry.top - (widths.top + base_width)
    right = geometry.right + (widths.right + base_width)
    bottom = geometry.bottom + (widths.bottom + base_width)
    if widths.top > 0:
        edge(horizontal_edge, os_window_id, tab_id, color, widths.top, left, right)(top)
    if widths.bottom > 0:
        edge(horizontal_edge, os_window_id, tab_id, color, widths.bottom, left, right)(geometry.bottom + base_width)
    if widths.left > 0:
        edge(vertical_edge, os_window_id, tab_id, color, widths.left, top, bottom)(left)
    if widths.right > 0:
        edge(vertical_edge, os_window_id, tab_id, color, widths.right, top, bottom)(geometry.right + base_width)


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
        for w in windows:
            g = w.geometry
            if bw > 0 and draw_window_borders:
                # Draw the border rectangles
                color = BorderColor.active if w is active_window else (BorderColor.bell if w.needs_attention else BorderColor.inactive)
                border(self.os_window_id, self.tab_id, color, w.border_widths, g, base_width=pw)
            if pw > 0:
                widths = Widths(pw)
                # Draw the background rectangles over the padding region
                color = w.screen.color_profile.default_bg
                border(
                    self.os_window_id, self.tab_id, (color << 8) | BorderColor.window_bg, widths, g)
