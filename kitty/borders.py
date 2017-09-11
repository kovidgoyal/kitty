#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from ctypes import addressof
from functools import partial
from itertools import chain

from .constants import GLfloat, GLuint, viewport_size
from .fast_data_types import (
    GL_STATIC_DRAW, GL_TRIANGLE_FAN, glDrawArraysInstanced, glUniform3fv,
    BORDERS_PROGRAM, GL_UNSIGNED_INT, glUniform2ui
)
from .shaders import ShaderProgram, load_shaders
from .utils import pt_to_px


def as_color(c):
    return c[0] / 255, c[1] / 255, c[2] / 255


def to_opengl(val, sz):
    return -1 + 2 * val / sz


def as_rect(left, top, right, bottom, color=0):
    yield left
    yield top
    yield right
    yield bottom


class BordersProgram(ShaderProgram):

    def __init__(self):
        ShaderProgram.__init__(self, BORDERS_PROGRAM, *load_shaders('border'))
        with self.array_object_creator() as add_attribute:
            self.vao_id = add_attribute.vao_id
            add_attribute('rect', size=4, dtype=GL_UNSIGNED_INT, divisor=1)

    def send_data(self, data):
        self.send_vertex_data(self.vao_id, data, usage=GL_STATIC_DRAW)

    def set_colors(self, color_buf):
        glUniform3fv(self.uniform_location('colors'), 3, addressof(color_buf))
        glUniform2ui(self.uniform_location('viewport'), viewport_size.width, viewport_size.height)


def border_maker(rects):
    ' Create a function that will add all the rectangles for drawing a border to rects '

    def r(l, t, b, r, color):
        rects.extend(as_rect(l, t, b, r, color))

    def vertical_edge(color, width, top, bottom, left):
        r(left, top, left + width, bottom, color)

    def horizontal_edge(color, height, left, right, top):
        r(left, top, right, top + height, color)

    def edge(func, color, sz, a, b):
        return partial(func, color, sz, a, b)

    def border(color, sz, left, top, right, bottom):
        horz = edge(horizontal_edge, color, sz, left, right)
        horz(top), horz(bottom - sz)  # top, bottom edges
        vert = edge(vertical_edge, color, sz, top, bottom)
        vert(left), vert(right - sz)  # left, right edges

    return border


class Borders:

    def __init__(self, opts):
        self.is_dirty = False
        self.can_render = False
        self.border_width = pt_to_px(opts.window_border_width)
        self.padding_width = pt_to_px(opts.window_padding_width)
        self.color_buf = (GLfloat * 9)(
            *as_color(opts.background), *as_color(opts.active_border_color),
            *as_color(opts.inactive_border_color))

    def __call__(
        self,
        windows,
        active_window,
        current_layout,
        extra_blank_rects,
        draw_window_borders=True
    ):
        rects = []
        for br in chain(current_layout.blank_rects, extra_blank_rects):
            rects.extend(as_rect(*br))
        bw, pw = self.border_width, self.padding_width
        fw = bw + pw
        border = border_maker(rects)

        if fw > 0:
            for w in windows:
                g = w.geometry
                if bw > 0 and draw_window_borders:
                    # Draw the border rectangles
                    color = 1 if w is active_window else 2
                    border(
                        color, bw, g.left - fw, g.top - fw, g.right + fw,
                        g.bottom + fw)
                if pw > 0:
                    # Draw the background rectangles over the padding region
                    color = 0
                    border(
                        color, pw, g.left - pw, g.top - pw, g.right + pw,
                        g.bottom + pw)

        self.num_of_rects = len(rects) // 4
        self.rects = (GLuint * len(rects))()
        for i, x in enumerate(rects):
            self.rects[i] = x
        self.is_dirty = True
        self.can_render = True

    def render(self, program):
        if not self.can_render:
            return
        with program:
            if self.is_dirty:
                program.send_data(self.rects)
                program.set_colors(self.color_buf)
                self.is_dirty = False
            with program.bound_vertex_array(program.vao_id):
                glDrawArraysInstanced(
                    GL_TRIANGLE_FAN, 0, 4, self.num_of_rects)
