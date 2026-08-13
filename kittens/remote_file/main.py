#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


import sys

from kitty.typing_compat import BossType
from kitty.utils import command_for_open, open_cmd

from ..tui.handler import result_handler

# Must match kittens/remote_file/ssh.go is_ssh_kitten_sentinel. Kept importable
# here because kitty/window.py:handle_remote_file imports it directly.
is_ssh_kitten_sentinel = '!#*&$#($ssh-kitten)(##$'


def option_text() -> str:
    return '''\
--mode -m
choices=ask,edit
default=ask
Which mode to operate in.


--path -p
Path to the remote file.


--hostname
Hostname of the remote host.


--ssh-connection-data
The data used to connect over ssh.
'''


def main(args: list[str]) -> None:
    raise SystemExit('This should be run as kitten remote_file')


@result_handler()
def handle_result(args: list[str], data: str | None, target_window_id: int, boss: BossType) -> None:
    if data:
        from kitty.fast_data_types import get_options
        cmd = command_for_open(get_options().open_url_with)
        open_cmd(cmd, data)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = ''
    cd['options'] = option_text
    cd['help_text'] = 'Ask the user what to do with the remote file. For internal use by kitty, do not run it directly.'
    cd['short_desc'] = 'Handle remote files'
