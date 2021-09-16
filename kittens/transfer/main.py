#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import sys
from typing import List, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import TransferCLIOptions

from .send import send_main


def option_text() -> str:
    return '''\
--direction -d
default=send
choices=send,receive
Whether to send or receive files.


--mode -m
default=normal
choices=mirror
How to interpret command line arguments. In :code:`mirror` mode all arguments
are assumed to be files on the sending computer and they are mirrored onto the
receiving computer. In :code:`normal` mode the last argument is assumed to be a
destination path on the receiving computer.


--permissions-password -p
The password to use to skip the transfer confirmation popup in kitty. Must match the
password set for the :opt:`file_transfer_password` option in kitty.conf. Note that
leading and trailing whitespace is removed from the password. A password starting with
., / or ~ characters is assumed to be a file name to read the password from. A value
of - means read the password from STDIN. A password that is purely a number less than 256
is assumed to be the number of a file descriptor from which to read the actual password.


--confirm-paths -c
type=bool-set
Before actually transferring files, show a mapping of local file names to remote file names
and ask for confirmation.
'''


def parse_transfer_args(args: List[str]) -> Tuple[TransferCLIOptions, List[str]]:
    return parse_args(
        args[1:], option_text, '', 'Transfer files over the TTY device',
        'kitty transfer', result_class=TransferCLIOptions
    )


def read_password(loc: str) -> str:
    if not loc:
        return ''
    if loc.isdigit() and int(loc) >= 0 and int(loc) < 256:
        with open(int(loc), 'rb') as f:
            return f.read().decode('utf-8')
    if loc[0] in ('.', '~', '/'):
        if loc[0] == '~':
            loc = os.path.expanduser(loc)
        with open(loc, 'rb') as f:
            return f.read().decode('utf-8')
    if loc == '-':
        return sys.stdin.read()
    return loc


def main(args: List[str]) -> None:
    cli_opts, items = parse_transfer_args(args)
    if cli_opts.permissions_password:
        cli_opts.permissions_password = read_password(cli_opts.permissions_password).strip()

    if not items:
        raise SystemExit('Usage: kitty +kitten transfer file_or_directory ...')
    if cli_opts.direction == 'send':
        send_main(cli_opts, items)
        return


if __name__ == '__main__':
    main(sys.argv)
