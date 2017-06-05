#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from ctypes import addressof
from itertools import chain
from threading import Lock

from .constants import GLfloat, GLint, GLuint, viewport_size
from .fast_data_types import GL_TRIANGLE_FAN, glMultiDrawArrays, glUniform3fv
from .shaders import ShaderProgram
from .utils import pt_to_px


def as_color(c):
    return c[0] / 255, c[1] / 255, c[2] / 255


def to_opengl(x, y):
    return -1 + 2 * x / viewport_size.width, 1 - 2 * y / viewport_size.height


def as_rect(left, top, right, bottom, color=0):
    for (x, y) in ((right, top), (right, bottom), (left, bottom), (left, top)):
        x, y = to_opengl(x, y)
        yield x
        yield y
        yield color


class BordersProgram(ShaderProgram):

    def __init__(self):
        ShaderProgram.__init__(self, '''\
uniform vec3 colors[3];
in vec3 rect;
out vec3 color;

void main() {
    gl_Position = vec4(rect[0], rect[1], 0, 1);
    color = colors[uint(rect[2])];
}
''', '''\
in vec3 color;
out vec4 final_color;

void main() {
    final_color = vec4(color, 1);
}
        ''')
        self.add_vertex_array('rect')

    def send_data(self, data):
        self.send_vertex_data('rect', data)

    def set_colors(self, color_buf):
        glUniform3fv(self.uniform_location('colors'), 3, addressof(color_buf))


class Borders:

    def __init__(self, opts):
        self.is_dirty = False
        self.lock = Lock()
        self.can_render = False
        self.border_width = pt_to_px(opts.window_border_width)
        self.color_buf = (GLfloat * 9)(
            *as_color(opts.background),
            *as_color(opts.active_border_color),
            *as_color(opts.inactive_border_color)
        )

    def __call__(self, windows, active_window, current_layout, extra_blank_rects, draw_window_borders=True):
        rects = []
        for br in chain(current_layout.blank_rects, extra_blank_rects):
            rects.extend(as_rect(*br))
        if draw_window_borders and self.border_width > 0:
            bw = self.border_width
            for w in windows:
                g = w.geometry
                color = 1 if w is active_window else 2
                rects.extend(as_rect(g.left - bw, g.top - bw, g.left, g.bottom + bw, color))
                rects.extend(as_rect(g.left - bw, g.top - bw, g.right + bw, g.top, color))
                rects.extend(as_rect(g.right, g.top - bw, g.right + bw, g.bottom + bw, color))
                rects.extend(as_rect(g.left - bw, g.bottom, g.right + bw, g.bottom + bw, color))
        with self.lock:
            self.num_of_rects = len(rects) // 12
            self.rects = (GLfloat * len(rects))()
            self.starts = (GLint * self.num_of_rects)()
            self.counts = (GLuint * self.num_of_rects)()
            for i, x in enumerate(rects):
                self.rects[i] = x
                if i % 12 == 0:
                    idx = i // 12
                    self.starts[idx] = i // 3
                    self.counts[idx] = 4
            self.is_dirty = True
            self.can_render = True

    def render(self, program):
        with self.lock:
            if not self.can_render:
                return
            with program:
                if self.is_dirty:
                    program.send_data(self.rects)
                    program.set_colors(self.color_buf)
                    self.is_dirty = False
                glMultiDrawArrays(GL_TRIANGLE_FAN, addressof(self.starts), addressof(self.counts), self.num_of_rects)
