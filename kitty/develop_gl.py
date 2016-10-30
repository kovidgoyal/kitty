#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import OpenGL.GL as gl
import sys

from kitty.shaders import ShaderProgram, GL_VERSION, Sprites, check_for_required_extensions
from kitty.fonts import set_font_family, cell_size
from kitty.char_grid import calculate_vertices, cell_shader


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
        self.color_pairs = [
            ((255, 255, 255), (0, 0, 0)),
            ((0, 0, 0), (255, 255, 255)),
            ((255, 255, 0), (0, 0, 255)),
        ]
        self.program = ShaderProgram(*cell_shader)
        self.sprites = Sprites()
        self.do_layout()

    def on_resize(self, window, w, h):
        gl.glViewport(0, 0, w, h)
        self.w, self.h = w, h
        self.do_layout()

    def do_layout(self):
        # Divide into cells
        cell_width, cell_height = cell_size()
        self.screen_geometry = sg = calculate_vertices(cell_width, cell_height, self.w, self.h)
        data = (gl.GLuint * (sg.xnum * sg.ynum * 9))()
        for i in range(0, len(data), 9):
            idx = i // 9
            c = '%d' % (idx % 10)
            data[i:i+3] = self.sprites.primary_sprite_position(c)
            fg, bg = self.color_pairs[idx % 3]
            data[i+3:i+9] = fg + bg
        self.sprites.set_sprite_map(data)

    def render(self):
        with self.program:
            ul = self.program.uniform_location
            sg = self.screen_geometry
            gl.glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
            gl.glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
            gl.glUniform1i(ul('sprites'), self.sprites.sampler_num)
            gl.glUniform1i(ul('sprite_map'), self.sprites.buffer_sampler_num)
            gl.glUniform2f(ul('sprite_layout'), *self.sprites.layout)
            with self.sprites:
                gl.glDrawArraysInstanced(gl.GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)

# window setup {{{


def key_callback(key, action):
    """ Sample keyboard callback function """
    print('Key: %s Action: %s pressed' % (key, action))


def gl_get_unicode(k):
    ans = gl.glGetString(k)
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
    glfw.glfwWindowHint(glfw.GLFW_CONTEXT_VERSION_MAJOR, GL_VERSION[0])
    glfw.glfwWindowHint(glfw.GLFW_CONTEXT_VERSION_MINOR, GL_VERSION[1])
    glfw.glfwWindowHint(glfw.GLFW_OPENGL_PROFILE,
                        glfw.GLFW_OPENGL_CORE_PROFILE)
    glfw.glfwWindowHint(glfw.GLFW_OPENGL_FORWARD_COMPAT, True)

    window = glfw.glfwCreateWindow(
        1024, 1024, "Trying this crap".encode('utf-8'), None, None)
    if not window:
        raise SystemExit("glfwCreateWindow failed")
    glfw.glfwMakeContextCurrent(window)
    glfw.glfwSwapInterval(1)
    check_for_required_extensions()

    # If everything went well the following calls
    # will display the version of opengl being used
    print('Vendor: %s' % (gl_get_unicode(gl.GL_VENDOR)))
    print('Opengl version: %s' % (gl_get_unicode(gl.GL_VERSION)))
    print('GLSL Version: %s' % (gl_get_unicode(gl.GL_SHADING_LANGUAGE_VERSION)))
    print('Renderer: %s' % (gl_get_unicode(gl.GL_RENDERER)))

    r = Renderer(1024, 1024)
    glfw.glfwSetFramebufferSizeCallback(window, r.on_resize)
    try:
        gl.glClearColor(0.5, 0.5, 0.5, 0)
        while not glfw.glfwWindowShouldClose(window):
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
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
    set_font_family('monospace', 144)
    try:
        _main()
    finally:
        glfw.glfwTerminate()
# }}}
