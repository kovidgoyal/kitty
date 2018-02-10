#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from functools import lru_cache
from gettext import gettext as _

from kitty.config import cached_values_for
from kitty.fast_data_types import wcswidth
from kitty.key_encoding import (
    ESCAPE, F1, F2, RELEASE, backspace_key, enter_key
)

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import (
    clear_screen, colored, cursor, set_line_wrapping, set_window_title, styled
)

HEX, NAME = 'HEX', 'NAME'


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

    def __init__(self, cached_values):
        self.cached_values = cached_values
        self.current_input = ''
        self.current_char = None
        self.prompt_template = '{}> '
        self.choice_line = ''
        self.mode = globals().get(cached_values.get('mode', 'HEX'), 'HEX')
        self.update_prompt()

    def update_current_char(self):
        if self.mode is HEX:
            try:
                code = int(self.current_input, 16)
                if code <= 32 or code == 127 or 128 <= code <= 159 or 0xd800 <= code <= 0xdbff or 0xDC00 <= code <= 0xDFFF:
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

    def draw_title_bar(self):
        entries = []
        for name, key, mode in [
                (_('Code'), 'F1', HEX),
                (_('Name'), 'F2', NAME),
        ]:
            entry = ' {} ({}) '.format(name, key)
            if mode is self.mode:
                entry = styled(entry, reverse=False, bold=True)
            entries.append(entry)
        text = _('Search by:{}').format(' '.join(entries))
        extra = self.screen_size.cols - wcswidth(text)
        if extra > 0:
            text += ' ' * extra
        self.print(styled(text, reverse=True))

    def draw_screen(self):
        self.write(clear_screen())
        self.draw_title_bar()
        if self.mode is HEX:
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
        self.current_input += text
        self.refresh()

    def on_key(self, key_event):
        if key_event is backspace_key:
            self.current_input = self.current_input[:-1]
            self.refresh()
        elif key_event is enter_key:
            self.quit_loop(0)
        elif key_event.type is RELEASE:
            if key_event.key is ESCAPE:
                self.quit_loop(1)
            elif key_event.key is F1:
                self.switch_mode(HEX)
            elif key_event.key is F2:
                self.switch_mode(NAME)

    def switch_mode(self, mode):
        if mode is not self.mode:
            self.mode = mode
            self.cached_values['mode'] = mode
            self.current_input = ''
            self.current_char = None
            self.choice_line = ''
            self.refresh()

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)

    def on_resize(self, new_size):
        Handler.on_resize(self, new_size)
        self.refresh()


def main(args=sys.argv):
    loop = Loop()
    with cached_values_for('unicode-input') as cached_values:
        handler = UnicodeInput(cached_values)
        loop.loop(handler)
    if handler.current_char and loop.return_code == 0:
        print('OK:', hex(ord(handler.current_char))[2:])
    raise SystemExit(loop.return_code)
