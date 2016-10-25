#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw
import OpenGL.GL as gl
import sys
from PIL import Image
import numpy
import ctypes

from kitty.shaders import ShaderProgram, VertexArrayObject

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
        triangle_texture(window)
    finally:
        glfw.glfwDestroyWindow(window)


def rectangle(window):
    program = ShaderProgram(vertex_shader, fragment)
    vao = VertexArrayObject()

    with program, vao:
        vao.make_rectangle()
        vertex = program.attribute_location('vertex')
        gl.glEnableVertexAttribArray(vertex)
        gl.glVertexAttribPointer(
            vertex, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program, vao:
            # Activate the texture
            # glActiveTexture(GL_TEXTURE0)
            # glBindTexture(GL_TEXTURE_2D, texture_id)
            # sampler_loc = program.attribute_location('texture_sampler')
            # glUniform1i(sampler_loc, 0)

            # Modern GL makes the draw call really simple
            # All the complexity has been pushed elsewhere
            gl.glDrawElements(gl.GL_TRIANGLE_STRIP, 4, gl.GL_UNSIGNED_BYTE, None)

        # Now lets show our master piece on the screen
        glfw.glfwSwapBuffers(window)
        glfw.glfwWaitEvents()


def triangle(window):
    program = ShaderProgram(vertex_shader, fragment)
    vao = VertexArrayObject()
    with program, vao:
        vao.make_triangle()
        vertex = program.attribute_location('vertex')
        gl.glEnableVertexAttribArray(vertex)
        gl.glVertexAttribPointer(
            vertex, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program, vao:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        glfw.glfwSwapBuffers(window)
        glfw.glfwWaitEvents()


def triangle_texture(window):
    program = ShaderProgram(
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
    // final_color = vec4(texture_position_out, 0, 1.0);
}
        ''')

    vao = VertexArrayObject()
    img = Image.open('/home/kovid/work/calibre/resources/images/library.png')
    img_data = numpy.array(list(img.getdata()), numpy.int8)
    with program, vao:
        program.set_2d_texture('tex', img_data, img.size[0], img.size[1])
        vao.make_triangle(add_texture=True)
        vertex = program.attribute_location('vertex')
        gl.glEnableVertexAttribArray(vertex)
        gl.glVertexAttribPointer(
            vertex, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        texture_position = program.attribute_location('texture_position')
        gl.glEnableVertexAttribArray(texture_position)
        gl.glVertexAttribPointer(
            texture_position, 2, gl.GL_FLOAT, gl.GL_TRUE, 0, ctypes.c_void_p(6 * gl.sizeof(gl.GLfloat)))

    while not glfw.glfwWindowShouldClose(window):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        with program, vao:
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

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
