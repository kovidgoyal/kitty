#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from threading import Lock

from .config import build_ansi_color_tables, to_color
from .fonts import set_font_family

import OpenGL.GL as gl


class CharGrid:

    def __init__(self, screen, opts, window_width, window_height):
        self.width, self.height = window_width, window_height
        self.screen = screen
        self.apply_opts(opts)
        self.dirty_everything()
        self.default_bg, self.default_fg = self.original_bg, self.original_fg
        self.resize_lock = Lock()
        self.apply_resize_to_screen(self.width, self.height)

    def dirty_everything(self):
        self.cell_resize_pending = True
        self.clear_color_changed = True
        self.resize_pending = self.width, self.height

    def apply_opts(self, opts):
        self.opts = opts
        build_ansi_color_tables(opts)
        self.opts = opts
        self.original_bg = opts.background
        self.original_fg = opts.foreground
        self.cell_width, self.cell_height = set_font_family(opts.font_family, opts.font_size)

    def apply_resize_to_screen(self, w, h):
        cells_per_line = w // self.cell_width
        lines_per_screen = h // self.cell_height
        self.screen.resize(lines_per_screen, cells_per_line)

    def resize_screen(self, w, h):
        ' Screen was resized by the user (called in non-UI thread) '
        with self.resize_lock:
            self.apply_resize_to_screen(w, h)
            self.resize_pending = w, h

    def do_layout(self, w, h):
        self.width, self.height = w, h
        self.cells_per_line = w // self.cell_width
        self.lines_per_screen = h // self.cell_height
        if self.cell_resize_pending:
            self.cell_resize_pending = False

    def render(self):
        with self.resize_lock:
            if self.resize_pending:
                self.do_layout(*self.resize_pending)
                gl.glViewport(0, 0, self.width, self.height)
                self.resize_pending = None
        if self.clear_color_changed:
            bg = self.default_bg
            self.clear_color_changed = False
            gl.glClearColor(bg[0]/255, bg[1]/255, bg[2]/255, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

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
            self.clear_color_changed = True
            self.update_screen()

    def update_screen(self, changes=None):
        if changes is None:
            changes = {'screen': True}
