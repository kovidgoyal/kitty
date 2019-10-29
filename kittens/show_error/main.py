#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress

from kitty.cli import parse_args

from ..tui.operations import styled

OPTIONS = '''\
--title
default=ERROR
The title for the error message.
'''.format


def real_main(args):
    msg = 'Show an error message'
    args, items = parse_args(args[1:], OPTIONS, '', msg, 'hints')
    error_message = sys.stdin.buffer.read().decode('utf-8')
    sys.stdin = open(os.ctermid())
    print(styled(args.title, fg_intense=True, fg='red', bold=True))
    print()
    print(error_message)
    print()
    input('Press Enter to close.')


def main(args):
    try:
        with suppress(KeyboardInterrupt):
            real_main(args)
    except Exception:
        import traceback
        traceback.print_exc()
        input('Press Enter to close.')


if __name__ == '__main__':
    main(sys.argv)
