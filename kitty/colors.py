#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
from contextlib import suppress
from typing import Iterable, Literal, Optional, Union

from .config import parse_config
from .constants import config_dir
from .fast_data_types import Color, get_boss, glfw_get_system_color_theme
from .options.types import Options, nullable_colors
from .rgb import color_from_int

ColorsSpec = dict[str, Optional[int]]
TransparentBackgroundColors = tuple[tuple[Color, float], ...]


class ThemeColors:

    dark_mtime: float = -1
    light_mtime: float = -1
    applied_theme: Literal['light', 'dark', ''] = ''

    def refresh(self) -> None:
        with suppress(FileNotFoundError), open(os.path.join(config_dir, 'dark-theme.conf')) as f:
            mtime = os.stat(f.fileno()).st_mtime
            if mtime > self.dark_mtime:
                self.dark_spec, self.dark_tbc = parse_colors((f,))
                self.dark_mtime = mtime
        with suppress(FileNotFoundError), open(os.path.join(config_dir, 'light-theme.conf')) as f:
            mtime = os.stat(f.fileno()).st_mtime
            if mtime > self.light_mtime:
                self.light_spec, self.light_tbc = parse_colors((f,))
                self.light_mtime = mtime

    @property
    def has_dark_theme(self) -> bool:
        return self.dark_mtime > -1

    @property
    def has_light_theme(self) -> bool:
        return self.light_mtime > -1

    def patch_opts(self, opts: Options) -> None:
        which = glfw_get_system_color_theme()
        if which == 'dark' and self.has_dark_theme:
            patch_options_with_color_spec(opts, self.dark_spec, self.dark_tbc)
            self.applied_theme = 'dark'
        elif which == 'light' and self.has_light_theme:
            patch_options_with_color_spec(opts, self.light_spec, self.light_tbc)
            self.applied_theme = 'light'

    def on_system_color_scheme_change(self, new_value: Literal['light', 'dark']) -> bool:
        boss = get_boss()
        if new_value == 'dark' and self.has_dark_theme:
            boss.patch_colors(self.dark_spec, self.dark_tbc, True)
            self.applied_theme = 'dark'
            return True
        if new_value == 'light' and self.has_light_theme:
            boss.patch_colors(self.light_spec, self.light_tbc, True)
            self.applied_theme = 'light'
            return True
        return False


theme_colors = ThemeColors()


def parse_colors(args: Iterable[Union[str, Iterable[str]]]) -> tuple[ColorsSpec, TransparentBackgroundColors]:
    colors: dict[str, Optional[Color]] = {}
    nullable_color_map: dict[str, Optional[int]] = {}
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
    ans: dict[str, Optional[int]] = {k: int(v) for k, v in colors.items() if isinstance(v, Color)}
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
