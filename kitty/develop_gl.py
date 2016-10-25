#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import OpenGL.GL as gl
import sys
from PIL import Image
import numpy

from kitty.shaders import ShaderProgram, array

vertex_shader = """
# version 410
in vec2 vertex;

void main() {
    gl_Position = vec4(vertex, 0, 1);
}
"""


fragment = """
# version 410
out vec4 final_color;

void main(void)
{
    final_color = vec4(1.0);
}
"""


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


def on_resize(window, w, h):
    gl.glViewport(0, 0, w, h)


def _main():
    # These Window hints are used to specify
    # which opengl version to use and other details
    # for the opengl context that will be created
    glfw.glfwWindowHint(glfw.GLFW_CONTEXT_VERSION_MAJOR, 4)
    glfw.glfwWindowHint(glfw.GLFW_CONTEXT_VERSION_MINOR, 1)
    glfw.glfwWindowHint(glfw.GLFW_OPENGL_PROFILE,
                        glfw.GLFW_OPENGL_CORE_PROFILE)
    glfw.glfwWindowHint(glfw.GLFW_OPENGL_FORWARD_COMPAT, True)

    window = glfw.glfwCreateWindow(
        1024, 1024, "Trying this crap".encode('utf-8'), None, None)
    if not window:
        raise SystemExit("glfwCreateWindow failed")
    glfw.glfwMakeContextCurrent(window)
    glfw.glfwSwapInterval(1)
    glfw.glfwSetFramebufferSizeCallback(window, on_resize)

    # If everything went well the following calls
    # will display the version of opengl being used
    print('Vendor: %s' % (gl_get_unicode(gl.GL_VENDOR)))
    print('Opengl version: %s' % (gl_get_unicode(gl.GL_VERSION)))
    print('GLSL Version: %s' % (gl_get_unicode(gl.GL_SHADING_LANGUAGE_VERSION)))
    print('Renderer: %s' % (gl_get_unicode(gl.GL_RENDERER)))

    try:
        gl.glClearColor(0.5, 0.5, 0.5, 0)
        rectangle_texture(window)
    finally:
        glfw.glfwDestroyWindow(window)


def triangle_vertices(width=0.8, height=0.8):
    return array(
        0.0, height,
        -width, -height,
        width, -height,
    )


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


def rectangle(window):
    program = ShaderProgram(vertex_shader, fragment)

    with program:
        program.set_attribute_data('vertex', rectangle_vertices()[0])

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

        glfw.glfwSwapBuffers(window)
        glfw.glfwWaitEvents()


def triangle(window):
    program = ShaderProgram(vertex_shader, fragment)
    with program:
        program.set_attribute_data('vertex', triangle_vertices())

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        glfw.glfwSwapBuffers(window)
        glfw.glfwWaitEvents()

textured_shaders = (
    '''
#version 410
in vec2 vertex;
in vec2 texture_position;
out vec2 texture_position_out;

void main() {
    gl_Position = vec4(vertex, 0, 1);
    texture_position_out = texture_position;
}
        ''',

    '''
#version 410
uniform sampler2D tex;
in vec2 texture_position_out;
out vec4 final_color;

void main() {
    final_color = texture(tex, texture_position_out);
}
        ''')


def texture_data():
    img = Image.open('/home/kovid/work/calibre/resources/images/library.png')
    img_data = numpy.array(list(img.getdata()), numpy.int8)
    return img_data, img.size[0], img.size[1]


def triangle_texture(window):
    program = ShaderProgram(*textured_shaders)
    img_data, w, h = texture_data()
    with program:
        program.set_2d_texture('tex', img_data, w, h)
        program.set_attribute_data('vertex', triangle_vertices())
        program.set_attribute_data('texture_position', array(
            0.5, 1.0,
            0.0, 0.0,
            1.0, 0.0
        ))

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        glfw.glfwSwapBuffers(window)
        glfw.glfwWaitEvents()


def rectangle_texture(window):
    program = ShaderProgram(*textured_shaders)
    img_data, w, h = texture_data()
    with program:
        program.set_2d_texture('tex', img_data, w, h)
        rv, texc = rectangle_vertices()
        program.set_attribute_data('vertex', rv)
        program.set_attribute_data('texture_position', texc)

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

        glfw.glfwSwapBuffers(window)
        glfw.glfwWaitEvents()


def on_error(code, msg):
    if isinstance(msg, bytes):
        try:
            msg = msg.decode('utf-8')
        except Exception:
            msg = repr(msg)
    print(msg, file=sys.stderr)


def main():
    if not glfw.glfwInit():
        raise SystemExit('GLFW initialization failed')
    glfw.glfwSetErrorCallback(on_error)
    try:
        _main()
    finally:
        glfw.glfwTerminate()
