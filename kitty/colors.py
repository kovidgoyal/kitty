#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import Iterable, Optional, Union

from .config import parse_config
from .fast_data_types import Color
from .options.types import Options, nullable_colors
from .rgb import color_from_int


def parse_colors(args: Iterable[Union[str, Iterable[str]]]) -> tuple[dict[str, Optional[int]], tuple[tuple[Color, float], ...]]:
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


def patch_options_with_color_spec(opts: Options, spec: dict[str, Optional[int]], transparent_background_colors: tuple[tuple[Color, float], ...]) -> None:

    for k, v in spec.items():
        if hasattr(opts, k):
            if v is None:
                if k in nullable_colors:
                    setattr(opts, k, None)
            else:
                setattr(opts, k, color_from_int(v))
    opts.transparent_background_colors = transparent_background_colors
