#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial
from itertools import chain

from .fast_data_types import (
    BORDERS_PROGRAM, add_borders_rect, compile_program, init_borders_program
)
from .utils import load_shaders


def vertical_edge(os_window_id, tab_id, color, width, top, bottom, left):
    add_borders_rect(os_window_id, tab_id, left, top, left + width, bottom, color)


def horizontal_edge(os_window_id, tab_id, color, height, left, right, top):
    add_borders_rect(os_window_id, tab_id, left, top, right, top + height, color)


def edge(func, os_window_id, tab_id, color, sz, a, b):
    return partial(func, os_window_id, tab_id, color, sz, a, b)


def border(os_window_id, tab_id, color, sz, left, top, right, bottom):
    horz = edge(horizontal_edge, os_window_id, tab_id, color, sz, left, right)
    horz(top), horz(bottom - sz)  # top, bottom edges
    vert = edge(vertical_edge, os_window_id, tab_id, color, sz, top, bottom)
    vert(left), vert(right - sz)  # left, right edges


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
        add_borders_rect(self.os_window_id, self.tab_id, 0, 0, 0, 0, 1)
        for br in chain(current_layout.blank_rects, extra_blank_rects):
            add_borders_rect(self.os_window_id, self.tab_id, *br, 1)
        bw, pw = self.border_width, self.padding_width
        fw = bw + pw

        if fw > 0:
            for w in windows:
                g = w.geometry
                if bw > 0 and draw_window_borders:
                    # Draw the border rectangles
                    color = 2 if w is active_window else (16 if w.needs_attention else 4)
                    border(
                        self.os_window_id, self.tab_id,
                        color, bw, g.left - fw, g.top - fw, g.right + fw,
                        g.bottom + fw
                    )
                if pw > 0:
                    # Draw the background rectangles over the padding region
                    color = w.screen.color_profile.default_bg
                    border(
                        self.os_window_id, self.tab_id,
                        (color << 8) | 8, pw, g.left - pw, g.top - pw, g.right + pw,
                        g.bottom + pw
                    )
