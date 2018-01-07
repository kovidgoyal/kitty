#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import re
import sys
from functools import partial

from kitty.cli import emph, parse_args
from kitty.constants import appname, version
from kitty.utils import read_with_timeout


def cmd(short_desc, desc=None, options_spec=None):

    def w(func):
        func.short_desc = short_desc
        func.desc = desc or short_desc
        func.name = func.__name__[4:]
        func.options_spec = options_spec
        return func
    return w


def parse_subcommand_cli(func, args):
    opts, items = parse_args(args[1:], func.options_spec or '\n'.format, '...', func.desc, '{} @ {}'.format(appname, func.name))
    return opts, items


@cmd(
    'List all tabs/windows'
)
def cmd_ls(global_opts, opts, args):
    pass


def ls(boss, window):
    raise NotImplementedError()


def handle_cmd(boss, window, cmd):
    cmd = json.loads(cmd)
    v = cmd['version']
    if tuple(v)[:2] > version[:2]:
        return {'ok': False, 'error': 'The kitty client you are using to send remote commands is newer than this kitty instance. This is not supported.'}
    func = partial(globals()[cmd['cmd']], boss, window)
    payload = cmd.get('payload')
    ans = func(payload) if payload is not None else func()
    response = {'ok': True}
    if ans is not None:
        response['data'] = ans
    return response


global_options_spec = partial('''\

'''.format, appname=appname)


def read_from_stdin(send):
    send = ('@kitty-cmd' + json.dumps(send)).encode('ascii')
    if not sys.stdout.isatty():
        raise SystemExit('stdout is not a terminal')
    sys.stdout.buffer.write(b'\x1bP' + send + b'\x1b\\')
    sys.stdout.flush()

    received = b''
    dcs = re.compile(br'\x1bP@kitty-cmd([^\x1b]+)\x1b\\')
    match = None

    def more_needed(data):
        nonlocal received, match
        received += data
        match = dcs.search(received)
        return match is None

    read_with_timeout(more_needed)
    if match is None:
        raise SystemExit('Failed to receive response from ' + appname)
    response = json.loads(match.group(1).decode('ascii'))
    return response


def main(args):
    cmap = {k[4:]: v for k, v in globals().items() if k.startswith('cmd_')}
    all_commands = tuple(sorted(cmap))
    cmds = ('  |G {}|\n    {}'.format(cmap[c].name, cmap[c].short_desc) for c in all_commands)
    msg = (
        'Control {appname} by sending it commands. Add'
        ' |_ allow_remote_control yes| to kitty.conf for this'
        ' to work.\n\n|T Commands|:\n{cmds}\n\n'
        'You can get help for each individual command by using:\n'
        '{appname} @ |_ command| -h'
    ).format(appname=appname, cmds='\n'.join(cmds))

    global_opts, items = parse_args(args[1:], global_options_spec, 'command ...', msg, '{} @'.format(appname))

    if not items:
        raise SystemExit('You must specify a command')
    cmd = items[0]
    try:
        func = cmap[cmd]
    except KeyError:
        raise SystemExit('{} is not a known command. Known commands are: {}'.format(
            emph(cmd), ', '.join(all_commands)))
    opts, items = parse_subcommand_cli(func, items)
    payload = func(global_opts, opts, items)
    send = {
        'cmd': cmd,
        'version': version,
    }
    if payload is not None:
        send['payload'] = payload
    response = read_from_stdin(send)
    if not response.get('ok'):
        if response.get('tb'):
            print(response['tb'], file=sys.stderr)
        raise SystemExit(response['error'])
    if 'data' in response:
        print(response['data'])
