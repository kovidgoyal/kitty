#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from ..tui.operations import styled


def main(args):
    text = ''
    if sys.stdin.isatty():
        if '--help' not in args and '-h' not in args:
            print('You must pass the text to be hinted on STDIN', file=sys.stderr)
            input('Press Enter to quit')
            return

    try:
        while True:
            text = sys.stdin.buffer.read().decode('utf-8')
            text = text.replace("hello", styled("hell", bold=True, bg="green", fg="black"))
            sys.stdout.write(text)
    except KeyboardInterrupt:
        pass
    return


def handle_result(args, data, target_window_id, boss):
    pass


handle_result.type_of_input = 'screen'


if __name__ == '__main__':
    # Run with kitty +kitten live_demo
    ans = main(sys.argv)
    if ans:
        print(ans)
