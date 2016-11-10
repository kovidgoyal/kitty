#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from copy import copy
from ctypes import c_uint
from itertools import chain, repeat
from queue import Queue, Empty

from .config import build_ansi_color_table, to_color
from .fonts import set_font_family
from .shaders import Sprites, ShaderProgram
from .utils import get_logical_dpi
from .fast_data_types import (
    glBlendFunc, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, glClear,
    GL_COLOR_BUFFER_BIT, glClearColor, glViewport, glUniform2ui, glUniform4f,
    glUniform1i, glUniform2f, glDrawArraysInstanced, GL_TRIANGLE_FAN,
    glEnable, glDisable, GL_BLEND, glDrawArrays, ColorProfile, REVERSE
)

Size = namedtuple('Size', 'width height')
Cursor = namedtuple('Cursor', 'x y hidden shape color blink')
ScreenGeometry = namedtuple('ScreenGeometry', 'xstart ystart xnum ynum dx dy')
COL_MASK = 0xFFFFFFFF
COL_SHIFT = 32
REVERSE_MASK = 1 << REVERSE

# cell shader {{{

cell_shader = (
    '''\
uniform uvec2 dimensions;  // xnum, ynum
uniform vec4 steps;  // xstart, ystart, dx, dy
uniform vec2 sprite_layout;  // dx, dy
uniform usamplerBuffer sprite_map; // gl_InstanceID -> x, y, z
out vec3 sprite_pos;
out vec4 foreground;
out vec4 background;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

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

    int sprite_id = int(instance_id) * 3;
    uvec4 spos = texelFetch(sprite_map, sprite_id);
    vec2 s_xpos = vec2(spos[0], spos[0] + 1.0) * sprite_layout[0];
    vec2 s_ypos = vec2(spos[1], spos[1] + 1.0) * sprite_layout[1];
    sprite_pos = vec3(s_xpos[pos[0]], s_ypos[pos[1]], spos[2]);
    foreground = texelFetch(sprite_map, sprite_id + 1) / 255.0;
    background = texelFetch(sprite_map, sprite_id + 2) / 255.0;
}
''',

    '''\
uniform sampler2DArray sprites;
in vec3 sprite_pos;
in vec4 foreground;
in vec4 background;
out vec4 final_color;

void main() {
    float alpha = texture(sprites, sprite_pos).r;
    final_color = background * (1 - alpha) + foreground * alpha;
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


def calculate_vertices(cell_width, cell_height, screen_width, screen_height):
    xnum = screen_width // cell_width
    ynum = screen_height // cell_height
    dx, dy = 2 * cell_width / screen_width, 2 * cell_height / screen_height
    xmargin = (screen_width - (xnum * cell_width)) / screen_width
    ymargin = (screen_height - (ynum * cell_height)) / screen_height
    xstart = -1 + xmargin
    ystart = 1 - ymargin
    return ScreenGeometry(xstart, ystart, xnum, ynum, dx, dy)


class RenderData:

    __slots__ = 'viewport clear_color cell_data screen_geometry sprite_layout cursor'.split()

    def __init__(self, viewport=None, clear_color=None, cell_data=None, screen_geometry=None, sprite_layout=None, cursor=None):
        self.viewport, self.clear_color, self.cell_data = viewport, clear_color, cell_data
        self.screen_geometry = screen_geometry
        self.sprite_layout = sprite_layout
        self.cursor = cursor

    def update(self, other):
        for k in self.__slots__:
            val = getattr(other, k)
            if val is not None:
                setattr(self, k, val)

empty_cell = (' ', 0)


class CharGrid:

    def __init__(self, screen, opts, window_width, window_height):
        self.dpix, self.dpiy = get_logical_dpi()
        self.width, self.height = window_width, window_height
        self.color_profile = ColorProfile()
        self.as_color = self.color_profile.as_color
        self.screen = screen
        self.opts = opts
        self.original_bg = opts.background
        self.original_fg = opts.foreground
        self.render_queue = Queue()
        self.program = ShaderProgram(*cell_shader)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self.sprites = Sprites()
        self.cursor_program = ShaderProgram(*cursor_shader)
        self.last_render_data = RenderData()
        self.default_cursor = Cursor(0, 0, False, opts.cursor_shape, opts.cursor, opts.cursor_blink)
        self.render_queue.put(RenderData(
            viewport=Size(self.width, self.height), clear_color=self.original_bg,
            cursor=self.default_cursor))

    def destroy(self):
        self.sprites.destroy()

    def initialize(self):
        self.default_bg, self.default_fg = self.original_bg, self.original_fg
        self.apply_opts(self.opts)

    def apply_opts(self, opts):
        self.dpix, self.dpiy = get_logical_dpi()
        self.opts = opts
        self.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        self.default_cursor = Cursor(0, 0, False, opts.cursor_shape, opts.cursor, opts.cursor_blink)
        self.opts = opts
        self.original_bg = opts.background
        self.original_fg = opts.foreground
        self.cell_width, self.cell_height = set_font_family(opts.font_family, opts.font_size)
        self.sprites.do_layout(self.cell_width, self.cell_height)
        self.do_layout(self.width, self.height)

    def resize_screen(self, w, h):
        ' Screen was resized by the user (called in non-UI thread) '
        self.do_layout(w, h)

    def do_layout(self, w, h):
        self.width, self.height = w, h
        self.screen_geometry = sg = calculate_vertices(self.cell_width, self.cell_height, self.width, self.height)
        self.screen.resize(sg.ynum, sg.xnum)
        self.sprite_map = (c_uint * (sg.ynum * sg.xnum * 9))()
        self.sprite_text = list(repeat(empty_cell, sg.xnum * sg.ynum))
        self.update_cell_data(add_viewport_data=True)

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
            self.render_queue.put(RenderData(clear_color=self.default_bg))

    def update_cell_data(self, changes=None, add_viewport_data=False):
        rd = RenderData(sprite_layout=self.sprites.layout)
        if add_viewport_data:
            rd.viewport = Size(self.width, self.height)
            rd.screen_geometry = self.screen_geometry
        if changes is None:
            changes = {'screen': True}
        sg = self.screen_geometry
        cell_data_changed = changes['screen'] or changes['cells'] or changes['lines']
        if cell_data_changed:
            if changes['screen']:
                lines = range(sg.ynum)
                cell_ranges = {}
            else:
                lines = changes['lines']
                cell_ranges = changes['cells']

            dfbg = self.default_bg
            dffg = self.default_fg

            for y in lines:
                self.update_line(y, range(sg.xnum), dffg, dfbg)

            for y, ranges in cell_ranges.items():
                self.update_line(y, chain.from_iterable(range(start, stop + 1) for start, stop in ranges),
                                 dffg, dfbg)

            rd.cell_data = copy(self.sprite_map), self.sprite_text[:]
            rd.sprite_layout = self.sprites.layout
        c = changes.get('cursor')
        if c is not None:
            rd.cursor = Cursor(c.x, c.y, c.hidden, c.shape, c.color, c.blink)
        self.render_queue.put(rd)

    def update_line(self, y, cell_range, dffg, dfbg):
        line = self.screen.line(y)
        for x in cell_range:
            self.update_cell(line, x, y, dffg, dfbg)

    def update_cell(self, line, x, y, dffg, dfbg):
        ch, attrs, colors = line.basic_cell_data(x)
        idx = x + y * self.screen_geometry.xnum
        offset = idx * 9
        bgcol = colors >> COL_SHIFT
        if bgcol:
            bgcol = self.as_color(bgcol) or dfbg
        else:
            bgcol = dfbg
        fgcol = colors & COL_MASK
        if fgcol:
            fgcol = self.as_color(fgcol) or dffg
        else:
            fgcol = dffg
        if attrs & REVERSE_MASK:
            self.sprite_map[offset + 3:offset + 6] = bgcol
            self.sprite_map[offset + 6:offset + 9] = fgcol
        else:
            self.sprite_map[offset + 3:offset + 6] = fgcol
            self.sprite_map[offset + 6:offset + 9] = bgcol
        if ch == 0 or ch == 32:
            self.sprite_text[idx] = empty_cell
        else:
            self.sprite_text[idx] = line[x], attrs

    def render(self):
        ' This is the only method in this class called in the UI thread (apart from __init__) '
        glClear(GL_COLOR_BUFFER_BIT)
        cell_data_changed = self.get_all_render_changes()
        with self.sprites:
            if cell_data_changed:
                self.update_sprite_map()
            data = self.last_render_data

            if data.screen_geometry is None:
                return
            sg = data.screen_geometry
            self.render_cells(sg, data.sprite_layout)
        if not data.cursor.hidden:
            self.render_cursor(sg, data.cursor)

    def get_all_render_changes(self):
        cell_data_changed = False
        data = self.last_render_data
        while True:
            try:
                rd = self.render_queue.get_nowait()
            except Empty:
                break
            cell_data_changed |= rd.cell_data is not None
            if rd.clear_color is not None:
                bg = rd.clear_color
                glClearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1)
            if rd.viewport is not None:
                glViewport(0, 0, self.width, self.height)
            data.update(rd)
        return cell_data_changed

    def update_sprite_map(self):
        spmap, sptext = self.last_render_data.cell_data
        psp = self.sprites.primary_sprite_position
        empty_val = psp(empty_cell)  # Ensure the empty cell is 0, 0, 0
        for i, key in enumerate(sptext):
            f = i * 9
            spmap[f:f + 3] = empty_val if key is empty_cell else psp(key)
        self.sprites.set_sprite_map(spmap)

    def render_cells(self, sg, sprite_layout):
        with self.program:
            ul = self.program.uniform_location
            glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
            glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
            glUniform1i(ul('sprites'), self.sprites.sampler_num)
            glUniform1i(ul('sprite_map'), self.sprites.buffer_sampler_num)
            glUniform2f(ul('sprite_layout'), *sprite_layout)
            glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)

    def render_cursor(self, sg, cursor):

        def width(w=2, vert=True):
            dpi = self.dpix if vert else self.dpiy
            w *= dpi / 72.0  # as pixels
            factor = 2 / (self.width if vert else self.height)
            return w * factor

        with self.cursor_program:
            ul = self.cursor_program.uniform_location
            left = sg.xstart + cursor.x * sg.dx
            top = sg.ystart - cursor.y * sg.dy
            col = cursor.color or self.default_cursor.color
            shape = cursor.shape or self.default_cursor.shape
            alpha = self.opts.cursor_opacity
            if alpha < 1.0 and shape == 'block':
                glEnable(GL_BLEND)
            right = left + (width(1.5) if shape == 'beam' else sg.dx)
            bottom = top - sg.dy
            if shape == 'underline':
                top = bottom + width(vert=False)
            glUniform4f(ul('color'), col[0], col[1], col[2], alpha)
            glUniform2f(ul('xpos'), left, right)
            glUniform2f(ul('ypos'), top, bottom)
            glDrawArrays(GL_TRIANGLE_FAN, 0, 4)
            glDisable(GL_BLEND)
