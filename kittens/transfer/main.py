#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import List

from kitty.cli import parse_args
from kitty.cli_stub import TransferCLIOptions


def option_text() -> str:
    return '''\
--direction -d
default=send
choices=send,receive
Whether to send or receive files.
'''


def send_main(cli_opts: TransferCLIOptions, args: List[str]) -> None:
    pass


def main(args: List[str]) -> None:
    cli_opts, items = parse_args(
        args[1:], option_text, '', 'Transfer files over the TTY device',
        'kitty transfer', result_class=TransferCLIOptions
    )
    if not items:
        raise SystemExit('Usage: kitty +kitten transfer file_or_directory ...')
    if cli_opts.direction == 'send':
        send_main(cli_opts, items)
        return


if __name__ == '__main__':
    main(sys.argv)
