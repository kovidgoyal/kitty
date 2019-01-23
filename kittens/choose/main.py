#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys


from ..tui.handler import Handler
from ..tui.loop import Loop


class ChooseHandler(Handler):

    def initialize(self):
        pass

    def on_text(self, text, in_bracketed_paste=False):
        pass

    def on_key(self, key_event):
        pass

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)


def main(args):
    loop = Loop()
    handler = ChooseHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
