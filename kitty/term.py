#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Tuple, Iterator, Union, Sequence

from PyQt5.QtCore import pyqtSignal, QTimer, QRect, Qt
from PyQt5.QtGui import QColor, QPainter, QFont, QFontMetrics, QRegion, QPen
from PyQt5.QtWidgets import QWidget

from .config import build_ansi_color_tables, Options
from .data_types import Line, Cursor
from .utils import set_current_font_metrics
from .tracker import ChangeTracker
from .screen import wrap_cursor_position


def ascii_width(fm: QFontMetrics) -> int:
    ans = 0
    for i in range(32, 128):
        ans = max(ans, fm.widthChar(chr(i)))
    return ans


class TerminalWidget(QWidget):

    relayout_lines = pyqtSignal(object, object, object, object)
    cells_per_line = 80
    lines_per_screen = 24

    def __init__(self, opts: Options, tracker: ChangeTracker, linebuf: Sequence[Line], parent: QWidget=None):
        QWidget.__init__(self, parent)
        self.setFocusPolicy(Qt.WheelFocus)
        tracker.dirtied.connect(self.update_screen)
        self.linebuf = linebuf
        self.cursor = Cursor()
        self.setAutoFillBackground(True)
        self.apply_opts(opts)
        self.debounce_resize_timer = t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(50)
        t.timeout.connect(self.do_layout)

    def apply_opts(self, opts):
        self.opts = opts
        pal = self.palette()
        pal.setColor(pal.Window, QColor(opts.background))
        pal.setColor(pal.WindowText, QColor(opts.foreground))
        self.setPalette(pal)
        self.current_bg = pal.color(pal.Window)
        self.current_fg = pal.color(pal.WindowText)
        build_ansi_color_tables(opts)
        f = QFont(opts.font_family)
        f.setPointSizeF(opts.font_size)
        self.setFont(f)
        self.font_metrics = fm = QFontMetrics(self.font())
        self.cell_height = fm.lineSpacing()
        self.cell_width = ascii_width(fm)
        set_current_font_metrics(fm, self.cell_width)
        self.baseline_offset = fm.ascent()
        self.cursor_color = c = QColor(opts.cursor)
        c.setAlphaF(opts.cursor_opacity)
        self.do_layout()

    def do_layout(self):
        previous, self.cells_per_line = self.cells_per_line, self.width() // self.cell_width
        previousl, self.lines_per_screen = self.lines_per_screen, self.height() // self.cell_height
        if (previous, previousl) != (self.cells_per_line, self.lines_per_screen):
            self.relayout_lines.emit(previous, self.cells_per_line, previousl, self.lines_per_screen)
        self.hmargin = (self.width() - self.cells_per_line * self.cell_width) // 2
        self.vmargin = (self.height() % self.cell_height) // 2
        self.line_positions = tuple(self.vmargin + i * self.cell_height for i in range(self.lines_per_screen))
        self.cell_positions = tuple(self.hmargin + i * self.cell_width for i in range(self.cells_per_line))
        self.layout_size = self.size()
        self.update()

    def resizeEvent(self, ev):
        self.debounce_resize_timer.start()

    def update_screen(self, changes):
        old_cursor, self.cursor = self.cursor, changes['cursor'] or self.cursor
        if changes['screen']:
            self.update()
            return
        cell_positions, line_positions, cell_width, cell_height = self.cell_positions, self.line_positions, self.cell_width, self.cell_height
        old_x, old_y = wrap_cursor_position(old_cursor.x, old_cursor.y, len(line_positions), len(cell_positions))
        del old_cursor
        rects = []
        for lnum in changes['lines']:
            rects.append(QRect(cell_positions[0], line_positions[lnum], cell_positions[-1] - cell_positions[0] + cell_width, cell_height))
        old_cursor_added = old_y in changes['lines']
        for lnum, ranges in changes['cells'].items():
            for start, stop in ranges:
                rects.append(QRect(cell_positions[start], line_positions[lnum], cell_width * (stop - start + 1), cell_height))
                if not old_cursor_added and old_y == lnum and (start <= old_x <= stop):
                    old_cursor_added = True
        rects.sort(key=lambda r: (r.y(), r.x()))
        reg = QRegion()
        for r in rects:
            reg += r
        if not old_cursor_added:
            reg += QRect(cell_positions[old_x], line_positions[old_y], cell_width, cell_height)
        self.update(reg)

    def dirty_lines(self, region: QRegion) -> Iterator[Tuple[int, QRegion]]:
        w = self.width() - 2 * self.hmargin
        for i, y in enumerate(self.line_positions):
            ir = region.intersected(QRect(self.hmargin, y, w, self.cell_height))
            if not ir.isEmpty():
                yield i, ir

    def dirty_cells(self, y: int, line_region: QRegion) -> Iterator[int]:
        for i, x in enumerate(self.cell_positions):
            if line_region.intersects(QRect(x, y, self.cell_width, self.cell_height)):
                yield i

    def line(self, screen_line: int) -> Union[Line, None]:
        try:
            return self.linebuf[screen_line]
        except IndexError:
            pass

    def paintEvent(self, ev):
        if self.size() != self.layout_size:
            return
        r = ev.region()
        p = QPainter(self)
        p.setRenderHints(p.TextAntialiasing | p.Antialiasing)

        try:
            self.paint_cursor(p)
        except Exception:
            import traceback
            traceback.print_exc()

        for lnum, line_region in self.dirty_lines(r):
            line = self.line(lnum)
            if line is not None:
                ypos = self.line_positions[lnum]
                for cnum in self.dirty_cells(ypos, line_region):
                    p.save()
                    try:
                        self.paint_cell(p, line, cnum, ypos)
                    except Exception:
                        import traceback
                        traceback.print_exc()
                    p.restore()

    def paint_cursor(self, painter):
        x, y = wrap_cursor_position(self.cursor.x, self.cursor.y, len(self.line_positions), len(self.cell_positions))
        r = QRect(self.cell_positions[x], self.line_positions[y], self.cell_width, self.cell_height)
        if self.hasFocus():
            painter.fillRect(r, self.cursor_color)
        else:
            painter.setPen(QPen(self.cursor_color))
            painter.drawRect(r)

    def paint_cell(self, painter: QPainter, line: Line, col: int, y: int) -> None:
        x, c = self.cell_positions[col], line.cursor_from(col)
        fg, bg, decoration_fg = c.colors()
        text = line.text_at(col)
        if fg is not None:
            painter.setPen(QPen(fg))
        if bg is not None:
            r = QRect(x, y, self.cell_width, self.cell_height)
            painter.fillRect(r, bg)
        if text.rstrip():
            painter.drawText(x, y + self.baseline_offset, text)
