#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.fast_data_types import wcswidth
from kitty.key_encoding import backspace_key, enter_key, ESCAPE

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, colored, set_line_wrapping, set_window_title
)


class UnicodeInput(Handler):

    def __init__(self):
        self.current_input = ''
        self.current_char = None
        self.prompt_template = '{}> '
        self.update_prompt()

    def update_current_char(self):
        try:
            code = int(self.current_input, 16)
            if code <= 32 or code == 127 or 128 <= code <= 159:
                self.current_char = None
            else:
                self.current_char = chr(code)
        except Exception:
            self.current_char = None

    def update_prompt(self):
        self.update_current_char()
        if self.current_char is None:
            c, color = '??', 'red'
        else:
            c, color = self.current_char, 'green'
        w = wcswidth(c)
        self.prompt = self.prompt_template.format(colored(c, color))
        self.promt_len = w + len(self.prompt_template) - 2

    def initialize(self, *args):
        Handler.initialize(self, *args)
        self.write(set_line_wrapping(False))
        self.write(set_window_title('Unicode input'))
        self.draw_screen()

    def draw_screen(self):
        self.write(clear_screen())
        self.print('Enter the hex code for the unicode character')
        self.write(self.prompt)
        self.write(self.current_input)

    def refresh(self):
        self.update_prompt()
        self.draw_screen()

    def on_text(self, text, in_bracketed_paste):
        self.current_input += text
        self.refresh()

    def on_key(self, key_event):
        if key_event is backspace_key:
            self.current_input = self.current_input[:-1]
            self.refresh()
        elif key_event is enter_key:
            self.quit_loop(0)
        else:
            if key_event.key is ESCAPE:
                self.quit_loop(1)

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)

    def on_resize(self, new_size):
        Handler.on_resize(self, new_size)
        self.draw_screen()


def main(args=sys.argv):
    loop = Loop()
    handler = UnicodeInput()
    loop.loop(handler)
    if handler.current_char and loop.return_code == 0:
        print(hex(ord(handler.current_char))[2:])
    raise SystemExit(loop.return_code)
