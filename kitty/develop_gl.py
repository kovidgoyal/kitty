#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import OpenGL.GL as gl
import sys

from kitty.shaders import ShaderProgram, GL_VERSION, ortho_matrix
from kitty.fonts import set_font_family, cell_size

textured_shaders = (
    '''\
in vec2 vertex;
in vec3 texture_position;
out vec3 texture_position_for_fs;
uniform mat4 transform;

void main() {
    gl_Position = transform * vec4(vertex, 0, 1);
    texture_position_for_fs = texture_position;
}
''',

    '''\
uniform sampler2DArray sprites;
uniform vec3 sprite_scale;
in vec3 texture_position_for_fs;
out vec4 final_color;
const vec3 background = vec3(0, 1, 0);
const vec3 foreground = vec3(0, 0, 1);

void main() {
    float alpha = texture(sprites, texture_position_for_fs / sprite_scale).r;
    vec3 color = background * (1 - alpha) + foreground * alpha;
    final_color = vec4(color, 1);
}
''')


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
        self.program = ShaderProgram(*textured_shaders)
        chars = '0123456789'
        sprite_vecs = (s[0] for s in self.program.sprites.positions_for(((x, False, False) for x in chars)))
        self.sprite_map = {i: v for i, v in enumerate(sprite_vecs)}
        self.do_layout()

    def on_resize(self, window, w, h):
        gl.glViewport(0, 0, w, h)
        self.w, self.h = w, h
        self.do_layout()

    def do_layout(self):
        # Divide into cells
        cell_width, cell_height = cell_size()
        xnum = self.w // cell_width
        ynum = self.h // cell_height
        vertices = (gl.GLfloat * (xnum * ynum * 12))()
        uv = (gl.GLfloat * (xnum * ynum * 18))()
        num = 0
        for r in range(ynum):
            aoff = r * xnum * 12
            uoff = r * xnum * 18
            for c in range(xnum):
                off = aoff + c * 12
                vertices[off:off + 12] = rectangle_vertices(left=c, top=r, right=c + 1, bottom=r + 1)
                sprite_pos = self.sprite_map[num % 10]
                off = uoff + c * 18
                uv[off:off + 18] = rectangle_uv(*sprite_pos)
                num += 1
        self.transform = ortho_matrix(right=xnum, bottom=ynum)
        with self.program:
            self.program.set_attribute_data('vertex', vertices)
            self.program.set_attribute_data('texture_position', uv, items_per_attribute_value=3)
        self.num_vertices = len(vertices) // 2

    def render(self):
        with self.program:
            gl.glUniformMatrix4fv(self.program.uniform_location('transform'), 1, gl.GL_TRUE, self.transform)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.num_vertices)


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


def rectangle_vertices(left=0, top=0, right=1, bottom=1):
    return (
        right, top,
        right, bottom,
        left, bottom,
        right, top,
        left, bottom,
        left, top
    )


def rectangle_uv(left=0., top=1., right=1., bottom=0., z=0.):
    return (
        right, top, z,
        right, bottom, z,
        left, bottom, z,
        right, top, z,
        left, bottom, z,
        left, top, z
    )


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
