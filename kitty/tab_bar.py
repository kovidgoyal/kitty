#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple

from .config import build_ansi_color_table
from .constants import WindowGeometry
from .fast_data_types import (
    DECAWM, Screen, cell_size_for_window, pt_to_px, set_tab_bar_render_data,
    viewport_for_window
)
from .layout import Rect
from .utils import color_as_int
from .window import calculate_gl_geometry
from .rgb import alpha_blend, color_from_int

TabBarData = namedtuple('TabBarData', 'title is_active needs_attention')
DrawData = namedtuple('DrawData', 'leading_spaces sep trailing_spaces bell_on_tab bell_fg alpha active_bg inactive_bg default_bg')


def as_rgb(x):
    return (x << 8) | 2


def draw_title(draw_data, screen, tab):
    if tab.needs_attention and draw_data.bell_on_tab:
        fg = screen.cursor.fg
        screen.cursor.fg = draw_data.bell_fg
        screen.draw('🔔 ')
        screen.cursor.fg = fg
    screen.draw(tab.title)


def draw_tab_with_separator(draw_data, screen, tab, before, max_title_length):
    if draw_data.leading_spaces:
        screen.draw(' ' * draw_data.leading_spaces)
    draw_title(draw_data, screen, tab)
    if draw_data.trailing_spaces:
        screen.draw(' ' * draw_data.trailing_spaces)
    extra = screen.cursor.x - before - max_title_length
    if extra > 0:
        screen.cursor.x -= extra + 1
        screen.draw('…')
    end = screen.cursor.x
    screen.cursor.bold = screen.cursor.italic = False
    screen.cursor.fg = screen.cursor.bg = 0
    screen.draw(draw_data.sep)
    return end


def draw_tab_with_fade(draw_data, screen, tab, before, max_title_length):
    tab_bg = draw_data.active_bg if tab.is_active else draw_data.inactive_bg
    fade_colors = [as_rgb(color_as_int(alpha_blend(tab_bg, draw_data.default_bg, alpha))) for alpha in draw_data.alpha]
    for bg in fade_colors:
        screen.cursor.bg = bg
        screen.draw(' ')
    draw_title(draw_data, screen, tab)
    extra = screen.cursor.x - before - max_title_length
    if extra > 0:
        screen.cursor.x = before
        draw_title(draw_data, screen, tab)
        extra = screen.cursor.x - before - max_title_length
        if extra > 0:
            screen.cursor.x -= extra + 1
            screen.draw('…')
    for bg in reversed(fade_colors):
        if extra >= 0:
            break
        extra += 1
        screen.cursor.bg = bg
        screen.draw(' ')
    end = screen.cursor.x
    screen.cursor.bg = as_rgb(color_as_int(draw_data.default_bg))
    screen.draw(' ')
    return end


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

        self.active_bg = as_rgb(color_as_int(opts.active_tab_background))
        self.active_fg = as_rgb(color_as_int(opts.active_tab_foreground))
        self.bell_fg = as_rgb(0xff0000)
        self.draw_data = DrawData(
            self.leading_spaces, self.sep, self.trailing_spaces, self.opts.bell_on_tab, self.bell_fg,
            self.opts.tab_fade, self.opts.active_tab_background, self.opts.inactive_tab_background,
            self.opts.background
        )
        self.draw_func = draw_tab_with_separator if self.opts.tab_bar_style == 'separator' else draw_tab_with_fade

    def patch_colors(self, spec):
        if 'active_tab_foreground' in spec:
            self.active_fg = (spec['active_tab_foreground'] << 8) | 2
        if 'active_tab_background' in spec:
            self.active_bg = (spec['active_tab_background'] << 8) | 2
            self.draw_data = self.draw_data._replace(active_bg=color_from_int(spec['active_tab_background']))
        if 'inactive_tab_background' in spec:
            self.draw_data = self.draw_data._replace(inactive_bg=color_from_int(spec['inactive_tab_background']))
        if 'background' in spec:
            self.draw_data = self.draw_data._replace(default_bg=color_from_int(spec['background']))
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
        max_title_length = max(1, (self.screen_geometry.xnum // max(1, len(data))) - 1)
        cr = []
        last_tab = data[-1] if data else None

        for t in data:
            s.cursor.bg = self.active_bg if t.is_active else 0
            s.cursor.fg = self.active_fg if t.is_active else 0
            s.cursor.bold, s.cursor.italic = self.active_font_style if t.is_active else self.inactive_font_style
            before = s.cursor.x
            end = self.draw_func(self.draw_data, s, t, before, max_title_length)
            cr.append((before, end))
            if s.cursor.x > s.columns - max_title_length and t is not last_tab:
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
