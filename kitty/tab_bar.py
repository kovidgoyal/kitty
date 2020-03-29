#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any, Dict, NamedTuple, Optional, Sequence, Set, Tuple

from .config import build_ansi_color_table
from .constants import WindowGeometry
from .fast_data_types import (
    DECAWM, Screen, cell_size_for_window, pt_to_px, set_tab_bar_render_data,
    viewport_for_window
)
from .layout import Rect
from .options_stub import Options
from .rgb import Color, alpha_blend, color_from_int
from .utils import color_as_int, log_error
from .window import calculate_gl_geometry


class TabBarData(NamedTuple):
    title: str
    is_active: bool
    needs_attention: bool


class DrawData(NamedTuple):
    leading_spaces: int
    sep: str
    trailing_spaces: int
    bell_on_tab: bool
    bell_fg: int
    alpha: Sequence[float]
    active_fg: Color
    active_bg: Color
    inactive_fg: Color
    inactive_bg: Color
    default_bg: Color
    title_template: str
    active_title_template: Optional[str]


def as_rgb(x: int) -> int:
    return (x << 8) | 2


template_failures: Set[str] = set()


def draw_title(draw_data: DrawData, screen: Screen, tab: TabBarData, index: int) -> None:
    if tab.needs_attention and draw_data.bell_on_tab:
        fg = screen.cursor.fg
        screen.cursor.fg = draw_data.bell_fg
        screen.draw('🔔 ')
        screen.cursor.fg = fg
    template = draw_data.title_template
    if tab.is_active and draw_data.active_title_template is not None:
        template = draw_data.active_title_template
    try:
        title = template.format(title=tab.title, index=index)
    except Exception as e:
        if template not in template_failures:
            template_failures.add(template)
            log_error('Invalid tab title template: "{}" with error: {}'.format(template, e))
        title = tab.title
    screen.draw(title)


def draw_tab_with_separator(draw_data: DrawData, screen: Screen, tab: TabBarData, before: int, max_title_length: int, index: int, is_last: bool) -> int:
    tab_bg = draw_data.active_bg if tab.is_active else draw_data.inactive_bg
    screen.cursor.bg = as_rgb(color_as_int(tab_bg))
    if draw_data.leading_spaces:
        screen.draw(' ' * draw_data.leading_spaces)
    draw_title(draw_data, screen, tab, index)
    trailing_spaces = min(max_title_length - 1, draw_data.trailing_spaces)
    max_title_length -= trailing_spaces
    extra = screen.cursor.x - before - max_title_length
    if extra > 0:
        screen.cursor.x -= extra + 1
        screen.draw('…')
    if trailing_spaces:
        screen.draw(' ' * trailing_spaces)
    end = screen.cursor.x
    screen.cursor.bold = screen.cursor.italic = False
    screen.cursor.fg = 0
    if not is_last:
        screen.cursor.bg = as_rgb(color_as_int(draw_data.inactive_bg))
    screen.draw(draw_data.sep)
    screen.cursor.bg = 0
    return end


def draw_tab_with_fade(draw_data: DrawData, screen: Screen, tab: TabBarData, before: int, max_title_length: int, index: int, is_last: bool) -> int:
    tab_bg = draw_data.active_bg if tab.is_active else draw_data.inactive_bg
    fade_colors = [as_rgb(color_as_int(alpha_blend(tab_bg, draw_data.default_bg, alpha))) for alpha in draw_data.alpha]
    for bg in fade_colors:
        screen.cursor.bg = bg
        screen.draw(' ')
    screen.cursor.bg = as_rgb(color_as_int(tab_bg))
    draw_title(draw_data, screen, tab, index)
    extra = screen.cursor.x - before - max_title_length
    if extra > 0:
        screen.cursor.x = before
        draw_title(draw_data, screen, tab, index)
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


def draw_tab_with_powerline(draw_data: DrawData, screen: Screen, tab: TabBarData, before: int, max_title_length: int, index: int, is_last: bool) -> int:
    tab_bg = as_rgb(color_as_int(draw_data.active_bg if tab.is_active else draw_data.inactive_bg))
    tab_fg = as_rgb(color_as_int(draw_data.active_fg if tab.is_active else draw_data.inactive_fg))
    inactive_bg = as_rgb(color_as_int(draw_data.inactive_bg))
    default_bg = as_rgb(color_as_int(draw_data.default_bg))

    min_title_length = 1 + 2

    if screen.cursor.x + min_title_length >= screen.columns:
        screen.cursor.x -= 2
        screen.cursor.bg = default_bg
        screen.cursor.fg = inactive_bg
        screen.draw('   ')
        return screen.cursor.x

    start_draw = 2
    if tab.is_active and screen.cursor.x >= 2:
        screen.cursor.x -= 2
        screen.cursor.fg = inactive_bg
        screen.cursor.bg = tab_bg
        screen.draw(' ')
        screen.cursor.fg = tab_fg
    elif screen.cursor.x == 0:
        screen.cursor.bg = tab_bg
        screen.draw(' ')
        start_draw = 1

    screen.cursor.bg = tab_bg
    if min_title_length >= max_title_length:
        screen.draw('…')
    else:
        draw_title(draw_data, screen, tab, index)
        extra = screen.cursor.x + start_draw - before - max_title_length
        if extra > 0 and extra + 1 < screen.cursor.x:
            screen.cursor.x -= extra + 1
            screen.draw('…')

    if tab.is_active or is_last:
        screen.draw(' ')
        screen.cursor.fg = tab_bg
        if is_last:
            screen.cursor.bg = default_bg
        else:
            screen.cursor.bg = inactive_bg
        screen.draw('')
    else:
        screen.draw(' ')

    end = screen.cursor.x
    if end < screen.columns:
        screen.draw(' ')
    return end


class TabBar:

    def __init__(self, os_window_id: int, opts: Options):
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
            color_as_int(opts.tab_bar_background or opts.background)
        )
        self.blank_rects: Tuple[Rect, ...] = ()
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
            self.opts.tab_fade, self.opts.active_tab_foreground, self.opts.active_tab_background,
            self.opts.inactive_tab_foreground, self.opts.inactive_tab_background,
            self.opts.tab_bar_background or self.opts.background, self.opts.tab_title_template,
            self.opts.active_tab_title_template
        )
        if self.opts.tab_bar_style == 'separator':
            self.draw_func = draw_tab_with_separator
        elif self.opts.tab_bar_style == 'powerline':
            self.draw_func = draw_tab_with_powerline
        else:
            self.draw_func = draw_tab_with_fade

    def patch_colors(self, spec: Dict[str, Any]) -> None:
        if 'active_tab_foreground' in spec:
            self.active_fg = (spec['active_tab_foreground'] << 8) | 2
        if 'active_tab_background' in spec:
            self.active_bg = (spec['active_tab_background'] << 8) | 2
            self.draw_data = self.draw_data._replace(active_bg=color_from_int(spec['active_tab_background']))
        if 'inactive_tab_background' in spec:
            self.draw_data = self.draw_data._replace(inactive_bg=color_from_int(spec['inactive_tab_background']))
        if 'tab_bar_background' in spec:
            self.draw_data = self.draw_data._replace(default_bg=color_from_int(spec['tab_bar_background']))
        elif 'background' in spec and not self.opts.tab_bar_background:
            self.draw_data = self.draw_data._replace(default_bg=color_from_int(spec['background']))
        fg = spec.get('inactive_tab_foreground', color_as_int(self.opts.inactive_tab_foreground))
        bg = spec.get('tab_bar_background', False)
        if bg is None:
            bg = color_as_int(self.opts.background)
        elif bg is False:
            bg = color_as_int(self.opts.tab_bar_background or self.opts.background)
        self.screen.color_profile.set_configured_colors(fg, bg)

    def layout(self) -> None:
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

    def update(self, data: Sequence[TabBarData]) -> None:
        if not self.laid_out_once:
            return
        s = self.screen
        s.cursor.x = 0
        s.erase_in_line(2, False)
        max_title_length = max(1, (self.screen_geometry.xnum // max(1, len(data))) - 1)
        cr = []
        last_tab = data[-1] if data else None

        for i, t in enumerate(data):
            s.cursor.bg = self.active_bg if t.is_active else 0
            s.cursor.fg = self.active_fg if t.is_active else 0
            s.cursor.bold, s.cursor.italic = self.active_font_style if t.is_active else self.inactive_font_style
            before = s.cursor.x
            end = self.draw_func(self.draw_data, s, t, before, max_title_length, i + 1, t is last_tab)
            s.cursor.bg = s.cursor.fg = 0
            cr.append((before, end))
            if s.cursor.x > s.columns - max_title_length and t is not last_tab:
                s.cursor.x = s.columns - 2
                s.cursor.bg = as_rgb(color_as_int(self.draw_data.default_bg))
                s.cursor.fg = self.bell_fg
                s.draw(' …')
                break
        s.erase_in_line(0, False)  # Ensure no long titles bleed after the last tab
        self.cell_ranges = cr

    def destroy(self) -> None:
        self.screen.reset_callbacks()
        del self.screen

    def tab_at(self, x: int) -> Optional[int]:
        x = (x - self.window_geometry.left) // self.cell_width
        for i, (a, b) in enumerate(self.cell_ranges):
            if a <= x <= b:
                return i
