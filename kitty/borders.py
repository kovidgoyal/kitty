#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes

from .constants import viewport_size
from .fast_data_types import glUniform3fv, GL_TRIANGLE_STRIP, glDrawArrays
from .layout import available_height
from .utils import get_dpi
from .shaders import ShaderProgram


def as_color(c):
    return c[0] / 255, c[1] / 255, c[2] / 255


def to_opengl(x, y):
    return -1 + 2 * x / viewport_size.width, 1 - 2 * y / viewport_size.height


def as_rect(left, top, right, bottom, color=0):
    for (x, y) in ((left, bottom), (right, bottom), (right, top), (left, top)):
        x, y = to_opengl(x, y)
        yield x
        yield y
        yield color


class BordersProgram(ShaderProgram):

    def __init__(self):
        ShaderProgram.__init__(self, '''\
uniform vec3 colors[3];
in vec3 vertex;
out vec3 color;

void main() {
    gl_Position = vec4(vertex[0], vertex[1], 0, 1);
    color = colors[uint(vertex[2])];
}
''', '''\
in vec3 color;
out vec4 final_color;

void main() {
    final_color = vec4(color, 1);
}
        ''')
        self.add_vertex_array('rects')

    def send_data(self, data):
        self.send_vertex_data('rects', data)

    def set_colors(self, color_buf):
        glUniform3fv(self.uniform_location('colors'), 3, ctypes.addressof(color_buf))


class Borders:

    def __init__(self, opts):
        self.is_dirty = False
        self.can_render = False
        dpix, dpiy = get_dpi()['logical']
        dpi = (dpix + dpiy) / 2
        self.border_width = round(opts.window_border_width * dpi / 72)
        self.color_buf = (ctypes.c_float * 9)(
            *as_color(opts.background),
            *as_color(opts.active_border_color),
            *as_color(opts.inactive_border_color)
        )

    def __call__(self, windows, active_window, draw_window_borders=True):
        self.can_render = True
        self.is_dirty = True
        vw, vh = viewport_size.width, available_height()
        if windows:
            left_edge = min(w.geometry.left for w in windows)
            right_edge = max(w.geometry.right for w in windows)
            top_edge = min(w.geometry.top for w in windows)
            bottom_edge = max(w.geometry.bottom for w in windows)
        else:
            left_edge = top_edge = 0
            right_edge = vw
            bottom_edge = vh
        rects = []
        if left_edge > 0:
            rects.extend(as_rect(0, 0, left_edge, vh))
        if top_edge > 0:
            rects.extend(as_rect(0, 0, vw, top_edge))
        if right_edge < vw:
            rects.extend(as_rect(right_edge, 0, vw, vh))
        if bottom_edge < vh:
            rects.extend(as_rect(0, bottom_edge, vw, vh))
        if draw_window_borders and self.border_width > 0:
            bw = self.border_width
            for w in windows:
                g = w.geometry
                color = 1 if w is active_window else 2
                rects.extend(as_rect(g.left - bw, g.top - bw, g.left, g.bottom + bw, color))
                rects.extend(as_rect(g.left - bw, g.top - bw, g.right + bw, g.top, color))
                rects.extend(as_rect(g.right, g.top - bw, g.right + bw, g.bottom + bw, color))
                rects.extend(as_rect(g.left - bw, g.bottom, g.right + bw, g.bottom + bw, color))
        self.data = (ctypes.c_float * len(rects))()
        for i, x in enumerate(rects):
            self.data[i] = x

    def render(self, program):
        if not self.can_render:
            return
        with program:
            if self.is_dirty:
                program.send_data(self.data)
                program.set_colors(self.color_buf)
                self.is_dirty = False
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
