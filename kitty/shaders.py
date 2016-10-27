#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.arrays import ArrayDatatype
import OpenGL.GL as gl

from .fonts import render_cell, cell_size, display_bitmap

GL_VERSION = (4, 1)
VERSION = GL_VERSION[0] * 100 + GL_VERSION[1] * 10


def array(*args, dtype=gl.GLfloat):
    return (dtype * len(args))(*args)


class Sprites:
    ''' Maintain sprite sheets of all rendered characters on the GPU as a texture
    array with each texture being a sprite sheet. '''

    def __init__(self, texture_unit=0):
        self.texture_unit = getattr(gl, 'GL_TEXTURE%d' % texture_unit)
        self.sampler_num = texture_unit
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.max_array_len = gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS)
        self.max_texture_size = gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)
        self.cell_width, self.cell_height = cell_size()
        self.xnum = self.max_texture_size // self.cell_width
        self.ynum = self.max_texture_size // self.cell_height
        # self.xnum = self.ynum = 2
        self.width = self.xnum * self.cell_width
        self.height = self.ynum * self.cell_height
        self.previous_layers = []
        self.current_layer_dirty = False
        self.current_layer_buffer = (gl.GLubyte * (self.width * self.height))()
        self.x = self.y = 0
        self.dx, self.dy = self.cell_width / self.width, self.cell_height / self.height
        self.texture_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.texture_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        self.commit_all_layers()

    def positions_for(self, items):
        ''' Yield 5-tuples (left, top, right, bottom, z) pointing to the desired sprite '''
        for key in items:
            first = self.first_cell_cache.get(key)
            if first is None:
                first, second = render_cell(*key)
                self.first_cell_cache[key] = first = self.add_sprite(first)
                if second is not None:
                    self.second_cell_cache[key] = self.add_sprite(second)
            yield first, self.second_cell_cache.get(key)
        if self.current_layer_dirty:
            self.commit_layer()

    def commit_all_layers(self):
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.texture_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_BASE_LEVEL, 0)
        gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_MAX_LEVEL, 0)
        gl.glTexImage3D(gl.GL_TEXTURE_2D_ARRAY, 0, gl.GL_R8, self.width, self.height, len(self.previous_layers) + 1, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, None)
        for i, buf in enumerate(self.previous_layers):
            self.commit_layer(i, buf, bind=False)
        self.commit_layer(bind=False)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)

    def commit_layer(self, num=None, buf=None, bind=True):
        if bind:
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.texture_id)
        if num is None:
            num, buf = len(self.previous_layers), self.current_layer_buffer
            self.current_layer_dirty = False
        gl.glTexSubImage3D(gl.GL_TEXTURE_2D_ARRAY, 0, 0, 0, num, self.width, self.height, 1,
                           gl.GL_RED, gl.GL_UNSIGNED_BYTE, buf)
        if bind:
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)

    def add_sprite(self, buf):
        self.current_layer_dirty = True
        pixels_per_line = self.cell_width * self.xnum
        pixels_per_row = pixels_per_line * self.cell_height
        offset_to_start_of_row = self.y * pixels_per_row

        for y in range(self.cell_height):
            doff = offset_to_start_of_row + self.x * self.cell_width
            soff = y * self.cell_width
            for x in range(self.cell_width):
                self.current_layer_buffer[doff + x] = buf[soff + x]
            offset_to_start_of_row += pixels_per_line

        # UV space co-ordinates
        left, top, z = self.x, self.y, len(self.previous_layers)

        # Now increment the current cell position
        self.x += 1
        if self.x >= self.xnum:
            self.x = 0
            self.y += 1
            if self.y >= self.ynum:
                self.y = 0
                self.previous_layers.append(self.current_layer_buffer)
                gl.glDeleteTextures([self.texture_id])
                self.texture_id = gl.glGenTextures(1)
                self.current_layer_buffer = (gl.GLubyte * (self.width * self.height))()
                self.commit_all_layers()
        return left, top, left + 1, top + 1, z

    def __enter__(self):
        gl.glActiveTexture(self.texture_unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.texture_id)

    def __exit__(self, *a):
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)

    def display_layer(self, num=None):
        if num is None:
            buf = self.current_layer_buffer
        else:
            buf = self.previous_layers[num]
        display_bitmap(buf, self.width, self.height)


class ShaderProgram:
    """ Helper class for using GLSL shader programs """

    def __init__(self, vertex, fragment):
        """
        Create a shader program.

        """
        self.program_id = gl.glCreateProgram()
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
        self.sprites = Sprites()

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
        gl.glUniform1i(self.uniform_location('sprites'), self.sprites.sampler_num)
        gl.glUniform3f(self.uniform_location('sprite_scale'), self.sprites.xnum, self.sprites.ynum, 1)
        self.sprites.__enter__()
        self.is_active = True

    def __exit__(self, *args):
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)
        self.sprites.__exit__(*args)
        self.is_active = False

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
