#!/usr/bin/env python
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
from collections.abc import Container, Iterable, Iterator, Sequence
from contextlib import suppress
from typing import Any, NamedTuple, Optional

from .boss import Boss
from .child import Child
from .cli import parse_args
from .cli_stub import LaunchCLIOptions
from .clipboard import set_clipboard_string, set_primary_selection
from .fast_data_types import add_timer, get_boss, get_options, get_os_window_title, patch_color_profiles
from .options.utils import env as parse_env
from .tabs import Tab, TabManager
from .types import OverlayType, run_once
from .utils import get_editor, log_error, resolve_custom_file, which
from .window import CwdRequest, CwdRequestType, Watchers, Window

try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


class LaunchSpec(NamedTuple):
    opts: LaunchCLIOptions
    args: list[str]


env_docs = '''\
type=list
Environment variables to set in the child process. Can be specified multiple
times to set different environment variables. Syntax: :code:`name=value`. Using
:code:`name=` will set to empty string and just :code:`name` will remove the
environment variable.
'''


remote_control_password_docs = '''\
type=list
Restrict the actions remote control is allowed to take. This works like
:opt:`remote_control_password`. You can specify a password and list of actions
just as for :opt:`remote_control_password`. For example::

    --remote-control-password '"my passphrase" get-* set-colors'

This password will be in effect for this window only.
Note that any passwords you have defined for :opt:`remote_control_password`
in :file:`kitty.conf` are also in effect. You can override them by using the same password here.
You can also disable all :opt:`remote_control_password` global passwords for this window, by using::

    --remote-control-password '!'

This option only takes effect if :option:`--allow-remote-control`
is also specified. Can be specified multiple times to create multiple passwords.
This option was added to kitty in version 0.26.0
'''


@run_once
def options_spec() -> str:
    return f'''
--window-title --title
The title to set for the new window. By default, title is controlled by the
child process. The special value :code:`current` will copy the title from the
currently active window.


--tab-title
The title for the new tab if launching in a new tab. By default, the title
of the active window in the tab is used as the tab title. The special value
:code:`current` will copy the title from the title of the currently active tab.


--type
type=choices
default=window
choices=window,tab,os-window,overlay,overlay-main,background,clipboard,primary
Where to launch the child process:

:code:`window`
    A new :term:`kitty window <window>` in the current tab

:code:`tab`
    A new :term:`tab` in the current OS window

:code:`os-window`
    A new :term:`operating system window <os_window>`

:code:`overlay`
    An :term:`overlay window <overlay>` covering the current active kitty window

:code:`overlay-main`
    An :term:`overlay window <overlay>` covering the current active kitty window.
    Unlike a plain overlay window, this window is considered as a :italic:`main`
    window which means it is used as the active window for getting the current working
    directory, the input text for kittens, launch commands, etc. Useful if this overlay is
    intended to run for a long time as a primary window.

:code:`background`
    The process will be run in the :italic:`background`, without a kitty
    window. Note that if :option:`kitten @ launch --allow-remote-control` is
    specified the :envvar:`KITTY_LISTEN_ON` environment variable will be set to
    a dedicated socket pair file descriptor that the process can use for remote
    control.

:code:`clipboard`, :code:`primary`
    These two are meant to work with :option:`--stdin-source <launch --stdin-source>` to copy
    data to the :italic:`system clipboard` or :italic:`primary selection`.

#placeholder_for_formatting#


--keep-focus --dont-take-focus
type=bool-set
Keep the focus on the currently active window instead of switching to the newly
opened window.


--cwd
completion=type:directory kwds:current,oldest,last_reported,root
The working directory for the newly launched child. Use the special value
:code:`current` to use the working directory of the currently active window.
The special value :code:`last_reported` uses the last working directory reported
by the shell (needs :ref:`shell_integration` to work). The special value
:code:`oldest` works like :code:`current` but uses the working directory of the
oldest foreground process associated with the currently active window rather
than the newest foreground process. Finally, the special value :code:`root`
refers to the process that was originally started when the window was created.


--env
{env_docs}


--var
type=list
User variables to set in the created window. Can be specified multiple
times to set different user variables. Syntax: :code:`name=value`. Using
:code:`name=` will set to empty string.


--hold
type=bool-set
Keep the window open even after the command being executed exits, at a shell prompt.


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
Copy the environment variables from the currently active window into the newly
launched child process. Note that this only copies the environment when the
window was first created, as it is not possible to get updated environment variables
from arbitrary processes. To copy that environment, use either the :ref:`clone-in-kitty
<clone_shell>` feature or the kitty remote control feature with :option:`kitten @ launch --copy-env`.


--location
type=choices
default=default
choices=first,after,before,neighbor,last,vsplit,hsplit,split,default
Where to place the newly created window when it is added to a tab which already
has existing windows in it. :code:`after` and :code:`before` place the new
window before or after the active window. :code:`neighbor` is a synonym for
:code:`after`. Also applies to creating a new tab, where the value of
:code:`after` will cause the new tab to be placed next to the current tab
instead of at the end. The values of :code:`vsplit`, :code:`hsplit` and
:code:`split` are only used by the :code:`splits` layout and control if the new
window is placed in a vertical, horizontal or automatic split with the currently
active window. The default is to place the window in a layout dependent manner,
typically, after the currently active window.


--bias
type=float
default=0
The bias used to alter the size of the window.
It controls what fraction of available space the window takes. The exact meaning
of bias depends on the current layout.

* Splits layout: The bias is interpreted as a percentage between 0 and 100.
When splitting a window into two, the new window will take up the specified fraction
of the space alloted to the original window and the original window will take up
the remainder of the space.

* Vertical/horizontal layout: The bias is interpreted as adding/subtracting from the
normal size of the window. It should be a number between -90 and 90. This number is
the percentage of the OS Window size that should be added to the window size.
So for example, if a window would normally have been size 50 in the layout inside an
OS Window that is size 80 high and --bias -10 is used it will become *approximately*
size 42 high. Note that sizes are approximations, you cannot use this method to
create windows of fixed sizes.

* Tall layout: If the window being created is the *first* window in a column, then
the bias is interpreted as a percentage, as for the splits layout, splitting the OS
Window width between columns. If the window is a second or subsequent window in a column
the bias is interpreted as adding/subtracting from the window size as for the vertical
layout above.

* Fat layout: Same as tall layout except it goes by rows instead of columns.

* Grid layout: The bias is interpreted the same way as for the Vertical and Horizontal
layouts, as something to be added/subtracted to the normal size. However, the
since in a grid layout there are rows *and* columns, the bias on the first window in a column
operates on the columns. Any later windows in that column operate on the row.
So, for example, if you bias the first window in a grid layout it will change the width
of the first column, the second window, the width of the second column, the third window,
the height of the second row and so on.

The bias option was introduced in kitty version 0.36.0.


--allow-remote-control
type=bool-set
Programs running in this window can control kitty (even if remote control is not
enabled in :file:`kitty.conf`). Note that any program with the right level of
permissions can still write to the pipes of any other program on the same
computer and therefore can control kitty. It can, however, be useful to block
programs running on other computers (for example, over SSH) or as other users.
See :option:`--remote-control-password` for ways to restrict actions allowed by
remote control.


--remote-control-password
{remote_control_password_docs}

--stdin-source
type=choices
default=none
choices=none,@selection,@screen,@screen_scrollback,@alternate,@alternate_scrollback,@first_cmd_output_on_screen,@last_cmd_output,@last_visited_cmd_output
Pass the screen contents as :file:`STDIN` to the child process.

:code:`@selection`
    is the currently selected text.

:code:`@screen`
    is the contents of the currently active window.

:code:`@screen_scrollback`
    is the same as :code:`@screen`, but includes the scrollback buffer as well.

:code:`@alternate`
    is the secondary screen of the current active window. For example if you run
    a full screen terminal application, the secondary screen will
    be the screen you return to when quitting the application.

:code:`@first_cmd_output_on_screen`
    is the output from the first command run in the shell on screen.

:code:`@last_cmd_output`
    is the output from the last command run in the shell.

:code:`@last_visited_cmd_output`
    is the first output below the last scrolled position via :ac:`scroll_to_prompt`,
    this needs :ref:`shell integration <shell_integration>` to work.

#placeholder_for_formatting#


--stdin-add-formatting
type=bool-set
When using :option:`--stdin-source <launch --stdin-source>` add formatting
escape codes, without this only plain text will be sent.


--stdin-add-line-wrap-markers
type=bool-set
When using :option:`--stdin-source <launch --stdin-source>` add a carriage
return at every line wrap location (where long lines are wrapped at screen
edges). This is useful if you want to pipe to program that wants to duplicate
the screen layout of the screen.


--marker
Create a marker that highlights text in the newly created window. The syntax is
the same as for the :ac:`toggle_marker` action (see :doc:`/marks`).


--os-window-class
Set the :italic:`WM_CLASS` property on X11 and the application id property on
Wayland for the newly created OS window when using :option:`--type=os-window
<launch --type>`. Defaults to whatever is used by the parent kitty process,
which in turn defaults to :code:`kitty`.


--os-window-name
Set the :italic:`WM_NAME` property on X11 for the newly created OS Window when
using :option:`--type=os-window <launch --type>`. Defaults to
:option:`--os-window-class <launch --os-window-class>`.


--os-window-title
Set the title for the newly created OS window. This title will override any
titles set by programs running in kitty. The special value :code:`current` will
use the title of the current OS window, if any.


--os-window-state
type=choices
default=normal
choices=normal,fullscreen,maximized,minimized
The initial state for the newly created OS Window.


--logo
completion=type:file ext:png group:"PNG images" relative:conf
Path to a PNG image to use as the logo for the newly created window. See
:opt:`window_logo_path`. Relative paths are resolved from the kitty configuration directory.


--logo-position
The position for the window logo. Only takes effect if :option:`--logo` is
specified. See :opt:`window_logo_position`.


--logo-alpha
type=float
default=-1
The amount the window logo should be faded into the background. Only takes
effect if :option:`--logo` is specified. See :opt:`window_logo_alpha`.


--color
type=list
Change colors in the newly launched window. You can either specify a path to a
:file:`.conf` file with the same syntax as :file:`kitty.conf` to read the colors
from, or specify them individually, for example::

    --color background=white --color foreground=red


--spacing
type=list
Set the margin and padding for the newly created window.
For example: :code:`margin=20` or :code:`padding-left=10` or :code:`margin-h=30`. The shorthand form sets
all values, the :code:`*-h` and :code:`*-v` variants set horizontal and vertical values.
Can be specified multiple times. Note that this is ignored for overlay windows as these use the settings
from the base window.


--watcher -w
type=list
completion=type:file ext:py relative:conf group:"Python scripts"
Path to a Python file. Appropriately named functions in this file will be called
for various events, such as when the window is resized, focused or closed. See
the section on watchers in the launch command documentation: :ref:`watchers`.
Relative paths are resolved relative to the :ref:`kitty config directory
<confloc>`. Global watchers for all windows can be specified with
:opt:`watcher` in :file:`kitty.conf`.
'''


def parse_launch_args(args: Optional[Sequence[str]] = None) -> LaunchSpec:
    args = list(args or ())
    try:
        opts, args = parse_args(result_class=LaunchCLIOptions, args=args, ospec=options_spec)
    except SystemExit as e:
        raise ValueError(str(e)) from e
    return LaunchSpec(opts, args)


def get_env(opts: LaunchCLIOptions, active_child: Optional[Child] = None, base_env: Optional[dict[str,str]] = None) -> dict[str, str]:
    env: dict[str, str] = {}
    if opts.copy_env and active_child:
        env.update(active_child.foreground_environ)
    if base_env is not None:
        env.update(base_env)
    for x in opts.env:
        for k, v in parse_env(x, env):
            env[k] = v
    return env


def tab_for_window(boss: Boss, opts: LaunchCLIOptions, target_tab: Optional[Tab] = None) -> Optional[Tab]:

    def create_tab(tm: Optional[TabManager] = None) -> Tab:
        if tm is None:
            oswid = boss.add_os_window(
                wclass=opts.os_window_class,
                wname=opts.os_window_name,
                window_state=opts.os_window_state,
                override_title=opts.os_window_title or None)
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


watcher_modules: dict[str, Any] = {}


def load_watch_modules(watchers: Iterable[str]) -> Optional[Watchers]:
    if not watchers:
        return None
    import runpy
    ans = Watchers()
    boss = get_boss()
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
            w = m.get('on_load')
            if callable(w):
                try:
                    w(boss, {})
                except Exception as err:
                    import traceback
                    log_error(traceback.format_exc())
                    log_error(f'Failed to call on_load() in watcher from {path} with error: {err}')
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
        w = m.get('on_set_user_var')
        if callable(w):
            ans.on_set_user_var.append(w)
        w = m.get('on_title_change')
        if callable(w):
            ans.on_title_change.append(w)
        w = m.get('on_cmd_startstop')
        if callable(w):
            ans.on_cmd_startstop.append(w)
    return ans


class LaunchKwds(TypedDict):

    allow_remote_control: bool
    remote_control_passwords: Optional[dict[str, Sequence[str]]]
    cwd_from: Optional[CwdRequest]
    cwd: Optional[str]
    location: Optional[str]
    override_title: Optional[str]
    copy_colors_from: Optional[Window]
    marker: Optional[str]
    cmd: Optional[list[str]]
    overlay_for: Optional[int]
    stdin: Optional[bytes]
    hold: bool
    bias: Optional[float]


def apply_colors(window: Window, spec: Sequence[str]) -> None:
    from .colors import parse_colors
    colors, transparent_background_colors = parse_colors(spec)
    profiles = window.screen.color_profile,
    patch_color_profiles(colors, transparent_background_colors, profiles, True)


def parse_var(defn: Iterable[str]) -> Iterator[tuple[str, str]]:
    for item in defn:
        a, sep, b = item.partition('=')
        yield a, b


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


def parse_remote_control_passwords(allow_remote_control: bool, passwords: Sequence[str]) -> Optional[dict[str, Sequence[str]]]:
    remote_control_restrictions: Optional[dict[str, Sequence[str]]] = None
    if allow_remote_control and passwords:
        from kitty.options.utils import remote_control_password
        remote_control_restrictions = {}
        for rcp in passwords:
            for pw, rcp_items in remote_control_password(rcp, {}):
                remote_control_restrictions[pw] = rcp_items
    return remote_control_restrictions


def _launch(
    boss: Boss,
    opts: LaunchCLIOptions,
    args: list[str],
    target_tab: Optional[Tab] = None,
    force_target_tab: bool = False,
    active: Optional[Window] = None,
    is_clone_launch: str = '',
    rc_from_window: Optional[Window] = None,
    base_env: Optional[dict[str, str]] = None,
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
    env = get_env(opts, active_child, base_env)
    kw: LaunchKwds = {
        'allow_remote_control': opts.allow_remote_control,
        'remote_control_passwords': parse_remote_control_passwords(opts.allow_remote_control, opts.remote_control_password),
        'cwd_from': None,
        'cwd': None,
        'location': None,
        'override_title': opts.window_title or None,
        'copy_colors_from': None,
        'marker': opts.marker or None,
        'cmd': None,
        'overlay_for': None,
        'stdin': None,
        'hold': False,
        'bias': None,
    }
    spacing = {}
    if opts.spacing:
        from .rc.set_spacing import parse_spacing_settings, patch_window_edges
        spacing = parse_spacing_settings(opts.spacing)
    if opts.bias:
        kw['bias'] = max(-100, min(opts.bias, 100))
    if opts.cwd:
        if opts.cwd == 'current':
            if active:
                kw['cwd_from'] = CwdRequest(active)
        elif opts.cwd == 'last_reported':
            if active:
                kw['cwd_from'] = CwdRequest(active, CwdRequestType.last_reported)
        elif opts.cwd == 'oldest':
            if active:
                kw['cwd_from'] = CwdRequest(active, CwdRequestType.oldest)
        elif opts.cwd == 'root':
            if active:
                kw['cwd_from'] = CwdRequest(active, CwdRequestType.root)
        else:
            kw['cwd'] = opts.cwd
        if kw['cwd_from'] is not None and rc_from_window is not None:
            kw['cwd_from'].rc_from_window_id = rc_from_window.id
    if opts.location != 'default':
        kw['location'] = opts.location
    if opts.copy_colors and active:
        kw['copy_colors_from'] = active
    pipe_data: dict[str, Any] = {}
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
        final_cmd: list[str] = []
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
        if rc_from_window is None and final_cmd:
            exe = which(final_cmd[0])
            if exe:
                final_cmd[0] = exe
        kw['cmd'] = final_cmd
    if force_window_launch and opts.type not in non_window_launch_types:
        opts.type = 'window'
    base_for_overlay = active
    if target_tab:
        base_for_overlay = target_tab.active_window
    if opts.type in ('overlay', 'overlay-main') and base_for_overlay:
        kw['overlay_for'] = base_for_overlay.id
    if opts.type == 'background':
        cmd = kw['cmd']
        if not cmd:
            raise ValueError('The cmd to run must be specified when running a background process')
        boss.run_background_process(
            cmd, cwd=kw['cwd'], cwd_from=kw['cwd_from'], env=env or None, stdin=kw['stdin'],
            allow_remote_control=kw['allow_remote_control'], remote_control_passwords=kw['remote_control_passwords']
        )
    elif opts.type in ('clipboard', 'primary'):
        stdin = kw.get('stdin')
        if stdin is not None:
            if opts.type == 'clipboard':
                set_clipboard_string(stdin)
            else:
                set_primary_selection(stdin)
    else:
        kw['hold'] = opts.hold
        if force_target_tab:
            tab = target_tab
        else:
            tab = tab_for_window(boss, opts, target_tab)
        if tab is not None:
            watchers = load_watch_modules(opts.watcher)
            with Window.set_ignore_focus_changes_for_new_windows(opts.keep_focus):
                new_window: Window = tab.new_window(
                    env=env or None, watchers=watchers or None, is_clone_launch=is_clone_launch, **kw)
            if spacing:
                patch_window_edges(new_window, spacing)
                tab.relayout()
            if opts.color:
                apply_colors(new_window, opts.color)
            if opts.keep_focus:
                if active:
                    boss.set_active_window(active, switch_os_window_if_needed=True, for_keep_focus=True)
                if not Window.initial_ignore_focus_changes_context_manager_in_operation:
                    new_window.ignore_focus_changes = False
            if opts.logo:
                new_window.set_logo(opts.logo, opts.logo_position or '', opts.logo_alpha)
            if opts.type == 'overlay-main':
                new_window.overlay_type = OverlayType.main
            if opts.var:
                for key, val in parse_var(opts.var):
                    new_window.set_user_var(key, val)
            return new_window
    return None


def launch(
    boss: Boss,
    opts: LaunchCLIOptions,
    args: list[str],
    target_tab: Optional[Tab] = None,
    force_target_tab: bool = False,
    active: Optional[Window] = None,
    is_clone_launch: str = '',
    rc_from_window: Optional[Window] = None,
    base_env: Optional[dict[str, str]] = None,
) -> Optional[Window]:
    active = active or boss.active_window_for_cwd
    if opts.keep_focus and active:
        orig, active.ignore_focus_changes = active.ignore_focus_changes, True
    try:
        return _launch(boss, opts, args, target_tab, force_target_tab, active, is_clone_launch, rc_from_window, base_env)
    finally:
        if opts.keep_focus and active:
            active.ignore_focus_changes = orig

@run_once
def clone_safe_opts() -> frozenset[str]:
    return frozenset((
        'window_title', 'tab_title', 'type', 'keep_focus', 'cwd', 'env', 'var', 'hold',
        'location', 'os_window_class', 'os_window_name', 'os_window_title', 'os_window_state',
        'logo', 'logo_position', 'logo_alpha', 'color', 'spacing',
    ))


def parse_opts_for_clone(args: list[str]) -> tuple[LaunchCLIOptions, list[str]]:
    unsafe, unsafe_args = parse_launch_args(args)
    default_opts, default_args = parse_launch_args()
    # only copy safe options, those that dont lead to local code exec
    for x in clone_safe_opts():
        setattr(default_opts, x, getattr(unsafe, x))
    return default_opts, unsafe_args


def parse_null_env(text: str) -> dict[str, str]:
    ans = {}
    for line in text.split('\0'):
        if line:
            try:
                k, v = line.split('=', 1)
            except ValueError:
                continue
            ans[k] = v
    return ans


def parse_message(msg: str, simple: Container[str]) -> Iterator[tuple[str, str]]:
    from base64 import standard_b64decode
    for x in msg.split(','):
        try:
            k, v = x.split('=', 1)
        except ValueError:
            continue
        if k not in simple:
            v = standard_b64decode(v).decode('utf-8', 'replace')
        yield k, v


class EditCmd:

    def __init__(self, msg: str) -> None:
        self.tdir = ''
        self.args: list[str] = []
        self.cwd = self.file_name = self.file_localpath = ''
        self.file_data = b''
        self.file_inode = -1, -1
        self.file_size = -1
        self.version = 0
        self.source_window_id = self.editor_window_id = -1
        self.abort_signaled = ''
        simple = 'file_inode', 'file_data', 'abort_signaled', 'version'
        for k, v in parse_message(msg, simple):
            if k == 'file_inode':
                q = map(int, v.split(':'))
                self.file_inode = next(q), next(q)
                self.file_size = next(q)
            elif k == 'a':
                self.args.append(v)
            elif k == 'file_data':
                import base64
                self.file_data = base64.standard_b64decode(v)
            elif k == 'version':
                self.version = int(v)
            else:
                setattr(self, k, v)
        if self.abort_signaled:
            return
        if self.version > 0:
            raise ValueError(f'Unsupported version received in edit protocol: {self.version}')
        self.opts, extra_args = parse_opts_for_clone(['--type=overlay'] + self.args)
        self.file_spec = extra_args.pop()
        self.line_number = 0
        import re
        pat = re.compile(r'\+(-?\d+)')
        for x in extra_args:
            m = pat.match(x)
            if m is not None:
                self.line_number = int(m.group(1))
        self.file_name = os.path.basename(self.file_spec)
        self.file_localpath = os.path.normpath(os.path.join(self.cwd, self.file_spec))
        self.is_local_file = False
        with suppress(OSError):
            st = os.stat(self.file_localpath)
            self.is_local_file = (st.st_dev, st.st_ino) == self.file_inode and os.access(self.file_localpath, os.W_OK | os.R_OK)
        if not self.is_local_file:
            import tempfile
            self.tdir = tempfile.mkdtemp()
            self.file_localpath = os.path.join(self.tdir, self.file_name)
            with open(self.file_localpath, 'wb') as f:
                f.write(self.file_data)
        self.file_data = b''
        self.last_mod_time = self.file_mod_time
        if not self.opts.cwd:
            self.opts.cwd = os.path.dirname(self.file_localpath)

    def __del__(self) -> None:
        if self.tdir:
            with suppress(OSError):
                shutil.rmtree(self.tdir)
            self.tdir = ''

    def read_data(self) -> bytes:
        with open(self.file_localpath, 'rb') as f:
            return f.read()

    @property
    def file_mod_time(self) -> int:
        return os.stat(self.file_localpath).st_mtime_ns

    def schedule_check(self) -> None:
        if not self.abort_signaled:
            add_timer(self.check_status, 1.0, False)

    def on_edit_window_close(self, window: Window) -> None:
        self.check_status()

    def check_status(self, timer_id: Optional[int] = None) -> None:
        if self.abort_signaled:
            return
        boss = get_boss()
        source_window = boss.window_id_map.get(self.source_window_id)
        if source_window is not None and not self.is_local_file:
            mtime = self.file_mod_time
            if mtime != self.last_mod_time:
                self.last_mod_time = mtime
                data = self.read_data()
                self.send_data(source_window, 'UPDATE', data)
        editor_window = boss.window_id_map.get(self.editor_window_id)
        if editor_window is None:
            edits_in_flight.pop(self.source_window_id, None)
            if source_window is not None:
                self.send_data(source_window, 'DONE')
            self.abort_signaled = self.abort_signaled or 'closed'
        else:
            self.schedule_check()

    def send_data(self, window: Window, data_type: str, data: bytes = b'') -> None:
        window.write_to_child(f'KITTY_DATA_START\n{data_type}\n')
        if data:
            import base64
            mv = memoryview(base64.standard_b64encode(data))
            while mv:
                window.write_to_child(bytes(mv[:512]))
                window.write_to_child('\n')
                mv = mv[512:]
        window.write_to_child('KITTY_DATA_END\n')


class CloneCmd:

    def __init__(self, msg: str) -> None:
        self.args: list[str] = []
        self.env: Optional[dict[str, str]] = None
        self.cwd = ''
        self.shell = ''
        self.envfmt = 'default'
        self.pid = -1
        self.bash_version = ''
        self.history = ''
        self.parse_message(msg)
        self.opts = parse_opts_for_clone(self.args)[0]

    def parse_message(self, msg: str) -> None:
        simple = 'pid', 'envfmt', 'shell', 'bash_version'
        for k, v in parse_message(msg, simple):
            if k in simple:
                if k == 'pid':
                    self.pid = int(v)
                else:
                    setattr(self, k, v)
            elif k == 'a':
                self.args.append(v)
            elif k == 'env':
                if self.envfmt == 'bash':
                    from .bash import parse_bash_env
                    env = parse_bash_env(v, self.bash_version)
                else:
                    env = parse_null_env(v)
                self.env = {k: v for k, v in env.items() if k not in {
                    'HOME', 'LOGNAME', 'USER', 'PWD',
                    # some people export these. We want the shell rc files to recreate them
                    'PS0', 'PS1', 'PS2', 'PS3', 'PS4', 'RPS1', 'PROMPT_COMMAND', 'SHLVL',
                    # conda state env vars
                    'CONDA_SHLVL', 'CONDA_PREFIX', 'CONDA_PROMPT_MODIFIER', 'CONDA_EXE', 'CONDA_PYTHON_EXE', '_CE_CONDA', '_CE_M',
                    # skip SSH environment variables
                    'SSH_CLIENT', 'SSH_CONNECTION', 'SSH_ORIGINAL_COMMAND', 'SSH_TTY', 'SSH2_TTY',
                    'SSH_TUNNEL', 'SSH_USER_AUTH', 'SSH_AUTH_SOCK',
                } and not k.startswith((
                    # conda state env vars for multi-level virtual environments
                    'CONDA_PREFIX_',
                ))}
            elif k == 'cwd':
                self.cwd = v
            elif k == 'history':
                self.history = v


edits_in_flight: dict[int, EditCmd] = {}


def remote_edit(msg: str, window: Window) -> None:
    c = EditCmd(msg)
    if c.abort_signaled:
        q = edits_in_flight.pop(window.id, None)
        if q is not None:
            q.abort_signaled = c.abort_signaled
        return
    cmdline = get_editor(path_to_edit=c.file_localpath, line_number=c.line_number)
    w = launch(get_boss(), c.opts, cmdline, active=window)
    if w is not None:
        c.source_window_id = window.id
        c.editor_window_id = w.id
        q = edits_in_flight.pop(window.id, None)
        if q is not None:
            q.abort_signaled = 'replaced'
        edits_in_flight[window.id] = c
        w.actions_on_close.append(c.on_edit_window_close)
        c.schedule_check()


def clone_and_launch(msg: str, window: Window) -> None:
    from .shell_integration import serialize_env
    c = CloneCmd(msg)
    if c.cwd and not c.opts.cwd:
        c.opts.cwd = c.cwd
    c.opts.copy_colors = True
    c.opts.copy_env = False
    if c.opts.type in non_window_launch_types:
        c.opts.type = 'window'
    env_to_serialize = c.env or {}
    if env_to_serialize.get('PATH') and env_to_serialize.get('VIRTUAL_ENV'):
        # only pass VIRTUAL_ENV if it is currently active
        if f"{env_to_serialize['VIRTUAL_ENV']}/bin" not in env_to_serialize['PATH'].split(os.pathsep):
            del env_to_serialize['VIRTUAL_ENV']
    env_to_serialize['KITTY_CLONE_SOURCE_STRATEGIES'] = ',' + ','.join(get_options().clone_source_strategies) + ','
    is_clone_launch = serialize_env(c.shell, env_to_serialize)
    ssh_kitten_cmdline = window.ssh_kitten_cmdline()
    if ssh_kitten_cmdline:
        from kittens.ssh.utils import patch_cmdline, set_cwd_in_cmdline, set_env_in_cmdline
        cmdline = ssh_kitten_cmdline
        if c.opts.cwd:
            set_cwd_in_cmdline(c.opts.cwd, cmdline)
            c.opts.cwd = None
        if c.env:
            set_env_in_cmdline({
                'KITTY_IS_CLONE_LAUNCH': is_clone_launch,
            }, cmdline)
            c.env = None
        if c.opts.env:
            for entry in reversed(c.opts.env):
                patch_cmdline('env', entry, cmdline)
            c.opts.env = []
    else:
        try:
            cmdline = window.child.cmdline_of_pid(c.pid)
        except Exception:
            cmdline = []
        if not cmdline:
            cmdline = list(window.child.argv)
        if cmdline and cmdline[0].startswith('-'):  # on macOS, run via run-shell kitten
            if window.child.is_default_shell:
                cmdline = window.child.unmodified_argv
            else:
                cmdline[0] = cmdline[0][1:]
                cmdline[0] = which(cmdline[0]) or cmdline[0]
        if cmdline and cmdline[0] == window.child.final_argv0:
            cmdline[0] = window.child.final_exe
        if cmdline and cmdline == [window.child.final_exe] + window.child.argv[1:]:
            cmdline = window.child.unmodified_argv
    launch(get_boss(), c.opts, cmdline, active=window, is_clone_launch=is_clone_launch)
