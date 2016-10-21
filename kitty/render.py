#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache
from collections import Counter, deque, defaultdict
from itertools import chain

from PyQt5.QtCore import QObject, pyqtSignal, Qt, QTimer, QRect
from PyQt5.QtGui import QPixmap, QRegion, QPainter, QPen, QColor, QFontMetrics, QFont

from .config import build_ansi_color_tables, fg_color_table, bg_color_table
from .data_types import Cursor, COL_SHIFT, COL_MASK, as_color, BOLD_MASK, ITALIC_MASK
from .screen import wrap_cursor_position
from .tracker import merge_ranges
from .utils import set_current_font_metrics


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


class Renderer(QObject):

    update_required = pyqtSignal()
    relayout_lines = pyqtSignal(object, object)
    cells_per_line = 80
    lines_per_screen = 24
    last_painted_cursor_at = 0, 0
    _has_focus = True

    def __init__(self, screen, dpix, dpiy, parent=None):
        QObject.__init__(self, parent)
        self.dpix, self.dpiy = dpix, dpiy
        self.screen = screen
        screen.change_default_color.connect(self.change_default_color)
        self.bufpix = QPixmap(10, 10)
        self.pending_changes = deque()
        self.debounce_update_timer = t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(20)
        t.timeout.connect(self.do_render)
        self.cursor = Cursor()

    def apply_opts(self, opts):
        pixmap_for_text.cache_clear()
        build_ansi_color_tables(opts)
        self.opts = opts
        self.default_bg = self.original_bg = QColor(opts.background)
        self.default_fg = self.original_fg = QColor(opts.foreground).getRgb()[:3]
        self.current_font = f = QFont(opts.font_family)
        f.setPointSizeF(opts.font_size)
        self.font_metrics = fm = QFontMetrics(f)
        self.bold_font = b = QFont(f)
        b.setBold(True)
        self.italic_font = i = QFont(f)
        i.setItalic(True)
        self.bi_font = bi = QFont(i)
        bi.setBold(True)
        self.cell_height = fm.lineSpacing()
        self.cell_width = ascii_width(fm)
        set_current_font_metrics(fm, self.cell_width)
        self.baseline_offset = fm.ascent()
        self.cursor_color = c = QColor(opts.cursor)
        c.setAlphaF(opts.cursor_opacity)

    def resize(self, size):
        self.bufpix = QPixmap(size)
        self.bufpix.fill(self.default_bg)
        previous, self.cells_per_line = self.cells_per_line, size.width() // self.cell_width
        previousl, self.lines_per_screen = self.lines_per_screen, size.height() // self.cell_height
        self.hmargin = (size.width() - self.cells_per_line * self.cell_width) // 2
        self.vmargin = (size.height() % self.cell_height) // 2
        self.line_positions = tuple(self.vmargin + i * self.cell_height for i in range(self.lines_per_screen))
        self.cell_positions = tuple(self.hmargin + i * self.cell_width for i in range(self.cells_per_line))
        self.row_rects = {lnum: QRect(self.hmargin, self.line_positions[lnum], self.cell_width *
                                      self.cells_per_line, self.cell_height) for lnum in range(self.lines_per_screen)}
        self.col_rects = {cnum: QRect(self.cell_positions[cnum], self.vmargin, self.cell_width,
                                      self.cell_height * self.lines_per_screen) for cnum in range(self.cells_per_line)}
        self.cell_rects = {
            lnum: {cnum: self.col_rects[cnum].intersected(self.row_rects[lnum]) for cnum in self.col_rects}
            for lnum in self.row_rects
        }
        self.line_width = self.cells_per_line * self.cell_width
        if (previous, previousl) != (self.cells_per_line, self.lines_per_screen):
            self.screen.resize(self.lines_per_screen, self.cells_per_line)
            self.relayout_lines.emit(self.cells_per_line, self.lines_per_screen)
        self.dirtied()

    def dirtied(self):
        self.update_screen({'screen': True})

    def size(self):
        return self.bufpix.size()

    def render(self, painter):
        painter.drawPixmap(0, 0, self.bufpix)

    def change_default_color(self, which, val):
        if which in ('fg', 'bg'):
            if not val:
                setattr(self, 'default_' + which, getattr(self, 'original_' + which))
                self.dirtied()
            else:
                val = QColor(val)
                if val.isValid():
                    if which == 'fg':
                        self.default_fg = val.getRgb()[:3]
                    else:
                        self.default_bg = val
                    self.dirtied()

    def update_screen(self, changes):
        self.pending_changes.append(changes)
        if not self.debounce_update_timer.isActive():
            self.debounce_update_timer.start()

    def wrap_cursor_pos(self):
        self.cursorx, self.cursory = wrap_cursor_position(self.cursor.x, self.cursor.y, self.lines_per_screen, self.cells_per_line)

    def set_has_focus(self, yes):
        if yes != self._has_focus:
            self._has_focus = yes
            self.wrap_cursor_pos()
            self.update_screen({'screen': False, 'lines': set(), 'cells': {self.cursory: {(self.cursorx, self.cursorx)}}})

    def line(self, lnum):
        return self.screen.line(lnum)

    def common_bg_color(self):
        c = Counter()
        for rdiv in range(1, 4):
            lnum = int(self.lines_per_screen * rdiv / 4)
            for cdiv in range(1, 4):
                cnum = int(self.cells_per_line * cdiv / 4)
                bgcol = self.line(lnum).bgcolor(cnum)
                c[bgcol] += 1
        return c.most_common(1)[0][0]

    def do_render(self):
        dirty_lines = set()
        dirty_cell_ranges = defaultdict(set)
        screen_dirtied = False

        while self.pending_changes:
            c = self.pending_changes.popleft()
            self.cursor = c.get('cursor') or self.cursor
            if not screen_dirtied:
                if c['screen']:
                    screen_dirtied = True
                    continue
                dirty_lines |= c['lines']
                for l, ranges in c['cells'].items():
                    if l not in dirty_lines:
                        for r in ranges:
                            dirty_cell_ranges[l].add(r)

        if screen_dirtied:
            dirty_cell_ranges = {}
            dirty_lines = tuple(range(self.lines_per_screen))
        else:
            dirty_cell_ranges = {l: tuple(merge_ranges(r)) for l, r in dirty_cell_ranges.items() if l not in dirty_lines}

        self.paint(dirty_lines, dirty_cell_ranges, screen_dirtied)
        self.update_required.emit()

    def calculate_dirty_region(self, dirty_lines, dirty_cell_ranges):
        ans = QRegion()
        for lnum in dirty_lines:
            ans += self.row_rects[lnum]
        for lnum, ranges in dirty_cell_ranges.items():
            lrect = self.cell_rects[lnum]
            for start, stop in ranges:
                for cnum in range(start, stop + 1):
                    ans += lrect[cnum]
        return ans

    def paint(self, dirty_lines, dirty_cell_ranges, screen_dirtied):
        self.current_bgcol = self.common_bg_color()
        bg = self.default_bg
        if self.current_bgcol & 0xff:
            cbg = as_color(self.current_bgcol, bg_color_table())
            if cbg:
                bg = QColor(*cbg)
        self.wrap_cursor_pos()
        self.cursor_painted = False
        self.old_cursorx, self.old_cursory = self.last_painted_cursor_at
        self.cursor_moved = self.old_cursorx != self.cursorx or self.old_cursory != self.cursory
        region = QRegion(self.bufpix.rect()) if screen_dirtied else self.calculate_dirty_region(dirty_lines, dirty_cell_ranges)
        if self.cursor_moved:
            r = QRect(self.cell_positions[self.old_cursorx], self.line_positions[self.old_cursory], self.cell_width, self.cell_height)
            if region.contains(r):
                self.cursor_moved = False
            else:
                region += r

        p = QPainter(self.bufpix)
        p.save()
        p.setClipRegion(region)
        p.fillRect(self.bufpix.rect(), bg)
        p.restore()

        for lnum in dirty_lines:
            self.paint_line(p, lnum, range(self.cells_per_line))

        for lnum, ranges in dirty_cell_ranges.items():
            self.paint_line(p, lnum, chain.from_iterable(range(start, stop + 1) for start, stop in ranges))

        if not self.cursor_painted:
            self.paint_cell(p, self.line(self.cursory), self.cursory, self.cursorx)

        if self.cursor_moved:
            self.paint_cell(p, self.line(self.old_cursory), self.old_cursory, self.old_cursorx)

        p.end()

    def paint_line(self, painter, lnum, cell_range):
        line = self.line(lnum)
        for cnum in cell_range:
            self.paint_cell(painter, line, lnum, cnum)

    def paint_cell(self, painter, line, lnum, cnum):
        paint_cursor = False
        if not self.cursor_painted:
            self.cursor_painted = paint_cursor = lnum == self.cursory and cnum == self.cursorx
        ch, attrs, colors = line.basic_cell_data(cnum)
        x, y = self.cell_positions[cnum], self.line_positions[lnum]
        bgcol = colors >> COL_SHIFT
        if bgcol != self.current_bgcol:
            bg = as_color(colors >> COL_SHIFT, bg_color_table())
            if bg is not None:
                r = QRect(x, y, self.cell_width, self.cell_height)
                painter.fillRect(r, QColor(*bg))
        if paint_cursor:
            self.paint_cursor(painter, cnum, lnum)
        if ch == 0 or ch == 32:
            # An empty cell
            pass
        else:
            font = self.current_font
            b, i = attrs & BOLD_MASK, attrs & ITALIC_MASK
            if b:
                font = self.bi_font() if i else self.bold_font
            elif i:
                font = self.italic_font
            text = chr(ch) + line.combining_chars.get(cnum, '')
            p = pixmap_for_text(text, colors, self.default_fg, font, self.cell_width * 2, self.cell_height, self.baseline_offset)
            painter.drawPixmap(x, y, p)

    def paint_cursor(self, painter, x, y):
        self.last_painted_cursor_at = x, y
        r = QRect(self.cell_positions[x], self.line_positions[y], self.cell_width, self.cell_height)
        cc = self.cursor_color
        if self.cursor.color:
            q = QColor(self.cursor.color)
            if q.isValid():
                cc = q
                cc.setAlphaF(self.opts.cursor_opacity)

        def width(w=2, vert=True):
            dpi = self.dpix if vert else self.dpiy
            return int(w * dpi / 72)

        if self._has_focus:
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
