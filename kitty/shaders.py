#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.arrays import ArrayDatatype
import OpenGL.GL as gl
from OpenGL.GL.ARB.copy_image import glCopyImageSubData  # only present in opengl core >= 4.3

from .fonts import render_cell, cell_size

GL_VERSION = (4, 1)
VERSION = GL_VERSION[0] * 100 + GL_VERSION[1] * 10


def array(*args, dtype=gl.GLfloat):
    return (dtype * len(args))(*args)


def translation_matrix(x, y):
    return array(
        1, 0, x,
        0, 1, y,
        0, 0, 1
    )


def scaling_matrix(x, y):
    return array(
        x, 0, 0,
        0, y, 0,
        0, 0, 1
    )


def multiply(a, b):
    # 0 1 2
    # 3 4 5
    # 6 7 8
    return array(
        # Row 1
        a[0] * b[0] + a[1] * b[3] + a[2] * b[6],
        a[0] * b[1] + a[1] * b[4] + a[2] * b[7],
        a[0] * b[2] + a[1] * b[5] + a[2] * b[8],
        # Row 2
        a[3] * b[0] + a[4] * b[3] + a[5] * b[6],
        a[3] * b[1] + a[4] * b[4] + a[5] * b[7],
        a[3] * b[2] + a[4] * b[5] + a[5] * b[8],
        # Row 3
        a[6] * b[0] + a[7] * b[3] + a[8] * b[6],
        a[6] * b[1] + a[7] * b[4] + a[8] * b[7],
        a[6] * b[2] + a[7] * b[5] + a[8] * b[8]
    )


def ortho_matrix(left=0, right=1, bottom=1, top=0, near=0, far=1):
    # See https://www.opengl.org/sdk/docs/man2/xhtml/glOrtho.xml
    def t(a, b):
        return (a + b) / (a - b)
    return array(
        2 / (right - left), 0, 0, -t(right, left),
        0, 2 / (bottom - top), 0, -t(bottom, top),
        0, 0, -2 / (far - near), -t(far, near),
        0, 0, 0, 1
    )


def map_pos(matrix, x, y):
    return (
        x * matrix[0] + y * matrix[1] + matrix[3],
        x * matrix[4] + y * matrix[5] + matrix[7]
    )


class Sprites:
    ''' Maintain sprite sheets of all rendered characters on the GPU as a texture
    array with each texture being a sprite sheet. '''

    def __init__(self, texture_unit=0):
        self.sampler_num = texture_unit
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.x = self.y = self.z = 0
        self.texture_id = None
        self.last_num_of_layers = 1

    def do_layout(self):
        self.texture_unit = getattr(gl, 'GL_TEXTURE%d' % self.sampler_num)
        self.max_array_len = gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS)
        self.max_texture_size = gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)
        self.cell_width, self.cell_height = cell_size()
        self.xnum = self.max_texture_size // self.cell_width
        self.max_y = self.max_texture_size // self.cell_height
        # self.xnum, self.max_y = 2, 2
        self.ynum = 1

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
        gl.glTexParameteri(tgt, gl.GL_TEXTURE_BASE_LEVEL, 0)
        gl.glTexParameteri(tgt, gl.GL_TEXTURE_MAX_LEVEL, 0)
        znum = self.z + 1
        width, height = self.xnum * self.cell_width, self.ynum * self.cell_height
        gl.glTexImage3D(tgt, 0, gl.GL_R8,
                        width, height, znum,
                        0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, None)
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

    def positions_for(self, items):
        ''' Yield 2, 5-tuples (left, top, right, bottom, z) pointing to the
        desired sprite and its second sprite if it is a wide character. '''
        for key in items:
            first = self.first_cell_cache.get(key)
            if first is None:
                first, second = render_cell(*key)
                self.first_cell_cache[key] = first = self.add_sprite(first)
                if second is not None:
                    self.second_cell_cache[key] = self.add_sprite(second)
            yield first, self.second_cell_cache.get(key)

    def add_sprite(self, buf):
        if self.texture_id is None:
            self.realloc_texture()
        tgt = gl.GL_TEXTURE_2D_ARRAY
        gl.glBindTexture(tgt, self.texture_id)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        x, y = self.x * self.cell_width, self.y * self.cell_height
        gl.glTexSubImage3D(tgt, 0, x, y, self.z, self.cell_width, self.cell_height, 1, gl.GL_RED, gl.GL_UNSIGNED_BYTE, buf)
        gl.glBindTexture(tgt, 0)

        # UV space co-ordinates
        left, top, z = self.x, self.y, self.z

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
        return left, top, left + 1, top + 1, z

    def __enter__(self):
        gl.glActiveTexture(self.texture_unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self.texture_id)

    def __exit__(self, *a):
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, 0)


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
