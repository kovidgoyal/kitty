#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from ctypes import addressof

from .fast_data_types import (
    GL_CLAMP_TO_EDGE, GL_MAX_ARRAY_TEXTURE_LAYERS, GL_MAX_TEXTURE_SIZE,
    GL_NEAREST, GL_R8, GL_RED, GL_TEXTURE0, GL_TEXTURE_2D_ARRAY,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_UNPACK_ALIGNMENT, GL_UNSIGNED_BYTE,
    copy_image_sub_data, glActiveTexture, glBindTexture, glCopyImageSubData,
    glDeleteTexture, glGenTextures, glGetIntegerv, glPixelStorei,
    glTexParameteri, glTexStorage3D, glTexSubImage3D, render_dirty_sprites,
    sprite_map_current_layout, sprite_map_free, sprite_map_increment,
    sprite_map_set_layout, sprite_map_set_limits
)
from .fonts.render import render_cell
from .utils import safe_print


class Sprites:
    ''' Maintain sprite sheets of all rendered characters on the GPU as a texture
    array with each texture being a sprite sheet. '''

    # TODO: Rewrite this class using the ARB_shader_image_load_store and ARB_shader_storage_buffer_object
    # extensions one they become available.

    def __init__(self):
        self.xnum = self.ynum = 1
        self.first_cell_cache = {}
        self.second_cell_cache = {}
        self.x = self.y = self.z = 0
        self.texture_id = None
        self.last_num_of_layers = 1
        self.last_ynum = -1
        self.sampler_num = 0
        self.texture_unit = GL_TEXTURE0 + self.sampler_num
        sprite_map_set_limits(glGetIntegerv(GL_MAX_TEXTURE_SIZE), glGetIntegerv(GL_MAX_ARRAY_TEXTURE_LAYERS))

    def do_layout(self, cell_width=1, cell_height=1):
        self.cell_width, self.cell_height = cell_width, cell_height
        sprite_map_set_layout(cell_width or 1, cell_height or 1)
        if self.texture_id is not None:
            glDeleteTexture(self.texture_id)
            self.texture_id = None
        self.ensure_state()
        # Pre-render the basic cells to ensure they have known sprite numbers

        def send(*a, **kw):
            buf = render_cell(*a, **kw)[0]
            x, y, z = sprite_map_increment()
            self.send_to_gpu(x, y, z, buf)
            return x

        send()  # blank
        send(underline=1)
        send(underline=2)
        if send(strikethrough=True) != 3:
            raise RuntimeError('Available OpenGL texture size is too small')

    def render_cell(self, text, bold, italic, is_second):
        first, second = render_cell(text, bold, italic)
        ans = second if is_second else first
        return ans or render_cell()[0]

    def render_dirty_sprites(self):
        ret = render_dirty_sprites()
        if ret:
            for text, bold, italic, is_second, x, y, z in ret:
                cell = self.render_cell(text, bold, italic, is_second)
                self.send_to_gpu(x, y, z, cell)

    def send_to_gpu(self, x, y, z, buf):
        xnum, ynum, znum = sprite_map_current_layout()
        if znum >= self.last_num_of_layers:
            self.realloc_texture()
        else:
            if znum == 0 and ynum > self.last_ynum:
                self.realloc_texture()
        tgt = GL_TEXTURE_2D_ARRAY
        glBindTexture(tgt, self.texture_id)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        x, y = x * self.cell_width, y * self.cell_height
        glTexSubImage3D(tgt, 0, x, y, z, self.cell_width, self.cell_height, 1, GL_RED, GL_UNSIGNED_BYTE, addressof(buf))

    def realloc_texture(self):
        tgt = GL_TEXTURE_2D_ARRAY
        tex = glGenTextures(1)
        glBindTexture(tgt, tex)
        # We use GL_NEAREST otherwise glyphs that touch the edge of the cell
        # often show a border between cells
        glTexParameteri(tgt, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(tgt, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(tgt, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(tgt, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        xnum, bynum, z = sprite_map_current_layout()
        znum = z + 1
        width, height = xnum * self.cell_width, bynum * self.cell_height
        glTexStorage3D(tgt, 1, GL_R8, width, height, znum)
        if self.texture_id is not None:
            ynum = bynum
            if z == 0:
                ynum -= 1  # Only copy the previous rows
            try:
                glCopyImageSubData(self.texture_id, tgt, 0, 0, 0, 0, tex, tgt, 0, 0, 0, 0,
                                   width, ynum * self.cell_height, self.last_num_of_layers)
            except RuntimeError:
                # OpenGL does not have ARB_copy_image
                if not hasattr(self, 'realloc_warned'):
                    safe_print(
                        'WARNING: Your system\'s OpenGL implementation does not have glCopyImageSubData, falling back to a slower implementation',
                        file=sys.stderr)
                    self.realloc_warned = True
                copy_image_sub_data(self.texture_id, tex, width, ynum * self.cell_height, self.last_num_of_layers)
                glBindTexture(tgt, tex)
            glDeleteTexture(self.texture_id)
        self.last_num_of_layers = znum
        self.last_ynum = bynum
        self.texture_id = tex

    def destroy(self):
        sprite_map_free()
        if self.texture_id is not None:
            glDeleteTexture(self.texture_id)
            self.texture_id = None

    def ensure_state(self):
        if self.texture_id is None:
            self.realloc_texture()

    def __enter__(self):
        self.ensure_state()
        glActiveTexture(self.texture_unit)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.texture_id)

    def __exit__(self, *a):
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)
