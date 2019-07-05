#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import os
import select
import sys
from ..tui.operations import styled


def main(args):
    text = ''
    if sys.stdin.isatty():
        if '--help' not in args and '-h' not in args:
            print('You must pass the text to be hinted on STDIN', file=sys.stderr)
            input('Press Enter to quit')
            return

    fcntl.fcntl(sys.__stdin__.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
    try:
        while True:
            if select.select([sys.__stdin__], [], [], 0) == ([sys.__stdin__], [], []):
                text = sys.__stdin__.read()
                text = text.replace("hello", styled("hello", bold=True, bg="green", fg="black"))
                sys.stdout.write(text)
    except KeyboardInterrupt:
        pass
    return


def handle_result(args, data, target_window_id, boss):
    print("in handle_result")
    pass


handle_result.type_of_input = 'live'


if __name__ == '__main__':
    # Run with kitty +kitten live_demo
    ans = main(sys.argv)
    if ans:
        print(ans)
