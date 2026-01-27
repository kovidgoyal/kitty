#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
from collections.abc import Iterable, Sequence
from contextlib import suppress
from enum import Enum
from typing import Literal, Optional, TypedDict

from .config import parse_config
from .constants import config_dir
from .fast_data_types import Color, get_boss, get_options, glfw_get_system_color_theme, patch_color_profiles, patch_global_colors, set_os_window_chrome
from .options.types import Options, nullable_colors, special_colors
from .rgb import color_from_int
from .typing_compat import WindowType

ColorsSpec = dict[str, Optional[int]]
TransparentBackgroundColors = tuple[tuple[Color, float], ...]
ColorSchemes = Literal['light', 'dark', 'no_preference']
Colors = tuple[ColorsSpec, TransparentBackgroundColors]


class BackgroundImageOptions(TypedDict, total=False):
    background_image: str | None
    background_image_layout: str | None
    background_image_linear: bool | None
    background_tint: float | None
    background_tint_gaps: float | None


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
    default_background_image_options: BackgroundImageOptions| None = None

    def get_default_colors(self) -> ColorsSpec:
        if self.default_colors is None:
            from kitty.options.types import defaults, option_names
            ans: ColorsSpec = dict.fromkeys(nullable_colors)

            for name in option_names:
                defval = getattr(defaults, name)
                if isinstance(defval, Color):
                    ans[name] = int(defval)
            for name in special_colors:
                ans[name] = getattr(defaults, name)
            self.default_colors = ans
            self.default_background_image_options: BackgroundImageOptions = {
                    k: getattr(defaults, k) for k in BackgroundImageOptions.__optional_keys__}  # type: ignore

        return self.default_colors

    def parse_colors(self, f: Iterable[str], background_image_options: BackgroundImageOptions | None = None) -> Colors:
        # When parsing the theme file we first apply the default theme so that
        # all colors are reset to default values first. This is needed for themes
        # that don't specify all colors.
        dc_spec = self.get_default_colors()
        if background_image_options is not None and self.default_background_image_options:
            background_image_options.update(self.default_background_image_options)
        spec, tbc = parse_colors((f,), background_image_options)
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
                            d: BackgroundImageOptions = {}
                            self.dark_spec, self.dark_tbc = self.parse_colors(f, d)
                            self.dark_background_image_options = d
                        self.dark_mtime = mtime
                        found = True
                elif x.name == ThemeFile.light.value:
                    mtime = x.stat().st_mtime_ns
                    if mtime > self.light_mtime:
                        with open(x.path) as f:
                            d = {}
                            self.light_spec, self.light_tbc = self.parse_colors(f, d)
                            self.light_background_image_options = d
                        self.light_mtime = mtime
                        found = True
                elif x.name == ThemeFile.no_preference.value:
                    mtime = x.stat().st_mtime_ns
                    if mtime > self.no_preference_mtime:
                        with open(x.path) as f:
                            d = {}
                            self.no_preference_spec, self.no_preference_tbc = self.parse_colors(f, d)
                            self.no_preference_background_image_options = d
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
        bgo: BackgroundImageOptions | None = None
        if which == 'dark' and self.has_dark_theme:
            cols = self.dark_spec, self.dark_tbc
            bgo = self.dark_background_image_options
        elif which == 'light' and self.has_light_theme:
            cols = self.light_spec, self.light_tbc
            bgo = self.light_background_image_options
        elif which == 'no_preference' and self.has_no_preference_theme:
            cols = self.no_preference_spec, self.no_preference_tbc
            bgo = self.no_preference_background_image_options
        if cols is not None:
            patch_options_with_color_spec(opts, *cols, background_image_options=bgo)
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
            patch_colors(
                self.dark_spec, self.dark_tbc, True, notify_on_bg_change=notify_on_bg_change, background_image_options=self.dark_background_image_options)
            self.applied_theme = new_value
            if boss.args.debug_rendering:
                log_error(f'Applied color theme {new_value}')
            return True
        if new_value == 'light' and self.has_light_theme:
            patch_colors(
                self.light_spec, self.light_tbc, True, notify_on_bg_change=notify_on_bg_change, background_image_options=self.light_background_image_options)
            self.applied_theme = new_value
            if boss.args.debug_rendering:
                log_error(f'Applied color theme {new_value}')
            return True
        if new_value == 'no_preference' and self.has_no_preference_theme:
            patch_colors(
                self.no_preference_spec, self.no_preference_tbc, True, notify_on_bg_change=notify_on_bg_change,
                background_image_options=self.no_preference_background_image_options)
            self.applied_theme = new_value
            if boss.args.debug_rendering:
                log_error(f'Applied color theme {new_value}')
            return True
        return False


theme_colors = ThemeColors()


def parse_colors(args: Iterable[str | Iterable[str]], background_image_options: BackgroundImageOptions | None = None) -> Colors:
    colors: dict[str, Color | None | int] = {}
    nullable_color_map: dict[str, int | None] = {}
    special_color_map: dict[str, int] = {}
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
        if background_image_options is not None:
            for key in BackgroundImageOptions.__optional_keys__:
                if key in conf:
                    background_image_options.__setitem__(key, conf[key])
        colors.update(conf)
    for k in nullable_colors:
        q = colors.pop(k, False)
        if q is not False:
            val = int(q) if isinstance(q, Color) else None
            nullable_color_map[k] = val
    for k in special_colors:
        sq = colors.pop(k, None)
        if isinstance(sq, int):
            special_color_map[k] = sq
    ans: dict[str, int | None] = {k: int(v) for k, v in colors.items() if isinstance(v, Color)}
    ans.update(nullable_color_map)
    ans.update(special_color_map)
    return ans, transparent_background_colors


def patch_options_with_color_spec(
    opts: Options, spec: ColorsSpec, transparent_background_colors: TransparentBackgroundColors,
    background_image_options: BackgroundImageOptions | None = None
) -> None:
    for k, v in spec.items():
        if hasattr(opts, k):
            if v is None:
                if k in nullable_colors:
                    setattr(opts, k, None)
            else:
                if k in special_colors:
                    setattr(opts, k, v)
                else:
                    setattr(opts, k, color_from_int(v))
    opts.transparent_background_colors = transparent_background_colors
    if background_image_options is not None:
        for k, bv in background_image_options.items():
            if hasattr(opts, k):
                setattr(opts, k, bv)


def patch_colors(
    spec: ColorsSpec, transparent_background_colors: TransparentBackgroundColors, configured: bool = False,
    windows: Sequence[WindowType] | None = None, notify_on_bg_change: bool = True,
    background_image_options: BackgroundImageOptions | None = None
) -> None:
    boss = get_boss()
    opts = get_options()
    has_256_color = any(key.startswith('color') and key[5:].isdigit()
        and int(key[5:]) >= 16 for key in spec)
    if configured and opts.generate_256_palette:
        opts.generate_256_palette = not has_256_color
    if opts.generate_256_palette and not has_256_color:
        generate_256_palette_for_spec(spec, opts)
    if windows is None:
        windows = tuple(boss.all_windows)
    bg_colors_before = {w.id: w.screen.color_profile.default_bg for w in windows}
    profiles = tuple(w.screen.color_profile for w in windows if w)
    patch_color_profiles(spec, transparent_background_colors, profiles, configured)
    if configured:
        patch_options_with_color_spec(opts, spec, transparent_background_colors, background_image_options)
    os_window_ids = set()
    for tm in get_boss().all_tab_managers:
        tm.tab_bar.patch_colors(spec)
        tm.tab_bar.layout()
        tm.mark_tab_bar_dirty()
        t = tm.active_tab
        if t is not None:
            t.relayout_borders()
        os_window_ids.add(tm.os_window_id)
    patch_global_colors(spec, configured)  # changes macos_titlebar_color
    for oswid in os_window_ids:
        set_os_window_chrome(oswid)
    default_bg_changed = 'background' in spec
    notify_bg = notify_on_bg_change and default_bg_changed
    boss = get_boss()
    if background_image_options is not None:
        boss.set_background_image(
            background_image_options.get('background_image'), tuple(os_window_ids), configured,
            layout=background_image_options.get('background_image_layout'),
            linear_interpolation=background_image_options.get('background_image_linear'), tint=background_image_options.get('background_tint'),
            tint_gaps=background_image_options.get('background_tint_gaps'))
    for w in windows:
        if w:
            if notify_bg and w.screen.color_profile.default_bg != bg_colors_before.get(w.id):
                boss.default_bg_changed_for(w.id)
            w.refresh()

Rgb = tuple[int, int, int]
RgbFloat = tuple[float, float, float]

def color_to_rgb(color: Color) -> Rgb:
    return (color.r, color.g, color.b)

def int_to_rgb(x: int) -> Rgb:
    return (x >> 16) & 255, (x >> 8) & 255, x & 255

def rgb_to_int(rgb: Rgb) -> int:
    return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]

def rgb_float_to_rgb(rgb: RgbFloat) -> Rgb:
    return (
        int(round(rgb[0])),
        int(round(rgb[1])),
        int(round(rgb[2]))
    )

def generate_256_palette_for_spec(spec: ColorsSpec, opts: Options) -> None:
    bg = spec.get('background')
    fg = spec.get('foreground')
    color1 = spec.get('color1', None)
    color2 = spec.get('color2', None)
    color3 = spec.get('color3', None)
    color4 = spec.get('color4', None)
    color5 = spec.get('color5', None)
    color6 = spec.get('color6', None)
    color_table = opts.color_table
    for i, rgb in enumerate(generate_256_palette([
        int_to_rgb(bg) if bg is not None else color_to_rgb(opts.background),
        int_to_rgb(color1 if color1 is not None else color_table[1]),
        int_to_rgb(color2 if color2 is not None else color_table[2]),
        int_to_rgb(color3 if color3 is not None else color_table[3]),
        int_to_rgb(color4 if color4 is not None else color_table[4]),
        int_to_rgb(color5 if color5 is not None else color_table[5]),
        int_to_rgb(color6 if color6 is not None else color_table[6]),
        int_to_rgb(fg) if fg is not None else color_to_rgb(opts.foreground),
    ]), 16):
        spec[f'color{i}'] = rgb_to_int(rgb)

def generate_256_palette_opts(opts: Options) -> None:
    color_table = opts.color_table
    for i, rgb in enumerate(generate_256_palette([
        color_to_rgb(opts.background),
        int_to_rgb(color_table[1]),
        int_to_rgb(color_table[2]),
        int_to_rgb(color_table[3]),
        int_to_rgb(color_table[4]),
        int_to_rgb(color_table[5]),
        int_to_rgb(color_table[6]),
        color_to_rgb(opts.foreground)
    ]), 16):
        color_table[i] = rgb_to_int(rgb)

def generate_256_palette(base8: list[Rgb]) -> list[Rgb]:
    def luminance(rgb: Rgb | RgbFloat) -> float:
        r, g, b = (
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in (c / 255 for c in rgb)
        )
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contrast_ratio(rgb1: Rgb | RgbFloat, rgb2: Rgb | RgbFloat) -> float:
        lum1 = luminance(rgb1)
        lum2 = luminance(rgb2)
        return (max(lum1, lum2) + 0.05) / (min(lum1, lum2) + 0.05)

    def lerp_color(t: float, c1: Rgb | RgbFloat, c2: Rgb | RgbFloat) -> RgbFloat:
        return (
            (1 - t) * c1[0] + t * c2[0],
            (1 - t) * c1[1] + t * c2[1],
            (1 - t) * c1[2] + t * c2[2],
        )

    def calc_contrast_adjust(
        color: Rgb, shade: int, num_shades: int,
        Target_contrast: float = 1.05,
        adjustment_intensity: float = 1.5
    ) -> float:
        t = shade / (num_shades - 1)
        contrast = contrast_ratio(lerp_color(t, base8[0], color), base8[0])
        return (contrast / target_contrast) ** adjustment_intensity

    NUM_GREY_SHADES = 26 # (BG, 24 shade greyscale ramp, FG)
    NUM_RGB_SHADES = 6

    r_contrast_adjust = calc_contrast_adjust(base8[1], 1, NUM_RGB_SHADES)
    g_contrast_adjust = calc_contrast_adjust(base8[2], 1, NUM_RGB_SHADES)
    b_contrast_adjust = calc_contrast_adjust(base8[4], 1, NUM_RGB_SHADES)
    grey_contrast_adjust = calc_contrast_adjust(base8[7], 2, NUM_GREY_SHADES)

    r_norms = [(r / 5) ** r_contrast_adjust for r in range(6)]
    g_norms = [(g / 5) ** g_contrast_adjust for g in range(6)]
    b_norms = [(b / 5) ** b_contrast_adjust for b in range(6)]

    palette: list[Rgb] = []

    for r_norm in r_norms:
        c0 = lerp_color(r_norm, base8[0], base8[1])
        c1 = lerp_color(r_norm, base8[2], base8[3])
        c2 = lerp_color(r_norm, base8[4], base8[5])
        c3 = lerp_color(r_norm, base8[6], base8[7])
        for g_norm in g_norms:
            c4 = lerp_color(g_norm, c0, c1)
            c5 = lerp_color(g_norm, c2, c3)
            for b_norm in b_norms:
                c6 = lerp_color(b_norm, c4, c5)
                palette.append(rgb_float_to_rgb(c6))


    for i in range(24):
        t = ((i + 1) / 25) ** grey_contrast_adjust
        rgb = lerp_color(t, base8[0], base8[7])
        palette.append(rgb_float_to_rgb(rgb))

    return palette
