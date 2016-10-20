#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache
from itertools import product
from typing import Tuple, Iterator, Sequence

from PyQt5.QtCore import pyqtSignal, QTimer, QRect, Qt
from PyQt5.QtGui import QColor, QPainter, QFont, QFontMetrics, QRegion, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from .config import build_ansi_color_tables, Options, fg_color_table, bg_color_table
from .data_types import Line, Cursor, HAS_BG_MASK, COL_SHIFT, COL_MASK, as_color
from .utils import set_current_font_metrics
from .tracker import ChangeTracker
from .screen import wrap_cursor_position
from .keys import key_event_to_data


def ascii_width(fm: QFontMetrics) -> int:
    ans = 0
    for i in range(32, 128):
        ans = max(ans, fm.widthChar(chr(i)))
    return ans


@lru_cache(maxsize=2**11)
def pixmap_for_text(text, color, default_fg, font, w, h, baseline):
    p = QPixmap(w, h)
    p.fill(Qt.transparent)
    fg = as_color(color & COL_MASK, fg_color_table()) or default_fg
    painter = QPainter(p)
    painter.setFont(font)
    painter.setPen(QPen(QColor(*fg)))
    painter.setRenderHints(QPainter.TextAntialiasing | QPainter.Antialiasing)
    painter.drawText(0, baseline, text)
    painter.end()
    return p


class TerminalWidget(QWidget):

    relayout_lines = pyqtSignal(object, object, object, object)
    send_data_to_child = pyqtSignal(object)
    cells_per_line = 80
    lines_per_screen = 24

    def __init__(self, opts: Options, tracker: ChangeTracker, linebuf: Sequence[Line], parent: QWidget=None):
        QWidget.__init__(self, parent)
        self.last_drew_cursor_at = (0, 0)
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
        self.debounce_update_timer = t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(50)
        t.timeout.connect(self.do_update_screen)
        self.pending_update = QRegion()

    def apply_opts(self, opts):
        self.opts = opts
        pixmap_for_text.cache_clear()
        pal = self.palette()
        pal.setColor(pal.Window, QColor(opts.background))
        pal.setColor(pal.WindowText, QColor(opts.foreground))
        self.setPalette(pal)
        self.current_bg = pal.color(pal.Window)
        self.current_fg = pal.color(pal.WindowText).getRgb()[:3]
        build_ansi_color_tables(opts)
        self.current_font = f = QFont(opts.font_family)
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
        self.hmargin = (self.width() - self.cells_per_line * self.cell_width) // 2
        self.vmargin = (self.height() % self.cell_height) // 2
        self.line_positions = tuple(self.vmargin + i * self.cell_height for i in range(self.lines_per_screen))
        self.cell_positions = tuple(self.hmargin + i * self.cell_width for i in range(self.cells_per_line))
        self.line_width = self.cells_per_line * self.cell_width
        self.layout_size = self.size()
        if (previous, previousl) != (self.cells_per_line, self.lines_per_screen):
            self.relayout_lines.emit(previous, self.cells_per_line, previousl, self.lines_per_screen)
        self.update()

    def resizeEvent(self, ev):
        self.debounce_resize_timer.start()

    def update_screen(self, changes):
        self.cursor = changes['cursor'] or self.cursor
        if changes['screen']:
            self.pending_update += self.rect()
        else:
            cell_positions, line_positions, cell_width, cell_height = self.cell_positions, self.line_positions, self.cell_width, self.cell_height
            old_x, old_y = self.last_drew_cursor_at
            rects = []
            for lnum in changes['lines']:
                try:
                    rects.append(QRect(cell_positions[0], line_positions[lnum], self.line_width, cell_height))
                except IndexError:
                    continue
            old_cursor_added = old_y in changes['lines']
            cursor_added = self.cursor.y in changes['lines']
            for lnum, ranges in changes['cells'].items():
                for start, stop in ranges:
                    try:
                        rects.append(QRect(cell_positions[start], line_positions[lnum], cell_width * (stop - start + 1), cell_height))
                    except IndexError:
                        continue
                    if not old_cursor_added and old_y == lnum and (start <= old_x <= stop):
                        old_cursor_added = True
                    if not cursor_added and self.cursor.y == lnum and (start <= self.cursor.x <= stop):
                        cursor_added = True
            rects.sort(key=lambda r: (r.y(), r.x()))
            for r in rects:
                self.pending_update += r
            if not cursor_added:
                try:
                    self.pending_update += QRect(cell_positions[self.cursor.x], line_positions[self.cursor.y], cell_width, cell_height)
                except IndexError:
                    pass
                if self.cursor.y == old_y and self.cursor.x == old_x:
                    old_cursor_added = True
            if not old_cursor_added:
                try:
                    self.pending_update += QRect(cell_positions[old_x], line_positions[old_y], cell_width, cell_height)
                except IndexError:
                    pass
        if not self.debounce_update_timer.isActive():
            self.debounce_update_timer.start()

    def do_update_screen(self):
        if not self.pending_update.isEmpty():
            self.update(self.pending_update)
            self.pending_update = QRegion()

    def dirty_cells(self, region: QRegion) -> Iterator[Tuple[int]]:
        lines = (l for l in range(self.lines_per_screen) if region.intersects(QRect(
            self.hmargin, self.line_positions[l], self.cell_width * self.cells_per_line, self.cell_height)))
        cells = (c for c in range(self.cells_per_line) if region.intersects(QRect(
            self.cell_positions[c], self.vmargin, self.cell_width, self.cell_height * self.lines_per_screen)))
        return product(lines, cells)

    def paintEvent(self, ev):
        if self.size() != self.layout_size:
            return
        r = ev.region()
        p = QPainter(self)

        try:
            self.paint_cursor(p)
        except Exception:
            pass

        for lnum, cnum in self.dirty_cells(r):
            try:
                self.paint_cell(p, cnum, lnum)
            except Exception:
                pass

    def paint_cursor(self, painter):
        x, y = wrap_cursor_position(self.cursor.x, self.cursor.y, len(self.line_positions), len(self.cell_positions))
        r = QRect(self.cell_positions[x], self.line_positions[y], self.cell_width, self.cell_height)
        self.last_drew_cursor_at = x, y
        line = self.linebuf[x]
        colors = line.basic_cell_data(y)[2]
        if colors & HAS_BG_MASK:
            bg = as_color(colors >> COL_SHIFT, bg_color_table())
            if bg is not None:
                painter.fillRect(r, QColor(*bg))
        if self.hasFocus():
            painter.fillRect(r, self.cursor_color)
        else:
            painter.setPen(QPen(self.cursor_color))
            painter.drawRect(r)

    def paint_cell(self, painter: QPainter, col: int, row: int) -> None:
        line = self.linebuf[row]
        ch, attrs, colors = line.basic_cell_data(col)
        x, y = self.cell_positions[col], self.line_positions[row]
        if colors & HAS_BG_MASK and (col != self.last_drew_cursor_at[0] or row != self.last_drew_cursor_at[1]):
            bg = as_color(colors >> COL_SHIFT, bg_color_table())
            if bg is not None:
                r = QRect(x, y, self.cell_width, self.cell_height)
                painter.fillRect(r, QColor(*bg))
        if ch == 0 or ch == 32:
            # An empty cell
            pass
        else:
            text = chr(ch) + line.combining_chars.get(col, '')
            p = pixmap_for_text(text, colors, self.current_fg, self.current_font, self.cell_width * 2, self.cell_height, self.baseline_offset)
            painter.drawPixmap(x, y, p)

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        if mods & Qt.ControlModifier and mods & Qt.ShiftModifier:
            ev.accept()
            return  # Terminal shortcuts
        data = key_event_to_data(ev, mods)
        if data:
            self.send_data_to_child.emit(data)
            ev.accept()
