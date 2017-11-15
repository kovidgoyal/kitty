#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial
from itertools import chain

from .fast_data_types import (
    BORDERS_PROGRAM, add_borders_rect, compile_program, init_borders_program
)
from .utils import color_as_int, load_shaders, pt_to_px


def vertical_edge(os_window_id, tab_id, color, width, top, bottom, left):
    add_borders_rect(os_window_id, tab_id, left, top, left + width, bottom, color)


def horizontal_edge(os_window_id, tab_id, color, height, left, right, top):
    add_borders_rect(os_window_id, tab_id, left, top, right, top + height, color)


def edge(func, os_window_id, tab_id, color, sz, a, b):
    return partial(func, os_window_id, tab_id, color, sz, a, b)


def border(os_window_id, tab_id, color, sz, left, top, right, bottom):
    horz = edge(horizontal_edge, os_window_id, tab_id, color, sz, left, right)
    horz(top), horz(bottom - sz)  # top, bottom edges
    vert = edge(vertical_edge, color, sz, top, bottom)
    vert(left), vert(right - sz)  # left, right edges


def load_borders_program():
    compile_program(BORDERS_PROGRAM, *load_shaders('border'))
    init_borders_program()
    Borders.program_initialized = True


class Borders:

    def __init__(self, os_window_id, tab_id, opts):
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.border_width = pt_to_px(opts.window_border_width)
        self.padding_width = pt_to_px(opts.window_padding_width)
        self.background = color_as_int(opts.background)
        self.active_border = color_as_int(opts.active_border_color)
        self.inactive_border = color_as_int(opts.inactive_border_color)

    def __call__(
        self,
        windows,
        active_window,
        current_layout,
        extra_blank_rects,
        draw_window_borders=True
    ):
        add_borders_rect(self.os_window_id, self.tab_id, 0, 0, 0, 0, 0)
        for br in chain(current_layout.blank_rects, extra_blank_rects):
            add_borders_rect(self.os_window_id, self.tab_id, *br, self.background)
        bw, pw = self.border_width, self.padding_width
        fw = bw + pw

        if fw > 0:
            for w in windows:
                g = w.geometry
                if bw > 0 and draw_window_borders:
                    # Draw the border rectangles
                    color = self.active_border if w is active_window else self.inactive_border
                    border(
                        self.os_window_id, self.tab_id,
                        color, bw, g.left - fw, g.top - fw, g.right + fw,
                        g.bottom + fw
                    )
                if pw > 0:
                    # Draw the background rectangles over the padding region
                    color = self.background
                    border(
                        self.os_window_id, self.tab_id,
                        color, pw, g.left - pw, g.top - pw, g.right + pw,
                        g.bottom + pw
                    )
