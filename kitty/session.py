#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import shlex
import sys
from typing import Generator, List, Optional, Sequence, Union

from .cli_stub import CLIOptions
from .options_types import to_layout_names, window_size
from .constants import kitty_exe
from .layout.interface import all_layouts
from .options_stub import Options
from .os_window_size import WindowSize, WindowSizeData, WindowSizes
from .typing import SpecialWindowInstance
from .utils import log_error, resolved_shell


def get_os_window_sizing_data(opts: Options, session: Optional['Session'] = None) -> WindowSizeData:
    if session is None or session.os_window_size is None:
        sizes = WindowSizes(WindowSize(*opts.initial_window_width), WindowSize(*opts.initial_window_height))
    else:
        sizes = session.os_window_size
    return WindowSizeData(sizes, opts.remember_window_size, opts.single_window_margin_width, opts.window_margin_width, opts.window_padding_width)


class Tab:

    def __init__(self, opts: Options, name: str):
        from .launch import LaunchSpec
        self.windows: List[Union[LaunchSpec, 'SpecialWindowInstance']] = []
        self.name = name.strip()
        self.active_window_idx = 0
        self.enabled_layouts = opts.enabled_layouts
        self.layout = (self.enabled_layouts or ['tall'])[0]
        self.cwd: Optional[str] = None
        self.next_title: Optional[str] = None


class Session:

    def __init__(self, default_title: Optional[str] = None, default_watchers: Sequence[str] = ()):
        self.tabs: List[Tab] = []
        self.default_watchers = list(default_watchers)
        self.active_tab_idx = 0
        self.default_title = default_title
        self.os_window_size: Optional[WindowSizes] = None
        self.os_window_class: Optional[str] = None

    def add_tab(self, opts: Options, name: str = '') -> None:
        if self.tabs and not self.tabs[-1].windows:
            del self.tabs[-1]
        self.tabs.append(Tab(opts, name))

    def set_next_title(self, title: str) -> None:
        self.tabs[-1].next_title = title.strip()

    def set_layout(self, val: str) -> None:
        if val.partition(':')[0] not in all_layouts:
            raise ValueError('{} is not a valid layout'.format(val))
        self.tabs[-1].layout = val

    def add_window(self, cmd: Union[None, str, List[str]]) -> None:
        from .launch import parse_launch_args
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        spec = parse_launch_args(cmd)
        if self.default_watchers:
            spec.opts.watcher = list(spec.opts.watcher) + self.default_watchers
        t = self.tabs[-1]
        spec.opts.cwd = spec.opts.cwd or t.cwd
        t.windows.append(spec)
        t.next_title = None

    def add_special_window(self, sw: 'SpecialWindowInstance') -> None:
        self.tabs[-1].windows.append(sw)

    def focus(self) -> None:
        self.active_tab_idx = max(0, len(self.tabs) - 1)
        self.tabs[-1].active_window_idx = max(0, len(self.tabs[-1].windows) - 1)

    def set_enabled_layouts(self, raw: str) -> None:
        self.tabs[-1].enabled_layouts = to_layout_names(raw)
        if self.tabs[-1].layout not in self.tabs[-1].enabled_layouts:
            self.tabs[-1].layout = self.tabs[-1].enabled_layouts[0]

    def set_cwd(self, val: str) -> None:
        self.tabs[-1].cwd = val


def parse_session(raw: str, opts: Options, default_title: Optional[str] = None) -> Generator[Session, None, None]:

    def finalize_session(ans: Session) -> Session:
        from .tabs import SpecialWindow
        for t in ans.tabs:
            if not t.windows:
                t.windows.append(SpecialWindow(cmd=resolved_shell(opts), override_title=default_title))
        return ans

    ans = Session(default_title)
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
            if cmd == 'new_tab':
                ans.add_tab(opts, rest)
            elif cmd == 'new_os_window':
                yield finalize_session(ans)
                ans = Session(default_title)
                ans.add_tab(opts, rest)
            elif cmd == 'layout':
                ans.set_layout(rest)
            elif cmd == 'launch':
                ans.add_window(rest)
            elif cmd == 'focus':
                ans.focus()
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
            else:
                raise ValueError('Unknown command in session file: {}'.format(cmd))
    yield finalize_session(ans)


class PreReadSession(str):

    def __new__(cls, val: str) -> 'PreReadSession':
        ans: PreReadSession = str.__new__(cls, val)
        ans.pre_read = True  # type: ignore
        return ans


def create_sessions(
    opts: Options,
    args: Optional[CLIOptions] = None,
    special_window: Optional['SpecialWindowInstance'] = None,
    cwd_from: Optional[int] = None,
    respect_cwd: bool = False,
    default_session: Optional[str] = None
) -> Generator[Session, None, None]:
    if args and args.session:
        if isinstance(args.session, PreReadSession):
            session_data = '' + str(args.session)
        else:
            if args.session == '-':
                f = sys.stdin
            else:
                f = open(args.session)
            with f:
                session_data = f.read()
        yield from parse_session(session_data, opts, getattr(args, 'title', None))
        return
    if default_session and default_session != 'none':
        try:
            with open(default_session) as f:
                session_data = f.read()
        except OSError:
            log_error('Failed to read from session file, ignoring: {}'.format(default_session))
        else:
            yield from parse_session(session_data, opts, getattr(args, 'title', None))
            return
    default_watchers = args.watcher if args else ()
    ans = Session(default_watchers=default_watchers)
    current_layout = opts.enabled_layouts[0] if opts.enabled_layouts else 'tall'
    ans.add_tab(opts)
    ans.tabs[-1].layout = current_layout
    if special_window is None:
        cmd = args.args if args and args.args else resolved_shell(opts)
        if args and args.hold:
            cmd = [kitty_exe(), '+hold'] + cmd
        from kitty.tabs import SpecialWindow
        cwd: Optional[str] = args.directory if respect_cwd and args else None
        title = getattr(args, 'title', None)
        special_window = SpecialWindow(cmd, override_title=title, cwd_from=cwd_from, cwd=cwd)
    ans.add_special_window(special_window)
    yield ans
