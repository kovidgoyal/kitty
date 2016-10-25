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
        self.is_active = False
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
        self.vao_id = gl.glGenVertexArrays(1)
        self.attribute_buffers = {}

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
        gl.glBindVertexArray(self.vao_id)
        self.is_active = True
        if self.texture_id is not None:
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture_id)
            gl.glUniform1i(self.texture_var, 0)  # 0 because using GL_TEXTURE0

    def __exit__(self, *args):
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)
        self.is_active = False

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

    def set_attribute_data(self, attribute_name, data, items_per_attribute_value=2, volatile=False, normalize=False):
        if not self.is_active:
            raise RuntimeError('The program must be active before you can add buffers')
        if len(data) % items_per_attribute_value != 0:
            raise ValueError('The length of the data buffer is not a multiple of the items_per_attribute_value')
        buf_id = self.attribute_buffers[attribute_name] = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buf_id)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, ArrayDatatype.arrayByteCount(data), data, gl.GL_STREAM_DRAW if volatile else gl.GL_STATIC_DRAW)
        loc = self.attribute_location(attribute_name)
        gl.glEnableVertexAttribArray(loc)
        typ = {
            gl.GLfloat: gl.GL_FLOAT,
            gl.GLubyte: gl.GL_UNSIGNED_BYTE,
            gl.GLuint: gl.GL_UNSIGNED_INT,
        }[data._type_]
        gl.glVertexAttribPointer(
            loc, items_per_attribute_value, typ, gl.GL_TRUE if normalize else gl.GL_FALSE, 0, None
        )


def array(*args, dtype=gl.GLfloat):
    return (dtype * len(args))(*args)
