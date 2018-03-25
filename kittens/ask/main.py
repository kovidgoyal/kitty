#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import readline
import sys

from kitty.cli import parse_args
from kitty.constants import cache_dir

from ..tui.operations import alternate_screen, styled


def get_history_items():
    return list(map(readline.get_history_item, range(1, readline.get_current_history_length() + 1)))


def sort_key(item):
    return len(item), item.lower()


class HistoryCompleter:

    def __init__(self, name=None):
        self.matches = []
        self.history_path = None
        if name:
            ddir = os.path.join(cache_dir(), 'ask')
            try:
                os.makedirs(ddir)
            except FileExistsError:
                pass
            self.history_path = os.path.join(ddir, name)

    def complete(self, text, state):
        response = None
        if state == 0:
            history_values = get_history_items()
            if text:
                self.matches = sorted(
                        (h for h in history_values if h and h.startswith(text)), key=sort_key)
            else:
                self.matches = []
        try:
            response = self.matches[state]
        except IndexError:
            response = None
        return response

    def __enter__(self):
        if self.history_path:
            if os.path.exists(self.history_path):
                readline.read_history_file(self.history_path)
            readline.set_completer(self.complete)
            readline.parse_and_bind('tab: complete')
        return self

    def __exit__(self, *a):
        if self.history_path:
            readline.write_history_file(self.history_path)


def option_text():
    return '''\
--type -t
choices=line
default=line
Type of input. Defaults to asking for a line of text.


--message -m
The message to display to the user. If not specified a default
message is shown.


--name -n
The name for this question. Used to store history of previous answers which can
be used for completions and via the browse history readline bindings.
'''


def real_main(args):
    msg = 'Ask the user for input'
    try:
        args, items = parse_args(args[1:], option_text, '', msg, 'kitty ask')
    except SystemExit as e:
        print(e.args[0])
        input('Press enter to quit...')
        raise SystemExit(1)

    readline.read_init_file()

    with alternate_screen(), HistoryCompleter(args.name):
        if args.message:
            print(styled(args.message, bold=True))

        prompt = '> '
        try:
            ans = input(prompt)
        except (KeyboardInterrupt, EOFError):
            return
    print('OK:', json.dumps(ans))


def main(args=sys.argv):
    try:
        real_main(args)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stdout)
        input('Press enter to quit...')
        raise SystemExit(1)
