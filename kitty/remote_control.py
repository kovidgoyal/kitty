#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import re
import socket
import sys
import types
from functools import partial

from .cli import emph, parse_args
from .constants import appname, version
from .utils import parse_address_spec, read_with_timeout
from .cmds import cmap, parse_subcommand_cli


def handle_cmd(boss, window, cmd):
    cmd = json.loads(cmd)
    v = cmd['version']
    if tuple(v)[:2] > version[:2]:
        return {'ok': False, 'error': 'The kitty client you are using to send remote commands is newer than this kitty instance. This is not supported.'}
    c = cmap[cmd['cmd']]
    func = partial(c.impl(), boss, window)
    payload = cmd.get('payload')
    ans = func() if payload is None else func(payload)
    response = {'ok': True}
    if ans is not None:
        response['data'] = ans
    if not c.no_response:
        return response


global_options_spec = partial('''\
--to
An address for the kitty instance to control. Corresponds to the address
given to the kitty instance via the --listen-on option. If not specified,
messages are sent to the controlling terminal for this process, i.e. they
will only work if this process is run within an existing kitty window.
'''.format, appname=appname)


def do_io(to, send, no_response):
    send = ('@kitty-cmd' + json.dumps(send)).encode('ascii')
    send = b'\x1bP' + send + b'\x1b\\'
    if to:
        family, address = parse_address_spec(to)[:2]
        s = socket.socket(family)
        s.connect(address)
        out = s.makefile('wb')
    else:
        out = open('/dev/tty', 'wb')
    with out:
        out.write(send)
    if to:
        s.shutdown(socket.SHUT_WR)
    if no_response:
        return {'ok': True}

    received = b''
    dcs = re.compile(br'\x1bP@kitty-cmd([^\x1b]+)\x1b\\')
    match = None

    def more_needed(data):
        nonlocal received, match
        received += data
        match = dcs.search(received)
        return match is None

    if to:
        src = s.makefile('rb')
    else:
        src = open('/dev/tty', 'rb')
    with src:
        read_with_timeout(more_needed, src=src)
    if match is None:
        raise SystemExit('Failed to receive response from ' + appname)
    response = json.loads(match.group(1).decode('ascii'))
    return response


def main(args):
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
        from kitty.shell import main
        main(global_opts)
        return
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
            print(response['tb'], file=sys.stderr)
        raise SystemExit(response['error'])
    if 'data' in response:
        print(response['data'])
