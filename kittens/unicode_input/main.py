#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from ..tui.handler import Handler
from ..tui.loop import Loop


class UnicodeInput(Handler):

    def initialize(self, *args):
        Handler.initialize(self, *args)
        self.write('Testing 123...')

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)


def main(args=sys.argv):
    loop = Loop()
    handler = UnicodeInput()
    loop.loop(handler)
