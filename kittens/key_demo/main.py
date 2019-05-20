#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.key_encoding import (
    ALT, CTRL, PRESS, RELEASE, REPEAT, SHIFT, SUPER, encode_key_event
)

from ..tui.handler import Handler
from ..tui.loop import Loop


class KeysHandler(Handler):

    def initialize(self):
        self.cmd.set_window_title('Kitty extended keyboard protocol demo')
        self.cmd.set_cursor_visible(False)
        self.print('Press any keys - Ctrl+C or Ctrl+D will terminate')

    def on_text(self, text, in_bracketed_paste=False):
        self.print('Text input: ' + text)

    def on_key(self, key_event):
        etype = {
            PRESS: 'PRESS',
            REPEAT: 'REPEAT',
            RELEASE: 'RELEASE'
        }[key_event.type]
        mods = []
        for m, name in {
                SHIFT: 'Shift',
                ALT: 'Alt',
                CTRL: 'Ctrl',
                SUPER: 'Super'}.items():
            if key_event.mods & m:
                mods.append(name)
        mods = '+'.join(mods)
        if mods:
            mods += '+'
        self.print('Key {}: {}{} [{}]'.format(etype, mods, key_event.key, encode_key_event(key_event)))

    def on_interrupt(self):
        self.quit_loop(0)

    def on_eot(self):
        self.quit_loop(0)


def main(args):
    loop = Loop()
    handler = KeysHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
