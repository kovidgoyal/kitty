#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import subprocess
import sys
import tempfile
from contextlib import suppress
from typing import List, Optional

from kitty.cli import parse_args
from kitty.cli_stub import RemoteFileCLIOptions
from kitty.typing import BossType
from kitty.utils import command_for_open, open_cmd

from ..ssh.main import SSHConnectionData
from ..tui.handler import result_handler
from ..tui.operations import clear_screen, faint, set_cursor_visible, styled


def option_text() -> str:
    return '''\
--mode -m
choices=ask,edit
default=ask
Which mode to operate in.


--path -p
Path to the remote file.


--hostname -h
Hostname of the remote host.


--ssh-connection-data
The data used to connect over ssh.
'''


def show_error(msg: str) -> None:
    print(styled(msg, fg='red'))
    print()
    print('Press any key to exit...')
    import tty
    sys.stdout.flush()
    tty.setraw(sys.stdin.fileno())
    try:
        while True:
            try:
                q = sys.stdin.buffer.read(1)
                if q:
                    break
            except (KeyboardInterrupt, EOFError):
                break
    finally:
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.flush()


def ask_action(opts: RemoteFileCLIOptions) -> str:
    print('What would you like to do with the remote file on {}:'.format(styled(opts.hostname or 'unknown', bold=True, fg='magenta')))
    print(styled(opts.path or '', fg='yellow', fg_intense=True))
    print()

    def key(x: str) -> str:
        return styled(x, bold=True, fg='green')

    def help_text(x: str) -> str:
        return faint(x)

    print('{}dit the file'.format(key('E')))
    print(help_text('The file will be downloaded and opened in an editor. Any changes you save will'
                    ' be automatically sent back to the remote machine'))
    print()

    print('{}pen the file'.format(key('O')))
    print(help_text('The file will be downloaded and opened by the default open program'))
    print()

    print('{}ancel'.format(key('C')))
    print()

    import tty
    sys.stdout.flush()
    tty.setraw(sys.stdin.fileno())
    response = 'c'
    try:
        while True:
            q = sys.stdin.buffer.read(1)
            if q:
                if q in b'\x1b\x03':
                    break
                with suppress(Exception):
                    response = q.decode('utf-8').lower()
                    if response in 'ceo':
                        break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.flush()

    return {'e': 'edit', 'o': 'open'}.get(response, 'cancel')


def simple_copy_command(conn_data: SSHConnectionData, path: str) -> List[str]:
    cmd = [conn_data.binary]
    if conn_data.port:
        cmd += ['-p', str(conn_data.port)]
    cmd += [conn_data.hostname, 'cat', path]
    return cmd


def save_output(cmd: List[str], dest_path: str) -> bool:
    with open(dest_path, 'wb') as f:
        cp = subprocess.run(cmd, stdout=f)
        return cp.returncode == 0


Result = Optional[str]


def main(args: List[str]) -> Result:
    msg = 'Ask the user what to do with the remote file'
    try:
        cli_opts, items = parse_args(args[1:], option_text, '', msg, 'kitty remote_file', result_class=RemoteFileCLIOptions)
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0])
            input('Press enter to quit...')
        raise SystemExit(e.code)

    print(set_cursor_visible(False), end='')
    try:
        action = ask_action(cli_opts)
    finally:
        print(set_cursor_visible(True), clear_screen(), end='')
    try:
        return handle_action(action, cli_opts)
    except Exception:
        import traceback
        traceback.print_exc()
        show_error('Failed with unhandled exception')


def handle_action(action: str, cli_opts: RemoteFileCLIOptions) -> Result:
    conn_data = SSHConnectionData(*json.loads(cli_opts.ssh_connection_data or ''))
    remote_path = cli_opts.path or ''
    if action == 'open':
        print('Opening', cli_opts.path, 'from', cli_opts.hostname)
        cmd = simple_copy_command(conn_data, remote_path)
        dest = os.path.join(tempfile.mkdtemp(), os.path.basename(remote_path))
        if save_output(cmd, dest):
            return dest
        show_error('Failed to copy file from remote machine')
    elif action == 'edit':
        print('Editing', cli_opts.path, 'from', cli_opts.hostname)


@result_handler()
def handle_result(args: List[str], data: Result, target_window_id: int, boss: BossType) -> None:
    if data:
        cmd = command_for_open(boss.opts.open_url_with)
        open_cmd(cmd, data)


if __name__ == '__main__':
    main(sys.argv)
