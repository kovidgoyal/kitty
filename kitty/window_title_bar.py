#!/usr/bin/env python
# License: GPL v3 Copyright: 2024, kitty contributors

import os
from functools import lru_cache
from typing import Any, NamedTuple

from .constants import config_dir
from .fast_data_types import (
    DECAWM,
    Screen,
    get_options,
)
from .rgb import color_as_sgr, color_from_int, to_color
from .tab_bar import draw_attributed_string, safe_builtins
from .types import WindowGeometry, run_once
from .utils import color_as_int, log_error


@lru_cache
def _report_template_failure(template: str, e: str) -> None:
    log_error(f'Invalid window title template: "{template}" with error: {e}')


@lru_cache
def _compile_template(template: str) -> Any:
    try:
        return compile('f"""' + template + '"""', '<window_title_template>', 'eval')
    except Exception as e:
        _report_template_failure(template, str(e))


def _resolve_color(opt_val: Any, fallback_val: Any) -> Any:
    if opt_val is None:
        return fallback_val
    return opt_val


class WindowTitleColorFormatter:
    is_active: bool = False

    def __init__(self, which: str):
        self.which = which

    def __getattr__(self, name: str) -> str:
        q = name
        if q == 'default':
            ans = '9'
        elif q == 'window':
            opts = get_options()
            if self.is_active:
                fg_color = _resolve_color(opts.window_title_bar_active_foreground, opts.active_tab_foreground)
                bg_color = _resolve_color(opts.window_title_bar_active_background, opts.active_tab_background)
                col = color_from_int(color_as_int(fg_color if self.which == '3' else bg_color))
            else:
                fg_color = _resolve_color(opts.window_title_bar_inactive_foreground, opts.inactive_tab_foreground)
                bg_color = _resolve_color(opts.window_title_bar_inactive_background, opts.inactive_tab_background)
                col = color_from_int(color_as_int(fg_color if self.which == '3' else bg_color))
            ans = f'8{color_as_sgr(col)}'
        elif q.startswith('color'):
            ans = f'8:5:{int(q[5:])}'
        else:
            if name.startswith('_'):
                q = f'#{name[1:]}'
            c = to_color(q)
            if c is None:
                raise AttributeError(f'{name} is not a valid color')
            ans = f'8{color_as_sgr(c)}'
        return f'\x1b[{self.which}{ans}m'


class WindowTitleFormatter:
    reset = '\x1b[0m'
    fg = WindowTitleColorFormatter('3')
    bg = WindowTitleColorFormatter('4')
    bold = '\x1b[1m'
    nobold = '\x1b[22m'
    italic = '\x1b[3m'
    noitalic = '\x1b[23m'


class WindowTitleData(NamedTuple):
    title: str
    is_active: bool
    window_id: int
    tab_id: int
    needs_attention: bool = False
    has_activity_since_last_focus: bool = False


@run_once
def load_custom_window_title_bar_module() -> dict[str, Any]:
    import runpy
    import traceback
    try:
        return runpy.run_path(os.path.join(config_dir, 'window_title_bar.py'))
    except FileNotFoundError:
        return {}
    except Exception as e:
        traceback.print_exc()
        log_error(f'Failed to load custom window_title_bar.py module with error: {e}')
        return {}


def _get_custom_draw_result(data: WindowTitleData) -> str | None:
    m = load_custom_window_title_bar_module()
    func = m.get('draw_window_title')
    if func is None:
        return None
    try:
        return str(func(data))
    except Exception as e:
        log_error(f'Custom draw_window_title function failed with error: {e}')
        return None


def clear_caches() -> None:
    load_custom_window_title_bar_module.clear_cached()


class WindowTitleBarScreen:
    def __init__(self, os_window_id: int, cell_width: int, cell_height: int):
        self.os_window_id = os_window_id
        self.cell_width = cell_width
        self.screen = Screen(None, 1, 10, 0, cell_width, cell_height)
        self.screen.reset_mode(DECAWM)

    def layout(self, geometry: WindowGeometry) -> None:
        ncells = max(4, (geometry.right - geometry.left) // self.cell_width)
        self.screen.resize(1, ncells)
        self.geometry = geometry

    def render(self, data: WindowTitleData, progress_percent: str) -> str:
        opts = get_options()
        s = self.screen
        s.cursor.x = 0

        is_active = data.is_active
        if is_active:
            fg_color = _resolve_color(opts.window_title_bar_active_foreground, opts.active_tab_foreground)
            bg_color = _resolve_color(opts.window_title_bar_active_background, opts.active_tab_background)
        else:
            fg_color = _resolve_color(opts.window_title_bar_inactive_foreground, opts.inactive_tab_foreground)
            bg_color = _resolve_color(opts.window_title_bar_inactive_background, opts.inactive_tab_background)

        s.color_profile.default_fg = fg_color
        s.color_profile.default_bg = bg_color
        fg = (color_as_int(fg_color) << 8) | 2
        bg = (color_as_int(bg_color) << 8) | 2

        s.cursor.fg = fg
        s.cursor.bg = bg

        template = opts.window_title_template
        if is_active and opts.active_window_title_template and opts.active_window_title_template != 'none':
            template = opts.active_window_title_template

        WindowTitleColorFormatter.is_active = is_active

        bell_symbol = opts.bell_on_tab if data.needs_attention else ''
        activity_symbol = opts.tab_activity_symbol if data.has_activity_since_last_focus else ''

        custom_result = _get_custom_draw_result(data)

        eval_locals = {
            'title': data.title,
            'is_active': is_active,
            'fmt': WindowTitleFormatter,
            'bell_symbol': bell_symbol,
            'activity_symbol': activity_symbol,
            'progress_percent': progress_percent,
            'custom': custom_result or '',
        }
        try:
            title = eval(_compile_template(template), {'__builtins__': safe_builtins}, eval_locals)
        except Exception as e:
            _report_template_failure(template, str(e))
            title = data.title

        align = opts.window_title_bar_align
        s.erase_in_line(2, False)
        draw_attributed_string((title_str := str(title)), s)
        title_len = s.cursor.x
        if align != 'left' and (pad := max(0, (s.columns - title_len) // (2 if align == 'center' else 1))):
            s.cursor.x = 0
            s.insert_characters(pad)
            s.cursor.x = 0
            s.erase_characters(pad)
        return title_str
