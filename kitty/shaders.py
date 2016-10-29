#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.arrays import ArrayDatatype
import OpenGL.GL as gl
from OpenGL.GL.ARB.copy_image import glCopyImageSubData  # only present in opengl core >= 4.3
from OpenGL.GL.ARB.texture_storage import glTexStorage3D  # only present in opengl core >= 4.2

from .fonts import render_cell, cell_size

GL_VERSION = (3, 3)
VERSION = GL_VERSION[0] * 100 + GL_VERSION[1] * 10
REQUIRED_EXTENSIONS = frozenset('GL_ARB_copy_image GL_ARB_texture_storage'.split())


def array(*args, dtype=gl.GLfloat):
    return (dtype * len(args))(*args)


def check_for_required_extensions():
    num = gl.glGetIntegerv(gl.GL_NUM_EXTENSIONS)
    required = set(REQUIRED_EXTENSIONS)
    for i in range(num):
        ext = gl.glGetStringi(gl.GL_EXTENSIONS, i).decode('utf-8')
        required.discard(ext)
        if not required:
            break
    if required:
        raise RuntimeError('Your OpenGL implementation is missing the following required extensions: %s' % ','.join(required))


class Sprites:
    ''' Maintain sprite sheets of all rendered characters on the GPU as a texture
    array with each texture being a sprite sheet. '''

    # TODO: Rewrite this class using the ARB_shader_image_load_store and ARB_shader_storage_buffer_object
    # extensions one they become available.

    def __init__(self, texture_unit=0):
        self.sampler_num = texture_unit
        self.buffer_sampler_num = texture_unit + 1
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.x = self.y = self.z = 0
        self.texture_id = self.buffer_id = self.buffer_texture_id = None
        self.last_num_of_layers = 1

    def do_layout(self):
        self.texture_unit = getattr(gl, 'GL_TEXTURE%d' % self.sampler_num)
        self.max_array_len = gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS)
        self.max_texture_size = gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)
        self.cell_width, self.cell_height = cell_size()
        self.xnum = self.max_texture_size // self.cell_width
        self.max_y = self.max_texture_size // self.cell_height
        self.ynum = 1

    @property
    def layout(self):
        return 1 / self.xnum, 1 / self.ynum

    def realloc_texture(self):
        if self.texture_id is None:
            self.do_layout()
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

    def add_sprite(self, buf):
        if self.texture_id is None:
            self.realloc_texture()
        if self.buffer_id is None:
            self.buffer_id = gl.glGenBuffers(1)
            self.buffer_texture_id = gl.glGenTextures(1)
            self.buffer_texture_unit = getattr(gl, 'GL_TEXTURE%d' % self.buffer_sampler_num)
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

    def primary_sprite_position(self, text, bold=False, italic=False):
        ' Return a 3-tuple (x, y, z) giving the position of this sprite on the sprite sheet '
        key = text, bold, italic
        first = self.first_cell_cache.get(key)
        if first is None:
            first, second = render_cell(text, bold, italic)
            self.first_cell_cache[key] = first = self.add_sprite(first)
            if second is not None:
                self.second_cell_cache[key] = self.add_sprite(second)
        return first

    def secondary_sprite_position(self, text, bold=False, italic=False):
        key = text, bold, italic
        ans = self.second_cell_cache.get(key)
        if ans is None:
            self.primary_sprite_position(text, bold, italic)
            ans = self.second_cell_cache.get(key)
            if ans is None:
                return 0, 0, 0
        return ans

    def __enter__(self):
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
            raise ValueError('Error linking shader program: \n%s' % info.decode('utf-8'))
        gl.glDeleteShader(vs_id)
        gl.glDeleteShader(frag_id)
        self.vao_id = gl.glGenVertexArrays(1)

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
                raise ValueError('GLSL {} compilation failed: \n{}'.format(shader_type, info.decode('utf-8')))
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

    def __exit__(self, *args):
        gl.glUseProgram(0)
        gl.glBindVertexArray(0)
        self.is_active = False
