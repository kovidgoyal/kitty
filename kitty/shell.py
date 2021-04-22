#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import readline
import shlex
import sys
import traceback
from contextlib import suppress
from functools import lru_cache
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

from .cli import (
    OptionDict, emph, green, italic, parse_option_spec, print_help_for_seq,
    title
)
from .cli_stub import RCOptions
from .constants import cache_dir, version, kitty_face
from .rc.base import (
    RemoteCommand, all_command_names, command_for_name,
    display_subcommand_help, parse_subcommand_cli
)
from .types import run_once


@run_once
def match_commands() -> Tuple[str, ...]:
    all_commands = tuple(sorted(x.replace('_', '-') for x in all_command_names()))
    return tuple(sorted(all_commands + ('exit', 'help', 'quit')))


def init_readline(readline: Any) -> None:
    with suppress(OSError):
        readline.read_init_file()
    if 'libedit' in readline.__doc__:
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind('tab: complete')


def cmd_names_matching(prefix: str) -> Generator[str, None, None]:
    for cmd in match_commands():
        if not prefix or cmd.startswith(prefix):
            yield cmd + ' '


@lru_cache()
def options_for_cmd(cmd: str) -> Tuple[Tuple[str, ...], Dict[str, OptionDict]]:
    alias_map: Dict[str, OptionDict] = {}
    try:
        func = command_for_name(cmd)
    except KeyError:
        return (), alias_map
    if not func.options_spec:
        return (), alias_map
    seq, disabled = parse_option_spec(func.options_spec)
    ans = []
    for opt in seq:
        if isinstance(opt, str):
            continue
        for alias in opt['aliases']:
            ans.append(alias)
            alias_map[alias] = opt
    return tuple(sorted(ans)), alias_map


def options_matching(prefix: str, cmd: str, last_word: str, aliases: Iterable[str], alias_map: Dict[str, OptionDict]) -> Generator[str, None, None]:
    for alias in aliases:
        if (not prefix or alias.startswith(prefix)) and alias.startswith('--'):
            yield alias + ' '


class Completer:

    def __init__(self) -> None:
        self.matches: List[str] = []
        ddir = cache_dir()
        os.makedirs(ddir, exist_ok=True)
        self.history_path = os.path.join(ddir, 'shell.history')

    def complete(self, text: str, state: int) -> Optional[str]:
        if state == 0:
            line = readline.get_line_buffer()
            cmdline = shlex.split(line)
            if len(cmdline) < 2 and not line.endswith(' '):
                self.matches = list(cmd_names_matching(text))
            else:
                self.matches = list(options_matching(text, cmdline[0], cmdline[-1], *options_for_cmd(cmdline[0])))
        if state < len(self.matches):
            return self.matches[state]
        return None

    def __enter__(self) -> 'Completer':
        with suppress(Exception):
            readline.read_history_file(self.history_path)
        readline.set_completer(self.complete)
        delims = readline.get_completer_delims()
        readline.set_completer_delims(delims.replace('-', ''))
        return self

    def __exit__(self, *a: Any) -> None:
        readline.write_history_file(self.history_path)


def print_err(*a: Any, **kw: Any) -> None:
    kw['file'] = sys.stderr
    print(*a, **kw)


def print_help(which: Optional[str] = None) -> None:
    if which is None:
        print('Control kitty by sending it commands.')
        print()
        print(title('Commands') + ':')
        for cmd in all_command_names():
            c = command_for_name(cmd)
            print(' ', green(c.name))
            print('   ', c.short_desc)
        print(' ', green('exit'))
        print('   ', 'Exit this shell')
        print('\nUse help {} for help on individual commands'.format(italic('command')))
    else:
        try:
            func = command_for_name(which)
        except KeyError:
            if which == 'exit':
                print('Exit this shell')
            elif which == 'help':
                print('Show help')
            else:
                print('Unknown command: {}'.format(emph(which)))
            return
        display_subcommand_help(func)


def run_cmd(global_opts: RCOptions, cmd: str, func: RemoteCommand, opts: Any, items: List[str]) -> None:
    from .remote_control import do_io
    payload = func.message_to_kitty(global_opts, opts, items)
    send = {
        'cmd': cmd,
        'version': version,
        'no_response': False,
    }
    if payload is not None:
        send['payload'] = payload
    response = do_io(global_opts.to, send, func.no_response)
    if not response.get('ok'):
        if response.get('tb'):
            print_err(response['tb'])
        print_err(response['error'])
        return
    if 'data' in response:
        print(response['data'])


def real_main(global_opts: RCOptions) -> None:
    init_readline(readline)
    print_help_for_seq.allow_pager = False
    print('Welcome to the kitty shell!')
    print('Use {} for assistance or {} to quit'.format(green('help'), green('exit')))
    awid = os.environ.pop('KITTY_SHELL_ACTIVE_WINDOW_ID', None)
    if awid is not None:
        print('The ID of the previously active window is: {}'.format(awid))

    while True:
        try:
            try:
                scmdline = input(f'{kitty_face} ')
            except UnicodeEncodeError:
                scmdline = input('kitty> ')
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            continue
        if not scmdline:
            continue
        cmdline = shlex.split(scmdline)
        cmd = cmdline[0].lower()

        try:
            func = command_for_name(cmd)
        except KeyError:
            if cmd in ('exit', 'quit'):
                break
            if cmd == 'help':
                print_help(cmdline[1] if len(cmdline) > 1 else None)
                continue
            print_err('"{}" is an unknown command. Use "help" to see a list of commands.'.format(emph(cmd)))
            continue

        try:
            opts, items = parse_subcommand_cli(func, cmdline)
        except SystemExit as e:
            if e.code != 0:
                print_err(e)
                print_err('Use "{}" to see how to use this command.'.format(emph('help ' + cmd)))
            continue
        except Exception:
            print_err('Unhandled error:')
            traceback.print_exc()
            continue
        else:
            try:
                run_cmd(global_opts, cmd, func, opts, items)
            except SystemExit as e:
                print_err(e)
                continue
            except KeyboardInterrupt:
                print()
                continue
            except Exception:
                print_err('Unhandled error:')
                traceback.print_exc()
                continue


def main(global_opts: RCOptions) -> None:
    try:
        with Completer():
            real_main(global_opts)
    except Exception:
        traceback.print_exc()
        input('Press enter to quit...')
        raise SystemExit(1)
