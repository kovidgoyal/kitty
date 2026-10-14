#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# A dialog shown when closing kitty while workspaces are open, asking whether
# to save them for the next launch, with a checkbox to remember the choice.

import sys
from typing import Any

from kitty.fast_data_types import wcswidth
from kitty.key_encoding import KeyEvent
from kitty.typing_compat import BossType

from ..tui.handler import Handler, result_handler
from ..tui.loop import Loop, MouseButton, MouseEvent
from ..tui.operations import MouseTracking, clear_screen, set_cursor_visible, set_window_title, styled

BUTTONS = (('save', 'Сохранить'), ('discard', 'Не сохранять'), ('cancel', 'Отмена'))
CHECKBOX = len(BUTTONS)  # focus index of the checkbox, after the buttons


class CloseDialog(Handler):
    mouse_tracking = MouseTracking.full

    def __init__(self, title: str, message: list[str]) -> None:
        self.title = title
        self.message = message
        self.remember = False
        self.focus = 0
        self.result: dict[str, Any] = {'action': 'cancel', 'remember': False}
        # clickable regions, filled in by draw_screen: (y, x_start, x_end, focus index)
        self.regions: list[tuple[int, int, int, int]] = []

    def initialize(self) -> None:
        self.cmd.set_cursor_visible(False)
        self.write(set_window_title(self.title))
        self.draw_screen()

    def finalize(self) -> None:
        self.write(set_cursor_visible(True))

    def on_resize(self, new_size: Any) -> None:
        super().on_resize(new_size)
        self.draw_screen()

    def activate(self, idx: int) -> None:
        if idx == CHECKBOX:
            self.remember = not self.remember
            self.focus = CHECKBOX
            self.draw_screen()
            return
        action = BUTTONS[idx][0]
        # Remembering "cancel" makes no sense, it would make kitty impossible to close
        self.result = {'action': action, 'remember': self.remember and action != 'cancel'}
        self.quit_loop(0)

    def on_key(self, key_event: KeyEvent) -> None:
        if key_event.matches('esc'):
            self.activate(BUTTONS.index(('cancel', 'Отмена')))
        elif key_event.matches('enter'):
            self.activate(self.focus)
        elif key_event.matches('space'):
            self.activate(CHECKBOX if self.focus == CHECKBOX else self.focus)
        elif key_event.matches('tab') or key_event.matches('right') or key_event.matches('down'):
            self.focus = (self.focus + 1) % (len(BUTTONS) + 1)
            self.draw_screen()
        elif key_event.matches('shift+tab') or key_event.matches('left') or key_event.matches('up'):
            self.focus = (self.focus - 1) % (len(BUTTONS) + 1)
            self.draw_screen()

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        shortcuts = {'s': 0, 'ы': 0, 'n': 1, 'т': 1, 'c': 2, 'с': 2, 'r': CHECKBOX, 'к': CHECKBOX}
        idx = shortcuts.get(text.lower())
        if idx is not None:
            self.activate(idx)

    def region_at(self, ev: MouseEvent) -> int:
        for y, x1, x2, idx in self.regions:
            if ev.cell_y == y and x1 <= ev.cell_x < x2:
                return idx
        return -1

    def on_mouse_move(self, ev: MouseEvent) -> None:
        idx = self.region_at(ev)
        if idx > -1 and idx != self.focus:
            self.focus = idx
            self.draw_screen()

    def on_click(self, ev: MouseEvent) -> None:
        if ev.buttons & MouseButton.LEFT and (idx := self.region_at(ev)) > -1:
            self.activate(idx)

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    on_eot = on_interrupt

    def draw_screen(self) -> None:
        self.regions = []
        cols, rows = self.screen_size.cols, self.screen_size.rows
        checkbox = ('☑' if self.remember else '☐') + ' Запомнить выбор и больше не спрашивать'
        button_labels = [f'  {label}  ' for _, label in BUTTONS]
        buttons_width = sum(wcswidth(b) for b in button_labels) + 3 * (len(BUTTONS) - 1)
        hint = 'Enter — выбрать · Tab/стрелки — перейти · Пробел — галочка · Esc — отмена'
        inner = max(wcswidth(self.title), buttons_width, wcswidth(checkbox), *(wcswidth(m) for m in self.message))
        inner = min(inner + 4, max(10, cols - 4))
        lines_count = 2 + len(self.message) + 2 + 2 + 1
        top = max(0, (rows - lines_count - 2) // 2)
        left = max(0, (cols - inner - 2) // 2)
        out: list[str] = [clear_screen()]

        def put(y: int, text: str) -> None:
            out.append(f'\x1b[{y + 1};{left + 1}H{text}')

        def padded(text: str, width: int) -> str:
            return text + ' ' * max(0, width - wcswidth(text))

        border = lambda s: styled(s, fg='gray')  # noqa: E731
        y = top
        put(y, border('╭' + '─' * inner + '╮'))
        y += 1
        put(y, border('│') + ' ' + styled(padded(self.title, inner - 1), bold=True) + border('│'))
        y += 1
        put(y, border('│') + ' ' * inner + border('│'))
        for line in self.message:
            y += 1
            put(y, border('│') + ' ' + padded(line, inner - 1) + border('│'))
        y += 1
        put(y, border('│') + ' ' * inner + border('│'))
        y += 1
        cb_text = styled(checkbox, reverse=True) if self.focus == CHECKBOX else checkbox
        put(y, border('│') + ' ' + cb_text + ' ' * max(0, inner - 1 - wcswidth(checkbox)) + border('│'))
        self.regions.append((y, left + 2, left + 2 + wcswidth(checkbox), CHECKBOX))
        y += 1
        put(y, border('│') + ' ' * inner + border('│'))
        y += 1
        x = left + 1 + max(0, inner - buttons_width) // 2
        row = border('│') + ' ' * (x - left - 1)
        for i, label in enumerate(button_labels):
            focused = self.focus == i
            if BUTTONS[i][0] == 'save':
                row += styled(label, fg='black', bg='green', bold=True) if focused else styled(label, fg='green', bold=True)
            else:
                row += styled(label, reverse=True) if focused else label
            self.regions.append((y, x, x + wcswidth(label), i))
            x += wcswidth(label)
            if i < len(button_labels) - 1:
                row += '   '
                x += 3
        row += ' ' * max(0, left + 1 + inner - x) + border('│')
        put(y, row)
        y += 1
        put(y, border('╰' + '─' * inner + '╯'))
        y += 2
        if y < rows:
            out.append(f'\x1b[{y + 1};{max(1, (cols - wcswidth(hint)) // 2 + 1)}H' + styled(hint, dim=True))
        self.write(''.join(out))


def main(args: list[str]) -> dict[str, Any]:
    # args: [kitten name, title, message line, message line, ...]
    title = args[1] if len(args) > 1 else 'Закрыть kitty?'
    message = args[2:] or ['Сохранить открытые воркспейсы?']
    loop = Loop()
    handler = CloseDialog(title, message)
    loop.loop(handler)
    return handler.result


@result_handler()
def handle_result(args: list[str], data: dict[str, Any], target_window_id: int, boss: BossType) -> None:
    pass


if __name__ == '__main__':
    print(main(sys.argv))
