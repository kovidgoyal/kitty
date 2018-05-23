#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.cli import parse_args
from ..tui.operations import styled


OPTIONS = '''\
--title
default=ERROR
The title for the error message.
'''.format


def real_main(args):
    error_message = sys.stdin.buffer.read().decode('utf-8')
    sys.stdin = open('/dev/tty')
    msg = 'Show an error message'
    args, items = parse_args(args, OPTIONS, '', msg, 'hints')
    print(styled(args.title, fg_intense=True, fg='red', bold=True))
    print()
    print(error_message)
    print()
    input('Press Enter to close.')


def main(args):
    try:
        real_main(args)
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        input('Press Enter to close.')


if __name__ == '__main__':
    main(sys.argv)
