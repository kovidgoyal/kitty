#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.arrays import ArrayDatatype
import OpenGL.GL as gl

from .fonts import render_cell, cell_size

GL_VERSION = (4, 1)
VERSION = GL_VERSION[0] * 100 + GL_VERSION[1] * 10


class TextureManager:

    def __init__(self):
        self.textures = []
        self.current_texture_array = None
        self.current_array_dirty = False
        self.current_array_data = None
        self.arraylengths = {}
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.max_array_len = gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS)
        self.max_active_textures = gl.glGetIntegerv(gl.GL_MAX_TEXTURE_IMAGE_UNITS)

    def ensure_texture_array(self, amt=2):
        if self.current_texture_array is None or self.arraylengths[self.current_texture_array] > self.max_array_len - amt:
            if self.current_texture_array is not None and len(self.textures) >= self.max_active_textures:
                raise RuntimeError('No space left to allocate character textures')
            if self.current_array_dirty:
                self.commit_current_array()
            self.current_texture_array = gl.glGenTextures(1)
            self.current_array_data = None
            self.current_array_dirty = False
            self.textures.append(self.current_texture_array)
            self.arraylengths[self.current_texture_array] = 0

    def texture_ids_for(self, items):
        for key in items:
            first = self.first_cell_cache.get(key)
            if first is None:
                self.ensure_texture_array()
                first, second = render_cell(*key)
                items = (first, second) if second is not None else (first,)
                texture_unit = len(self.textures) - 1
                layerf = len(self.arraylengths[self.current_texture_array])
                self.append_to_current_array(items)
                self.first_cell_cache[key] = first = texture_unit, layerf
                if second is not None:
                    self.second_cell_cache[key] = texture_unit, layerf + 1
            yield first, self.second_cell_cache.get(key)
        if self.current_array_dirty:
            self.commit_current_array()

    def commit_current_array(self):
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.current_texture_array)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        width, height = cell_size()
        gl.glTexStorage3D(gl.GL_TEXTURE_2D_ARRAY, 0, gl.GL_R8, width, height, self.arraylengths[self.current_texture_array])
        gl.glTexSubImage3D(gl.GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, self.arraylengths[
                           self.current_texture_array], gl.GL_RED, gl.GL_UNSIGNED_BYTE, self.current_array_data)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)
        self.current_array_dirty = False

    def append_to_current_array(self, items):
        current_len = len(self.current_array_data or '')
        self.arraylengths[self.current_texture_array] += len(items)
        new_data = (gl.GLubyte * (current_len + sum(map(len, items))))()
        if current_len:
            new_data[:current_len] = self.current_array_data
            gl.glDeleteTextures([self.current_texture_array])
        pos = current_len
        for i in items:
            new_data[pos:pos + len(i)] = i
            pos += len(i)
        self.current_array_data = new_data
        self.current_array_dirty = True

    def __enter__(self):
        for i, texture_id in enumerate(self.textures):
            gl.glActiveTexture(getattr(gl, 'GL_TEXTURE{}'.format(i)))
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, texture_id)

    def __exit__(self, *a):
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)


class ShaderProgram:
    """ Helper class for using GLSL shader programs """

    def __init__(self, vertex, fragment):
        """
        Create a shader program.

        """
        self.program_id = gl.glCreateProgram()
        self.texture_id = None
        self.is_active = False
        vs_id = self.add_shader(vertex, gl.GL_VERTEX_SHADER)
        gl.glAttachShader(self.program_id, vs_id)

        frag_id = self.add_shader(fragment, gl.GL_FRAGMENT_SHADER)
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
        source = '#version {}\n{}'.format(VERSION, source)
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
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture_id)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glUniform1i(self.texture_var, 0)  # 0 because using GL_TEXTURE0

    def __exit__(self, *args):
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)
        self.is_active = False

    def set_2d_texture(self, var_name, data, width, height, data_type='red',
                       min_filter=gl.GL_LINEAR, mag_filter=gl.GL_LINEAR,
                       swrap=gl.GL_CLAMP_TO_EDGE, twrap=gl.GL_CLAMP_TO_EDGE):
        if not self.is_active:
            raise RuntimeError('The program must be active before you can add buffers')
        if self.texture_id is not None:
            gl.glDeleteTextures([self.texture_id])
        texture_id = self.texture_id = gl.glGenTextures(1)
        self.texture_var = self.uniform_location(var_name)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture_id)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1 if data_type == 'red' else 4)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, min_filter)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, mag_filter)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, swrap)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, twrap)
        internal_format, external_format = {
            'rgba': (gl.GL_RGBA8, gl.GL_RGBA),
            'rgb': (gl.GL_RGB8, gl.GL_RGB),
            'red': (gl.GL_R8, gl.GL_RED),
        }[data_type]
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, internal_format, width, height,
                        0, external_format, gl.GL_UNSIGNED_BYTE, data)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        return texture_id

    def set_attribute_data(self, attribute_name, data, items_per_attribute_value=2, divisor=None, normalize=False):
        if not self.is_active:
            raise RuntimeError('The program must be active before you can add buffers')
        if len(data) % items_per_attribute_value != 0:
            raise ValueError('The length of the data buffer is not a multiple of the items_per_attribute_value')
        buf_id = self.attribute_buffers.get(attribute_name)  # glBufferData auto-deletes previous data
        if buf_id is None:
            buf_id = self.attribute_buffers[attribute_name] = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buf_id)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, ArrayDatatype.arrayByteCount(data), data, gl.GL_STATIC_DRAW)
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
        if divisor is not None:
            gl.glVertexBindingDivisor(loc, divisor)


def array(*args, dtype=gl.GLfloat):
    return (dtype * len(args))(*args)
