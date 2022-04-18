#!/usr/bin/env python
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


import os
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence

from .boss import Boss
from .child import Child
from .cli import parse_args
from .cli_stub import LaunchCLIOptions
from .constants import kitty_exe, shell_path
from .fast_data_types import (
    get_boss, get_options, get_os_window_title, patch_color_profiles,
    set_clipboard_string
)
from .options.utils import env as parse_env
from .tabs import Tab, TabManager
from .types import run_once
from .utils import log_error, resolve_custom_file, set_primary_selection, which
from .window import CwdRequest, CwdRequestType, Watchers, Window

try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


class LaunchSpec(NamedTuple):
    opts: LaunchCLIOptions
    args: List[str]


@run_once
def options_spec() -> str:
    return '''
--window-title --title
The title to set for the new window. By default, title is controlled by the
child process. The special value :code:`current` will copy the title from the currently
active window.


--tab-title
The title for the new tab if launching in a new tab. By default, the title
of the active window in the tab is used as the tab title. The special value
:code:`current` will copy the title form the title of the currently active tab.


--type
type=choices
default=window
choices=window,tab,os-window,overlay,background,clipboard,primary
Where to launch the child process, in a new kitty window in the current tab,
a new tab, or a new OS window or an overlay over the current window.
Note that if the current window already has an overlay, then it will
open a new window. The value of background means the process will be
run in the background. The values clipboard and primary are meant
to work with :option:`launch --stdin-source` to copy data to the system
clipboard or primary selection.


--keep-focus --dont-take-focus
type=bool-set
Keep the focus on the currently active window instead of switching
to the newly opened window.


--cwd
The working directory for the newly launched child. Use the special value
:code:`current` to use the working directory of the currently active window.
The special value :code:`last_reported` uses the last working directory
reported by the shell (needs :ref:`shell_integration` to work). The special
value :code:`oldest` works like :code:`current` but uses the working directory
of the oldest foreground process associated with the currently active window
rather than the newest foreground process.


--env
type=list
Environment variables to set in the child process. Can be specified multiple
times to set different environment variables.  Syntax: :code:`name=value`.
Using :code:`name=` will set to empty string and just :code:`name` will
remove the environment variable.


--hold
type=bool-set
Keep the window open even after the command being executed exits.


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
newly launched child process. Note that most shells only set environment
variables for child processes, so this will only copy the environment
variables that the shell process itself has not the environment variables
child processes inside the shell see. To copy that enviroment, use the
kitty remote control feature with :code:`kitty @launch --copy-env`.


--location
type=choices
default=default
choices=first,after,before,neighbor,last,vsplit,hsplit,split,default
Where to place the newly created window when it is added to a tab which
already has existing windows in it. :code:`after` and :code:`before` place the new
window before or after the active window. :code:`neighbor` is a synonym for :code:`after`.
Also applies to creating a new tab, where the value of :code:`after`
will cause the new tab to be placed next to the current tab instead of at the end.
The values of :code:`vsplit`, :code:`hsplit` and :code:`split` are only used by the
:code:`splits` layout and control if the new window is placed in a vertical,
horizontal or automatic split with the currently active window. The default is
to place the window in a layout dependent manner, typically, after the
currently active window.


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
choices=none,@selection,@screen,@screen_scrollback,@alternate,@alternate_scrollback,@first_cmd_output_on_screen,@last_cmd_output,@last_visited_cmd_output
Pass the screen contents as :code:`STDIN` to the child process. :code:`@selection` is
the currently selected text. :code:`@screen` is the contents of the currently active
window. :code:`@screen_scrollback` is the same as :code:`@screen`, but includes the
scrollback buffer as well. :code:`@alternate` is the secondary screen of the current
active window. For example if you run a full screen terminal application, the
secondary screen will be the screen you return to when quitting the application.
:code:`@first_cmd_output_on_screen` is the output from the first command run in the shell on screen,
:code:`@last_cmd_output` is the output from the last command run in the shell,
:code:`@last_visited_cmd_output` is the first output below the last scrolled position via
scroll_to_prompt, this three needs :ref:`shell_integration` to work.


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


--os-window-title
Set the title for the newly created OS window. This title will override any
titles set by programs running in kitty. The special value :code:`current`
will use the title of the current OS Window, if any.


--logo
Path to a PNG image to use as the logo for the newly created window. See :opt:`window_logo_path`.


--logo-position
The position for the window logo. Only takes effect if :option:`--logo` is specified. See :opt:`window_logo_position`.


--logo-alpha
type=float
default=-1
The amount the window logo should be faded into the background.
Only takes effect if :option:`--logo` is specified. See :opt:`window_logo_position`.


--color
type=list
Change colors in the newly launched window. You can either specify a path to a .conf
file with the same syntax as kitty.conf to read the colors from, or specify them
individually, for example: ``--color background=white`` ``--color foreground=red``


--watcher -w
type=list
Path to a python file. Appropriately named functions in this file will be called
for various events, such as when the window is resized, focused or closed. See the section
on watchers in the launch command documentation: :ref:`watchers`. Relative paths are
resolved relative to the kitty config directory. Global watchers for all windows can be
specified with :opt:`watcher`.
'''


def parse_launch_args(args: Optional[Sequence[str]] = None) -> LaunchSpec:
    args = list(args or ())
    try:
        opts, args = parse_args(result_class=LaunchCLIOptions, args=args, ospec=options_spec)
    except SystemExit as e:
        raise ValueError from e
    return LaunchSpec(opts, args)


def get_env(opts: LaunchCLIOptions, active_child: Optional[Child] = None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if opts.copy_env and active_child:
        env.update(active_child.foreground_environ)
    for x in opts.env:
        for k, v in parse_env(x, env):
            env[k] = v
    return env


def tab_for_window(boss: Boss, opts: LaunchCLIOptions, target_tab: Optional[Tab] = None) -> Optional[Tab]:

    def create_tab(tm: Optional[TabManager] = None) -> Tab:
        if tm is None:
            oswid = boss.add_os_window(wclass=opts.os_window_class, wname=opts.os_window_name, override_title=opts.os_window_title or None)
            tm = boss.os_window_map[oswid]
        tab = tm.new_tab(empty_tab=True, location=opts.location)
        if opts.tab_title:
            tab.set_title(opts.tab_title)
        return tab

    if opts.type == 'tab':
        if target_tab is not None:
            tm = target_tab.tab_manager_ref() or boss.active_tab_manager
        else:
            tm = boss.active_tab_manager
        tab = create_tab(tm)
    elif opts.type == 'os-window':
        tab = create_tab()
    else:
        tab = target_tab or boss.active_tab or create_tab()

    return tab


watcher_modules: Dict[str, Any] = {}


def load_watch_modules(watchers: Iterable[str]) -> Optional[Watchers]:
    if not watchers:
        return None
    import runpy
    ans = Watchers()
    for path in watchers:
        path = resolve_custom_file(path)
        m = watcher_modules.get(path, None)
        if m is None:
            try:
                m = runpy.run_path(path, run_name='__kitty_watcher__')
            except Exception as err:
                import traceback
                log_error(traceback.format_exc())
                log_error(f'Failed to load watcher from {path} with error: {err}')
                watcher_modules[path] = False
                continue
            watcher_modules[path] = m
        if m is False:
            continue
        w = m.get('on_close')
        if callable(w):
            ans.on_close.append(w)
        w = m.get('on_resize')
        if callable(w):
            ans.on_resize.append(w)
        w = m.get('on_focus_change')
        if callable(w):
            ans.on_focus_change.append(w)
    return ans


class LaunchKwds(TypedDict):

    allow_remote_control: bool
    cwd_from: Optional[CwdRequest]
    cwd: Optional[str]
    location: Optional[str]
    override_title: Optional[str]
    copy_colors_from: Optional[Window]
    marker: Optional[str]
    cmd: Optional[List[str]]
    overlay_for: Optional[int]
    stdin: Optional[bytes]


def apply_colors(window: Window, spec: Sequence[str]) -> None:
    from kitty.rc.set_colors import parse_colors
    colors = parse_colors(spec)
    profiles = window.screen.color_profile,
    patch_color_profiles(colors, profiles, True)


class ForceWindowLaunch:

    def __init__(self) -> None:
        self.force = False

    def __bool__(self) -> bool:
        return self.force

    def __call__(self, force: bool) -> 'ForceWindowLaunch':
        self.force = force
        return self

    def __enter__(self) -> None:
        pass

    def __exit__(self, *a: object) -> None:
        self.force = False


force_window_launch = ForceWindowLaunch()
non_window_launch_types = 'background', 'clipboard', 'primary'


def launch(
    boss: Boss,
    opts: LaunchCLIOptions,
    args: List[str],
    target_tab: Optional[Tab] = None,
    force_target_tab: bool = False,
    active: Optional[Window] = None,
    is_clone_launch: str = '',
) -> Optional[Window]:
    active = active or boss.active_window_for_cwd
    if active:
        active_child = active.child
    else:
        active_child = None
    if opts.window_title == 'current':
        opts.window_title = active.title if active else None
    if opts.tab_title == 'current':
        atab = boss.active_tab
        opts.tab_title = atab.effective_title if atab else None
    if opts.os_window_title == 'current':
        tm = boss.active_tab_manager
        opts.os_window_title = get_os_window_title(tm.os_window_id) if tm else None
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
            if active:
                kw['cwd_from'] = CwdRequest(active)
        elif opts.cwd == 'last_reported':
            if active:
                kw['cwd_from'] = CwdRequest(active, CwdRequestType.last_reported)
        elif opts.cwd == 'oldest':
            if active:
                kw['cwd_from'] = CwdRequest(active, CwdRequestType.last_reported)
        else:
            kw['cwd'] = opts.cwd
    if opts.location != 'default':
        kw['location'] = opts.location
    if opts.copy_colors and active:
        kw['copy_colors_from'] = active
    pipe_data: Dict[str, Any] = {}
    if opts.stdin_source != 'none':
        q = str(opts.stdin_source)
        if opts.stdin_add_formatting:
            if q in ('@screen', '@screen_scrollback', '@alternate', '@alternate_scrollback',
                     '@first_cmd_output_on_screen', '@last_cmd_output', '@last_visited_cmd_output'):
                q = f'@ansi_{q[1:]}'
        if opts.stdin_add_line_wrap_markers:
            q += '_wrap'
        penv, stdin = boss.process_stdin_source(window=active, stdin=q, copy_pipe_data=pipe_data)
        if stdin:
            kw['stdin'] = stdin
            if penv:
                env.update(penv)

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
                elif x == '@input-line-number':
                    if 'input_line_number' in pipe_data:
                        x = str(pipe_data['input_line_number'])
                elif x == '@line-count':
                    if 'lines' in pipe_data:
                        x = str(pipe_data['lines'])
                elif x in ('@cursor-x', '@cursor-y', '@scrolled-by', '@first-line-on-screen', '@last-line-on-screen'):
                    if active is not None:
                        screen = active.screen
                        if x == '@scrolled-by':
                            x = str(screen.scrolled_by)
                        elif x == '@cursor-x':
                            x = str(screen.cursor.x + 1)
                        elif x == '@cursor-y':
                            x = str(screen.cursor.y + 1)
                        elif x == '@first-line-on-screen':
                            x = str(screen.visual_line(0) or '')
                        elif x == '@last-line-on-screen':
                            x = str(screen.visual_line(screen.lines - 1) or '')
            final_cmd.append(x)
        exe = which(final_cmd[0])
        if exe:
            final_cmd[0] = exe
        kw['cmd'] = final_cmd
    if force_window_launch and opts.type not in non_window_launch_types:
        opts.type = 'window'
    if opts.type == 'overlay' and active:
        kw['overlay_for'] = active.id
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
        if opts.hold:
            cmd = kw['cmd'] or [shell_path]
            kw['cmd'] = [kitty_exe(), '+hold'] + cmd
        if force_target_tab:
            tab = target_tab
        else:
            tab = tab_for_window(boss, opts, target_tab)
        if tab is not None:
            watchers = load_watch_modules(opts.watcher)
            new_window: Window = tab.new_window(env=env or None, watchers=watchers or None, is_clone_launch=is_clone_launch, **kw)
            if opts.color:
                apply_colors(new_window, opts.color)
            if opts.keep_focus and active:
                boss.set_active_window(active, switch_os_window_if_needed=True, for_keep_focus=True)
            if opts.logo:
                new_window.set_logo(opts.logo, opts.logo_position or '', opts.logo_alpha)
            return new_window
    return None


def parse_opts_for_clone(args: List[str]) -> LaunchCLIOptions:
    unsafe, unsafe_args = parse_launch_args(args)
    default_opts, default_args = parse_launch_args()
    # only copy safe options, those that dont lead to local code exec
    for x in (
        'window_title', 'tab_title', 'type', 'keep_focus', 'cwd', 'env', 'hold',
        'location', 'os_window_class', 'os_window_name', 'os_window_title',
        'logo', 'logo_position', 'logo_alpha', 'color'
    ):
        setattr(default_opts, x, getattr(unsafe, x))
    return default_opts


def parse_bash_env(text: str) -> Dict[str, str]:
    # See https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
    ans = {}
    pos = 0
    escapes = r'"\$`'
    while pos < len(text):
        idx = text.find('="', pos)
        if idx < 0:
            break
        i = text.rfind(' ', 0, idx)
        if i < 0:
            break
        key = text[i+1:idx]
        pos = idx + 2
        buf: List[str] = []
        a = buf.append
        while pos < len(text):
            ch = text[pos]
            pos += 1
            if ch == '\\':
                if text[pos] in escapes:
                    a(text[pos])
                    pos += 1
                    continue
                a(ch)
            elif ch == '"':
                break
            else:
                a(ch)
        ans[key] = ''.join(buf)
    return ans


def parse_null_env(text: str) -> Dict[str, str]:
    ans = {}
    for line in text.split('\0'):
        if line:
            try:
                k, v = line.split('=', 1)
            except ValueError:
                continue
            ans[k] = v
    return ans


class CloneCmd:

    def __init__(self, msg: str) -> None:
        self.args: List[str] = []
        self.env: Optional[Dict[str, str]] = None
        self.cwd = ''
        self.shell = ''
        self.envfmt = 'default'
        self.pid = -1
        self.parse_message(msg)
        self.opts = parse_opts_for_clone(self.args)

    def parse_message(self, msg: str) -> None:
        import base64
        simple = 'pid', 'envfmt', 'shell'
        for x in msg.split(','):
            k, v = x.split('=', 1)
            if k in simple:
                setattr(self, k, int(v) if k == 'pid' else v)
                continue
            v = base64.standard_b64decode(v).decode('utf-8', 'replace')
            if k == 'a':
                self.args.append(v)
            elif k == 'env':
                env = parse_bash_env(v) if self.envfmt == 'bash' else parse_null_env(v)
                self.env = {k: v for k, v in env.items() if k not in {
                    'HOME', 'LOGNAME', 'USER', 'PWD',
                    # some people export these. We want the shell rc files to recreate them
                    'PS0', 'PS1', 'PS2', 'PS3', 'PS4', 'RPS1', 'PROMPT_COMMAND', 'SHLVL',
                    # conda state env vars
                    'CONDA_SHLVL', 'CONDA_PREFIX', 'CONDA_PROMPT_MODIFIER', 'CONDA_EXE', 'CONDA_PYTHON_EXE', '_CE_CONDA', '_CE_M',
                    # skip SSH environment variables
                    'SSH_CLIENT', 'SSH_CONNECTION', 'SSH_ORIGINAL_COMMAND', 'SSH_TTY', 'SSH2_TTY',
                } and not k.startswith((
                    # conda state env vars for multi-level virtual environments
                    'CONDA_PREFIX_',
                ))}
            elif k == 'cwd':
                self.cwd = v


def clone_and_launch(msg: str, window: Window) -> None:
    from .child import cmdline_of_process
    from .shell_integration import serialize_env
    c = CloneCmd(msg)
    if c.cwd and not c.opts.cwd:
        c.opts.cwd = c.cwd
    c.opts.copy_colors = True
    c.opts.copy_env = False
    if c.opts.type in non_window_launch_types:
        c.opts.type = 'window'
    if c.env and c.env.get('PATH') and c.env.get('VIRTUAL_ENV'):
        # only pass VIRTUAL_ENV if it is currently active
        if f"{c.env['VIRTUAL_ENV']}/bin" not in c.env['PATH'].split(os.pathsep):
            del c.env['VIRTUAL_ENV']
    is_clone_launch = serialize_env(c.shell, c.env or {})
    ssh_kitten_cmdline = window.ssh_kitten_cmdline()
    if ssh_kitten_cmdline:
        from kittens.ssh.main import (
            patch_cmdline, set_cwd_in_cmdline, set_env_in_cmdline
        )
        cmdline = ssh_kitten_cmdline
        if c.opts.cwd:
            set_cwd_in_cmdline(c.opts.cwd, cmdline)
            c.opts.cwd = None
        if c.env:
            set_env_in_cmdline({
                'KITTY_IS_CLONE_LAUNCH': is_clone_launch,
                'KITTY_CLONE_SOURCE_STRATEGIES': ',' + ','.join(get_options().clone_source_strategies) + ','
            }, cmdline)
            c.env = None
        if c.opts.env:
            for entry in reversed(c.opts.env):
                patch_cmdline('env', entry, cmdline)
            c.opts.env = []
    else:
        try:
            cmdline = cmdline_of_process(c.pid)
        except Exception:
            cmdline = []
        if not cmdline:
            cmdline = list(window.child.argv)
        if cmdline and cmdline[0] == window.child.final_argv0:
            cmdline[0] = window.child.final_exe
        if cmdline and cmdline == [window.child.final_exe] + window.child.argv[1:]:
            cmdline = window.child.unmodified_argv
    launch(get_boss(), c.opts, cmdline, active=window, is_clone_launch=is_clone_launch)
