#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import re
import sys
import types
from functools import partial

from .cli import emph, parse_args
from .cmds import cmap, parse_subcommand_cli
from .constants import appname, version
from .fast_data_types import read_command_response
from .utils import TTYIO, parse_address_spec


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
given to the kitty instance via the :option:`kitty --listen-on` option. If not specified,
messages are sent to the controlling terminal for this process, i.e. they
will only work if this process is run within an existing kitty window.
'''.format, appname=appname)


def encode_send(send):
    send = ('@kitty-cmd' + json.dumps(send)).encode('ascii')
    return b'\x1bP' + send + b'\x1b\\'


class SocketIO:

    def __init__(self, to):
        self.family, self.address = parse_address_spec(to)[:2]

    def __enter__(self):
        import socket
        self.socket = socket.socket(self.family)
        self.socket.setblocking(True)
        self.socket.connect(self.address)

    def __exit__(self, *a):
        import socket
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except EnvironmentError:
            pass  # on some OSes such as macOS the socket is already closed at this point
        self.socket.close()

    def send(self, data):
        import socket
        with self.socket.makefile('wb') as out:
            if isinstance(data, bytes):
                out.write(data)
            else:
                for chunk in data:
                    if isinstance(chunk, str):
                        chunk = chunk.encode('utf-8')
                    out.write(chunk)
                    out.flush()
        self.socket.shutdown(socket.SHUT_WR)

    def recv(self, timeout):
        dcs = re.compile(br'\x1bP@kitty-cmd([^\x1b]+)\x1b\\')
        self.socket.settimeout(timeout)
        with self.socket.makefile('rb') as src:
            data = src.read()
        m = dcs.search(data)
        if m is None:
            raise TimeoutError('Timed out while waiting to read cmd response')
        return m.group(1)


class RCIO(TTYIO):

    def recv(self, timeout):
        ans = []
        read_command_response(self.tty_fd, timeout, ans)
        return b''.join(ans)


def do_io(to, send, no_response):
    payload = send.get('payload')
    if not isinstance(payload, types.GeneratorType):
        send_data = encode_send(send)
    else:
        def send_generator():
            for chunk in payload:
                send['payload'] = chunk
                yield encode_send(send)
        send_data = send_generator()

    io = SocketIO(to) if to else RCIO()
    with io:
        io.send(send_data)
        if no_response:
            return {'ok': True}
        received = io.recv(timeout=10)

    response = json.loads(received.decode('ascii'))
    return response


all_commands = tuple(sorted(cmap))
cli_msg = (
        'Control {appname} by sending it commands. Set the'
        ' :opt:`allow_remote_control` option to yes in :file:`kitty.conf` for this'
        ' to work.'
).format(appname=appname)


def parse_rc_args(args):
    cmds = ('  :green:`{}`\n    {}'.format(cmap[c].name, cmap[c].short_desc) for c in all_commands)
    msg = cli_msg + (
            '\n\n:title:`Commands`:\n{cmds}\n\n'
            'You can get help for each individual command by using:\n'
            '{appname} @ :italic:`command` -h').format(appname=appname, cmds='\n'.join(cmds))
    return parse_args(args[1:], global_options_spec, 'command ...', msg, '{} @'.format(appname))


def main(args):
    global_opts, items = parse_rc_args(args)

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
    if payload is not None:
        send['payload'] = payload
    response = do_io(global_opts.to, send, func.no_response)
    if not response.get('ok'):
        if response.get('tb'):
            print(response['tb'], file=sys.stderr)
        raise SystemExit(response['error'])
    data = response.get('data')
    if data is not None:
        if func.string_return_is_error and isinstance(data, str):
            raise SystemExit(data)
        print(data)
