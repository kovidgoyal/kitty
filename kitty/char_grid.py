#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import namedtuple
from ctypes import sizeof
from enum import Enum

from .config import build_ansi_color_table
from .constants import (
    GLfloat, GLuint, ScreenGeometry, cell_size, viewport_size
)
from .fast_data_types import (
    CELL, CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE, GL_BLEND, GL_FLOAT,
    GL_LINE_LOOP, GL_STATIC_DRAW, GL_TRIANGLE_FAN, GL_UNSIGNED_INT,
    GL_UNSIGNED_SHORT, glDisable, glDrawArrays, glDrawArraysInstanced,
    glEnable, glUniform1i, glUniform2f, glUniform2i, glUniform2ui, glUniform4f,
    glUniform4ui
)
from .rgb import to_color
from .shaders import ShaderProgram, load_shaders
from .utils import (
    color_as_int, color_from_int, get_logical_dpi, open_url,
    set_primary_selection
)

Cursor = namedtuple('Cursor', 'x y shape blink')


class DynamicColor(Enum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


class CellProgram(ShaderProgram):  # {{{

    def send_color_table(self, color_profile):
        if color_profile.ubo is None:
            color_profile.ubo = self.init_uniform_block('ColorTable', 'color_table')
        ubo = color_profile.ubo
        offset = ubo.offsets['color_table'] // sizeof(GLuint)
        stride = ubo.size // (256 * sizeof(GLuint))
        with self.mapped_uniform_data(ubo, usage=GL_STATIC_DRAW) as address:
            color_profile.copy_color_table(address, offset, stride)

    def create_sprite_map(self):
        with self.array_object_creator() as add_attribute:
            stride = CELL['size']
            add_attribute('text_attrs', size=1, dtype=GL_UNSIGNED_INT, offset=CELL['ch'], stride=stride, divisor=1)
            add_attribute('sprite_coords', size=3, dtype=GL_UNSIGNED_SHORT, offset=CELL['sprite_x'], stride=stride, divisor=1)
            add_attribute('colors', size=3, dtype=GL_UNSIGNED_INT, stride=stride, offset=CELL['fg'], divisor=1)
            add_attribute.newbuf()
            add_attribute('is_selected', size=1, dtype=GL_FLOAT, stride=sizeof(GLfloat), divisor=1)
            return add_attribute.vao_id


def load_shader_programs():
    cell = CellProgram(*load_shaders('cell'))
    cursor = ShaderProgram(*load_shaders('cursor'))
    with cursor.array_object_creator() as add_attribute:
        cursor.vao_id = add_attribute.vao_id
    return cell, cursor
# }}}


class Selection:  # {{{

    __slots__ = tuple('in_progress start_x start_y start_scrolled_by end_x end_y end_scrolled_by'.split())

    def __init__(self):
        self.clear()

    def clear(self):
        self.in_progress = False
        self.start_x = self.start_y = self.end_x = self.end_y = 0
        self.start_scrolled_by = self.end_scrolled_by = 0

    def limits(self, scrolled_by, lines, columns):

        def coord(x, y, ydelta):
            y = y - ydelta + scrolled_by
            if y < 0:
                x, y = 0, 0
            elif y >= lines:
                x, y = columns - 1, lines - 1
            return x, y

        a = coord(self.start_x, self.start_y, self.start_scrolled_by)
        b = coord(self.end_x, self.end_y, self.end_scrolled_by)
        return (a, b) if a[1] < b[1] or (a[1] == b[1] and a[0] <= b[0]) else (b, a)

# }}}


def calculate_gl_geometry(window_geometry, viewport_width, viewport_height, cell_width, cell_height):
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def render_cells(vao_id, sg, cell_program, sprites, color_profile, invert_colors=False, screen_reversed=False):
    if color_profile.dirty:
        cell_program.send_color_table(color_profile)
        color_profile.dirty = False
    ul = cell_program.uniform_location
    glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
    glUniform4ui(ul('default_colors'), color_profile.default_fg, color_profile.default_bg, color_profile.highlight_fg, color_profile.highlight_bg)
    inverted = invert_colors or screen_reversed
    glUniform2i(ul('color_indices'), 1 if inverted else 0, 0 if inverted else 1)
    glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
    glUniform1i(ul('sprites'), sprites.sampler_num)
    glUniform1i(ul('screen_reversed'), 1 if screen_reversed else 0)
    glUniform2f(ul('sprite_layout'), *(sprites.layout))
    with cell_program.bound_vertex_array(vao_id), cell_program.bound_uniform_buffer(color_profile.ubo):
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)


class CharGrid:

    url_pat = re.compile('(?:http|https|file|ftp)://\S+', re.IGNORECASE)

    def __init__(self, screen, opts):
        self.vao_id = None
        self.current_selection = Selection()
        self.screen_reversed = False
        self.last_rendered_selection = None
        self.render_data = None
        self.data_buffer_size = None
        self.screen = screen
        self.opts = opts
        self.screen.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        self.screen.color_profile.set_configured_colors(*map(color_as_int, (
            opts.foreground, opts.background, opts.cursor, opts.selection_foreground, opts.selection_background)))
        self.screen.color_profile.dirty = True
        self.dpix, self.dpiy = get_logical_dpi()
        self.opts = opts
        self.default_cursor = self.current_cursor = Cursor(0, 0, opts.cursor_shape, opts.cursor_blink_interval > 0)
        self.opts = opts

    def destroy(self, cell_program):
        if self.vao_id is not None:
            cell_program.remove_vertex_array(self.vao_id)
            self.vao_id = None

    def update_position(self, window_geometry):
        self.screen_geometry = calculate_gl_geometry(window_geometry, viewport_size.width, viewport_size.height, cell_size.width, cell_size.height)

    def resize(self, window_geometry):
        self.update_position(window_geometry)
        self.data_buffer_size = self.screen_geometry.ynum * self.screen_geometry.xnum * CELL['size']
        self.selection_buffer_size = self.screen_geometry.ynum * self.screen_geometry.xnum * sizeof(GLfloat)
        self.current_selection.clear()

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

    def update_cell_data(self, cell_program):
        if self.data_buffer_size is None:
            return
        clear_selection = self.screen.is_dirty
        with cell_program.mapped_vertex_data(self.vao_id, self.data_buffer_size) as address:
            cursor_changed, self.screen_reversed = self.screen.update_cell_data(
                address, False)

        if clear_selection:
            self.current_selection.clear()
        self.render_data = self.screen_geometry
        if cursor_changed:
            c = self.screen.cursor
            self.current_cursor = Cursor(c.x, c.y, c.shape, c.blink)

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
            self.current_selection.start_x = self.current_selection.end_x = x
            self.current_selection.start_y = self.current_selection.end_y = y
            self.current_selection.start_scrolled_by = self.current_selection.end_scrolled_by = self.screen.scrolled_by
            self.current_selection.in_progress = True
        elif self.current_selection.in_progress:
            self.current_selection.end_x = x
            self.current_selection.end_y = y
            self.current_selection.end_scrolled_by = self.screen.scrolled_by
            if is_press is False:
                self.current_selection.in_progress = False
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
                s = self.current_selection
                s.start_scrolled_by = s.end_scrolled_by = self.scrolled_by
                s.start_y = s.end_y = y
                s.in_progress = False
                if count == 2:
                    s.start_x, xlimit = self.screen.selection_range_for_word(x, y, self.opts.select_by_word_characters)
                    s.end_x = max(s.start_x, xlimit - 1)
                elif count == 3:
                    s.start_x, xlimit = self.screen.selection_range_for_line(y)
                    s.end_x = max(s.start_x, xlimit - 1)
            ps = self.text_for_selection()
            if ps:
                set_primary_selection(ps)

    def get_scrollback_as_ansi(self):
        ans = []
        self.screen.historybuf.as_ansi(ans.append)
        self.screen.linebuf.as_ansi(ans.append)
        return ''.join(ans).encode('utf-8')

    def text_for_selection(self, sel=None):
        s = sel or self.current_selection
        start, end = s.limits(self.screen.scrolled_by, self.screen.lines, self.screen.columns)
        return ''.join(self.screen.text_for_selection(*start, *end))

    def prepare_for_render(self, cell_program):
        if self.vao_id is None:
            self.vao_id = cell_program.create_sprite_map()
        if self.screen.scroll_changed or self.screen.is_dirty:
            self.update_cell_data(cell_program)
        sg = self.render_data
        start, end = self.current_selection.limits(self.screen.scrolled_by, self.screen.lines, self.screen.columns)
        sel = start, end, self.screen.scrolled_by
        selection_changed = sel != self.last_rendered_selection
        if selection_changed:
            with cell_program.mapped_vertex_data(self.vao_id, self.selection_buffer_size, bufnum=1) as address:
                self.screen.apply_selection(address, self.selection_buffer_size, *start, *end)
            self.last_rendered_selection = sel
        return sg

    def render_cells(self, sg, cell_program, sprites, invert_colors=False):
        render_cells(self.vao_id, sg, cell_program, sprites, self.screen.color_profile, invert_colors=invert_colors, screen_reversed=self.screen_reversed)

    def render_cursor(self, sg, cursor_program, is_focused):
        cursor = self.current_cursor
        if not self.screen.cursor_visible or self.screen.scrolled_by:
            return

        def width(w=2, vert=True):
            dpi = self.dpix if vert else self.dpiy
            w *= dpi / 72.0  # as pixels
            factor = 2 / (viewport_size.width if vert else viewport_size.height)
            return w * factor

        ul = cursor_program.uniform_location
        left = sg.xstart + cursor.x * sg.dx
        top = sg.ystart - cursor.y * sg.dy
        col = color_from_int(self.screen.color_profile.cursor_color)
        shape = cursor.shape or self.default_cursor.shape
        alpha = self.opts.cursor_opacity
        if alpha < 1.0 and shape == CURSOR_BLOCK:
            glEnable(GL_BLEND)
        mult = self.screen.current_char_width()
        right = left + (width(1.5) if shape == CURSOR_BEAM else sg.dx * mult)
        bottom = top - sg.dy
        if shape == CURSOR_UNDERLINE:
            top = bottom + width(vert=False)
        glUniform4f(ul('color'), col[0] / 255.0, col[1] / 255.0, col[2] / 255.0, alpha)
        glUniform2f(ul('xpos'), left, right)
        glUniform2f(ul('ypos'), top, bottom)
        with cursor_program.bound_vertex_array(cursor_program.vao_id):
            glDrawArrays(GL_TRIANGLE_FAN if is_focused else GL_LINE_LOOP, 0, 4)
        glDisable(GL_BLEND)
