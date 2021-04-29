#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.key_encoding import (
    ALT, CAPS_LOCK, CTRL, HYPER, META, NUM_LOCK, PRESS, RELEASE, REPEAT, SHIFT,
    SUPER, KeyEvent, encode_key_event
)

from kittens.tui.handler import Handler
from kittens.tui.loop import Loop


class KeysHandler(Handler):

    def initialize(self) -> None:
        self.cmd.set_window_title('Kitty extended keyboard protocol demo')
        self.cmd.set_cursor_visible(False)
        self.print('Press any keys - Ctrl+C or Ctrl+D will terminate')

    def on_key_event(self, key_event: KeyEvent, in_bracketed_paste: bool = False) -> None:
        etype = {
            PRESS: 'PRESS',
            REPEAT: 'REPEAT',
            RELEASE: 'RELEASE'
        }[key_event.type]
        lmods = []
        for m, name in {
                SHIFT: 'Shift',
                ALT: 'Alt',
                CTRL: 'Ctrl',
                SUPER: 'Super',
                HYPER: 'Hyper',
                META: 'Meta',
                NUM_LOCK: 'NumLock',
                CAPS_LOCK: 'CapsLock',
        }.items():
            if key_event.mods & m:
                lmods.append(name)
        mods = '+'.join(lmods)
        if mods:
            mods += '+'
        key = f'{mods}{key_event.key} '
        self.cmd.colored(key, 'green')
        self.cmd.colored(etype + ' ', 'yellow')
        self.cmd.styled(key_event.text, italic=True)
        self.print()
        rep = 'CSI ' + encode_key_event(key_event)[2:]
        rep = rep.replace(';', ' ; ').replace(':', ' : ')[:-1] + ' ' + rep[-1]
        self.cmd.styled(rep, fg='magenta')
        if (key_event.shifted_key or key_event.alternate_key):
            self.print()
            if key_event.shifted_key:
                self.cmd.colored('Shifted key: ', 'gray')
                self.print(key_event.shifted_key + ' ', end='')
            if key_event.alternate_key:
                self.cmd.colored('Alternate key: ', 'gray')
                self.print(key_event.alternate_key + ' ', end='')
        self.print()
        self.print()

    def on_interrupt(self) -> None:
        self.quit_loop(0)

    def on_eot(self) -> None:
        self.quit_loop(0)


def main() -> None:
    loop = Loop()
    handler = KeysHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code)
