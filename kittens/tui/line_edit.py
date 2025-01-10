#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Callable

from kitty.fast_data_types import truncate_point_for_length, wcswidth
from kitty.key_encoding import EventType, KeyEvent

from .operations import RESTORE_CURSOR, SAVE_CURSOR, move_cursor_by, set_cursor_shape


class LineEdit:

    def __init__(self, is_password: bool = False) -> None:
        self.clear()
        self.is_password = is_password

    def clear(self) -> None:
        self.current_input = ''
        self.cursor_pos = 0
        self.pending_bell = False

    def split_at_cursor(self, delta: int = 0) -> tuple[str, str]:
        pos = max(0, self.cursor_pos + delta)
        x = truncate_point_for_length(self.current_input, pos) if pos else 0
        before, after = self.current_input[:x], self.current_input[x:]
        return before, after

    def write(self, write: Callable[[str], None], prompt: str = '', screen_cols: int = 0) -> None:
        if self.pending_bell:
            write('\a')
            self.pending_bell = False
        ci = self.current_input
        if self.is_password:
            ci = '*' * wcswidth(ci)
        text = prompt + ci
        cursor_pos = self.cursor_pos + wcswidth(prompt)
        if screen_cols:
            write(SAVE_CURSOR + text + RESTORE_CURSOR)
            used_lines, last_line_cursor_pos = divmod(cursor_pos, screen_cols)
            if used_lines == 0:
                if last_line_cursor_pos:
                    write(move_cursor_by(last_line_cursor_pos, 'right'))
            else:
                if used_lines:
                    write(move_cursor_by(used_lines, 'down'))
                if last_line_cursor_pos:
                    write(move_cursor_by(last_line_cursor_pos, 'right'))
        else:
            write(text)
            write('\r')
            if cursor_pos:
                write(move_cursor_by(cursor_pos, 'right'))
            write(set_cursor_shape('beam'))

    def add_text(self, text: str) -> None:
        if self.current_input:
            x = truncate_point_for_length(self.current_input, self.cursor_pos) if self.cursor_pos else 0
            self.current_input = self.current_input[:x] + text + self.current_input[x:]
        else:
            self.current_input = text
        self.cursor_pos += wcswidth(text)

    def on_text(self, text: str, in_bracketed_paste: bool) -> None:
        self.add_text(text)

    def backspace(self, num: int = 1) -> bool:
        before, after = self.split_at_cursor()
        nbefore = before[:-num]
        if nbefore != before:
            self.current_input = nbefore + after
            self.cursor_pos = wcswidth(nbefore)
            return True
        self.pending_bell = True
        return False

    def delete(self, num: int = 1) -> bool:
        before, after = self.split_at_cursor()
        nafter = after[num:]
        if nafter != after:
            self.current_input = before + nafter
            self.cursor_pos = wcswidth(before)
            return True
        self.pending_bell = True
        return False

    def _left(self) -> None:
        if not self.current_input:
            self.cursor_pos = 0
            return
        if self.cursor_pos:
            before, after = self.split_at_cursor(-1)
            self.cursor_pos = wcswidth(before)

    def _right(self) -> None:
        if not self.current_input:
            self.cursor_pos = 0
            return
        max_pos = wcswidth(self.current_input)
        if self.cursor_pos >= max_pos:
            self.cursor_pos = max_pos
            return
        before, after = self.split_at_cursor(1)
        self.cursor_pos += 1 + int(wcswidth(before) == self.cursor_pos)

    def _move_loop(self, func: Callable[[], None], num: int) -> bool:
        before = self.cursor_pos
        changed = False
        while num > 0:
            func()
            changed = self.cursor_pos != before
            if not changed:
                break
            num -= 1
        if not changed:
            self.pending_bell = True
        return changed

    def left(self, num: int = 1) -> bool:
        return self._move_loop(self._left, num)

    def right(self, num: int = 1) -> bool:
        return self._move_loop(self._right, num)

    def home(self) -> bool:
        if self.cursor_pos:
            self.cursor_pos = 0
            return True
        return False

    def end(self) -> bool:
        orig = self.cursor_pos
        self.cursor_pos = wcswidth(self.current_input)
        return self.cursor_pos != orig

    def on_key(self, key_event: KeyEvent) -> bool:
        if key_event.type is EventType.RELEASE:
            return False
        if key_event.matches('home') or key_event.matches('ctrl+a'):
            return self.home()
        if key_event.matches('end') or key_event.matches('ctrl+e'):
            return self.end()
        if key_event.matches('backspace'):
            self.backspace()
            return True
        if key_event.matches('delete') or key_event.matches('ctrl+d'):
            self.delete()
            return True
        if key_event.matches('left') or key_event.matches('ctrl+b'):
            self.left()
            return True
        if key_event.matches('right') or key_event.matches('ctrl+f'):
            self.right()
            return True
        return False
