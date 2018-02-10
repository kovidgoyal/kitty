#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from functools import lru_cache
from gettext import gettext as _

from kitty.fast_data_types import wcswidth
from kitty.key_encoding import ESCAPE, backspace_key, enter_key

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, colored, cursor, set_line_wrapping, set_window_title, styled
)

HEX, NAME = 0, 1


@lru_cache()
def points_for_word(w):
    from .unicode_names import codepoints_for_word
    return codepoints_for_word(w.lower())


@lru_cache()
def name(cp):
    from .unicode_names import name_for_codepoint
    if isinstance(cp, str):
        cp = ord(cp[0])
    return (name_for_codepoint(cp) or '').capitalize()


FAINT = 242


class UnicodeInput(Handler):

    def __init__(self):
        self.current_input = ''
        self.current_char = None
        self.prompt_template = '{}> '
        self.choice_line = ''
        self.mode = HEX
        self.update_prompt()

    def update_current_char(self):
        if self.mode is HEX:
            try:
                code = int(self.current_input, 16)
                if code <= 32 or code == 127 or 128 <= code <= 159:
                    self.current_char = None
                else:
                    self.current_char = chr(code)
            except Exception:
                self.current_char = None
        else:
            self.current_char = None
            parts = self.current_input.split()
            if parts and parts[0]:
                codepoints = points_for_word(parts[0])
                for word in parts[1:]:
                    pts = points_for_word(word)
                    if pts:
                        codepoints &= pts
                if codepoints:
                    codepoints = tuple(sorted(codepoints))
                    self.current_char = chr(codepoints[0])
                    # name_map = {c: name(c) for c in codepoints}

    def update_prompt(self):
        self.update_current_char()
        if self.current_char is None:
            c, color = '??', 'red'
            self.choice_line = ''
        else:
            c, color = self.current_char, 'green'
            self.choice_line = _('Chosen:') + ' {} ({}) {}'.format(
                colored(c, 'green'), hex(ord(c))[2:], styled(name(c) or '', italic=True, fg=FAINT))
        w = wcswidth(c)
        self.prompt = self.prompt_template.format(colored(c, color))
        self.promt_len = w + len(self.prompt_template) - 2

    def initialize(self, *args):
        Handler.initialize(self, *args)
        self.write(set_line_wrapping(False))
        self.write(set_window_title(_('Unicode input')))
        self.draw_screen()

    def draw_screen(self):
        self.write(clear_screen())
        if self.mode is HEX:
            self.print(styled(_('Press the / key to search by character name'), fg=FAINT, italic=True))
            self.print(_('Enter the hex code for the character'))
        else:
            self.print(_('Enter words from the name of the character'))
        self.write(self.prompt)
        self.write(self.current_input)
        with cursor(self.write):
            self.print()
            if self.choice_line:
                self.print(self.choice_line)
                self.print()

    def refresh(self):
        self.update_prompt()
        self.draw_screen()

    def on_text(self, text, in_bracketed_paste):
        if self.mode is HEX and text == '/':
            self.mode = NAME
        else:
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
        print('OK:', hex(ord(handler.current_char))[2:])
    raise SystemExit(loop.return_code)
