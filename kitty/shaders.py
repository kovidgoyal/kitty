#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.arrays import ArrayDatatype
import OpenGL.GL as gl
from OpenGL.GL.ARB.copy_image import glCopyImageSubData  # only present in opengl core >= 4.3
from OpenGL.GL.ARB.texture_storage import glTexStorage3D  # only present in opengl core >= 4.2

from .fonts import render_cell
from .data_types import ITALIC_MASK, BOLD_MASK
from .fast_data_types import (
    glCreateProgram, glAttachShader, GL_FRAGMENT_SHADER, GL_VERTEX_SHADER, glLinkProgram,
    GL_TRUE, GL_LINK_STATUS, glGetProgramiv, glGetProgramInfoLog, glDeleteShader, glDeleteProgram,
    glGenVertexArrays, glCreateShader, glShaderSource, glCompileShader, glGetShaderiv, GL_COMPILE_STATUS,
    glGetShaderInfoLog, glGetUniformLocation, glGetAttribLocation, glUseProgram, glBindVertexArray,
)

GL_VERSION = (3, 3)
VERSION = GL_VERSION[0] * 100 + GL_VERSION[1] * 10


class Sprites:
    ''' Maintain sprite sheets of all rendered characters on the GPU as a texture
    array with each texture being a sprite sheet. '''

    # TODO: Rewrite this class using the ARB_shader_image_load_store and ARB_shader_storage_buffer_object
    # extensions one they become available.

    def __init__(self, texture_unit=0):
        self.xnum = self.ynum = 1
        self.sampler_num = texture_unit
        self.buffer_sampler_num = texture_unit + 1
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.x = self.y = self.z = 0
        self.texture_id = self.buffer_id = self.buffer_texture_id = None
        self.last_num_of_layers = 1

    def initialize(self):
        self.texture_unit = getattr(gl, 'GL_TEXTURE%d' % self.sampler_num)
        self.max_array_len = gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS)
        self.max_texture_size = gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)
        self.do_layout(getattr(self, 'cell_width', 1), getattr(self, 'cell_height', 1))

    def do_layout(self, cell_width=1, cell_height=1):
        self.cell_width, self.cell_height = cell_width or 1, cell_height or 1
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.xnum = max(1, self.max_texture_size // self.cell_width)
        self.max_y = max(1, self.max_texture_size // self.cell_height)
        self.ynum = 1
        if self.texture_id is not None:
            gl.glDeleteTextures([self.texture_id])
            self.texture_id = None

    @property
    def layout(self):
        return 1 / self.xnum, 1 / self.ynum

    def realloc_texture(self):
        if self.texture_id is None:
            self.initialize()
        tgt = gl.GL_TEXTURE_2D_ARRAY
        tex = gl.glGenTextures(1)
        gl.glBindTexture(tgt, tex)
        gl.glTexParameteri(tgt, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(tgt, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(tgt, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(tgt, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        znum = self.z + 1
        width, height = self.xnum * self.cell_width, self.ynum * self.cell_height
        glTexStorage3D(tgt, 1, gl.GL_R8, width, height, znum)
        if self.texture_id is not None:
            ynum = self.ynum
            if self.z == 0:
                ynum -= 1  # Only copy the previous rows
            glCopyImageSubData(self.texture_id, tgt, 0, 0, 0, 0, tex, tgt, 0, 0, 0, 0,
                               width, ynum * self.cell_height, self.last_num_of_layers)
            gl.glDeleteTextures([self.texture_id])
        self.last_num_of_layers = znum
        self.texture_id = tex
        gl.glBindTexture(tgt, 0)

    def ensure_state(self):
        if self.texture_id is None:
            self.realloc_texture()
            self.buffer_id = gl.glGenBuffers(1)
            self.buffer_texture_id = gl.glGenTextures(1)
            self.buffer_texture_unit = getattr(gl, 'GL_TEXTURE%d' % self.buffer_sampler_num)

    def add_sprite(self, buf):
        tgt = gl.GL_TEXTURE_2D_ARRAY
        gl.glBindTexture(tgt, self.texture_id)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        x, y = self.x * self.cell_width, self.y * self.cell_height
        gl.glTexSubImage3D(tgt, 0, x, y, self.z, self.cell_width, self.cell_height, 1, gl.GL_RED, gl.GL_UNSIGNED_BYTE, buf)
        gl.glBindTexture(tgt, 0)

        # co-ordinates for this sprite in the sprite sheet
        x, y, z = self.x, self.y, self.z

        # Now increment the current cell position
        self.x += 1
        if self.x >= self.xnum:
            self.x = 0
            self.y += 1
            self.ynum = min(max(self.ynum, self.y + 1), self.max_y)
            if self.y >= self.max_y:
                self.y = 0
                self.z += 1
            self.realloc_texture()  # we allocate a row at a time
        return x, y, z

    def set_sprite_map(self, data):
        tgt = gl.GL_TEXTURE_BUFFER
        gl.glBindBuffer(tgt, self.buffer_id)
        gl.glBufferData(tgt, ArrayDatatype.arrayByteCount(data), data, gl.GL_STATIC_DRAW)
        gl.glBindBuffer(tgt, 0)

    def primary_sprite_position(self, key):
        ' Return a 3-tuple (x, y, z) giving the position of this sprite on the sprite sheet '
        try:
            return self.first_cell_cache[key]
        except KeyError:
            pass
        text, attrs = key
        bold, italic = bool(attrs & BOLD_MASK), bool(attrs & ITALIC_MASK)
        first, second = render_cell(text, bold, italic)
        self.first_cell_cache[key] = first = self.add_sprite(first)
        if second is not None:
            self.second_cell_cache[key] = self.add_sprite(second)
        return first

    def secondary_sprite_position(self, key):
        ans = self.second_cell_cache.get(key)
        if ans is None:
            self.primary_sprite_position(key)
            ans = self.second_cell_cache.get(key)
            if ans is None:
                return 0, 0, 0
        return ans

    def __enter__(self):
        self.ensure_state()
        gl.glActiveTexture(self.texture_unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.texture_id)

        gl.glActiveTexture(self.buffer_texture_unit)
        gl.glBindTexture(gl.GL_TEXTURE_BUFFER, self.buffer_texture_id)
        gl.glTexBuffer(gl.GL_TEXTURE_BUFFER, gl.GL_RGB32UI, self.buffer_id)

    def __exit__(self, *a):
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)
        gl.glBindTexture(gl.GL_TEXTURE_BUFFER, 0)


class ShaderProgram:
    """ Helper class for using GLSL shader programs """

    def __init__(self, vertex, fragment):
        """
        Create a shader program.

        """
        self.program_id = glCreateProgram()
        self.is_active = False
        vs_id = self.add_shader(vertex, GL_VERTEX_SHADER)
        glAttachShader(self.program_id, vs_id)

        frag_id = self.add_shader(fragment, GL_FRAGMENT_SHADER)
        glAttachShader(self.program_id, frag_id)

        glLinkProgram(self.program_id)
        if glGetProgramiv(self.program_id, GL_LINK_STATUS) != GL_TRUE:
            info = glGetProgramInfoLog(self.program_id)
            glDeleteProgram(self.program_id)
            glDeleteShader(vs_id)
            glDeleteShader(frag_id)
            raise ValueError('Error linking shader program: \n%s' % info.decode('utf-8'))
        glDeleteShader(vs_id)
        glDeleteShader(frag_id)
        self.vao_id = glGenVertexArrays(1)

    def __hash__(self) -> int:
        return self.program_id

    def __eq__(self, other) -> bool:
        return isinstance(other, ShaderProgram) and other.program_id == self.program_id

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def add_shader(self, source: str, shader_type: int) -> int:
        ' Compile a shader and return its id, or raise an exception if compilation fails '
        shader_id = glCreateShader(shader_type)
        source = '#version {}\n{}'.format(VERSION, source)
        try:
            glShaderSource(shader_id, source)
            glCompileShader(shader_id)
            if glGetShaderiv(shader_id, GL_COMPILE_STATUS) != GL_TRUE:
                info = glGetShaderInfoLog(shader_id)
                raise ValueError('GLSL {} compilation failed: \n{}'.format(shader_type, info.decode('utf-8')))
            return shader_id
        except Exception:
            glDeleteShader(shader_id)
            raise

    @lru_cache(maxsize=2**6)
    def uniform_location(self, name: str) -> int:
        ' Return the id for the uniform variable `name` or -1 if not found. '
        return glGetUniformLocation(self.program_id, name)

    @lru_cache(maxsize=2**6)
    def attribute_location(self, name: str) -> int:
        ' Return the id for the attribute variable `name` or -1 if not found. '
        return glGetAttribLocation(self.program_id, name)

    def __enter__(self):
        glUseProgram(self.program_id)
        glBindVertexArray(self.vao_id)
        self.is_active = True

    def __exit__(self, *args):
        glUseProgram(0)
        glBindVertexArray(0)
        self.is_active = False
