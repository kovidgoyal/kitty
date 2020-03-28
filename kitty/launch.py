#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .boss import Boss
from .child import Child
from .cli import parse_args
from .cli_stub import LaunchCLIOptions
from .constants import resolve_custom_file
from .fast_data_types import set_clipboard_string
from .tabs import Tab
from .utils import set_primary_selection
from .window import Watchers, Window

try:
    from typing import TypedDict
except ImportError:
    TypedDict = Dict[str, Any]


@lru_cache(maxsize=2)
def options_spec() -> str:
    return '''
--window-title --title
The title to set for the new window. By default, title is controlled by the
child process.


--tab-title
The title for the new tab if launching in a new tab. By default, the title
of the active window in the tab is used as the tab title.


--type
type=choices
default=window
choices=window,tab,os-window,overlay,background,clipboard,primary
Where to launch the child process, in a new kitty window in the current tab,
a new tab, or a new OS window or an overlay over the current window.
Note that if the current window already has an overlay, then it will
open a new window. The value of none means the process will be
run in the background. The values clipboard and primary are meant
to work with :option:`launch --stdin-source` to copy data to the system
clipboard or primary selection.


--keep-focus
type=bool-set
Keep the focus on the currently active window instead of switching
to the newly opened window.


--cwd
The working directory for the newly launched child. Use the special value
:code:`current` to use the working directory of the currently active window.


--env
type=list
Environment variables to set in the child process. Can be specified multiple
times to set different environment variables.
Syntax: :italic:`name=value`.


--copy-colors
type=bool-set
Set the colors of the newly created window to be the same as the colors in the
currently active window.


--copy-cmdline
type=bool-set
Ignore any specified command line and instead use the command line from the
currently active window.


--copy-env
type=bool-set
Copy the environment variables from the currently active window into the
newly launched child process.


--location
type=choices
default=last
choices=first,after,before,neighbor,last,vsplit,hsplit
Where to place the newly created window when it is added to a tab which
already has existing windows in it. :code:`after` and :code:`before` place the new
window before or after the active window. :code:`neighbor` is a synonym for :code:`after`.
Also applies to creating a new tab, where the value of :code:`after`
will cause the new tab to be placed next to the current tab instead of at the end.
The values of :code:`vsplit` and :code:`hsplit` are only used by the :code:`splits`
layout and control if the new window is placed in a vertical or horizontal split
with the currently active window.


--allow-remote-control
type=bool-set
Programs running in this window can control kitty (if remote control is
enabled). Note that any program with the right level of permissions can still
write to the pipes of any other program on the same computer and therefore can
control kitty. It can, however, be useful to block programs running on other
computers (for example, over ssh) or as other users.


--stdin-source
type=choices
default=none
choices=none,@selection,@screen,@screen_scrollback,@alternate,@alternate_scrollback
Pass the screen contents as :code:`STDIN` to the child process. @selection is
the currently selected text. @screen is the contents of the currently active
window. @screen_scrollback is the same as @screen, but includes the scrollback
buffer as well. @alternate is the secondary screen of the current active
window. For example if you run a full screen terminal application, the
secondary screen will be the screen you return to when quitting the
application.


--stdin-add-formatting
type=bool-set
When using :option:`launch --stdin-source` add formatting escape codes, without this
only plain text will be sent.


--stdin-add-line-wrap-markers
type=bool-set
When using :option:`launch --stdin-source` add a carriage return at every line wrap
location (where long lines are wrapped at screen edges). This is useful if you
want to pipe to program that wants to duplicate the screen layout of the
screen.


--marker
Create a marker that highlights text in the newly created window. The syntax is
the same as for the :code:`toggle_marker` map action (see :doc:`/marks`).


--os-window-class
Set the WM_CLASS property on X11 and the application id property on Wayland for
the newly created OS Window when using :option:`launch --type`=os-window.
Defaults to whatever is used by the parent kitty process, which in turn
defaults to :code:`kitty`.


--os-window-name
Set the WM_NAME property on X11 for the newly created OS Window when using
:option:`launch --type`=os-window. Defaults to :option:`launch --os-window-class`.


--watcher -w
type=list
Path to a python file. Appropriately named functions in this file will be called
for various events, such as when the window is resized or closed. See the section
on watchers in the launch command documentation :doc:`launch`. Relative paths are
resolved relative to the kitty config directory.
'''


def parse_launch_args(args: Optional[Sequence[str]] = None) -> Tuple[LaunchCLIOptions, List[str]]:
    args = list(args or ())
    try:
        opts, args = parse_args(result_class=LaunchCLIOptions, args=args, ospec=options_spec)
    except SystemExit as e:
        raise ValueError from e
    return opts, args


def get_env(opts: LaunchCLIOptions, active_child: Child) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if opts.copy_env and active_child:
        env.update(active_child.foreground_environ)
    for x in opts.env:
        parts = x.split('=', 1)
        if len(parts) == 2:
            env[parts[0]] = parts[1]
    return env


def tab_for_window(boss: Boss, opts: LaunchCLIOptions, target_tab: Optional[Tab] = None) -> Optional[Tab]:
    if opts.type == 'tab':
        tm = boss.active_tab_manager
        if tm:
            tab: Optional[Tab] = tm.new_tab(empty_tab=True, location=opts.location)
            if opts.tab_title and tab is not None:
                tab.set_title(opts.tab_title)
        else:
            tab = None
    elif opts.type == 'os-window':
        oswid = boss.add_os_window(wclass=opts.os_window_class, wname=opts.os_window_name)
        tm = boss.os_window_map[oswid]
        tab = tm.new_tab(empty_tab=True)
        if opts.tab_title and tab is not None:
            tab.set_title(opts.tab_title)
    else:
        tab = target_tab or boss.active_tab

    return tab


def load_watch_modules(opts: LaunchCLIOptions) -> Optional[Watchers]:
    if not opts.watcher:
        return None
    import runpy
    ans = Watchers()
    for path in opts.watcher:
        path = resolve_custom_file(path)
        m = runpy.run_path(path, run_name='__kitty_watcher__')
        w = m.get('on_close')
        if callable(w):
            ans.on_close.append(w)
        w = m.get('on_resize')
        if callable(w):
            ans.on_resize.append(w)
    return ans


class LaunchKwds(TypedDict):

    allow_remote_control: bool
    cwd_from: Optional[int]
    cwd: Optional[str]
    location: Optional[str]
    override_title: Optional[str]
    copy_colors_from: Optional[Window]
    marker: Optional[str]
    cmd: Optional[List[str]]
    overlay_for: Optional[int]
    stdin: Optional[bytes]


def launch(boss: Boss, opts: LaunchCLIOptions, args: List[str], target_tab: Optional[Tab] = None) -> Optional[Window]:
    active = boss.active_window_for_cwd
    active_child = getattr(active, 'child', None)
    env = get_env(opts, active_child)
    kw: LaunchKwds = {
        'allow_remote_control': opts.allow_remote_control,
        'cwd_from': None,
        'cwd': None,
        'location': None,
        'override_title': opts.window_title or None,
        'copy_colors_from': None,
        'marker': opts.marker or None,
        'cmd': None,
        'overlay_for': None,
        'stdin': None
    }
    if opts.cwd:
        if opts.cwd == 'current':
            if active_child:
                kw['cwd_from'] = active_child.pid_for_cwd
        else:
            kw['cwd'] = opts.cwd
    if opts.location != 'last':
        kw['location'] = opts.location
    if opts.copy_colors and active:
        kw['copy_colors_from'] = active
    cmd = args or None
    if opts.copy_cmdline and active_child:
        cmd = active_child.foreground_cmdline
    if cmd:
        final_cmd: List[str] = []
        for x in cmd:
            if active and not opts.copy_cmdline:
                if x == '@selection':
                    s = boss.data_for_at(which=x, window=active)
                    if s:
                        x = s
                elif x == '@active-kitty-window-id':
                    x = str(active.id)
            final_cmd.append(x)
        kw['cmd'] = final_cmd
    if opts.type == 'overlay' and active and not active.overlay_window_id:
        kw['overlay_for'] = active.id
    if opts.stdin_source and opts.stdin_source != 'none':
        q = opts.stdin_source
        if opts.stdin_add_line_wrap_markers:
            q += '_wrap'
        penv, stdin = boss.process_stdin_source(window=active, stdin=q)
        if stdin:
            kw['stdin'] = stdin
            if penv:
                env.update(penv)

    if opts.type == 'background':
        cmd = kw['cmd']
        if not cmd:
            raise ValueError('The cmd to run must be specified when running a background process')
        boss.run_background_process(cmd, cwd=kw['cwd'], cwd_from=kw['cwd_from'], env=env or None, stdin=kw['stdin'])
    elif opts.type in ('clipboard', 'primary'):
        stdin = kw.get('stdin')
        if stdin is not None:
            if opts.type == 'clipboard':
                set_clipboard_string(stdin)
            else:
                set_primary_selection(stdin)
    else:
        tab = tab_for_window(boss, opts, target_tab)
        if tab is not None:
            watchers = load_watch_modules(opts)
            new_window: Window = tab.new_window(env=env or None, watchers=watchers or None, **kw)
            if opts.keep_focus and active:
                boss.set_active_window(active, switch_os_window_if_needed=True)
            return new_window
    return None
