#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import OpenGL.GL as gl
import sys

from kitty.shaders import ShaderProgram, array, GL_VERSION
from kitty.fonts import set_font_family, render_cell, cell_size


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


class Renderer:

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.do_layout()
        self.program = rectangle_texture()
        print(gl.glGetIntegerv(gl.GL_MAX_VERTEX_UNIFORM_COMPONENTS))
        print(gl.glGetIntegerv(gl.GL_MAX_UNIFORM_BLOCK_SIZE))
        print(gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS))

    def on_resize(self, window, w, h):
        gl.glViewport(0, 0, w, h)
        self.w, self.h = w, h
        self.do_layout()

    def do_layout(self):
        # Divide into cells
        cell_width, cell_height = cell_size()
        self.cells_per_line = self.w // cell_width
        self.lines_per_screen = self.h // cell_height

    def render(self):
        rectangle_texture(self.program)


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


def rectangle_vertices(left=-0.8, top=0.8, right=0.8, bottom=-0.8):
    vertex_data = array(
        right, top,
        right, bottom,
        left, bottom,
        right, top,
        left, bottom,
        left, top
    )

    texture_coords = array(
        1, 0,  # right top
        1, 1,  # right bottom
        0, 1,  # left bottom
        1, 0,  # right top
        0, 1,  # left bottom
        0, 0)  # left top
    return vertex_data, texture_coords


textured_shaders = (
    '''\
in vec2 vertex;
in vec2 texture_position;
out vec2 texture_position_for_fs;

void main() {
    gl_Position = vec4(vertex, 0, 1);
    texture_position_for_fs = texture_position;
}
''',

    '''\
uniform sampler2D tex;
in vec2 texture_position_for_fs;
out vec4 final_color;
const vec3 background = vec3(0, 1, 0);
const vec3 foreground = vec3(0, 0, 1);

void main() {
    float alpha = texture(tex, texture_position_for_fs).r;
    vec3 color = background * (1 - alpha) + foreground * alpha;
    final_color = vec4(color, 1);
}
''')


def texture_data():
    cell = render_cell('K')[0]
    w, h = cell_size()
    return cell, w, h


def rectangle_texture(program=None):
    if program is None:
        program = ShaderProgram(*textured_shaders)
        img_data, w, h = texture_data()
        with program:
            program.set_2d_texture('tex', img_data, w, h)
            rv, texc = rectangle_vertices()
            program.set_attribute_data('vertex', rv)
            program.set_attribute_data('texture_position', texc)
        return program
    else:
        with program:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)


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
