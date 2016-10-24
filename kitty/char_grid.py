#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from threading import Lock

from .config import build_ansi_color_tables, to_color
from .fonts import set_font_family

from OpenGL.arrays import ArrayDatatype
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_COLOR_BUFFER_BIT, GL_COMPILE_STATUS,
    GL_FALSE, GL_FLOAT, GL_FRAGMENT_SHADER,
    GL_LINK_STATUS, GL_RENDERER,
    GL_SHADING_LANGUAGE_VERSION,
    GL_STATIC_DRAW, GL_TEXTURE_2D, GL_TRIANGLES,
    GL_TRUE, GL_UNPACK_ALIGNMENT, GL_VENDOR, GL_VERSION,
    GL_VERTEX_SHADER, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_LINEAR, GL_RGB, GL_RGBA, GL_UNSIGNED_BYTE, GL_TEXTURE0,
    GL_REPEAT,
    glActiveTexture, glAttachShader,
    glBindBuffer, glBindTexture, glBindVertexArray,
    glBufferData, glClear, glClearColor,
    glCompileShader, glCreateProgram,
    glCreateShader, glDeleteProgram,
    glDeleteShader, glDrawArrays,
    glEnableVertexAttribArray, glGenBuffers, glGenTextures,
    glGenVertexArrays, glGetAttribLocation,
    glGetProgramInfoLog, glGetProgramiv,
    glGetShaderInfoLog, glGetShaderiv, glGetString,
    glGetUniformLocation, glLinkProgram, glPixelStorei,
    glShaderSource, glTexImage2D, glTexParameteri, glUniform1i, glUseProgram,
    glVertexAttribPointer, glViewport)


class CharGrid:

    def __init__(self, opts):
        self.apply_opts(opts)
        self.lock = Lock()

    def apply_clear_color(self):
        bg = self.default_bg
        glClearColor(bg[0]/255, bg[1]/255, bg[2]/255, 1)

    def apply_opts(self, opts):
        self.opts = opts
        build_ansi_color_tables(opts)
        self.opts = opts
        self.default_bg = self.original_bg = opts.background
        self.default_fg = self.original_fg = opts.foreground
        self.cell_width, self.cell_height = set_font_family(opts.font_family, opts.font_size)
        self.apply_clear_color()

    def on_resize(self, window, w, h):
        glViewport(0, 0, w, h)
        self.do_layout(w, h)

    def do_layout(self, w, h):
        pass

    def redraw(self):
        pass

    def render(self):
        with self.lock:
            glClear(GL_COLOR_BUFFER_BIT)

    def change_colors(self, changes):
        dirtied = False
        for which, val in changes.items():
            if which in ('fg', 'bg'):
                if not val:
                    setattr(self, 'default_' + which, getattr(self, 'original_' + which))
                    dirtied = True
                else:
                    val = to_color(val)
                    if val is not None:
                        setattr(self, 'default_' + which, val)
                        dirtied = True
        if dirtied:
            self.apply_clear_color()
            self.redraw()

    def update_screen(self, changes):
        self.redraw()
