#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import shlex
from collections import namedtuple

from .config_data import to_layout_names
from .constants import shell_path, kitty_exe
from .layout import all_layouts
from .utils import log_error


WindowSizeOpts = namedtuple(
    'WindowSizeOpts', 'initial_window_width initial_window_height window_margin_width window_padding_width remember_window_size')


class Tab:

    def __init__(self, opts, name):
        self.windows = []
        self.name = name.strip()
        self.active_window_idx = 0
        self.enabled_layouts = opts.enabled_layouts
        self.layout = (self.enabled_layouts or ['tall'])[0]
        self.cwd = None
        self.next_title = None


class Session:

    def __init__(self, default_title=None):
        self.tabs = []
        self.active_tab_idx = 0
        self.default_title = default_title
        self.os_window_size = None

    def add_tab(self, opts, name=''):
        if self.tabs and not self.tabs[-1].windows:
            del self.tabs[-1]
        self.tabs.append(Tab(opts, name))

    def set_next_title(self, title):
        self.tabs[-1].next_title = title.strip()

    def set_layout(self, val):
        if val not in all_layouts:
            raise ValueError('{} is not a valid layout'.format(val))
        self.tabs[-1].layout = val

    def add_window(self, cmd):
        if cmd:
            cmd = shlex.split(cmd) if isinstance(cmd, str) else cmd
        else:
            cmd = None
        from .tabs import SpecialWindow
        t = self.tabs[-1]
        t.windows.append(SpecialWindow(cmd, cwd=t.cwd, override_title=t.next_title or self.default_title))
        t.next_title = None

    def add_special_window(self, sw):
        self.tabs[-1].windows.append(sw)

    def focus(self):
        self.active_tab_idx = max(0, len(self.tabs) - 1)
        self.tabs[-1].active_window_idx = max(0, len(self.tabs[-1].windows) - 1)

    def set_enabled_layouts(self, raw):
        self.tabs[-1].enabled_layouts = to_layout_names(raw)
        if self.tabs[-1].layout not in self.tabs[-1].enabled_layouts:
            self.tabs[-1].layout = self.tabs[-1].enabled_layouts[0]

    def set_cwd(self, val):
        self.tabs[-1].cwd = val


def resolved_shell(opts):
    ans = opts.shell
    if ans == '.':
        ans = [shell_path]
    else:
        ans = shlex.split(ans)
    return ans


def parse_session(raw, opts, default_title=None):

    def finalize_session(ans):
        for t in ans.tabs:
            if not t.windows:
                t.windows.append(resolved_shell(opts))
        return ans

    ans = Session(default_title)
    ans.add_tab(opts)
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            cmd, rest = line.split(maxsplit=1)
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
                from kitty.config_data import window_size
                w, h = map(window_size, rest.split(maxsplit=1))
                ans.os_window_size = WindowSizeOpts(w, h, opts.window_margin_width, opts.window_padding_width, False)
            else:
                raise ValueError('Unknown command in session file: {}'.format(cmd))
    yield finalize_session(ans)


def create_sessions(opts, args=None, special_window=None, cwd_from=None, respect_cwd=False, default_session=None):
    if args and args.session:
        with open(args.session) as f:
            yield from parse_session(f.read(), opts, getattr(args, 'title', None))
            return
    if default_session and default_session != 'none':
        try:
            with open(default_session) as f:
                session_data = f.read()
        except EnvironmentError:
            log_error('Failed to read from session file, ignoring: {}'.format(default_session))
        else:
            yield from parse_session(session_data, opts, getattr(args, 'title', None))
            return
    ans = Session()
    current_layout = opts.enabled_layouts[0] if opts.enabled_layouts else 'tall'
    ans.add_tab(opts)
    ans.tabs[-1].layout = current_layout
    if special_window is None:
        cmd = args.args if args and args.args else resolved_shell(opts)
        if args and args.hold:
            cmd = [kitty_exe(), '+hold'] + cmd
        from kitty.tabs import SpecialWindow
        k = {'cwd_from': cwd_from}
        if respect_cwd:
            k['cwd'] = args.directory
        if getattr(args, 'title', None):
            k['override_title'] = args.title
        special_window = SpecialWindow(cmd, **k)
    ans.add_special_window(special_window)
    yield ans
