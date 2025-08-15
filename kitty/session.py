#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import shlex
import sys
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import suppress
from functools import partial
from gettext import gettext as _
from typing import TYPE_CHECKING, Any, Optional, Sequence, Union

from .cli_stub import CLIOptions
from .constants import config_dir
from .fast_data_types import get_options
from .layout.interface import all_layouts
from .options.types import Options
from .options.utils import resize_window, to_layout_names, window_size
from .os_window_size import WindowSize, WindowSizeData, WindowSizes
from .typing_compat import BossType, SpecialWindowInstance, WindowType
from .utils import expandvars, log_error, resolve_custom_file, resolved_shell, shlex_split

if TYPE_CHECKING:
    from .launch import LaunchSpec
    from .window import CwdRequest


def get_os_window_sizing_data(opts: Options, session: Optional['Session'] = None) -> WindowSizeData:
    if session is None or session.os_window_size is None:
        sizes = WindowSizes(WindowSize(*opts.initial_window_width), WindowSize(*opts.initial_window_height))
    else:
        sizes = session.os_window_size
    return WindowSizeData(
        sizes, opts.remember_window_size, opts.single_window_margin_width, opts.window_margin_width,
        opts.single_window_padding_width, opts.window_padding_width)


ResizeSpec = tuple[str, int]


class WindowSpec:

    def __init__(self, launch_spec: Union['LaunchSpec', 'SpecialWindowInstance']):
        self.launch_spec = launch_spec
        self.resize_spec: ResizeSpec | None = None
        self.focus_matching_window_spec: str = ''
        self.is_background_process = False
        if hasattr(launch_spec, 'opts'):  # LaunchSpec
            from .launch import LaunchSpec
            assert isinstance(launch_spec, LaunchSpec)
            self.is_background_process = launch_spec.opts.type == 'background'


class Tab:

    def __init__(self, opts: Options, name: str):
        self.windows: list[WindowSpec] = []
        self.pending_resize_spec: ResizeSpec | None = None
        self.pending_focus_matching_window: str = ''
        self.name = name.strip()
        self.active_window_idx = 0
        self.enabled_layouts = opts.enabled_layouts
        self.layout = (self.enabled_layouts or ['tall'])[0]
        self.layout_state: dict[str, Any] | None = None
        self.cwd: str | None = None
        self.next_title: str | None = None

    @property
    def has_non_background_processes(self) -> bool:
        for w in self.windows:
            if not w.is_background_process:
                return True
        return False


class Session:

    session_name: str = ''
    num_of_windows_in_definition: int = 0

    def __init__(self, default_title: str | None = None):
        self.tabs: list[Tab] = []
        self.active_tab_idx = 0
        self.default_title = default_title
        self.os_window_size: WindowSizes | None = None
        self.os_window_class: str | None = None
        self.os_window_name: str | None = None
        self.os_window_state: str | None = None
        self.focus_os_window: bool = False

    @property
    def has_non_background_processes(self) -> bool:
        for t in self.tabs:
            if t.has_non_background_processes:
                return True
        return False

    def add_tab(self, opts: Options, name: str = '') -> None:
        if self.tabs and not self.tabs[-1].windows:
            del self.tabs[-1]
        self.tabs.append(Tab(opts, name))

    def set_next_title(self, title: str) -> None:
        self.tabs[-1].next_title = title.strip()

    def set_layout(self, val: str) -> None:
        if val.partition(':')[0] not in all_layouts:
            raise ValueError(f'{val} is not a valid layout')
        self.tabs[-1].layout = val

    def set_layout_state(self, val: str) -> None:
        self.tabs[-1].layout_state = json.loads(val)

    def add_window(self, cmd: None | str | list[str], expand: Callable[[str], str] = lambda x: x) -> None:
        from .launch import parse_launch_args
        needs_expandvars = False
        if isinstance(cmd, str) and cmd:
            needs_expandvars = True
            cmd = list(shlex_split(cmd))
        spec = parse_launch_args(cmd)
        if needs_expandvars:
            assert isinstance(cmd, list)
            limit = len(cmd)
            if len(spec.args):
                with suppress(ValueError):
                    limit = cmd.index(spec.args[0])
            cmd = [(expand(x) if i < limit else x) for i, x in enumerate(cmd)]
            spec = parse_launch_args(cmd)

        t = self.tabs[-1]
        if t.next_title and not spec.opts.window_title:
            spec.opts.window_title = t.next_title
        spec.opts.cwd = spec.opts.cwd or t.cwd
        t.windows.append(WindowSpec(spec))
        t.next_title = None
        if t.pending_resize_spec is not None:
            t.windows[-1].resize_spec = t.pending_resize_spec
            t.pending_resize_spec = None
        if t.pending_focus_matching_window:
            t.windows[-1].focus_matching_window_spec = t.pending_focus_matching_window
            t.pending_focus_matching_window = ''

    def resize_window(self, args: list[str]) -> None:
        s = resize_window('resize_window', shlex.join(args))[1]
        spec: ResizeSpec = s[0], s[1]
        t = self.tabs[-1]
        if t.windows:
            t.windows[-1].resize_spec = spec
        else:
            t.pending_resize_spec = spec

    def focus_matching_window(self, spec: str) -> None:
        t = self.tabs[-1]
        if t.windows:
            t.windows[-1].focus_matching_window_spec = spec
        else:
            t.pending_focus_matching_window = spec

    def add_special_window(self, sw: 'SpecialWindowInstance') -> None:
        self.tabs[-1].windows.append(WindowSpec(sw))

    def focus(self) -> None:
        self.active_tab_idx = max(0, len(self.tabs) - 1)
        self.tabs[-1].active_window_idx = max(0, len(self.tabs[-1].windows) - 1)

    def set_enabled_layouts(self, raw: str) -> None:
        self.tabs[-1].enabled_layouts = to_layout_names(raw)
        if self.tabs[-1].layout not in self.tabs[-1].enabled_layouts:
            self.tabs[-1].layout = self.tabs[-1].enabled_layouts[0]

    def set_cwd(self, val: str) -> None:
        self.tabs[-1].cwd = val


def session_arg_to_name(session_arg: str) -> str:
    if session_arg in ('-', '/dev/stdin', 'none'):
        session_arg = ''
    session_name = os.path.basename(session_arg)
    if session_name.rpartition('.')[2] in ('session', 'kitty-session'):
        session_name = session_name.rpartition('.')[0]
    return session_name



def parse_session(raw: str, opts: Options, environ: Mapping[str, str] | None = None, session_arg: str = '') -> Generator[Session, None, None]:
    session_name = session_arg_to_name(session_arg)
    def finalize_session(ans: Session) -> Session:
        ans.session_name = session_name
        ans.num_of_windows_in_definition = sum(len(t.windows) for t in ans.tabs)
        from .tabs import SpecialWindow
        for t in ans.tabs:
            if not t.windows:
                t.windows.append(WindowSpec(SpecialWindow(cmd=resolved_shell(opts))))
        return ans

    if environ is None:
        environ = os.environ
    expand = partial(expandvars, env=environ, fallback_to_os_env=False)
    ans = Session()
    ans.add_tab(opts)
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            parts = line.split(maxsplit=1)
            if len(parts) == 1:
                cmd, rest = parts[0], ''
            else:
                cmd, rest = parts
            cmd, rest = cmd.strip(), rest.strip()
            if cmd not in ('launch', 'set_layout_state'):
                rest = expand(rest)
            if cmd == 'new_tab':
                ans.add_tab(opts, rest)
            elif cmd == 'new_os_window':
                yield finalize_session(ans)
                ans = Session()
                ans.add_tab(opts, rest)
            elif cmd == 'layout':
                ans.set_layout(rest)
            elif cmd == 'launch':
                ans.add_window(rest, expand)
            elif cmd == 'focus':
                ans.focus()
            elif cmd == 'focus_os_window':
                ans.focus_os_window = True
            elif cmd == 'enabled_layouts':
                ans.set_enabled_layouts(rest)
            elif cmd == 'cd':
                ans.set_cwd(rest)
            elif cmd == 'title':
                ans.set_next_title(rest)
            elif cmd == 'os_window_size':
                w, h = map(window_size, rest.split(maxsplit=1))
                ans.os_window_size = WindowSizes(WindowSize(*w), WindowSize(*h))
            elif cmd == 'os_window_class':
                ans.os_window_class = rest
            elif cmd == 'os_window_name':
                ans.os_window_name = rest
            elif cmd == 'os_window_state':
                ans.os_window_state = rest
            elif cmd == 'resize_window':
                ans.resize_window(rest.split())
            elif cmd == 'focus_matching_window':
                ans.focus_matching_window(rest)
            elif cmd == 'set_layout_state':
                ans.set_layout_state(rest)
            else:
                raise ValueError(f'Unknown command in session file: {cmd}')
    yield finalize_session(ans)


class PreReadSession(str):

    associated_environ: Mapping[str, str]
    session_arg: str

    def __new__(cls, val: str, associated_environ: Mapping[str, str], session_arg: str) -> 'PreReadSession':
        ans: PreReadSession = str.__new__(cls, val)
        ans.associated_environ = associated_environ
        ans.session_arg = session_arg
        return ans


def create_sessions(
    opts: Options,
    args: CLIOptions | None = None,
    special_window: Optional['SpecialWindowInstance'] = None,
    cwd_from: Optional['CwdRequest'] = None,
    respect_cwd: bool = False,
    default_session: str | None = None,
    env_when_no_session: dict[str, str] | None = None,
) -> Iterator[Session]:
    if args and args.session:
        if args.session == "none":
            default_session = "none"
        else:
            session_arg = args.session
            environ: Mapping[str, str] | None = None
            if isinstance(args.session, PreReadSession):
                session_data = '' + str(args.session)
                environ = args.session.associated_environ
                session_arg = args.session.session_arg
            else:
                if args.session == '-':
                    f = sys.stdin
                else:
                    f = open(resolve_custom_file(args.session))
                with f:
                    session_data = f.read()
            yield from parse_session(session_data, opts, environ=environ, session_arg=session_arg)
            return
    if default_session and default_session != 'none' and not getattr(args, 'args', None):
        session_arg = session_arg_to_name(default_session)
        try:
            with open(default_session) as f:
                session_data = f.read()
        except OSError:
            log_error(f'Failed to read from session file, ignoring: {default_session}')
        else:
            yield from parse_session(session_data, opts, session_arg=session_arg)
            return
    ans = Session()
    current_layout = opts.enabled_layouts[0] if opts.enabled_layouts else 'tall'
    ans.add_tab(opts)
    ans.tabs[-1].layout = current_layout
    if args is not None:
        ans.os_window_class = args.cls
        ans.os_window_name = args.name
    if special_window is None:
        cmd = args.args if args and args.args else resolved_shell(opts)
        from kitty.tabs import SpecialWindow
        cwd: str | None = args.directory if respect_cwd and args else None
        special_window = SpecialWindow(cmd, cwd_from=cwd_from, cwd=cwd, env=env_when_no_session, hold=bool(args and args.hold))
    ans.add_special_window(special_window)
    yield ans


def window_for_session_name(boss: BossType, session_name: str) -> WindowType | None:
    windows = [w for w in boss.all_windows if w.created_in_session_name == session_name]
    if not windows:
        tabs = (t for t in boss.all_tabs if t.created_in_session_name == session_name)
        windows = [t.active_window for t in tabs if t.active_window]
        if not windows:
            os_windows = (tm for tm in boss.all_tab_managers if tm.created_in_session_name == session_name)
            windows = [tm.active_window for tm in os_windows if tm.active_window]
    if windows:
        def skey(w: WindowType) -> float:
            return w.last_focused_at
        windows.sort(key=skey, reverse=True)
        return windows[0]
    return None


seen_session_paths: dict[str, str] = {}


def create_session(boss: BossType, path: str) -> str:
    session_name = ''
    for i, s in enumerate(create_sessions(get_options(), default_session=path)):
        if i == 0:
            session_name = s.session_name
            if s.num_of_windows_in_definition == 0:  # leading new_os_window
                continue
            tm = boss.active_tab_manager
            if tm is None:
                boss.add_os_window(s)
            else:
                tm.add_tabs_from_session(s)
        else:
            boss.add_os_window(s)
    seen_session_paths[session_name] = path
    return session_name


goto_session_history: list[str] = []


def append_to_session_history(name: str) -> None:
    with suppress(ValueError):
        goto_session_history.remove(name)
    goto_session_history.append(name)


def switch_to_session(boss: BossType, session_name: str) -> bool:
    w = window_for_session_name(boss, session_name)
    if w is not None:
        append_to_session_history(session_name)
        boss.set_active_window(w, switch_os_window_if_needed=True)
        return True
    return False


def resolve_session_path_and_name(path: str) -> tuple[str, str]:
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(config_dir, path)
    path = os.path.abspath(path)
    return path, session_arg_to_name(path)


def get_all_known_sessions() -> dict[str, str]:
    opts = get_options()
    all_known_sessions = seen_session_paths.copy()
    for km in opts.keyboard_modes.values():
        for kdefs in km.keymap.values():
            for kd in kdefs:
                for key_action in opts.alias_map.resolve_aliases(kd.definition, 'map'):
                    if key_action.func == 'goto_session':
                        path = ''
                        for x in key_action.args:
                            if isinstance(x, str) and not x.startswith('-'):
                                path = x
                                break
                        if path:
                            path, session_name = resolve_session_path_and_name(path)
                            if session_name not in all_known_sessions:
                                all_known_sessions[session_name] = path
    return all_known_sessions


def choose_session(boss: BossType) -> None:
    all_known_sessions = get_all_known_sessions()
    hmap = {n: len(goto_session_history)-i for i, n in enumerate(goto_session_history)}
    def skey(name: str) -> tuple[int, str]:
        return hmap.get(name, len(goto_session_history)), name.lower()
    names = sorted(all_known_sessions, key=skey)

    def chosen(name: str | None) -> None:
        if name:
            goto_session(boss, (all_known_sessions[name],))
    boss.choose_entry(
        _('Select a session to activate'), ((name, name) for name in names), chosen)


def goto_session(boss: BossType, cmdline: Sequence[str]) -> None:
    if not cmdline:
        choose_session(boss)
        return
    path = cmdline[0]
    if len(cmdline) == 1:
        try:
            idx = int(path)
        except Exception:
            idx = 0
        if idx < 0:
            nidx = max(0, len(goto_session_history) - 1 - idx)
            switch_to_session(boss, goto_session_history[nidx])
            return
    else:
        for x in cmdline:
            if not x.startswith('-'):
                path = x
                break
    path, session_name = resolve_session_path_and_name(path)
    if not session_name:
        boss.show_error(_('Invalid session'), _('{} is not a valid path for a session').format(path))
        return
    if switch_to_session(boss, session_name):
        return
    try:
        session_name = create_session(boss, path)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        boss.show_error(_('Failed to create session'), _('Could not create session from {0} with error:\n{1}').format(path, tb))
    else:
        append_to_session_history(session_name)
