#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import re
import sys
from functools import partial

from .cli import emph, parse_args
from .config import parse_send_text_bytes
from .constants import appname, version
from .utils import read_with_timeout


def cmd(short_desc, desc=None, options_spec=None, no_response=False):

    def w(func):
        func.short_desc = short_desc
        func.desc = desc or short_desc
        func.name = func.__name__[4:].replace('_', '-')
        func.options_spec = options_spec
        func.is_cmd = True
        func.impl = lambda: globals()[func.__name__[4:]]
        func.no_response = no_response
        return func
    return w


def parse_subcommand_cli(func, args):
    opts, items = parse_args(args[1:], (func.options_spec or '\n').format, '...', func.desc, '{} @ {}'.format(appname, func.name))
    return opts, items


@cmd(
    'List all tabs/windows',
    'List all windows. The list is returned as JSON tree. The top-level is a list of'
    ' operating system {appname} windows. Each OS window has an |_ id| and a list'
    ' of |_ tabs|. Each tab has its own |_ id|, a |_ title| and a list of |_ windows|.'
    ' Each window has an |_ id|, |_ title|, |_ current working directory|, |_ process id (PID)| and'
    ' |_ command-line| of the process running in the window.\n\n'
    'You can use these criteria to select windows/tabs for the other commands.'.format(appname=appname)
)
def cmd_ls(global_opts, opts, args):
    pass


def ls(boss, window):
    data = list(boss.list_os_windows())
    data = json.dumps(data, indent=2, sort_keys=True)
    return data


MATCH_WINDOW_OPTION = '''\
--match
The window to match. Match specifications are of the form:
|_ field:regexp|. Where field can be one of: id, title, pid, cwd, cmdline.
You can use the |_ ls| command to get a list of windows. Note that for
numeric fields such as id and pid the expression is interpreted as a number,
not a regular expression.
'''


@cmd(
    'Send arbitrary text to specified windows',
    'Send arbitrary text to specified windows. The text follows Python'
    ' escaping rules. So you can use escapes like |_ \\x1b| to send control codes'
    ' and |_ \\u21fa| to send unicode characters. If you use the |_ --match| option'
    ' the text will be sent to all matched windows. By default, text is sent to'
    ' only the currently active window.',
    options_spec=MATCH_WINDOW_OPTION,
    no_response=True
)
def cmd_send_text(global_opts, opts, args):
    return {'text': ' '.join(args), 'match': opts.match}


def send_text(boss, window, payload):
    windows = [boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
    for window in windows:
        if window is not None:
            window.write_to_child(parse_send_text_bytes(payload['text']))


@cmd(
    'Set the window title',
    'Set the title for the specified window(s). If you use the |_ --match| option'
    ' the title will be set for all matched windows. By default, only the window'
    ' in which the command is run is affected. If you do not specify a title, the'
    ' last title set by the child process running in the window will be used.',
    options_spec=MATCH_WINDOW_OPTION
)
def cmd_set_window_title(global_opts, opts, args):
    return {'title': ' '.join(args), 'match': opts.match}


def set_window_title(boss, window, payload):
    windows = [window or boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise ValueError('No matching windows for expression: {}'.format(match))
    for window in windows:
        if window:
            window.set_title(payload['title'])


cmap = {v.name: v for v in globals().values() if hasattr(v, 'is_cmd')}


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

'''.format, appname=appname)


def read_from_stdin(send, no_response):
    send = ('@kitty-cmd' + json.dumps(send)).encode('ascii')
    if not sys.stdout.isatty():
        raise SystemExit('stdout is not a terminal')
    sys.stdout.buffer.write(b'\x1bP' + send + b'\x1b\\')
    sys.stdout.flush()
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

    read_with_timeout(more_needed)
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
    response = read_from_stdin(send, func.no_response)
    if not response.get('ok'):
        if response.get('tb'):
            print(response['tb'], file=sys.stderr)
        raise SystemExit(response['error'])
    if 'data' in response:
        print(response['data'])
