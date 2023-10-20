#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any, Callable, Dict, NamedTuple, Tuple

from .constants import is_macos, is_wayland
from .types import FloatEdges
from .typing import EdgeLiteral
from .utils import log_error


class WindowSize(NamedTuple):

    size: int
    unit: str


class WindowSizes(NamedTuple):

    width: WindowSize
    height: WindowSize


class WindowSizeData(NamedTuple):
    initial_window_sizes: WindowSizes
    remember_window_size: bool
    single_window_margin_width: FloatEdges
    window_margin_width: FloatEdges
    single_window_padding_width: FloatEdges
    window_padding_width: FloatEdges


def sanitize_window_size(x: Any) -> int:
    ans = int(x)
    return max(20, min(ans, 50000))


def initial_window_size_func(opts: WindowSizeData, cached_values: Dict[str, Any]) -> Callable[[int, int, float, float, float, float], Tuple[int, int]]:

    if 'window-size' in cached_values and opts.remember_window_size:
        ws = cached_values['window-size']
        try:
            w, h = map(sanitize_window_size, ws)

            def initial_window_size(*a: Any) -> Tuple[int, int]:
                return w, h
            return initial_window_size
        except Exception:
            log_error('Invalid cached window size, ignoring')

    w, w_unit = opts.initial_window_sizes.width
    h, h_unit = opts.initial_window_sizes.height

    def get_window_size(cell_width: int, cell_height: int, dpi_x: float, dpi_y: float, xscale: float, yscale: float) -> Tuple[int, int]:
        if not is_macos and not is_wayland():
            # Not sure what the deal with scaling on X11 is
            xscale = yscale = 1

        def effective_margin(which: EdgeLiteral) -> float:
            ans: float = getattr(opts.single_window_margin_width, which)
            if ans < 0:
                ans = getattr(opts.window_margin_width, which)
            return ans

        def effective_padding(which: EdgeLiteral) -> float:
            ans: float = getattr(opts.single_window_padding_width, which)
            if ans < 0:
                ans = getattr(opts.window_padding_width, which)
            return ans

        if w_unit == 'cells':
            spacing = effective_margin('left') + effective_margin('right')
            spacing += effective_padding('left') + effective_padding('right')
            width = cell_width * w / xscale + (dpi_x / 72) * spacing + 1
        else:
            width = w
        if h_unit == 'cells':
            spacing = effective_margin('top') + effective_margin('bottom')
            spacing += effective_padding('top') + effective_padding('bottom')
            height = cell_height * h / yscale + (dpi_y / 72) * spacing + 1
        else:
            height = h
        return int(width), int(height)

    return get_window_size
