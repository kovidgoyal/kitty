#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import List

from kitty.key_encoding import KeyEvent

from ..tui.handler import Handler
from ..tui.loop import Loop


class ChooseHandler(Handler):

    def initialize(self) -> None:
        pass

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        pass

    def on_key(self, key_event: KeyEvent) -> None:
        pass

    def on_interrupt(self) -> None:
        self.quit_loop(1)

    def on_eot(self) -> None:
        self.quit_loop(1)


def main(args: List[str]) -> None:
    loop = Loop()
    handler = ChooseHandler()
    loop.loop(handler)
    raise SystemExit(loop.return_code)


if __name__ == '__main__':
    main(sys.argv)
