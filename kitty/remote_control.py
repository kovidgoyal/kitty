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
from .config import parse_send_text_bytes
from .constants import appname, version
from .tabs import SpecialWindow
from .utils import non_blocking_read, parse_address_spec, read_with_timeout


class MatchError(ValueError):

    hide_traceback = True

    def __init__(self, expression, target='windows'):
        ValueError.__init__(self, 'No matching {} for expression: {}'.format(target, expression))


def cmd(short_desc, desc=None, options_spec=None, no_response=False, argspec='...'):

    def w(func):
        func.short_desc = short_desc
        func.argspec = argspec
        func.desc = desc or short_desc
        func.name = func.__name__[4:].replace('_', '-')
        func.options_spec = options_spec
        func.is_cmd = True
        func.impl = lambda: globals()[func.__name__[4:]]
        func.no_response = no_response
        return func
    return w


def parse_subcommand_cli(func, args):
    opts, items = parse_args(args[1:], (func.options_spec or '\n').format, func.argspec, func.desc, '{} @ {}'.format(appname, func.name))
    return opts, items


MATCH_WINDOW_OPTION = '''\
--match -m
The window to match. Match specifications are of the form:
|_ field:regexp|. Where field can be one of: id, title, pid, cwd, cmdline.
You can use the |_ ls| command to get a list of windows. Note that for
numeric fields such as id and pid the expression is interpreted as a number,
not a regular expression.
'''
MATCH_TAB_OPTION = '''\
--match -m
The tab to match. Match specifications are of the form:
|_ field:regexp|. Where field can be one of: id, title, pid, cwd, cmdline.
You can use the |_ ls| command to get a list of tabs. Note that for
numeric fields such as id and pid the expression is interpreted as a number,
not a regular expression. When using title or id, first a matching tab is
looked for and if not found a matching window is looked for, and the tab
for that window is used.
'''


# ls {{{
@cmd(
    'List all tabs/windows',
    'List all windows. The list is returned as JSON tree. The top-level is a list of'
    ' operating system {appname} windows. Each OS window has an |_ id| and a list'
    ' of |_ tabs|. Each tab has its own |_ id|, a |_ title| and a list of |_ windows|.'
    ' Each window has an |_ id|, |_ title|, |_ current working directory|, |_ process id (PID)| and'
    ' |_ command-line| of the process running in the window.\n\n'
    'You can use these criteria to select windows/tabs for the other commands.'.format(appname=appname),
    argspec=''
)
def cmd_ls(global_opts, opts, args):
    pass


def ls(boss, window):
    data = list(boss.list_os_windows())
    data = json.dumps(data, indent=2, sort_keys=True)
    return data
# }}}


# set_font_size {{{
@cmd(
    'Set the font size in all windows',
    'Sets the font size to the specified size, in pts.',
    argspec='FONT_SIZE'
)
def cmd_set_font_size(global_opts, opts, args):
    try:
        return {'size': float(args[0])}
    except IndexError:
        raise SystemExit('No font size specified')


def set_font_size(boss, window, payload):
    boss.set_font_size(payload['size'])
# }}}


# send_text {{{
@cmd(
    'Send arbitrary text to specified windows',
    'Send arbitrary text to specified windows. The text follows Python'
    ' escaping rules. So you can use escapes like |_ \\x1b| to send control codes'
    ' and |_ \\u21fa| to send unicode characters. If you use the |_ --match| option'
    ' the text will be sent to all matched windows. By default, text is sent to'
    ' only the currently active window.',
    options_spec=MATCH_WINDOW_OPTION + '''\n
--stdin
type=bool-set
Read the text to be sent from |_ stdin|. Note that in this case the text is sent as is,
not interpreted for escapes. If stdin is a terminal, you can press Ctrl-D to end reading.


--from-file
Path to a file whose contents you wish to send. Note that in this case the file contents
are sent as is, not interpreted for escapes.
''',
    no_response=True,
    argspec='[TEXT TO SEND]'
)
def cmd_send_text(global_opts, opts, args):
    limit = 1024
    ret = {'match': opts.match, 'is_binary': False}

    def pipe(src=sys.stdin):
        ret['is_binary'] = True
        import select
        with non_blocking_read() as fd:
            keep_going = True
            while keep_going:
                rd = select.select([fd], [], [])
                if rd:
                    data = sys.stdin.buffer.read()
                    if not data:
                        break
                    data = data.decode('utf-8')
                    if '\x04' in data:
                        data = data[:data.index('\x04')]
                        keep_going = False
                    while data:
                        ret['text'] = data[:limit]
                        yield ret
                        data = data[limit:]
                else:
                    break

    def chunks(text):
        ret['is_binary'] = False
        while text:
            ret['text'] = text[:limit]
            yield ret
            text = text[limit:]

    def file_pipe(path):
        ret['is_binary'] = True
        with open(path, encoding='utf-8') as f:
            while True:
                data = f.read(limit)
                if not data:
                    break
                ret['text'] = data
                yield ret

    sources = []
    if opts.stdin:
        sources.append(pipe())

    if opts.from_file:
        sources.append(file_pipe(opts.from_file))

    text = ' '.join(args)
    sources.append(chunks(text))

    def chain():
        for src in sources:
            yield from src
    return chain()


def send_text(boss, window, payload):
    windows = [boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
    data = payload['text'].encode('utf-8') if payload['is_binary'] else parse_send_text_bytes(payload['text'])
    for window in windows:
        if window is not None:
            window.write_to_child(data)
# }}}


# set_window_title {{{
@cmd(
    'Set the window title',
    'Set the title for the specified window(s). If you use the |_ --match| option'
    ' the title will be set for all matched windows. By default, only the window'
    ' in which the command is run is affected. If you do not specify a title, the'
    ' last title set by the child process running in the window will be used.',
    options_spec=MATCH_WINDOW_OPTION,
    argspec='TITLE ...'
)
def cmd_set_window_title(global_opts, opts, args):
    return {'title': ' '.join(args), 'match': opts.match}


def set_window_title(boss, window, payload):
    windows = [window or boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    for window in windows:
        if window:
            window.set_title(payload['title'])
# }}}


# set_tab_title {{{
@cmd(
    'Set the tab title',
    'Set the title for the specified tab(s). If you use the |_ --match| option'
    ' the title will be set for all matched tabs. By default, only the tab'
    ' in which the command is run is affected. If you do not specify a title, the'
    ' title of the currently active window in the tab is used.',
    options_spec=MATCH_TAB_OPTION,
    argspec='TITLE ...'
)
def cmd_set_tab_title(global_opts, opts, args):
    return {'title': ' '.join(args), 'match': opts.match}


def set_tab_title(boss, window, payload):
    match = payload['match']
    if match:
        tabs = tuple(boss.match_tabs(match))
        if not tabs:
            raise MatchError(match, 'tabs')
    else:
        tabs = [boss.tab_for_window(window) if window else boss.active_tab]
    for tab in tabs:
        if tab:
            tab.set_title(payload['title'])
# }}}


# close_window {{{
@cmd(
    'Close the specified window(s)',
    options_spec=MATCH_WINDOW_OPTION + '''\n
--self
type=bool-set
If specified close the window this command is run in, rather than the active window.
''',
    argspec=''
)
def cmd_close_window(global_opts, opts, args):
    return {'match': opts.match, 'self': opts.self}


def close_window(boss, window, payload):
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    else:
        windows = [window if window and payload['self'] else boss.active_window]
    for window in windows:
        if window:
            boss.close_window(window)
# }}}


# close_tab {{{
@cmd(
    'Close the specified tab(s)',
    options_spec=MATCH_TAB_OPTION + '''\n
--self
type=bool-set
If specified close the tab this command is run in, rather than the active tab.
''',
    argspec=''
)
def cmd_close_tab(global_opts, opts, args):
    return {'match': opts.match, 'self': opts.self}


def close_tab(boss, window, payload):
    match = payload['match']
    if match:
        tabs = tuple(boss.match_tabs(match))
        if not tabs:
            raise MatchError(match, 'tabs')
    else:
        tabs = [boss.tab_for_window(window) if window and payload['self'] else boss.active_tab]
    for tab in tabs:
        if window:
            if tab:
                boss.close_tab(tab)
# }}}


# new_window {{{
@cmd(
    'Open new window',
    'Open a new window in the specified tab. If you use the |_ --match| option'
    ' the first matching tab is used. Otherwise the currently active tab is used.'
    ' Prints out the id of the newly opened window. Any command line arguments'
    ' are assumed to be the command line used to run in the new window, if none'
    ' are provided, the default shell is run. For example:\n'
    '|_ kitty @ new-window --title Email mutt|',
    options_spec=MATCH_TAB_OPTION + '''\n
--title
The title for the new window. By default it will use the title set by the
program running in it.


--cwd
The initial working directory for the new window.


--keep-focus
type=bool-set
Keep the current window focused instead of switching to the newly opened window


--new-tab
type=bool-set
Open a new tab


--tab-title
When using --new-tab set the title of the tab.
''',
    argspec='[CMD ...]'
)
def cmd_new_window(global_opts, opts, args):
    return {'match': opts.match, 'title': opts.title, 'cwd': opts.cwd,
            'new_tab': opts.new_tab, 'tab_title': opts.tab_title,
            'keep_focus': opts.keep_focus, 'args': args or []}


def new_window(boss, window, payload):
    w = SpecialWindow(cmd=payload['args'] or None, override_title=payload['title'], cwd=payload['cwd'])
    old_window = boss.active_window
    if payload['new_tab']:
        boss._new_tab(w)
        tab = boss.active_tab
        if payload['tab_title']:
            tab.set_title(payload['tab_title'])
        wid = boss.active_window.id
        if payload['keep_focus'] and old_window:
            boss.set_active_window(old_window)
        return str(wid)

    match = payload['match']
    if match:
        tabs = tuple(boss.match_tabs(match))
        if not tabs:
            raise MatchError(match, 'tabs')
    else:
        tabs = [boss.active_tab]
    tab = tabs[0]
    w = tab.new_special_window(w)
    if payload['keep_focus'] and old_window:
        boss.set_active_window(old_window)
    return str(w.id)
# }}}


# focus_window {{{
@cmd(
    'Focus the specified window',
    options_spec=MATCH_WINDOW_OPTION,
    argspec='',
)
def cmd_focus_window(global_opts, opts, args):
    return {'match': opts.match}


def focus_window(boss, window, payload):
    windows = [window or boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    for window in windows:
        if window:
            boss.set_active_window(window)
            break
# }}}


# focus_tab {{{
@cmd(
    'Focus the specified tab',
    'The active window in the specified tab will be focused.',
    options_spec=MATCH_TAB_OPTION,
    argspec='',
)
def cmd_focus_tab(global_opts, opts, args):
    return {'match': opts.match}


def focus_tab(boss, window, payload):
    match = payload['match']
    tabs = tuple(boss.match_tabs(match))
    if not tabs:
        raise MatchError(match, 'tabs')
    tab = tabs[0]
    boss.set_active_tab(tab)
# }}}


# get_text {{{
@cmd(
    'Get text from the specified window',
    options_spec=MATCH_WINDOW_OPTION + '''\n
--extent
default=screen
choices=screen, all, selection
What text to get. The default of screen means all text currently on the screen. all means
all the screen+scrollback and selection means currently selected text.


--ansi
type=bool-set
By default, only plain text is returned. If you specify this flag, the text will
include the formatting escape codes for colors/bold/italic/etc. Note that when
getting the current selection, the result is always plain text.


--self
type=bool-set
If specified get text from the window this command is run in, rather than the active window.
''',
    argspec=''
)
def cmd_get_text(global_opts, opts, args):
    return {'match': opts.match, 'extent': opts.extent, 'ansi': opts.ansi, 'self': opts.self}


def get_text(boss, window, payload):
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    else:
        windows = [window if window and payload['self'] else boss.active_window]
    window = windows[0]
    if payload['extent'] == 'selection':
        ans = window.text_for_selection()
    else:
        ans = window.as_text(as_ansi=bool(payload['ansi']), add_history=True)
    return ans
# }}}


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
