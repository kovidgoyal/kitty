#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from ctypes import c_uint, addressof, memmove, sizeof
from itertools import count
from threading import Lock

from .config import build_ansi_color_table
from .constants import tab_manager, viewport_size, cell_size, ScreenGeometry
from .utils import get_logical_dpi, to_color
from .fast_data_types import (
    glUniform2ui, glUniform4f, glUniform1i, glUniform2f, glDrawArraysInstanced,
    GL_TRIANGLE_FAN, glEnable, glDisable, GL_BLEND, glDrawArrays, ColorProfile,
    CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE, DATA_CELL_SIZE
)

Cursor = namedtuple('Cursor', 'x y hidden shape color blink')

if DATA_CELL_SIZE % 3:
    raise ValueError('Incorrect data cell size, must be a multiple of 3')

# cell shader {{{

cell_shader = (
    '''\
uniform uvec2 dimensions;  // xnum, ynum
uniform vec4 steps;  // xstart, ystart, dx, dy
uniform vec2 sprite_layout;  // dx, dy
uniform usamplerBuffer sprite_map; // gl_InstanceID -> x, y, z
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 strike_pos;
out vec3 foreground;
out vec3 background;
out vec3 decoration_fg;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

const uint BYTE_MASK = uint(255);
const uint ZERO = uint(0);
const uint SMASK = uint(3);

vec3 to_color(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(r / 255.0, g / 255.0, b / 255.0);
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, x + 1.0) * sprite_layout[0];
    vec2 s_ypos = vec2(y, y + 1.0) * sprite_layout[1];
    return vec3(s_xpos[pos[0]], s_ypos[pos[1]], z);
}

void main() {
    uint instance_id = uint(gl_InstanceID);
    uint r = instance_id / dimensions[0];
    uint c = instance_id - r * dimensions[0];
    float left = steps[0] + c * steps[2];
    float top = steps[1] - r * steps[3];
    vec2 xpos = vec2(left, left + steps[2]);
    vec2 ypos = vec2(top, top - steps[3]);
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos[0]], ypos[pos[1]], 0, 1);

    int sprite_id = int(instance_id) * STRIDE;
    uvec4 spos = texelFetch(sprite_map, sprite_id);
    uvec4 colors = texelFetch(sprite_map, sprite_id + 1);
    sprite_pos = to_sprite_pos(pos, spos[0], spos[1], spos[2]);
    foreground = to_color(colors[0]);
    background = to_color(colors[1]);
    uint decoration = colors[2];
    decoration_fg = to_color(decoration);
    underline_pos = to_sprite_pos(pos, (decoration >> 24) & SMASK, ZERO, ZERO);
    strike_pos = to_sprite_pos(pos, (decoration >> 26) & SMASK, ZERO, ZERO);
}
'''.replace('STRIDE', str(DATA_CELL_SIZE // 3)),

    '''\
uniform sampler2DArray sprites;
in vec3 sprite_pos;
in vec3 underline_pos;
in vec3 strike_pos;
in vec3 foreground;
in vec3 background;
in vec3 decoration_fg;
out vec4 final_color;

vec3 blend(float alpha, vec3 over, vec3 under) {
    return over + (1 - alpha) * under;
}

void main() {
    float text_alpha = texture(sprites, sprite_pos).r;
    float underline_alpha = texture(sprites, underline_pos).r;
    float strike_alpha = texture(sprites, strike_pos).r;
    vec3 underline = underline_alpha * decoration_fg;
    vec3 strike = strike_alpha * foreground;
    vec3 fg = text_alpha * foreground;
    vec3 decoration = blend(underline_alpha, underline, strike);
    vec3 combined_fg = blend(text_alpha, fg, decoration);
    float combined_alpha = max(max(underline_alpha, strike_alpha), text_alpha);
    final_color = vec4(blend(combined_alpha, combined_fg, background), 1);
}
''')
# }}}

# cursor shader {{{

cursor_shader = (
    '''\
uniform vec2 xpos;
uniform vec2 ypos;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos[0]], ypos[pos[1]], 0, 1);
}
''',

    '''\
uniform vec4 color;
out vec4 final_color;

void main() {
    final_color = color;
}
''')
# }}}


def color_as_int(val):
    return val[0] << 16 | val[1] << 8 | val[2]


render_data_num = count()


class CharGrid:

    def __init__(self, screen, opts):
        self.buffer_lock = Lock()
        self.render_num = next(render_data_num)
        self.render_data = None
        self.last_render_send_num = -1
        self.scrolled_by = 0
        self.color_profile = ColorProfile()
        self.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        self.screen = screen
        self.opts = opts
        self.original_bg = opts.background
        self.original_fg = opts.foreground
        self.default_cursor = Cursor(0, 0, False, opts.cursor_shape, opts.cursor, opts.cursor_blink)
        self.default_bg = color_as_int(self.original_bg)
        self.default_fg = color_as_int(self.original_fg)
        self.dpix, self.dpiy = get_logical_dpi()
        self.opts = opts
        self.default_cursor = self.current_cursor = Cursor(0, 0, False, opts.cursor_shape, opts.cursor, opts.cursor_blink)
        self.opts = opts
        self.original_bg = opts.background
        self.original_fg = opts.foreground
        self.sprite_map_type = self.main_sprite_map = self.scroll_sprite_map = self.render_buf = None

    def update_position(self, window_geometry):
        dx, dy = 2 * cell_size.width / viewport_size.width, 2 * cell_size.height / viewport_size.height
        xmargin = window_geometry.left / viewport_size.width
        ymargin = window_geometry.top / viewport_size.height
        xstart = -1 + xmargin
        ystart = 1 - ymargin
        self.screen_geometry = ScreenGeometry(xstart, ystart, window_geometry.xnum, window_geometry.ynum, dx, dy)

    def resize(self, window_geometry):
        self.update_position(window_geometry)
        self.sprite_map_type = (c_uint * (self.screen_geometry.ynum * self.screen_geometry.xnum * DATA_CELL_SIZE))
        self.main_sprite_map = self.sprite_map_type()
        self.scroll_sprite_map = self.sprite_map_type()
        with self.buffer_lock:
            self.render_buf = self.sprite_map_type()
            self.render_num = next(render_data_num)

    def change_colors(self, changes):
        dirtied = False
        for which, val in changes.items():
            if which in ('fg', 'bg'):
                if not val:
                    setattr(self, 'default_' + which, color_as_int(getattr(self, 'original_' + which)))
                    dirtied = True
                else:
                    val = to_color(val)
                    if val is not None:
                        setattr(self, 'default_' + which, color_as_int(val))
                        dirtied = True
        if dirtied:
            self.screen.mark_as_dirty()

    def scroll(self, amt, upwards=True):
        amt = {'line': 1, 'page': self.screen.lines - 1, 'full': self.screen.historybuf.count}[amt]
        if not upwards:
            amt *= -1
        y = max(0, min(self.scrolled_by + amt, self.screen.historybuf.count))
        if y != self.scrolled_by:
            self.scrolled_by = y
            self.update_cell_data()

    def update_cell_data(self, force_full_refresh=False):
        sprites = tab_manager().sprites
        with sprites.lock:
            cursor_changed, history_line_added_count = self.screen.update_cell_data(
                sprites.backend, self.color_profile, addressof(self.main_sprite_map), self.default_fg, self.default_bg, force_full_refresh)
            if self.scrolled_by:
                self.scrolled_by = min(self.scrolled_by + history_line_added_count, self.screen.historybuf.count)
                self.screen.set_scroll_cell_data(
                    sprites.backend, self.color_profile, addressof(self.main_sprite_map), self.default_fg, self.default_bg,
                    self.scrolled_by, addressof(self.scroll_sprite_map))

        data = self.scroll_sprite_map if self.scrolled_by else self.main_sprite_map
        with self.buffer_lock:
            memmove(self.render_buf, data, sizeof(type(data)))
            self.render_num = next(render_data_num)
            self.render_data = self.screen_geometry
        if cursor_changed:
            c = self.screen.cursor
            self.current_cursor = Cursor(c.x, c.y, c.hidden, c.shape, c.color, c.blink)

    def prepare_for_render(self, sprites):
        with self.buffer_lock:
            sg = self.render_data
            if sg is None:
                return
            if self.last_render_send_num != self.render_num:
                sprites.set_sprite_map(self.render_buf)
                self.last_render_send_num = self.render_num
        return sg

    def render_cells(self, sg, cell_program, sprites):
        ul = cell_program.uniform_location
        glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
        glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
        glUniform1i(ul('sprites'), sprites.sampler_num)
        glUniform1i(ul('sprite_map'), sprites.buffer_sampler_num)
        glUniform2f(ul('sprite_layout'), *(sprites.layout))
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)

    def render_cursor(self, sg, cursor_program):
        cursor = self.current_cursor
        if cursor.hidden or self.scrolled_by:
            return

        def width(w=2, vert=True):
            dpi = self.dpix if vert else self.dpiy
            w *= dpi / 72.0  # as pixels
            factor = 2 / (self.width if vert else self.height)
            return w * factor

        ul = cursor_program.uniform_location
        left = sg.xstart + cursor.x * sg.dx
        top = sg.ystart - cursor.y * sg.dy
        col = cursor.color or self.default_cursor.color
        shape = cursor.shape or self.default_cursor.shape
        alpha = self.opts.cursor_opacity
        if alpha < 1.0 and shape == CURSOR_BLOCK:
            glEnable(GL_BLEND)
        mult = self.screen.current_char_width()
        right = left + (width(1.5) if shape == CURSOR_BEAM else sg.dx * mult)
        bottom = top - sg.dy
        if shape == CURSOR_UNDERLINE:
            top = bottom + width(vert=False)
        glUniform4f(ul('color'), col[0], col[1], col[2], alpha)
        glUniform2f(ul('xpos'), left, right)
        glUniform2f(ul('ypos'), top, bottom)
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4)
        glDisable(GL_BLEND)
