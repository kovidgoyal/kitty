#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import os
import readline
import shlex
import sys
import traceback
import types

from .cli import emph, green, italic, print_help_for_seq, title
from .cmds import cmap, display_subcommand_help, parse_subcommand_cli
from .constants import cache_dir, version

all_commands = tuple(sorted(cmap))


class Completer:

    def __init__(self):
        self.matches = []
        ddir = cache_dir()
        try:
            os.makedirs(ddir)
        except FileExistsError:
            pass
        self.history_path = os.path.join(ddir, 'shell.history')

    def complete(self, text, state):
        response = None
        return response

    def __enter__(self):
        if os.path.exists(self.history_path):
            readline.read_history_file(self.history_path)
        readline.set_completer(self.complete)
        readline.parse_and_bind('tab: complete')
        return self

    def __exit__(self, *a):
        readline.write_history_file(self.history_path)


def print_err(*a, **kw):
    kw['file'] = sys.stderr
    print(*a, **kw)


def print_help(which=None):
    if which is None:
        print('Control kitty by sending it commands.')
        print()
        print(title('Commands') + ':')
        for cmd in all_commands:
            c = cmap[cmd]
            print(' ', green(c.name))
            print('   ', c.short_desc)
        print(' ', green('exit'))
        print('   ', 'Exit this shell')
        print('\nUse help {} for help on individual commands'.format(italic('command')))
    else:
        try:
            func = cmap[which]
        except KeyError:
            if which == 'exit':
                print('Exit this shell')
            elif which == 'help':
                print('Show help')
            else:
                print('Unknown command: {}'.format(emph(which)))
            return
        display_subcommand_help(func)


def run_cmd(global_opts, cmd, func, opts, items):
    from .remote_control import do_io
    payload = func(global_opts, opts, items)
    send = {
        'cmd': cmd,
        'version': version,
    }
    if func.no_response and isinstance(payload, types.GeneratorType):
        for item in payload:
            send['payload'] = item
            do_io(global_opts.to, send, func.no_response)
        return
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


def real_main(global_opts):
    readline.read_init_file()
    print_help_for_seq.allow_pager = False

    while True:
        try:
            cmdline = input('🐱 ')
        except EOFError:
            break
        except KeyboardInterrupt:
            continue
        if not cmdline:
            continue
        cmdline = shlex.split(cmdline)
        cmd = cmdline[0].lower()

        try:
            func = cmap[cmd]
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
                continue
            except Exception:
                print_err('Unhandled error:')
                traceback.print_exc()
                continue


def main(global_opts):
    try:
        real_main(global_opts)
    except Exception:
        traceback.print_exc()
        input('Press enter to quit...')
        raise SystemExit(1)
