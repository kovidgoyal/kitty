#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache
from itertools import product
from collections import Counter
from typing import Tuple, Iterator

from PyQt5.QtCore import pyqtSignal, QTimer, QRect, Qt
from PyQt5.QtGui import QColor, QPainter, QFont, QFontMetrics, QRegion, QPen, QPixmap
from PyQt5.QtWidgets import QWidget, QApplication

from .config import build_ansi_color_tables, Options, fg_color_table, bg_color_table
from .data_types import Cursor, COL_SHIFT, COL_MASK, as_color
from .utils import set_current_font_metrics
from .tracker import ChangeTracker
from .screen import wrap_cursor_position
from .keys import key_event_to_data
from .screen import Screen
from pyte.streams import Stream, DebugStream
from pyte import modes as mo


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

    relayout_lines = pyqtSignal(object, object)
    write_to_child = pyqtSignal(object)
    title_changed = pyqtSignal(object)
    icon_changed = pyqtSignal(object)
    send_data_to_child = pyqtSignal(object)
    cells_per_line = 80
    lines_per_screen = 24

    def __init__(self, opts: Options, parent: QWidget=None, dump_commands: bool=False):
        QWidget.__init__(self, parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.cursor = Cursor()
        self.tracker = ChangeTracker(self)
        self.tracker.dirtied.connect(self.update_screen)
        sclass = DebugStream if dump_commands else Stream
        self.screen = Screen(opts, self.tracker, parent=self)
        for s in 'write_to_child title_changed icon_changed change_default_color'.split():
            getattr(self.screen, s).connect(getattr(self, s))
        self.stream = sclass(self.screen)
        self.feed = self.stream.feed
        self.last_drew_cursor_at = (0, 0)
        self.setFocusPolicy(Qt.WheelFocus)
        self.apply_opts(opts)
        self.debounce_resize_timer = t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(50)
        t.timeout.connect(self.do_layout)
        self.debounce_update_timer = t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(20)
        t.timeout.connect(self.do_update_screen)
        self.pending_update = QRegion()

    def apply_opts(self, opts):
        self.screen.apply_opts(opts)
        self.opts = opts
        pixmap_for_text.cache_clear()
        pal = self.palette()
        pal.setColor(pal.Window, QColor(opts.background))
        pal.setColor(pal.WindowText, QColor(opts.foreground))
        self.setPalette(pal)
        self.default_bg = self.original_bg = pal.color(pal.Window)
        self.default_fg = self.original_fg = pal.color(pal.WindowText).getRgb()[:3]
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

    def change_default_color(self, which, val):
        if which in ('fg', 'bg'):
            if not val:
                setattr(self, 'default_' + which, getattr(self, 'original_' + which))
                self.update()
            else:
                val = QColor(val)
                if val.isValid():
                    if which == 'fg':
                        self.default_fg = val.getRgb()[:3]
                    else:
                        self.default_bg = val
                    self.update()

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
            self.screen.resize(self.lines_per_screen, self.cells_per_line)
            self.relayout_lines.emit(self.cells_per_line, self.lines_per_screen)
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

    def common_bg_color(self):
        c = Counter()
        for rdiv in range(1, 4):
            lnum = int(self.lines_per_screen * rdiv / 4)
            for cdiv in range(1, 4):
                cnum = int(self.cells_per_line * cdiv / 4)
                bgcol = self.screen.line(lnum).bgcolor(cnum)
                c[bgcol] += 1
        return c.most_common(1)[0][0]

    def paintEvent(self, ev):
        if self.size() != self.layout_size:
            return
        r = ev.region()
        self.current_bgcol = self.common_bg_color()
        bg = self.default_bg
        if self.current_bgcol & 0xff:
            cbg = as_color(self.current_bgcol, bg_color_table())
            if cbg:
                bg = QColor(*cbg)

        p = QPainter(self)
        p.fillRect(self.rect(), bg)

        for lnum, cnum in self.dirty_cells(r):
            try:
                self.paint_cell(p, cnum, lnum)
            except Exception:
                pass
        if not self.cursor.hidden:
            x, y = wrap_cursor_position(self.cursor.x, self.cursor.y, len(self.line_positions), len(self.cell_positions))
            cr = QRect(self.cell_positions[x], self.line_positions[y], self.cell_width, self.cell_height)
            if r.intersects(cr):
                self.paint_cell(p, x, y, True)
        p.end()

    def paint_cursor(self, painter, x, y):
        r = QRect(self.cell_positions[x], self.line_positions[y], self.cell_width, self.cell_height)
        self.last_drew_cursor_at = x, y
        cc = self.cursor_color
        if self.cursor.color:
            q = QColor(self.cursor.color)
            if q.isValid():
                cc = q
                cc.setAlphaF(self.opts.cursor_opacity)

        def width(w=2, vert=True):
            dpi = self.logicalDpiX() if vert else self.logicalDpiY()
            return int(w * dpi / 72)

        if self.hasFocus():
            cs = self.cursor.shape or self.opts.cursor_shape
            if cs == 'block':
                painter.fillRect(r, cc)
            elif cs == 'beam':
                w = width(1.5)
                painter.fillRect(r.left(), r.top(), w, self.cell_height, cc)
            elif cs == 'underline':
                y = r.top() + self.font_metrics.underlinePos() + self.baseline_offset
                w = width(vert=False)
                painter.fillRect(r.left(), min(y, r.bottom() - w), self.cell_width, w, cc)
        else:
            painter.setPen(QPen(cc))
            painter.drawRect(r)

    def paint_cell(self, painter: QPainter, col: int, row: int, draw_cursor: bool=False) -> None:
        line = self.screen.line(row)
        ch, attrs, colors = line.basic_cell_data(col)
        x, y = self.cell_positions[col], self.line_positions[row]
        bgcol = colors >> COL_SHIFT
        if bgcol != self.current_bgcol:
            bg = as_color(colors >> COL_SHIFT, bg_color_table())
            if bg is not None:
                r = QRect(x, y, self.cell_width, self.cell_height)
                painter.fillRect(r, QColor(*bg))
        if draw_cursor:
            self.paint_cursor(painter, col, row)
        if ch == 0 or ch == 32:
            # An empty cell
            pass
        else:
            text = chr(ch) + line.combining_chars.get(col, '')
            p = pixmap_for_text(text, colors, self.default_fg, self.current_font, self.cell_width * 2, self.cell_height, self.baseline_offset)
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
            return
        return QWidget.keyPressEvent(self, ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            c = QApplication.clipboard()
            if c.supportsSelection():
                text = c.text(c.Selection)
                if text:
                    text = text.encode('utf-8')
                    if self.screen.in_bracketed_paste_mode:
                        text = mo.BRACKETED_PASTE_START + text + mo.BRACKETED_PASTE_END
                    self.send_data_to_child.emit(text)
                ev.accept()
                return
        return QWidget.mousePressEvent(self, ev)

    def focusInEvent(self, ev):
        if self.screen.enable_focus_tracking:
            self.send_data_to_child.emit(b'\x1b[I')
        return QWidget.focusInEvent(self, ev)

    def focusOutEvent(self, ev):
        if self.screen.enable_focus_tracking:
            self.send_data_to_child.emit(b'\x1b[O')
        return QWidget.focusOutEvent(self, ev)
