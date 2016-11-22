#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import glfw_constants
import sys
import ctypes

from kitty.shaders import ShaderProgram, GL_VERSION, Sprites
from kitty.fonts import set_font_family, cell_size
from kitty.char_grid import calculate_screen_geometry, cell_shader
from kitty.fast_data_types import (
    glViewport, enable_automatic_opengl_error_checking, glClearColor,
    glUniform2f, glUniform4f, glUniform2ui, glUniform1i, glewInit, glGetString,
    GL_VERSION as GL_VERSION_C, GL_VENDOR, GL_SHADING_LANGUAGE_VERSION, GL_RENDERER,
    glClear, GL_COLOR_BUFFER_BIT, GL_TRIANGLE_FAN, glDrawArraysInstanced,
    Cursor, LineBuf, ColorProfile
)


def rectangle_uv(left=0, top=0, right=1, bottom=1):
    return (
        right, top,
        right, bottom,
        left, bottom,
        right, top,
        left, bottom,
        left, top,
    )


class Renderer:

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.color_pairs = (
            (0xffffff, 0),
            (0, 0xffffff),
            (0xffff00, 0x0000ff)
        )
        self.color_profile = ColorProfile()
        self.program = ShaderProgram(*cell_shader)
        self.sprites = Sprites()
        self.sprites.initialize()
        self.do_layout()

    def on_resize(self, window, w, h):
        glViewport(0, 0, w, h)
        self.w, self.h = w, h
        self.do_layout()

    def do_layout(self):
        # Divide into cells
        cell_width, cell_height = cell_size()
        self.sprites.do_layout(cell_width, cell_height)
        self.sprites.ensure_state()
        self.screen_geometry = sg = calculate_screen_geometry(cell_width, cell_height, self.w, self.h)
        data = (ctypes.c_uint * (sg.xnum * sg.ynum * 9))()
        lb = LineBuf(sg.ynum, sg.xnum)
        i = -1
        for y in range(sg.ynum):
            line = lb.line(y)
            for x in range(sg.xnum):
                i += 1
                c = Cursor()
                fg, bg = self.color_pairs[i % 3]
                c.fg = (fg << 8) | 3
                c.bg = (bg << 8) | 3
                c.x = x
                line.set_text('%d' % (i % 10), 0, 1, c)
            self.sprites.backend.update_cell_data(line, 0, sg.xnum - 1, self.color_profile, 0xffffff, 0, ctypes.addressof(data))
        self.sprites.render_dirty_cells()
        self.sprites.set_sprite_map(data)

    def render(self):
        self.sprites.render_dirty_cells()
        with self.program:
            ul = self.program.uniform_location
            sg = self.screen_geometry
            glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
            glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
            glUniform1i(ul('sprites'), self.sprites.sampler_num)
            glUniform1i(ul('sprite_map'), self.sprites.buffer_sampler_num)
            glUniform2f(ul('sprite_layout'), *self.sprites.layout)
            with self.sprites:
                glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)

# window setup {{{


def key_callback(key, action):
    """ Sample keyboard callback function """
    print('Key: %s Action: %s pressed' % (key, action))


def gl_get_unicode(k):
    ans = glGetString(k)
    if isinstance(ans, bytes):
        try:
            ans = ans.decode('utf-8')
        except Exception:
            ans = repr(ans)
    return ans


def _main():
    # These Window hints are used to specify
    # which opengl version to use and other details
    # for the opengl context that will be created
    glfw.glfwWindowHint(glfw_constants.GLFW_CONTEXT_VERSION_MAJOR, GL_VERSION[0])
    glfw.glfwWindowHint(glfw_constants.GLFW_CONTEXT_VERSION_MINOR, GL_VERSION[1])
    glfw.glfwWindowHint(glfw_constants.GLFW_OPENGL_PROFILE,
                        glfw_constants.GLFW_OPENGL_CORE_PROFILE)
    glfw.glfwWindowHint(glfw_constants.GLFW_OPENGL_FORWARD_COMPAT, True)

    window = glfw.glfwCreateWindow(
        1024, 1024, "Trying this crap".encode('utf-8'), None, None)
    if not window:
        raise SystemExit("glfwCreateWindow failed")
    glfw.glfwMakeContextCurrent(window)
    glewInit()
    glfw.glfwSwapInterval(1)

    # If everything went well the following calls
    # will display the version of opengl being used
    print('Vendor: %s' % (gl_get_unicode(GL_VENDOR)))
    print('Opengl version: %s' % (gl_get_unicode(GL_VERSION_C)))
    print('GLSL Version: %s' % (gl_get_unicode(GL_SHADING_LANGUAGE_VERSION)))
    print('Renderer: %s' % (gl_get_unicode(GL_RENDERER)))

    r = Renderer(1024, 1024)
    glfw.glfwSetFramebufferSizeCallback(window, r.on_resize)
    try:
        glClearColor(0.5, 0.5, 0.5, 0)
        while not glfw.glfwWindowShouldClose(window):
            glClear(GL_COLOR_BUFFER_BIT)
            r.render()
            glfw.glfwSwapBuffers(window)
            glfw.glfwWaitEvents()
    finally:
        glfw.glfwDestroyWindow(window)


def on_error(code, msg):
    if isinstance(msg, bytes):
        try:
            msg = msg.decode('utf-8')
        except Exception:
            msg = repr(msg)
    print(msg, file=sys.stderr)


def main():
    glfw.glfwSetErrorCallback(on_error)
    if not glfw.glfwInit():
        raise SystemExit('GLFW initialization failed')
    enable_automatic_opengl_error_checking(True)
    set_font_family('monospace', 144)
    try:
        _main()
    finally:
        glfw.glfwTerminate()
# }}}
