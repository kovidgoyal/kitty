#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import namedtuple
from enum import Enum

from .config import build_ansi_color_table
from .constants import ScreenGeometry, cell_size, viewport_size
from .fast_data_types import (
    CELL_PROGRAM, CURSOR_BEAM, CURSOR_BLOCK, CURSOR_PROGRAM, CURSOR_UNDERLINE,
    compile_program, create_cell_vao, draw_cells, draw_cursor,
    init_cell_program, init_cursor_program, remove_vao
)
from .rgb import to_color
from .utils import (
    color_as_int, get_logical_dpi, load_shaders, open_url,
    set_primary_selection
)

Cursor = namedtuple('Cursor', 'x y shape blink')


class DynamicColor(Enum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


def load_shader_programs():
    compile_program(CELL_PROGRAM, *load_shaders('cell'))
    init_cell_program()
    compile_program(CURSOR_PROGRAM, *load_shaders('cursor'))
    init_cursor_program()


def calculate_gl_geometry(window_geometry, viewport_width, viewport_height, cell_width, cell_height):
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def render_cells(vao_id, sg, screen):
    draw_cells(vao_id, sg.xstart, sg.ystart, sg.dx, sg.dy, screen)


class CharGrid:

    url_pat = re.compile('(?:http|https|file|ftp)://\S+', re.IGNORECASE)

    def __init__(self, screen, opts):
        self.vao_id = create_cell_vao()
        self.screen_reversed = False
        self.screen = screen
        self.opts = opts
        self.screen.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        self.screen.color_profile.set_configured_colors(*map(color_as_int, (
            opts.foreground, opts.background, opts.cursor, opts.selection_foreground, opts.selection_background)))
        self.dpix, self.dpiy = get_logical_dpi()
        self.opts = opts
        self.default_cursor = Cursor(0, 0, opts.cursor_shape, opts.cursor_blink_interval > 0)
        self.opts = opts

    def destroy(self):
        if self.vao_id is not None:
            remove_vao(self.vao_id)
            self.vao_id = None

    def update_position(self, window_geometry):
        self.screen_geometry = calculate_gl_geometry(window_geometry, viewport_size.width, viewport_size.height, cell_size.width, cell_size.height)

    def resize(self, window_geometry):
        self.update_position(window_geometry)

    def change_colors(self, changes):
        dirtied = False

        def item(raw):
            if raw is None:
                return 0
            val = to_color(raw)
            return None if val is None else (color_as_int(val) << 8) | 2

        for which, val in changes.items():
            val = item(val)
            if val is None:
                continue
            dirtied = True
            setattr(self.screen.color_profile, which.name, val)
        if dirtied:
            self.screen.mark_as_dirty()

    def cell_for_pos(self, x, y):
        x, y = int(x // cell_size.width), int(y // cell_size.height)
        if 0 <= x < self.screen.columns and 0 <= y < self.screen.lines:
            return x, y
        return None, None

    def update_drag(self, is_press, mx, my):
        x, y = self.cell_for_pos(mx, my)
        if x is None:
            x = 0 if mx <= cell_size.width else self.screen.columns - 1
            y = 0 if my <= cell_size.height else self.screen.lines - 1
        ps = None
        if is_press:
            self.screen.start_selection(x, y)
        elif self.screen.is_selection_in_progress():
            ended = is_press is False
            self.screen.update_selection(x, y, ended)
            if ended:
                ps = self.text_for_selection()
        if ps and ps.strip():
            set_primary_selection(ps)

    def has_url_at(self, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            l = self.screen.visual_line(y)
            if l is not None:
                text = str(l)
                for m in self.url_pat.finditer(text):
                    if m.start() <= x < m.end():
                        return True
        return False

    def click_url(self, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            l = self.screen.visual_line(y)
            if l is not None:
                text = str(l)
                for m in self.url_pat.finditer(text):
                    if m.start() <= x < m.end():
                        url = ''.join(l[i] for i in range(*m.span())).rstrip('.')
                        # Remove trailing "] and similar
                        url = re.sub(r'''["'][)}\]]$''', '', url)
                        # Remove closing trailing character if it is matched by it's
                        # corresponding opening character before the url
                        if m.start() > 0:
                            before = l[m.start() - 1]
                            closing = {'(': ')', '[': ']', '{': '}', '<': '>', '"': '"', "'": "'", '`': '`', '|': '|', ':': ':'}.get(before)
                            if closing is not None and url.endswith(closing):
                                url = url[:-1]
                        if url:
                            open_url(url, self.opts.open_url_with)

    def multi_click(self, count, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            line = self.screen.visual_line(y)
            if line is not None and count in (2, 3):
                if count == 2:
                    start_x, xlimit = self.screen.selection_range_for_word(x, y, self.opts.select_by_word_characters)
                    end_x = max(start_x, xlimit - 1)
                elif count == 3:
                    start_x, xlimit = self.screen.selection_range_for_line(y)
                    end_x = max(start_x, xlimit - 1)
                self.screen.start_selection(start_x, y)
                self.screen.update_selection(end_x, y, True)
            ps = self.text_for_selection()
            if ps:
                set_primary_selection(ps)

    def get_scrollback_as_ansi(self):
        ans = []
        self.screen.historybuf.as_ansi(ans.append)
        self.screen.linebuf.as_ansi(ans.append)
        return ''.join(ans).encode('utf-8')

    def text_for_selection(self):
        return ''.join(self.screen.text_for_selection())

    def render_cells(self):
        render_cells(self.vao_id, self.screen_geometry, self.screen)

    def render_cursor(self, is_focused):
        if not self.screen.cursor_visible or self.screen.scrolled_by:
            return
        cursor = self.screen.cursor

        def width(w=2, vert=True):
            dpi = self.dpix if vert else self.dpiy
            w *= dpi / 72.0  # as pixels
            factor = 2 / (viewport_size.width if vert else viewport_size.height)
            return w * factor

        sg = self.screen_geometry
        left = sg.xstart + cursor.x * sg.dx
        top = sg.ystart - cursor.y * sg.dy
        col = self.screen.color_profile.cursor_color
        shape = cursor.shape or self.default_cursor.shape
        alpha = self.opts.cursor_opacity
        mult = self.screen.current_char_width()
        right = left + (width(1.5) if shape == CURSOR_BEAM else sg.dx * mult)
        bottom = top - sg.dy
        if shape == CURSOR_UNDERLINE:
            top = bottom + width(vert=False)
        semi_transparent = alpha < 1.0 and shape == CURSOR_BLOCK
        draw_cursor(semi_transparent, is_focused, col, alpha, left, right, top, bottom)
