#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from .fast_data_types import Color


def alpha_blend_channel(top_color: int, bottom_color: int, alpha: float) -> int:
    return int(alpha * top_color + (1 - alpha) * bottom_color)


def alpha_blend(top_color: Color, bottom_color: Color, alpha: float) -> Color:
    return Color(
            alpha_blend_channel(top_color.red, bottom_color.red, alpha),
            alpha_blend_channel(top_color.green, bottom_color.green, alpha),
            alpha_blend_channel(top_color.blue, bottom_color.blue, alpha)
    )


def color_from_int(x: int) -> Color:
    return Color((x >> 16) & 255, (x >> 8) & 255, x & 255)


def color_as_int(x: Color) -> int:
    return int(x)


def color_as_sharp(x: Color) -> str:
    return x.as_sharp


def color_as_sgr(x: Color) -> str:
    return x.as_sgr


def to_color(raw: str, validate: bool = False) -> Color | None:
    if (val := Color.parse_color(raw)) is None and validate:
        raise ValueError(f'Invalid color name: {raw!r}')
    return val
