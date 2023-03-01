#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import sys
import termios
from contextlib import suppress
from typing import List

from kitty.cli import parse_args
from kitty.cli_stub import ErrorCLIOptions
from kitty.fast_data_types import open_tty
from kitty.utils import hold_till_enter, no_echo, write_all

from ..tui.operations import styled

OPTIONS = '''\
--title
default=ERROR
The title for the error message.
'''.format


def real_main(args: List[str]) -> None:
    msg = 'Show an error message. For internal use by kitty.'
    cli_opts, items = parse_args(args[1:], OPTIONS, '', msg, 'kitty +kitten show_error', result_class=ErrorCLIOptions)
    if sys.stdin.isatty():
        raise SystemExit('Input data for this kitten must be piped as JSON to STDIN')
    data = json.loads(sys.stdin.buffer.read())
    error_message = data['msg']
    if cli_opts.title:
        print(styled(cli_opts.title, fg_intense=True, fg='red', bold=True))
        print()
    print(error_message, flush=True)
    if data.get('tb'):
        import select

        from kittens.tui.operations import init_state, set_cursor_visible
        fd, original_termios = open_tty()
        msg = '\n\r\x1b[1;32mPress e to see detailed traceback or any other key to exit\x1b[m'
        write_all(fd, msg)
        write_all(fd, init_state(alternate_screen=False, kitty_keyboard_mode=False) + set_cursor_visible(False))
        with no_echo(fd):
            termios.tcdrain(fd)
            while True:
                rd = select.select([fd], [], [])[0]
                if not rd:
                    break
                q = os.read(fd, 1)
                if q in b'eE':
                    break
                return
    if data.get('tb'):
        tb = data['tb']
        for ln in tb.splitlines():
            print('\r\n', ln, sep='', end='')
        print(end='\r\n', flush=True)
    hold_till_enter()


def main(args: List[str]) -> None:
    try:
        with suppress(KeyboardInterrupt, EOFError):
            real_main(args)
    except Exception:
        import traceback
        traceback.print_exc()
        input('Press Enter to close')


if __name__ == '__main__':
    main(sys.argv)
