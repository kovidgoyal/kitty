#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress
from typing import List

from kitty.cli import parse_args
from kitty.cli_stub import ErrorCLIOptions

from ..tui.operations import styled

OPTIONS = '''\
--title
default=ERROR
The title for the error message.
'''.format


def real_main(args: List[str]) -> None:
    msg = 'Show an error message'
    cli_opts, items = parse_args(args[1:], OPTIONS, '', msg, 'hints', result_class=ErrorCLIOptions)
    error_message = sys.stdin.buffer.read().decode('utf-8')
    sys.stdin = open(os.ctermid())
    print(styled(cli_opts.title, fg_intense=True, fg='red', bold=True))
    print()
    print(error_message)
    print()
    input('Press Enter to close.')


def main(args: List[str]) -> None:
    try:
        with suppress(KeyboardInterrupt):
            real_main(args)
    except Exception:
        import traceback
        traceback.print_exc()
        input('Press Enter to close.')


if __name__ == '__main__':
    main(sys.argv)
