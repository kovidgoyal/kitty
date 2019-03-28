#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import sys

from .cli import parse_args
from .config import parse_config, parse_send_text_bytes
from .constants import appname
from .fast_data_types import focus_os_window
from .tabs import SpecialWindow
from .utils import natsort_ints


class MatchError(ValueError):

    hide_traceback = True

    def __init__(self, expression, target='windows'):
        ValueError.__init__(self, 'No matching {} for expression: {}'.format(target, expression))


class OpacityError(ValueError):

    hide_traceback = True


class UnknownLayout(ValueError):

    hide_traceback = True


cmap = {}


def cmd(short_desc, desc=None, options_spec=None, no_response=False, argspec='...', string_return_is_error=False, args_count=None):

    def w(func):
        func.short_desc = short_desc
        func.argspec = argspec
        func.desc = desc or short_desc
        func.name = func.__name__[4:].replace('_', '-')
        func.options_spec = options_spec
        func.is_cmd = True
        func.impl = lambda: globals()[func.__name__[4:]]
        func.no_response = no_response
        func.string_return_is_error = string_return_is_error
        func.args_count = 0 if not argspec else args_count
        cmap[func.name] = func
        return func
    return w


MATCH_WINDOW_OPTION = '''\
--match -m
The window to match. Match specifications are of the form:
:italic:`field:regexp`. Where field can be one of: id, title, pid, cwd, cmdline, num, env.
You can use the :italic:`ls` command to get a list of windows. Note that for
numeric fields such as id, pid and num the expression is interpreted as a number,
not a regular expression. The field num refers to the window position in the current tab,
starting from zero and counting clockwise (this is the same as the order in which the
windows are reported by the :italic:`ls` command). The window id of the current window
is available as the KITTY_WINDOW_ID environment variable. When using the :italic:`env` field
to match on environment variables you can specify only the environment variable name or a name
and value, for example, :italic:`env:MY_ENV_VAR=2`
'''
MATCH_TAB_OPTION = '''\
--match -m
The tab to match. Match specifications are of the form:
:italic:`field:regexp`. Where field can be one of: id, title, pid, cwd, env, cmdline.
You can use the :italic:`ls` command to get a list of tabs. Note that for
numeric fields such as id and pid the expression is interpreted as a number,
not a regular expression. When using title or id, first a matching tab is
looked for and if not found a matching window is looked for, and the tab
for that window is used.
'''


# ls {{{
@cmd(
    'List all tabs/windows',
    'List all windows. The list is returned as JSON tree. The top-level is a list of'
    ' operating system {appname} windows. Each OS window has an :italic:`id` and a list'
    ' of :italic:`tabs`. Each tab has its own :italic:`id`, a :italic:`title` and a list of :italic:`windows`.'
    ' Each window has an :italic:`id`, :italic:`title`, :italic:`current working directory`, :italic:`process id (PID)`, '
    ' :italic:`command-line` and :italic:`environment` of the process running in the window.\n\n'
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
    argspec='FONT_SIZE', args_count=1
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
    ' escaping rules. So you can use escapes like :italic:`\\x1b` to send control codes'
    ' and :italic:`\\u21fa` to send unicode characters. If you use the :option:`kitty @ send-text --match` option'
    ' the text will be sent to all matched windows. By default, text is sent to'
    ' only the currently active window.',
    options_spec=MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t') + '''\n
--stdin
type=bool-set
Read the text to be sent from :italic:`stdin`. Note that in this case the text is sent as is,
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
    ret = {'match': opts.match, 'is_binary': False, 'match_tab': opts.match_tab}

    def pipe():
        ret['is_binary'] = True
        if sys.stdin.isatty():
            import select
            fd = sys.stdin.fileno()
            keep_going = True
            while keep_going:
                rd = select.select([fd], [], [])[0]
                if not rd:
                    break
                data = os.read(fd, limit)
                if not data:
                    break  # eof
                data = data.decode('utf-8')
                if '\x04' in data:
                    data = data[:data.index('\x04')]
                    keep_going = False
                ret['text'] = data
                yield ret
        else:
            while True:
                data = sys.stdin.read(limit)
                if not data:
                    break
                ret['text'] = data[:limit]
                yield ret

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
    if payload['match_tab']:
        windows = []
        tabs = tuple(boss.match_tabs(payload['match_tab']))
        if not tabs:
            raise MatchError(payload['match_tab'], 'tabs')
        for tab in tabs:
            windows += tuple(tab)
    data = payload['text'].encode('utf-8') if payload['is_binary'] else parse_send_text_bytes(payload['text'])
    for window in windows:
        if window is not None:
            window.write_to_child(data)
# }}}


# set_window_title {{{
@cmd(
    'Set the window title',
    'Set the title for the specified window(s). If you use the :option:`kitty @ set-window-title --match` option'
    ' the title will be set for all matched windows. By default, only the window'
    ' in which the command is run is affected. If you do not specify a title, the'
    ' last title set by the child process running in the window will be used.',
    options_spec='''
--temporary
type=bool-set
By default, if you use :italic:`set-window-title` the title will be permanently changed
and programs running in the window will not be able to change it again. If you
want to allow other programs to change it afterwards, use this option.
    ''' + '\n\n' + MATCH_WINDOW_OPTION,
    argspec='TITLE ...'
)
def cmd_set_window_title(global_opts, opts, args):
    return {'title': ' '.join(args), 'match': opts.match, 'temporary': opts.temporary}


def set_window_title(boss, window, payload):
    windows = [window or boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    for window in windows:
        if window:
            if payload['temporary']:
                window.override_title = None
                window.title_changed(payload['title'])
            else:
                window.set_title(payload['title'])

# }}}


# set_tab_title {{{
@cmd(
    'Set the tab title',
    'Set the title for the specified tab(s). If you use the :option:`kitty @ set-tab-title --match` option'
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


# goto_layout {{{
@cmd(
    'Set the window layout',
    'Set the window layout in the specified tab (or the active tab if not specified).'
    ' You can use special match value :italic:`all` to set the layout in all tabs.',
    options_spec=MATCH_TAB_OPTION,
    argspec='LAYOUT_NAME'
)
def cmd_goto_layout(global_opts, opts, args):
    try:
        return {'layout': args[0], 'match': opts.match}
    except IndexError:
        raise SystemExit('No layout specified')


def goto_layout(boss, window, payload):
    match = payload['match']
    if match:
        if match == 'all':
            tabs = tuple(boss.all_tabs)
        else:
            tabs = tuple(boss.match_tabs(match))
        if not tabs:
            raise MatchError(match, 'tabs')
    else:
        tabs = [boss.tab_for_window(window) if window else boss.active_tab]
    for tab in tabs:
        if tab:
            try:
                tab.goto_layout(payload['layout'], raise_exception=True)
            except ValueError:
                raise UnknownLayout('The layout {} is unknown or disabled'.format(payload['layout']))
# }}}


# last_used_layout {{{
@cmd(
    'Switch to the last used layout',
    'Switch to the last used window layout in the specified tab (or the active tab if not specified).'
    ' You can use special match value :italic:`all` to set the layout in all tabs.',
    options_spec=MATCH_TAB_OPTION,
)
def cmd_last_used_layout(global_opts, opts, args):
    return {'match': opts.match}


def last_used_layout(boss, window, payload):
    match = payload['match']
    if match:
        if match == 'all':
            tabs = tuple(boss.all_tabs)
        else:
            tabs = tuple(boss.match_tabs(match))
        if not tabs:
            raise MatchError(match, 'tabs')
    else:
        tabs = [boss.tab_for_window(window) if window else boss.active_tab]
    for tab in tabs:
        if tab:
            tab.last_used_layout()
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


# resize_window {{{
@cmd(
    'Resize the specified window',
    'Resize the specified window in the current layout. Note that not all layouts can resize all windows in all directions.',
    options_spec=MATCH_WINDOW_OPTION + '''\n
--increment -i
type=int
default=2
The number of cells to change the size by, can be negative to decrease the size.


--axis -a
type=choices
choices=horizontal,vertical,reset
default=horizontal
The axis along which to resize. If :italic:`horizontal`, it will make the window wider or narrower by the specified increment.
If :italic:`vertical`, it will make the window taller or shorter by the specified increment. The special value :italic:`reset` will
reset the layout to its default configuration.


--self
type=bool-set
If specified resize the window this command is run in, rather than the active window.
''',
    argspec='',
    string_return_is_error=True
)
def cmd_resize_window(global_opts, opts, args):
    return {'match': opts.match, 'increment': opts.increment, 'axis': opts.axis, 'self': opts.self}


def resize_window(boss, window, payload):
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    else:
        windows = [window if window and payload['self'] else boss.active_window]
    resized = False
    if windows and windows[0]:
        resized = boss.resize_layout_window(
            windows[0], increment=payload['increment'], is_horizontal=payload['axis'] == 'horizontal',
            reset=payload['axis'] == 'reset'
        )
    return resized
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
    'Open a new window in the specified tab. If you use the :option:`kitty @ new-window --match` option'
    ' the first matching tab is used. Otherwise the currently active tab is used.'
    ' Prints out the id of the newly opened window (unless :option:`--no-response` is used). Any command line arguments'
    ' are assumed to be the command line used to run in the new window, if none'
    ' are provided, the default shell is run. For example:\n'
    ':italic:`kitty @ new-window --title Email mutt`',
    options_spec=MATCH_TAB_OPTION + '''\n
--title
The title for the new window. By default it will use the title set by the
program running in it.


--cwd
The initial working directory for the new window. Defaults to whatever
the working directory for the kitty process you are talking to is.


--keep-focus
type=bool-set
Keep the current window focused instead of switching to the newly opened window


--window-type
default=kitty
choices=kitty,os
What kind of window to open. A kitty window or a top-level OS window.


--new-tab
type=bool-set
Open a new tab


--tab-title
When using --new-tab set the title of the tab.


--no-response
type=bool-set
default=false
Don't wait for a response giving the id of the newly opened window. Note that
using this option means that you will not be notified of failures and that
the id of the new window will not be printed out.
''',
    argspec='[CMD ...]'
)
def cmd_new_window(global_opts, opts, args):
    if opts.no_response:
        global_opts.no_command_response = True
    return {'match': opts.match, 'title': opts.title, 'cwd': opts.cwd,
            'new_tab': opts.new_tab, 'tab_title': opts.tab_title,
            'window_type': opts.window_type, 'no_response': opts.no_response,
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
        return None if payload['no_response'] else str(wid)

    if payload['window_type'] == 'os':
        boss._new_os_window(w)
        wid = boss.active_window.id
        if payload['keep_focus'] and old_window:
            os_window_id = boss.set_active_window(old_window)
            if os_window_id:
                focus_os_window(os_window_id)
        return None if payload['no_response'] else str(wid)

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
    return None if payload['no_response'] else str(w.id)
# }}}


# focus_window {{{
@cmd(
    'Focus the specified window',
    'Focus the specified window, if no window is specified, focus the window this command is run inside.',
    argspec='',
    options_spec=MATCH_WINDOW_OPTION + '''\n\n
--no-response
type=bool-set
default=false
Don't wait for a response from kitty. This means that even if no matching window is found,
the command will exit with a success code.
'''
)
def cmd_focus_window(global_opts, opts, args):
    if opts.no_response:
        global_opts.no_command_response = True
    return {'match': opts.match, 'no_response': opts.no_response}


def focus_window(boss, window, payload):
    windows = [window or boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    for window in windows:
        if window:
            os_window_id = boss.set_active_window(window)
            if os_window_id:
                focus_os_window(os_window_id, True)
            break
# }}}


# focus_tab {{{
@cmd(
    'Focus the specified tab',
    'The active window in the specified tab will be focused.',
    options_spec=MATCH_TAB_OPTION + '''

--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
''',
    argspec='',
    no_response=True,
)
def cmd_focus_tab(global_opts, opts, args):
    if opts.no_response:
        global_opts.no_command_response = True
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
        ans = window.as_text(as_ansi=bool(payload['ansi']), add_history=payload['extent'] == 'all')
    return ans
# }}}


# set_colors {{{
@cmd(
    'Set terminal colors',
    'Set the terminal colors for the specified windows/tabs (defaults to active window). You can either specify the path to a conf file'
    ' (in the same format as kitty.conf) to read the colors from or you can specify individual colors,'
    ' for example: kitty @ set-colors foreground=red background=white',
    options_spec='''\
--all -a
type=bool-set
By default, colors are only changed for the currently active window. This option will
cause colors to be changed in all windows.


--configured -c
type=bool-set
Also change the configured colors (i.e. the colors kitty will use for new
windows or after a reset).


--reset
type=bool-set
Restore all colors to the values they had at kitty startup. Note that if you specify
this option, any color arguments are ignored and --configured and --all are implied.
''' + '\n\n' + MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t'),
    argspec='COLOR_OR_FILE ...'
)
def cmd_set_colors(global_opts, opts, args):
    from .rgb import color_as_int, Color
    colors, cursor_text_color = {}, False
    if not opts.reset:
        for spec in args:
            if '=' in spec:
                colors.update(parse_config((spec.replace('=', ' '),)))
            else:
                with open(os.path.expanduser(spec), encoding='utf-8', errors='replace') as f:
                    colors.update(parse_config(f))
        cursor_text_color = colors.pop('cursor_text_color', False)
        colors = {k: color_as_int(v) for k, v in colors.items() if isinstance(v, Color)}
    return {
        'title': ' '.join(args), 'match_window': opts.match, 'match_tab': opts.match_tab,
        'all': opts.all or opts.reset, 'configured': opts.configured or opts.reset,
        'colors': colors, 'reset': opts.reset, 'cursor_text_color': cursor_text_color
    }


def set_colors(boss, window, payload):
    from .rgb import color_as_int, Color
    if payload['all']:
        windows = tuple(boss.all_windows)
    else:
        windows = (window or boss.active_window,)
        if payload['match_window']:
            windows = tuple(boss.match_windows(payload['match_window']))
            if not windows:
                raise MatchError(payload['match_window'])
        if payload['match_tab']:
            tabs = tuple(boss.match_tabs(payload['match_tab']))
            if not tabs:
                raise MatchError(payload['match_tab'], 'tabs')
            for tab in tabs:
                windows += tuple(tab)
    if payload['reset']:
        payload['colors'] = {k: color_as_int(v) for k, v in boss.startup_colors.items()}
        payload['cursor_text_color'] = boss.startup_cursor_text_color
    profiles = tuple(w.screen.color_profile for w in windows)
    from .fast_data_types import patch_color_profiles
    cursor_text_color = payload.get('cursor_text_color', False)
    if isinstance(cursor_text_color, (tuple, list, Color)):
        cursor_text_color = color_as_int(Color(*cursor_text_color))
    patch_color_profiles(payload['colors'], cursor_text_color, profiles, payload['configured'])
    boss.patch_colors(payload['colors'], cursor_text_color, payload['configured'])
    default_bg_changed = 'background' in payload['colors']
    for w in windows:
        if default_bg_changed:
            boss.default_bg_changed_for(w.id)
        w.refresh()
# }}}


# get_colors {{{
@cmd(
    'Get terminal colors',
    'Get the terminal colors for the specified window (defaults to active window). Colors will be output to stdout in the same syntax as used for kitty.conf',
    options_spec='''\
--configured -c
type=bool-set
Instead of outputting the colors for the specified window, output the currently
configured colors.

''' + '\n\n' + MATCH_WINDOW_OPTION
)
def cmd_get_colors(global_opts, opts, args):
    return {'configured': opts.configured, 'match': opts.match}


def get_colors(boss, window, payload):
    from .rgb import Color, color_as_sharp, color_from_int
    ans = {k: getattr(boss.opts, k) for k in boss.opts if isinstance(getattr(boss.opts, k), Color)}
    if not payload['configured']:
        windows = (window or boss.active_window,)
        if payload['match']:
            windows = tuple(boss.match_windows(payload['match']))
            if not windows:
                raise MatchError(payload['match'])
        ans.update({k: color_from_int(v) for k, v in windows[0].current_colors.items()})
    all_keys = natsort_ints(ans)
    maxlen = max(map(len, all_keys))
    return '\n'.join(('{:%ds} {}' % maxlen).format(key, color_as_sharp(ans[key])) for key in all_keys)
# }}}


# set_background_opacity {{{
@cmd(
    'Set the background_opacity',
    'Set the background opacity for the specified windows. This will only work if you have turned on'
    ' :opt:`dynamic_background_opacity` in :file:`kitty.conf`. The background opacity affects all kitty windows in a'
    ' single os_window. For example: kitty @ set-background-opacity 0.5',
    options_spec='''\
--all -a
type=bool-set
By default, colors are only changed for the currently active window. This option will
cause colors to be changed in all windows.

''' + '\n\n' + MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t'),
    argspec='OPACITY',
    args_count=1
)
def cmd_set_background_opacity(global_opts, opts, args):
    opacity = max(0.1, min(float(args[0]), 1.0))
    return {
            'opacity': opacity, 'match_window': opts.match,
            'all': opts.all,
    }


def set_background_opacity(boss, window, payload):
    if not boss.opts.dynamic_background_opacity:
        raise OpacityError('You must turn on the dynamic_background_opacity option in kitty.conf to be able to set background opacity')
    if payload['all']:
        windows = tuple(boss.all_windows)
    else:
        windows = (window or boss.active_window,)
        if payload['match_window']:
            windows = tuple(boss.match_windows(payload['match_window']))
            if not windows:
                raise MatchError(payload['match_window'])
    for os_window_id in {w.os_window_id for w in windows}:
        boss._set_os_window_background_opacity(os_window_id, payload['opacity'])
# }}}


# kitten {{{
@cmd(
    'Run a kitten',
    'Run a kitten over the specified window (active window by default).'
    ' The :italic:`kitten_name` can be either the name of a builtin kitten'
    ' or the path to a python file containing a custom kitten. If a relative path'
    ' is used it is searched for in the kitty config directory.',
    options_spec=MATCH_WINDOW_OPTION,
    argspec='kitten_name',
)
def cmd_kitten(global_opts, opts, args):
    if len(args) < 1:
        raise SystemExit('Must specify kitten name')
    return {'match': opts.match, 'args': list(args)[1:], 'kitten': args[0]}


def kitten(boss, window, payload):
    windows = [window or boss.active_window]
    match = payload['match']
    if match:
        windows = tuple(boss.match_windows(match))
        if not windows:
            raise MatchError(match)
    for window in windows:
        if window:
            boss._run_kitten(payload['kitten'], args=tuple(payload['args']), window=window)
            break
# }}}


def cli_params_for(func):
    return (func.options_spec or '\n').format, func.argspec, func.desc, '{} @ {}'.format(appname, func.name)


def parse_subcommand_cli(func, args):
    opts, items = parse_args(args[1:], *cli_params_for(func))
    if func.args_count is not None and func.args_count != len(items):
        if func.args_count == 0:
            raise SystemExit('Unknown extra argument(s) supplied to {}'.format(func.name))
        raise SystemExit('Must specify exactly {} argument(s) for {}'.format(func.args_count, func.name))
    return opts, items


def display_subcommand_help(func):
    try:
        parse_args(['--help'], (func.options_spec or '\n').format, func.argspec, func.desc, func.name)
    except SystemExit:
        pass
