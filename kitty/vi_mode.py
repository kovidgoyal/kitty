#!/usr/bin/env python
# License: GPL v3
# Alacritty-style vi mode: a keyboard driven cursor over the screen and
# scrollback that can make selections and copy them.

from typing import TYPE_CHECKING

from .fast_data_types import (
    GLFW_FKEY_ESCAPE,
    GLFW_MOD_ALT,
    GLFW_MOD_CONTROL,
    GLFW_MOD_SHIFT,
    GLFW_MOD_SUPER,
    KeyEvent,
    is_modifier_key,
)

if TYPE_CHECKING:
    from .window import Window

# Rows are "absolute": 0 is the top line of the screen, negative rows are in
# the scrollback (-1 is the most recent scrollback line).

BLANK, PUNCT, WORD = 0, 1, 2


def char_class(ch: str) -> int:
    if not ch or ch == '\0' or ch.isspace():
        return BLANK
    if ch.isalnum() or ch == '_':
        return WORD
    return PUNCT


class ViMode:

    def __init__(self, window: 'Window') -> None:
        self.window = window
        self.visual: str = ''  # '', 'v', 'V' or 'ctrl-v'
        self.anchor = (0, 0)  # (x, abs_row)
        self.pending = ''  # for multi key commands like gg
        screen = self.screen
        self.x = min(screen.cursor.x, screen.columns - 1)
        self.y = screen.cursor.y  # cursor.y is a screen row == absolute row
        if screen.scrolled_by:
            # keep the view where it is, put the cursor at the top-left of the view
            self.y = -screen.scrolled_by
            self.x = 0
        self.refresh()

    @property
    def screen(self):  # type: ignore
        return self.window.screen

    # Geometry {{{
    @property
    def top_row(self) -> int:
        return -self.screen.historybuf.count

    @property
    def bottom_row(self) -> int:
        return self.screen.lines - 1

    def cells(self, row: int) -> list[str]:
        s = self.screen
        line = s.historybuf.line(-row - 1) if row < 0 else s.line(row)
        return [line[i] for i in range(s.columns)]

    def is_continuation(self, cells: list[str], x: int) -> bool:
        # The trailing cells of a wide character have empty text
        return cells[x] == ''

    def last_col(self, row: int) -> int:
        ' Column of the last non-blank character on the line, or 0 '
        cells = self.cells(row)
        for x in range(len(cells) - 1, -1, -1):
            if char_class(cells[x]) != BLANK:
                return x
        return 0

    def snap_left(self, row: int, x: int) -> int:
        ' Move x left onto the start of a wide character '
        cells = self.cells(row)
        while x > 0 and self.is_continuation(cells, x):
            x -= 1
        return x
    # }}}

    # Rendering {{{
    def ensure_visible(self) -> None:
        s = self.screen
        view_top = -s.scrolled_by
        view_bottom = view_top + s.lines - 1
        if self.y < view_top:
            s.scroll(view_top - self.y, True)
        elif self.y > view_bottom:
            s.scroll(self.y - view_bottom, False)

    def refresh(self) -> None:
        self.ensure_visible()
        s = self.screen
        s.set_vi_cursor(True, self.x, self.y + s.scrolled_by)
        if self.visual:
            ax, ay = self.anchor
            if self.visual == 'V':
                top, bottom = min(ay, self.y), max(ay, self.y)
                s.set_vi_selection(0, top, s.columns - 1, bottom, False)
            else:
                s.set_vi_selection(ax, ay, self.x, self.y, self.visual == 'ctrl-v')
    # }}}

    # Motions {{{
    def move_vertical(self, delta: int) -> None:
        self.y = max(self.top_row, min(self.bottom_row, self.y + delta))
        self.x = self.snap_left(self.y, min(self.x, self.screen.columns - 1))

    def move_horizontal(self, delta: int) -> None:
        cells = self.cells(self.y)
        x = self.x
        step = 1 if delta > 0 else -1
        for _ in range(abs(delta)):
            nx = x + step
            while 0 <= nx < len(cells) and self.is_continuation(cells, nx):
                nx += step
            if not 0 <= nx < len(cells):
                break
            x = nx
        self.x = x

    def iter_forward(self):  # type: ignore
        ' Yield (x, row, class) for each cell after the cursor. Line ends count as blanks. '
        x, row = self.x, self.y
        cells = self.cells(row)
        while True:
            x += 1
            if x >= len(cells):
                if row >= self.bottom_row:
                    return
                row += 1
                cells = self.cells(row)
                x = -1
                yield 0, row, BLANK  # line break separates words
                continue
            if self.is_continuation(cells, x):
                continue
            yield x, row, char_class(cells[x])

    def iter_backward(self):  # type: ignore
        x, row = self.x, self.y
        cells = self.cells(row)
        while True:
            x -= 1
            if x < 0:
                if row <= self.top_row:
                    return
                row -= 1
                cells = self.cells(row)
                x = len(cells)
                yield x - 1, row, BLANK
                continue
            if self.is_continuation(cells, x):
                continue
            yield x, row, char_class(cells[x])

    def word_forward(self) -> None:
        ' w: start of the next word '
        cur = char_class(self.cells(self.y)[self.x])
        seen_other = cur == BLANK
        for x, row, cls in self.iter_forward():
            if cls == BLANK:
                seen_other = True
                continue
            if cls != cur or seen_other:
                self.x, self.y = x, row
                return
        # no next word: go to end of buffer
        self.y = self.bottom_row
        self.x = self.last_col(self.y)

    def word_backward(self) -> None:
        ' b: start of the current/previous word '
        target = None
        cls_of_target = BLANK
        for x, row, cls in self.iter_backward():
            if target is None:
                if cls == BLANK:
                    continue
                target, cls_of_target = (x, row), cls
                continue
            if cls != cls_of_target or row != target[1]:
                break
            target = (x, row)
        if target is not None:
            self.x, self.y = target

    def line_start(self) -> None:
        self.x = 0

    def line_end(self) -> None:
        self.x = self.snap_left(self.y, self.last_col(self.y))

    def buffer_top(self) -> None:
        self.y = self.top_row
        self.x = 0

    def buffer_bottom(self) -> None:
        self.y = self.bottom_row
        self.x = 0

    def half_page(self, down: bool) -> None:
        amt = max(1, self.screen.lines // 2)
        s = self.screen
        if down:
            s.scroll(amt, False)
        else:
            s.scroll(amt, True)
        self.move_vertical(amt if down else -amt)
    # }}}

    # Visual mode and copying {{{
    def toggle_visual(self, kind: str) -> None:
        if self.visual == kind:
            self.visual = ''
            self.screen.clear_selection()
            return
        if not self.visual:
            self.anchor = (self.x, self.y)
        self.visual = kind

    def yank(self) -> None:
        if not self.visual:
            return
        self.window.copy_to_clipboard()
        self.exit()
    # }}}

    def exit(self) -> None:
        s = self.screen
        s.set_vi_cursor(False)
        s.clear_selection()
        s.scroll(s.historybuf.count, False)  # back to the bottom
        self.window.vi_mode = None

    def handle_key(self, ev: KeyEvent) -> bool:
        ' Returns True if the key was handled '
        if is_modifier_key(ev.key):
            return True
        mods = ev.mods & (GLFW_MOD_CONTROL | GLFW_MOD_ALT | GLFW_MOD_SUPER | GLFW_MOD_SHIFT)
        if ev.key == GLFW_FKEY_ESCAPE and not mods:
            if self.pending:
                self.pending = ''
            elif self.visual:
                self.visual = ''
                self.screen.clear_selection()
            else:
                self.exit()
                return True
            self.refresh()
            return True
        if mods == GLFW_MOD_CONTROL:
            k = chr(ev.key) if 0 < ev.key < 0x110000 else ''
            if k == 'v':
                self.toggle_visual('ctrl-v')
            elif k == 'u':
                self.half_page(down=False)
            elif k == 'd':
                self.half_page(down=True)
            elif k == 'c':
                self.exit()
                return True
            else:
                return False
            self.refresh()
            return True
        if mods & (GLFW_MOD_CONTROL | GLFW_MOD_ALT | GLFW_MOD_SUPER):
            return False
        t = ev.text
        if not t:
            return True
        if self.pending == 'g':
            self.pending = ''
            if t == 'g':
                self.buffer_top()
                self.refresh()
            return True
        match t:
            case 'h': self.move_horizontal(-1)
            case 'l': self.move_horizontal(1)
            case 'j': self.move_vertical(1)
            case 'k': self.move_vertical(-1)
            case 'w': self.word_forward()
            case 'b': self.word_backward()
            case '0': self.line_start()
            case '$': self.line_end()
            case 'G': self.buffer_bottom()
            case 'g':
                self.pending = 'g'
                return True
            case 'v': self.toggle_visual('v')
            case 'V': self.toggle_visual('V')
            case 'y':
                self.yank()
                return True
            case 'q' | 'i':
                self.exit()
                return True
            case _:
                return True
        self.refresh()
        return True
