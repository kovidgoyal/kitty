#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import readline
import sys
from gettext import gettext as _

from kitty.cli import parse_args

from ..tui.operations import alternate_screen, styled


def option_text():
    return '''\
--type -t
choices=line
default=line
Type of input. Defaults to asking for a line of text.


--message -m
The message to display to the user. If not specified a default
message is shown.
'''


def main(args=sys.argv):
    msg = 'Ask the user for input'
    try:
        args, items = parse_args(args[1:], option_text, '', msg, 'kitty ask')
    except SystemExit as e:
        print(e.args[0], file=sys.stderr)
        input('Press enter to quit...')
        return 1

    with alternate_screen():
        if args.message:
            print(styled(args.message), bold=True)

        readline.read_init_file()

        prompt = ': '
        if args.type == 'line':
            prompt = _('Enter line: ')
        try:
            ans = input(prompt)
        except (KeyboardInterrupt, EOFError):
            return
    print('OK:', json.dumps(ans))
