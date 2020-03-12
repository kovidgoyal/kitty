#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import List

from kitty.key_encoding import (
    ALT, CTRL, PRESS, RELEASE, REPEAT, SHIFT, SUPER, KeyEvent,
    encode_key_event
)

from ..tui.handler import Handler
from ..tui.loop import Loop


class KeysHandler(Handler):

    def initialize(self) -> None:
        self.cmd.set_window_title('Kitty extended keyboard protocol demo')
        self.cmd.set_cursor_visible(False)
        self.print('Press any keys - Ctrl+C or Ctrl+D will terminate')

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        self.print('Text input: ' + text)

    def on_key(self, key_event: KeyEvent) -> None:
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
                SUPER: 'Super'}.items():
            if key_event.mods & m:
                lmods.append(name)
        mods = '+'.join(lmods)
        if mods:
            mods += '+'
        self.print('Key {}: {}{} [{}]'.format(etype, mods, key_event.key, encode_key_event(key_event)))

    def on_interrupt(self) -> None:
        self.quit_loop(0)

    def on_eot(self) -> None:
        self.quit_loop(0)


def main(args: List[str]) -> None:
    loop = Loop()
    handler = KeysHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
