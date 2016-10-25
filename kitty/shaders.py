#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.arrays import ArrayDatatype
import OpenGL.GL as gl


class ShaderProgram:
    """ Helper class for using GLSL shader programs """

    def __init__(self, vertex: str, fragment: str):
        """
        Create a shader program.

        :param vertex: The vertex shader
        :param fragment: The fragment shader

        """
        self.program_id = gl.glCreateProgram()
        self.texture_id = None
        vs_id = self.add_shader(vertex, gl.GL_VERTEX_SHADER)
        frag_id = self.add_shader(fragment, gl.GL_FRAGMENT_SHADER)

        gl.glAttachShader(self.program_id, vs_id)
        gl.glAttachShader(self.program_id, frag_id)
        gl.glLinkProgram(self.program_id)

        if gl.glGetProgramiv(self.program_id, gl.GL_LINK_STATUS) != gl.GL_TRUE:
            info = gl.glGetProgramInfoLog(self.program_id)
            gl.glDeleteProgram(self.program_id)
            gl.glDeleteShader(vs_id)
            gl.glDeleteShader(frag_id)
            raise ValueError('Error linking shader program: %s' % info)
        gl.glDeleteShader(vs_id)
        gl.glDeleteShader(frag_id)

    def __hash__(self) -> int:
        return self.program_id

    def __eq__(self, other) -> bool:
        return isinstance(other, ShaderProgram) and other.program_id == self.program_id

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def add_shader(self, source: str, shader_type: int) -> int:
        ' Compile a shader and return its id, or raise an exception if compilation fails '
        shader_id = gl.glCreateShader(shader_type)
        try:
            gl.glShaderSource(shader_id, source)
            gl.glCompileShader(shader_id)
            if gl.glGetShaderiv(shader_id, gl.GL_COMPILE_STATUS) != gl.GL_TRUE:
                info = gl.glGetShaderInfoLog(shader_id)
                raise ValueError('GLSL Shader compilation failed: %s' % info)
            return shader_id
        except Exception:
            gl.glDeleteShader(shader_id)
            raise

    @lru_cache(maxsize=None)
    def uniform_location(self, name: str) -> int:
        ' Return the id for the uniform variable `name` or -1 if not found. '
        return gl.glGetUniformLocation(self.program_id, name)

    @lru_cache(maxsize=None)
    def attribute_location(self, name: str) -> int:
        ' Return the id for the attribute variable `name` or -1 if not found. '
        return gl.glGetAttribLocation(self.program_id, name)

    def __enter__(self):
        gl.glUseProgram(self.program_id)
        if self.texture_id is not None:
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture_id)
            gl.glUniform1i(self.texture_var, 0)  # 0 because using GL_TEXTURE0

    def __exit__(self, *args):
        gl.glUseProgram(0)

    def set_2d_texture(self, var_name, data, width, height, data_type='rgba',
                       min_filter=gl.GL_LINEAR, mag_filter=gl.GL_LINEAR,
                       swrap=gl.GL_CLAMP_TO_EDGE, twrap=gl.GL_CLAMP_TO_EDGE):
        texture_id = self.texture_id = gl.glGenTextures(1)
        self.texture_var = self.uniform_location(var_name)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1 if data_type == 'red' else 4)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, min_filter)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, mag_filter)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, swrap)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, twrap)
        internal_format, external_format = {
            'rgba': (gl.GL_RGBA8, gl.GL_RGBA),
            'rgb': (gl.GL_RGB8, gl.GL_RGB),
            'red': (gl.GL_RED, gl.GL_RED),
        }[data_type]
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, internal_format, width, height,
                        0, external_format, gl.GL_UNSIGNED_BYTE, data)
        return texture_id


def array(*args, dtype=gl.GLfloat):
    return (dtype * len(args))(*args)


def make_buffer(data, target=gl.GL_ARRAY_BUFFER, usage=gl.GL_STREAM_DRAW):
    buf_id = gl.glGenBuffers(1)
    gl.glBindBuffer(target, buf_id)
    gl.glBufferData(target, ArrayDatatype.arrayByteCount(data), data, usage)
    return buf_id


class VertexArrayObject:

    def __init__(self):
        self.vao_id = gl.glGenVertexArrays(1)
        self.is_active = False
        self.texture_id = None

    def __enter__(self):
        gl.glBindVertexArray(self.vao_id)
        self.is_active = True

    def __exit__(self, *a):
        gl.glBindVertexArray(0)
        self.is_active = False

    def make_triangle(self, width=0.8, height=0.8, add_texture=False, usage=gl.GL_STATIC_DRAW):
        if not self.is_active:
            raise RuntimeError('This VertexArrayObject is not active')
        if add_texture:
            vertices = array(
                0.0, height,
                -width, -height,
                width, -height,
                0.5, 1.0,
                0.0, 0.0,
                1.0, 0.0
            )
        else:
            vertices = array(
                0.0, height,
                -width, -height,
                width, -height,
            )
        make_buffer(vertices, usage=usage)

    def make_rectangle(self, left=-0.8, top=0.8, right=0.8, bottom=-0.8, usage=gl.GL_STATIC_DRAW):
        if not self.is_active:
            raise RuntimeError('This VertexArrayObject is not active')
        vertices = array(
            left, bottom,
            right, bottom,
            left, top,
            right, top
        )
        make_buffer(vertices, usage=usage)
        elements = array(0, 1, 2, 3, dtype=gl.GLubyte)
        make_buffer(elements, gl.GL_ELEMENT_ARRAY_BUFFER, usage=usage)
