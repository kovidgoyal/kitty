#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
from collections.abc import Iterable, Sequence
from contextlib import suppress
from enum import Enum
from typing import Literal, Optional

from .config import parse_config
from .constants import config_dir
from .fast_data_types import Color, get_boss, get_options, glfw_get_system_color_theme, patch_color_profiles, patch_global_colors, set_os_window_chrome
from .options.types import Options, nullable_colors
from .rgb import color_from_int
from .typing import WindowType

ColorsSpec = dict[str, Optional[int]]
TransparentBackgroundColors = tuple[tuple[Color, float], ...]
ColorSchemes = Literal['light', 'dark', 'no_preference']
Colors = tuple[ColorsSpec, TransparentBackgroundColors]


class ThemeFile(Enum):
    dark = 'dark-theme.auto.conf'
    light = 'light-theme.auto.conf'
    no_preference = 'no-preference-theme.auto.conf'


class ThemeColors:

    dark_mtime: int = -1
    light_mtime: int = -1
    no_preference_mtime: int = -1
    applied_theme: Literal['light', 'dark', 'no_preference', ''] = ''
    default_colors: ColorsSpec | None = None

    def get_default_colors(self) -> ColorsSpec:
        if self.default_colors is None:
            from kitty.options.types import defaults, option_names
            ans: ColorsSpec = dict.fromkeys(nullable_colors)

            for name in option_names:
                defval = getattr(defaults, name)
                if isinstance(defval, Color):
                    ans[name] = int(defval)
            self.default_colors = ans
        return self.default_colors

    def parse_colors(self, f: Iterable[str]) -> Colors:
        # When parsing the theme file we first apply the default theme so that
        # all colors are reset to default values first. This is needed for themes
        # that don't specify all colors.
        spec, tbc = parse_colors((f,))
        dc_spec = self.get_default_colors()
        ans = dc_spec.copy()
        ans.update(spec)
        return ans, tbc

    def refresh(self) -> bool:
        found = False
        with suppress(FileNotFoundError):
            for x in os.scandir(config_dir):
                if x.name == ThemeFile.dark.value:
                    mtime = x.stat().st_mtime_ns
                    if mtime > self.dark_mtime:
                        with open(x.path) as f:
                            self.dark_spec, self.dark_tbc = self.parse_colors(f)
                        self.dark_mtime = mtime
                        found = True
                elif x.name == ThemeFile.light.value:
                    mtime = x.stat().st_mtime_ns
                    if mtime > self.light_mtime:
                        with open(x.path) as f:
                            self.light_spec, self.light_tbc = self.parse_colors(f)
                        self.light_mtime = mtime
                        found = True
                elif x.name == ThemeFile.no_preference.value:
                    mtime = x.stat().st_mtime_ns
                    if mtime > self.no_preference_mtime:
                        with open(x.path) as f:
                            self.no_preference_spec, self.no_preference_tbc = self.parse_colors(f)
                        self.no_preference_mtime = mtime
                        found = True
        return found

    @property
    def has_applied_theme(self) -> bool:
        match self.applied_theme:
            case '':
                return False
            case 'dark':
                return self.has_dark_theme
            case 'light':
                return self.has_light_theme
            case 'no_preference':
                return self.has_no_preference_theme

    @property
    def has_dark_theme(self) -> bool:
        return self.dark_mtime > -1

    @property
    def has_light_theme(self) -> bool:
        return self.light_mtime > -1

    @property
    def has_no_preference_theme(self) -> bool:
        return self.no_preference_mtime > -1

    def patch_opts(self, opts: Options, debug_rendering: bool = False) -> None:
        from .utils import log_error
        if debug_rendering:
            log_error('Querying system for current color scheme')
        which = glfw_get_system_color_theme()
        if debug_rendering:
            log_error('Current system color scheme:', which)
        cols: Colors | None = None
        if which == 'dark' and self.has_dark_theme:
            cols = self.dark_spec, self.dark_tbc
        elif which == 'light' and self.has_light_theme:
            cols = self.light_spec, self.light_tbc
        elif which == 'no_preference' and self.has_no_preference_theme:
            cols = self.no_preference_spec, self.no_preference_tbc
        if cols is not None:
            patch_options_with_color_spec(opts, *cols)
            patch_global_colors(cols[0], True)
            self.applied_theme = which
            if debug_rendering:
                log_error(f'Applied {self.applied_theme} color theme')

    def on_system_color_scheme_change(self, new_value: ColorSchemes, is_initial_value: bool = False) -> bool:
        if is_initial_value:
            return False
        self.refresh()
        return self.apply_theme(new_value)

    def apply_theme(self, new_value: ColorSchemes, notify_on_bg_change: bool = True) -> bool:
        from .utils import log_error
        boss = get_boss()
        if new_value == 'dark' and self.has_dark_theme:
            patch_colors(self.dark_spec, self.dark_tbc, True, notify_on_bg_change=notify_on_bg_change)
            self.applied_theme = new_value
            if boss.args.debug_rendering:
                log_error(f'Applied color theme {new_value}')
            return True
        if new_value == 'light' and self.has_light_theme:
            patch_colors(self.light_spec, self.light_tbc, True, notify_on_bg_change=notify_on_bg_change)
            self.applied_theme = new_value
            if boss.args.debug_rendering:
                log_error(f'Applied color theme {new_value}')
            return True
        if new_value == 'no_preference' and self.has_no_preference_theme:
            patch_colors(self.no_preference_spec, self.no_preference_tbc, True, notify_on_bg_change=notify_on_bg_change)
            self.applied_theme = new_value
            if boss.args.debug_rendering:
                log_error(f'Applied color theme {new_value}')
            return True
        return False


theme_colors = ThemeColors()


def parse_colors(args: Iterable[str | Iterable[str]]) -> Colors:
    colors: dict[str, Color | None] = {}
    nullable_color_map: dict[str, int | None] = {}
    transparent_background_colors = ()
    for spec in args:
        if isinstance(spec, str):
            if '=' in spec:
                conf = parse_config((spec.replace('=', ' '),))
            else:
                with open(os.path.expanduser(spec), encoding='utf-8', errors='replace') as f:
                    conf = parse_config(f)
        else:
            conf = parse_config(spec)
        transparent_background_colors = conf.pop('transparent_background_colors', ())
        colors.update(conf)
    for k in nullable_colors:
        q = colors.pop(k, False)
        if q is not False:
            val = int(q) if isinstance(q, Color) else None
            nullable_color_map[k] = val
    ans: dict[str, int | None] = {k: int(v) for k, v in colors.items() if isinstance(v, Color)}
    ans.update(nullable_color_map)
    return ans, transparent_background_colors


def patch_options_with_color_spec(opts: Options, spec: ColorsSpec, transparent_background_colors: TransparentBackgroundColors) -> None:
    for k, v in spec.items():
        if hasattr(opts, k):
            if v is None:
                if k in nullable_colors:
                    setattr(opts, k, None)
            else:
                setattr(opts, k, color_from_int(v))
    opts.transparent_background_colors = transparent_background_colors


def patch_colors(
    spec: ColorsSpec, transparent_background_colors: TransparentBackgroundColors, configured: bool = False,
    windows: Sequence[WindowType] | None = None, notify_on_bg_change: bool = True,
) -> None:
    boss = get_boss()
    if windows is None:
        windows = tuple(boss.all_windows)
    bg_colors_before = {w.id: w.screen.color_profile.default_bg for w in windows}
    profiles = tuple(w.screen.color_profile for w in windows if w)
    patch_color_profiles(spec, transparent_background_colors, profiles, configured)
    opts = get_options()
    if configured:
        patch_options_with_color_spec(opts, spec, transparent_background_colors)
    for tm in get_boss().all_tab_managers:
        tm.tab_bar.patch_colors(spec)
        tm.tab_bar.layout()
        tm.mark_tab_bar_dirty()
        t = tm.active_tab
        if t is not None:
            t.relayout_borders()
        set_os_window_chrome(tm.os_window_id)
    patch_global_colors(spec, configured)
    default_bg_changed = 'background' in spec
    notify_bg = notify_on_bg_change and default_bg_changed
    boss = get_boss()
    for w in windows:
        if w:
            if notify_bg and w.screen.color_profile.default_bg != bg_colors_before.get(w.id):
                boss.default_bg_changed_for(w.id)
            w.refresh()
