#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

from collections import deque

from .fast_data_types import DECAWM, Screen, get_options
from .utils import color_as_int


class FPSCounterScreen:
    def __init__(self, os_window_id: int, cell_width: int, cell_height: int):
        self.os_window_id = os_window_id
        self.cell_width = cell_width
        self.cell_height = cell_height
        self.screen = Screen(None, 1, 32, 0, cell_width, cell_height)
        self.screen.reset_mode(DECAWM)
        self.last_text = ''
        self.samples: deque[int] = deque(maxlen=1000)
        self.geometry = 0, 0, 0, 0

    def required_columns(self) -> int:
        return max(32, len(self.last_text) + 2)

    def layout(self, left: int, top: int, columns: int) -> bool:
        width = columns * self.cell_width
        geometry = left, top, left + width, top + self.cell_height
        changed = geometry != self.geometry or columns != self.screen.columns
        self.geometry = geometry
        if changed:
            self.screen.resize(1, columns)
        return changed

    def add_sample(self, fps: int) -> None:
        self.samples.append(max(0, fps))

    def _percentile(self, q: float) -> int:
        if not self.samples:
            return 0
        data = sorted(self.samples)
        idx = min(len(data) - 1, max(0, int(round((len(data) - 1) * q))))
        return data[idx]

    def render(self, fps: int) -> bool:
        self.add_sample(fps)
        p50 = self._percentile(0.50)
        p99 = self._percentile(0.99)
        fps_ms = 0 if fps <= 0 else (1000 + fps // 2) // fps
        p50_ms = 0 if p50 <= 0 else (1000 + p50 // 2) // p50
        p99_ms = 0 if p99 <= 0 else (1000 + p99 // 2) // p99
        text = f'fps {fps} {fps_ms}ms p50 {p50} {p50_ms}ms p99 {p99} {p99_ms}ms'
        text_changed = text != self.last_text
        resized = False
        if text_changed:
            self.last_text = text
            columns = self.required_columns()
            if columns != self.screen.columns:
                self.screen.resize(1, columns)
                resized = True
        opts = get_options()
        screen = self.screen
        screen.cursor.x = 0
        screen.color_profile.default_fg = opts.foreground
        screen.color_profile.default_bg = opts.background
        screen.cursor.fg = (color_as_int(opts.foreground) << 8) | 2
        screen.cursor.bg = (color_as_int(opts.background) << 8) | 2
        screen.erase_in_line(2, False)
        screen.cursor.x = max(0, screen.columns - len(text))
        screen.draw(text)
        return resized or text_changed
