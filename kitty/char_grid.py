#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
from collections import namedtuple
from ctypes import addressof, memmove, sizeof
from enum import Enum
from threading import Lock

from .config import build_ansi_color_table, defaults
from .constants import (
    GLfloat, GLuint, ScreenGeometry, cell_size, get_boss, viewport_size
)
from .fast_data_types import (
    CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE, DATA_CELL_SIZE, GL_BLEND,
    GL_FLOAT, GL_LINE_LOOP, GL_TRIANGLE_FAN, GL_UNSIGNED_INT, glDisable,
    glDrawArrays, glDrawArraysInstanced, glEnable, glUniform1i, glUniform2f,
    glUniform2i, glUniform2ui, glUniform4f, glUniform4ui
)
from .rgb import to_color
from .shaders import ShaderProgram, load_shaders
from .utils import (
    color_as_int, color_from_int, get_logical_dpi, open_url, safe_print,
    set_primary_selection
)

Cursor = namedtuple('Cursor', 'x y shape blink')


class DynamicColor(Enum):
    default_fg, default_bg, cursor_color, highlight_fg, highlight_bg = range(1, 6)


class CellProgram(ShaderProgram):

    def __init__(self, *args):
        ShaderProgram.__init__(self, *args)
        self.color_table_buf = None

    def send_color_table(self, color_profile):
        if color_profile.ubo is None:
            color_profile.ubo = self.init_uniform_block('ColorTable', 'color_table')
        ubo = color_profile.ubo
        if self.color_table_buf is None:
            self.color_table_buf = (GLuint * (ubo.size // sizeof(GLuint)))()
        offset = ubo.offsets['color_table'] // sizeof(GLuint)
        stride = ubo.size // (256 * sizeof(GLuint))
        color_profile.copy_color_table(addressof(self.color_table_buf), offset, stride)
        self.send_uniform_buffer_data(ubo, self.color_table_buf)

    def create_sprite_map(self):
        with self.array_object_creator() as add_attribute:
            stride = DATA_CELL_SIZE * sizeof(GLuint)
            size = DATA_CELL_SIZE // 2
            add_attribute('sprite_coords', size=size, dtype=GL_UNSIGNED_INT, stride=stride, divisor=1)
            add_attribute('colors', size=size, dtype=GL_UNSIGNED_INT, stride=stride, offset=stride // 2, divisor=1)
            add_attribute.newbuf()
            add_attribute('is_selected', size=1, dtype=GL_FLOAT, stride=sizeof(GLfloat), divisor=1)
            return add_attribute.vao_id


def load_shader_programs():
    cell = CellProgram(*load_shaders('cell'))
    cursor = ShaderProgram(*load_shaders('cursor'))
    with cursor.array_object_creator() as add_attribute:
        cursor.vao_id = add_attribute.vao_id
    return cell, cursor


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

    def text(self, linebuf, historybuf):
        sy = self.start_y - self.start_scrolled_by
        ey = self.end_y - self.end_scrolled_by
        if sy == ey and self.start_x == self.end_x:
            return ''
        a, b = (sy, self.start_x), (ey, self.end_x)
        if a > b:
            a, b = b, a

        def line(y):
            if y < 0:
                return historybuf.line(-1 - y)
            return linebuf.line(y)

        lines = []
        for y in range(a[0], b[0] + 1):
            startx, endx = 0, linebuf.xnum - 1
            if y == a[0]:
                startx = max(0, min(a[1], endx))
            if y == b[0]:
                endx = max(0, min(b[1], endx))
            l = line(y)
            is_continued = l.is_continued()
            if endx - startx >= linebuf.xnum - 1:
                l = str(l).rstrip(' ')
            else:
                l = ''.join(l[x] for x in range(startx, endx + 1))
            if not is_continued and startx == 0 and len(lines) > 0:
                l = '\n' + l
            lines.append(l)
        return ''.join(lines)
# }}}


def calculate_gl_geometry(window_geometry, viewport_width, viewport_height, cell_width, cell_height):
    dx, dy = 2 * cell_width / viewport_width, 2 * cell_height / viewport_height
    xmargin = window_geometry.left / viewport_width
    ymargin = window_geometry.top / viewport_height
    xstart = -1 + 2 * xmargin
    ystart = 1 - 2 * ymargin
    return ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)


def render_cells(vao_id, sg, cell_program, sprites, color_profile, invert_colors=False):
    if color_profile.dirty:
        cell_program.send_color_table(color_profile)
        color_profile.dirty = False
    ul = cell_program.uniform_location
    glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
    glUniform4ui(ul('default_colors'), color_profile.default_fg, color_profile.default_bg, color_profile.highlight_fg, color_profile.highlight_bg)
    glUniform2i(ul('color_indices'), 1 if invert_colors else 0, 0 if invert_colors else 1)
    glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
    glUniform1i(ul('sprites'), sprites.sampler_num)
    glUniform2f(ul('sprite_layout'), *(sprites.layout))
    with cell_program.bound_vertex_array(vao_id), cell_program.bound_uniform_buffer(color_profile.ubo):
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)


class CharGrid:

    url_pat = re.compile('(?:http|https|file|ftp)://\S+', re.IGNORECASE)

    def __init__(self, screen, opts):
        self.buffer_lock = Lock()
        self.vao_id = None
        self.current_selection = Selection()
        self.last_rendered_selection = None
        self.render_buf_is_dirty = True
        self.render_data = None
        self.scrolled_by = 0
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
        self.main_sprite_map = self.scroll_sprite_map = self.render_buf = None

        def escape(chars):
            return ''.join(frozenset(chars)).replace('\\', r'\\').replace(']', r'\]').replace('-', r'\-')

        try:
            self.word_pat = re.compile(r'[\w{}]'.format(escape(self.opts.select_by_word_characters)), re.UNICODE)
        except Exception:
            safe_print('Invalid characters in select_by_word_characters, ignoring', file=sys.stderr)
            self.word_pat = re.compile(r'[\w{}]'.format(escape(defaults.select_by_word_characters)), re.UNICODE)

    def destroy(self, cell_program):
        if self.vao_id is not None:
            cell_program.remove_vertex_array(self.vao_id)
            self.vao_id = None

    def update_position(self, window_geometry):
        self.screen_geometry = calculate_gl_geometry(window_geometry, viewport_size.width, viewport_size.height, cell_size.width, cell_size.height)

    def resize(self, window_geometry):
        self.update_position(window_geometry)
        rt = (GLuint * (self.screen_geometry.ynum * self.screen_geometry.xnum * DATA_CELL_SIZE))
        self.main_sprite_map = rt()
        self.scroll_sprite_map = rt()
        with self.buffer_lock:
            self.render_buf = rt()
            self.selection_buf = (GLfloat * (self.screen_geometry.ynum * self.screen_geometry.xnum))()
            self.render_buf_is_dirty = True
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

    def scroll(self, amt, upwards=True):
        if not isinstance(amt, int):
            amt = {'line': 1, 'page': self.screen.lines - 1, 'full': self.screen.historybuf.count}[amt]
        if not upwards:
            amt *= -1
        y = max(0, min(self.scrolled_by + amt, self.screen.historybuf.count))
        if y != self.scrolled_by:
            self.scrolled_by = y
            self.update_cell_data()

    def update_cell_data(self, force_full_refresh=False):
        sprites = get_boss().sprites
        is_dirty = self.screen.is_dirty()
        with sprites.lock:
            cursor_changed, history_line_added_count = self.screen.update_cell_data(
                sprites.backend, addressof(self.main_sprite_map), force_full_refresh)
            if self.scrolled_by:
                self.scrolled_by = min(self.scrolled_by + history_line_added_count, self.screen.historybuf.count)
                self.screen.set_scroll_cell_data(
                    sprites.backend, addressof(self.main_sprite_map),
                    self.scrolled_by, addressof(self.scroll_sprite_map))

        data = self.scroll_sprite_map if self.scrolled_by else self.main_sprite_map
        with self.buffer_lock:
            if is_dirty:
                self.current_selection.clear()
            memmove(self.render_buf, data, sizeof(type(data)))
            self.render_data = self.screen_geometry
            self.render_buf_is_dirty = True
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
        with self.buffer_lock:
            if is_press:
                self.current_selection.start_x = self.current_selection.end_x = x
                self.current_selection.start_y = self.current_selection.end_y = y
                self.current_selection.start_scrolled_by = self.current_selection.end_scrolled_by = self.scrolled_by
                self.current_selection.in_progress = True
            elif self.current_selection.in_progress:
                self.current_selection.end_x = x
                self.current_selection.end_y = y
                self.current_selection.end_scrolled_by = self.scrolled_by
                if is_press is False:
                    self.current_selection.in_progress = False
                    ps = self.text_for_selection()
        if ps and ps.strip():
            set_primary_selection(ps)

    def has_url_at(self, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            l = self.screen_line(y)
            if l is not None:
                text = l.as_base_text()
                for m in self.url_pat.finditer(text):
                    if m.start() <= x < m.end():
                        return True
        return False

    def click_url(self, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            l = self.screen_line(y)
            if l is not None:
                text = l.as_base_text()
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

    def screen_line(self, y):
        ' Return the Line object corresponding to the yth line on the rendered screen '
        if y >= 0 and y < self.screen.lines:
            if self.scrolled_by:
                if y < self.scrolled_by:
                    return self.screen.historybuf.line(self.scrolled_by - 1 - y)
                return self.screen.line(y - self.scrolled_by)
            else:
                return self.screen.line(y)

    def multi_click(self, count, x, y):
        x, y = self.cell_for_pos(x, y)
        if x is not None:
            line = self.screen_line(y)
            if line is not None and count in (2, 3):
                s = self.current_selection
                s.start_scrolled_by = s.end_scrolled_by = self.scrolled_by
                s.start_y = s.end_y = y
                s.in_progress = False
                if count == 3:
                    for i in range(self.screen.columns):
                        if line[i] != ' ':
                            s.start_x = i
                            break
                    else:
                        s.start_x = 0
                    for i in range(self.screen.columns):
                        c = self.screen.columns - 1 - i
                        if line[c] != ' ':
                            s.end_x = c
                            break
                    else:
                        s.end_x = self.screen.columns - 1
                elif count == 2:
                    i = x
                    while i >= 0 and self.word_pat.match(line[i]) is not None:
                        i -= 1
                    s.start_x = i if i == x else i + 1
                    i = x
                    while i < self.screen.columns and self.word_pat.match(line[i]) is not None:
                        i += 1
                    s.end_x = i if i == x else i - 1
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
        return s.text(self.screen.linebuf, self.screen.historybuf)

    def prepare_for_render(self, cell_program):
        with self.buffer_lock:
            sg = self.render_data
            if sg is None:
                return
            if self.vao_id is None:
                self.vao_id = cell_program.create_sprite_map()
            start, end = sel = self.current_selection.limits(self.scrolled_by, self.screen.lines, self.screen.columns)
            selection_changed = sel != self.last_rendered_selection
            if selection_changed:
                self.screen.apply_selection(addressof(self.selection_buf), start[0], start[1], end[0], end[1], len(self.selection_buf))
                cell_program.send_vertex_data(self.vao_id, self.selection_buf, bufnum=1)
                self.last_rendered_selection = sel
            if self.render_buf_is_dirty:
                cell_program.send_vertex_data(self.vao_id, self.render_buf)
                self.render_buf_is_dirty = False
        return sg

    def render_cells(self, sg, cell_program, sprites, invert_colors=False):
        render_cells(self.vao_id, sg, cell_program, sprites, self.screen.color_profile, invert_colors=invert_colors)

    def render_cursor(self, sg, cursor_program, is_focused):
        cursor = self.current_cursor
        if not self.screen.cursor_visible or self.scrolled_by:
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
