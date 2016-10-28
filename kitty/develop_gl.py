#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import OpenGL.GL as gl
import sys

from kitty.shaders import ShaderProgram, GL_VERSION, Sprites, check_for_required_extensions
from kitty.fonts import set_font_family, cell_size

textured_shaders = (
    '''\
uniform uvec2 dimensions;  // xnum, ynum
uniform vec4 steps;  // xstart, ystart, dx, dy
uniform vec2 sprite_layout;  // dx, dy
uniform usamplerBuffer sprite_map; // gl_InstanceID -> x, y, z
out vec3 sprite_pos;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

void main() {
    uint instance_id = uint(gl_InstanceID);
    uint r = instance_id / dimensions[0];
    uint c = instance_id - r * dimensions[0];
    float left = steps[0] + c * steps[2];
    float top = steps[1] - r * steps[3];
    vec2 xpos = vec2(left, left + steps[2]);
    vec2 ypos = vec2(top, top - steps[3]);
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos[0]], ypos[pos[1]], 0, 1);

    uvec4 spos = texelFetch(sprite_map, int(instance_id));
    vec2 s_xpos = vec2(spos[0], spos[0] + 1.0) * sprite_layout[0];
    vec2 s_ypos = vec2(spos[1], spos[1] + 1.0) * sprite_layout[1];
    sprite_pos = vec3(s_xpos[pos[0]], s_ypos[pos[1]], spos[2]);
}
''',

    '''\
uniform sampler2DArray sprites;
in vec3 sprite_pos;
out vec4 final_color;

const vec3 background = vec3(0, 0, 1);
const vec3 foreground = vec3(0, 1, 0);

void main() {
    float alpha = texture(sprites, sprite_pos).r;
    vec3 color = background * (1 - alpha) + foreground * alpha;
    final_color = vec4(color, 1);
}
''')


def rectangle_uv(left=0, top=0, right=1, bottom=1):
    return (
        right, top,
        right, bottom,
        left, bottom,
        right, top,
        left, bottom,
        left, top,
    )


def calculate_vertices(cell_width, cell_height, screen_width, screen_height):
    xnum = screen_width // cell_width
    ynum = screen_height // cell_height
    dx, dy = 2 * cell_width / screen_width, 2 * cell_height / screen_height
    xmargin = (screen_width - (xnum * cell_width)) / screen_width
    ymargin = (screen_height - (ynum * cell_height)) / screen_height
    xstart = -1 + xmargin
    ystart = 1 - ymargin
    return xnum, ynum, xstart, ystart, dx, dy


class Renderer:

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.program = ShaderProgram(*textured_shaders)
        self.sprites = Sprites()
        self.do_layout()

    def on_resize(self, window, w, h):
        gl.glViewport(0, 0, w, h)
        self.w, self.h = w, h
        self.do_layout()

    def do_layout(self):
        # Divide into cells
        cell_width, cell_height = cell_size()
        self.xnum, self.ynum, self.xstart, self.ystart, self.dx, self.dy = calculate_vertices(cell_width, cell_height, self.w, self.h)
        data = (gl.GLuint * (self.xnum * self.ynum * 3))()
        for i in range(0, self.xnum * self.ynum * 3, 3):
            c = '%d' % ((i // 3) % 10)
            data[i:i+3] = self.sprites.primary_sprite_position(c)
        self.sprites.set_sprite_map(data)

    def render(self):
        with self.program:
            ul = self.program.uniform_location
            gl.glUniform2ui(ul('dimensions'), self.xnum, self.ynum)
            gl.glUniform4f(ul('steps'), self.xstart, self.ystart, self.dx, self.dy)
            gl.glUniform1i(ul('sprites'), self.sprites.sampler_num)
            gl.glUniform1i(ul('sprite_map'), self.sprites.buffer_sampler_num)
            gl.glUniform2f(ul('sprite_layout'), *self.sprites.layout)
            with self.sprites:
                gl.glDrawArraysInstanced(gl.GL_TRIANGLE_FAN, 0, 4, self.xnum * self.ynum)

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
