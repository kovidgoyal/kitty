#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Tuple, Iterator, Union

from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QRect
from PyQt5.QtGui import QColor, QPainter, QFont, QFontMetrics, QRegion, QPen
from PyQt5.QtWidgets import QWidget

from .config import build_ansi_color_tables
from .data_types import Line, as_color


def ascii_width(fm: QFontMetrics) -> int:
    ans = 0
    for i in range(32, 128):
        ans = max(ans, fm.widthChar(chr(i)))
    return ans


class TerminalWidget(QWidget):

    relayout_lines = pyqtSignal(object, object)
    cells_per_line = 80

    def __init__(self, opts, linebuf, parent=None):
        QWidget.__init__(self, parent)
        self.linebuf = linebuf
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
        self.ansi_fg, self.ansi_bg = build_ansi_color_tables(opts)
        f = QFont(opts.font_family)
        f.setPointSizeF(opts.font_size)
        self.setFont(f)
        self.font_metrics = fm = QFontMetrics(self.font())
        self.cell_height = fm.lineSpacing()
        self.cell_width = ascii_width(fm)
        self.do_layout()

    def do_layout(self):
        previous, self.cells_per_line = self.cells_per_line, self.width() // self.cell_width
        if previous != self.cells_per_line:
            self.relayout_lines.emit(previous, self.cells_per_line)
        self.lines_per_screen = self.height() // self.cell_height
        self.hmargin = (self.width() - self.cells_per_line * self.cell_width) // 2
        self.vmargin = (self.height() % self.cell_height) // 2
        self.line_positions = tuple(self.vmargin + i * self.cell_height for i in range(self.lines_per_screen))
        self.cell_positions = tuple(self.hmargin + i * self.cell_width for i in range(self.cells_per_line))
        self.layout_size = self.size()
        self.update()

    def resizeEvent(self, ev):
        self.debounce_resize_timer.start()

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
            lpos = len(self.linebuf) - self.lines_per_screen
            return self.linebuf[lpos]
        except IndexError:
            pass

    def paintEvent(self, ev):
        if self.size() != self.layout_size:
            return
        r = ev.region()
        p = QPainter(self)
        for lnum, line_region in self.dirty_lines(r):
            line = self.line(lnum)
            if line is not None:
                ypos = self.line_positions[lnum]
                for cnum in self.dirty_cells(ypos, line_region):
                    p.save()
                    self.paint_cell(p, line, cnum, ypos)
                    p.restore()

    def paint_cell(self, painter: QPainter, line: Line, col: int, y: int) -> None:
        char = line.char[col]
        if not char:
            return
        x = self.cell_positions[col]
        r = QRect(x, y, self.cell_width, self.cell_height)
        t, r, g, b = line.fg[col]
        fg = as_color(line.fg[col], self.ansi_fg)
        if fg is not None:
            painter.setPen(QPen(fg))
        bg = as_color(line.bg[col], self.ansi_bg)
        if bg is not None:
            painter.fillRect(r, bg)
        painter.drawText(r, Qt.AlignHCenter | Qt.AlignBaseline | Qt.TextSingleLine, char)
