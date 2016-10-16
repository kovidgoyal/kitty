#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from PyQt5.QtGui import QFontMetrics

current_font_metrics = cell_width = None


@lru_cache(maxsize=2**13)
def wcwidth(c: str) -> int:
    if current_font_metrics is None:
        return 1
    w = current_font_metrics.widthChar(c)
    cells, extra = divmod(w, cell_width)
    if extra > 0.1 * cell_width:
        cells += 1
    return cells


def set_current_font_metrics(fm: QFontMetrics, cw: int) -> None:
    global current_font_metrics, cell_width
    current_font_metrics, cell_width = fm, cw
    wcwidth.cache_clear()
