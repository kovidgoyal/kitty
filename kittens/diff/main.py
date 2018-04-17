#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from functools import partial

from kitty.cli import parse_args

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import set_line_wrapping, set_window_title
from .collect import create_collection


class DiffHandler(Handler):

    def __init__(self, collection):
        self.collection = collection

    def init_terminal_state(self):
        self.write(set_line_wrapping(False))
        self.write(set_window_title('kitty +diff'))

    def initialize(self, *args):
        Handler.initialize(self, *args)
        self.init_terminal_state()


OPTIONS = partial('''\
'''.format, )


def main(args):
    msg = 'Show a side-by-side diff of the specified files/directories'
    args, items = parse_args(args[1:], OPTIONS, 'file_or_directory file_or_directory', msg, 'kitty +kitten diff')
    if len(items) != 2:
        raise SystemExit('You must specify exactly two files/directories to compare')
    left, right = items
    if os.path.isdir(left) != os.path.isdir(right):
        raise SystemExit('The items to be diffed should both be either directories or files. Comparing a directory to a file is not valid.')
    collection = create_collection(left, right)

    loop = Loop()
    handler = DiffHandler(collection)
    loop.loop(handler)
    if loop.return_code != 0:
        raise SystemExit(loop.return_code)


def handle_result(args, current_char, target_window_id, boss):
    pass


if __name__ == '__main__':
    main(sys.argv)
