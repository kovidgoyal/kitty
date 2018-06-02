#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from .config import build_ansi_color_table
from .constants import WindowGeometry
from .fast_data_types import (
    DECAWM, Screen, cell_size_for_window, pt_to_px, viewport_for_window, set_tab_bar_render_data
)
from .layout import Rect
from .utils import color_as_int
from .window import calculate_gl_geometry


class TabBar:

    def __init__(self, os_window_id, opts):
        self.os_window_id = os_window_id
        self.opts = opts
        self.num_tabs = 1
        self.margin_width = pt_to_px(self.opts.tab_bar_margin_width, self.os_window_id)
        self.cell_width, cell_height = cell_size_for_window(self.os_window_id)
        self.data_buffer_size = 0
        self.laid_out_once = False
        self.dirty = True
        self.screen = s = Screen(None, 1, 10, 0, self.cell_width, cell_height)
        s.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        s.color_profile.set_configured_colors(
            color_as_int(opts.inactive_tab_foreground),
            color_as_int(opts.inactive_tab_background)
        )
        self.blank_rects = ()
        sep = opts.tab_separator
        self.trailing_spaces = self.leading_spaces = 0
        while sep and sep[0] == ' ':
            sep = sep[1:]
            self.trailing_spaces += 1
        while sep and sep[-1] == ' ':
            self.leading_spaces += 1
            sep = sep[:-1]
        self.sep = sep
        self.active_font_style = opts.active_tab_font_style
        self.inactive_font_style = opts.inactive_tab_font_style

        def as_rgb(x):
            return (x << 8) | 2

        self.active_bg = as_rgb(color_as_int(opts.active_tab_background))
        self.active_fg = as_rgb(color_as_int(opts.active_tab_foreground))
        self.bell_fg = as_rgb(0xff0000)

    def patch_colors(self, spec):
        if 'active_tab_foreground' in spec:
            self.active_fg = (spec['active_tab_foreground'] << 8) | 2
        if 'active_tab_background' in spec:
            self.active_bg = (spec['active_tab_background'] << 8) | 2
        self.screen.color_profile.set_configured_colors(
                spec.get('inactive_tab_foreground', color_as_int(self.opts.inactive_tab_foreground)),
                spec.get('inactive_tab_background', color_as_int(self.opts.inactive_tab_background))
        )

    def layout(self):
        central, tab_bar, vw, vh, cell_width, cell_height = viewport_for_window(self.os_window_id)
        if tab_bar.width < 2:
            return
        self.cell_width = cell_width
        s = self.screen
        viewport_width = tab_bar.width - 2 * self.margin_width
        ncells = viewport_width // cell_width
        s.resize(1, ncells)
        s.reset_mode(DECAWM)
        self.laid_out_once = True
        margin = (viewport_width - ncells * cell_width) // 2 + self.margin_width
        self.window_geometry = g = WindowGeometry(
            margin, tab_bar.top, viewport_width - margin, tab_bar.bottom, s.columns, s.lines)
        if margin > 0:
            self.blank_rects = (Rect(0, g.top, g.left, g.bottom + 1), Rect(g.right - 1, g.top, viewport_width, g.bottom + 1))
        else:
            self.blank_rects = ()
        self.screen_geometry = sg = calculate_gl_geometry(g, vw, vh, cell_width, cell_height)
        set_tab_bar_render_data(self.os_window_id, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen)

    def update(self, data):
        if not self.laid_out_once:
            return
        s = self.screen
        s.cursor.x = 0
        s.erase_in_line(2, False)
        max_title_length = (self.screen_geometry.xnum // max(1, len(data))) - 1
        cr = []

        for t in data:
            s.cursor.bg = self.active_bg if t.is_active else 0
            s.cursor.fg = fg = self.active_fg if t.is_active else 0
            s.cursor.bold, s.cursor.italic = self.active_font_style if t.is_active else self.inactive_font_style
            before = s.cursor.x
            if self.leading_spaces:
                s.draw(' ' * self.leading_spaces)
            if t.needs_attention and self.opts.bell_on_tab:
                s.cursor.fg = self.bell_fg
                s.draw('🔔 ')
                s.cursor.fg = fg
            s.draw(t.title)
            if self.trailing_spaces:
                s.draw(' ' * self.trailing_spaces)
            extra = s.cursor.x - before - max_title_length
            if extra > 0:
                s.cursor.x -= extra + 1
                s.draw('…')
            cr.append((before, s.cursor.x))
            s.cursor.bold = s.cursor.italic = False
            s.cursor.fg = s.cursor.bg = 0
            s.draw(self.sep)
            if s.cursor.x > s.columns - max_title_length and not t.is_last:
                s.draw('…')
                break
        s.erase_in_line(0, False)  # Ensure no long titles bleed after the last tab
        self.cell_ranges = cr

    def destroy(self):
        self.screen.reset_callbacks()
        del self.screen

    def tab_at(self, x):
        x = (x - self.window_geometry.left) // self.cell_width
        for i, (a, b) in enumerate(self.cell_ranges):
            if a <= x <= b:
                return i
