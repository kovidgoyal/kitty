#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque

from .child import Child
from .constants import get_boss, appname, shell_path, cell_size, queue_action
from .fast_data_types import glfw_post_empty_event
from .layout import all_layouts
from .borders import Borders
from .window import Window


class Tab:

    def __init__(self, opts, args, session_tab=None):
        self.opts, self.args = opts, args
        self.enabled_layouts = list((session_tab or opts).enabled_layouts)
        self.borders = Borders(opts)
        self.windows = deque()
        self.active_window_idx = 0
        if session_tab is None:
            self.cwd = args.directory
            self.current_layout = self.enabled_layouts[0]
            queue_action(self.new_window)
        else:
            self.cwd = session_tab.cwd or args.directory
            self.current_layout = all_layouts[session_tab.layout](opts, self.borders.border_width, self.windows)
            queue_action(self.startup, session_tab)

    def startup(self, session_tab):
        for cmd in session_tab.windows:
            self.new_window(cmd=cmd)
        self.active_window_idx = session_tab.active_window_idx

    @property
    def is_visible(self):
        return get_boss().is_tab_visible(self)

    @property
    def active_window(self):
        return self.windows[self.active_window_idx] if self.windows else None

    @property
    def title(self):
        return getattr(self.active_window, 'title', appname)

    def visible_windows(self):
        for w in self.windows:
            if w.is_visible_in_layout:
                yield w

    def relayout(self):
        if self.windows:
            self.current_layout(self.windows, self.active_window_idx)
        self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)

    def next_layout(self):
        if len(self.opts.enabled_layouts) > 1:
            try:
                idx = self.opts.enabled_layouts.index(self.current_layout.name)
            except Exception:
                idx = -1
            nl = self.opts.enabled_layouts[(idx + 1) % len(self.opts.enabled_layouts)]
            self.current_layout = all_layouts[nl](self.opts, self.borders.border_width, self.windows)
            for w in self.windows:
                w.is_visible_in_layout = True
            self.relayout()

    def launch_child(self, use_shell=False, cmd=None):
        if cmd is None:
            if use_shell:
                cmd = [shell_path]
            else:
                cmd = self.args.args or [shell_path]
        ans = Child(cmd, self.cwd, self.opts)
        ans.fork()
        return ans

    def new_window(self, use_shell=True, cmd=None):
        child = self.launch_child(use_shell=use_shell, cmd=cmd)
        window = Window(self, child, self.opts, self.args)
        get_boss().add_child_fd(child.child_fd, window.read_ready, window.write_ready)
        self.active_window_idx = self.current_layout.add_window(self.windows, window, self.active_window_idx)
        self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
        glfw_post_empty_event()

    def close_window(self):
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def remove_window(self, window):
        self.active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
        glfw_post_empty_event()

    def set_active_window(self, window):
        try:
            idx = self.windows.index(window)
        except ValueError:
            return
        if idx != self.active_window_idx:
            self.current_layout.set_active_window(self.windows, idx)
            self.active_window_idx = idx
            self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
            glfw_post_empty_event()

    def _next_window(self, delta=1):
        if len(self.windows) > 1:
            self.active_window_idx = self.current_layout.next_window(self.windows, self.active_window_idx, delta)
            self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
            glfw_post_empty_event()

    def next_window(self):
        self._next_window()

    def previous_window(self):
        self._next_window(-1)

    def __iter__(self):
        yield from iter(self.windows)

    def __len__(self):
        return len(self.windows)

    def __contains__(self, window):
        return window in self.windows

    def destroy(self):
        if hasattr(self, 'windows'):
            for w in self.windows:
                w.destroy()
            del self.windows

    def render(self):
        self.borders.render(get_boss().borders_program)


class TabManager:

    def __init__(self, opts, args, startup_session):
        self.opts, self.args = opts, args
        self.tabs = [Tab(opts, args, t) for t in startup_session.tabs]
        self.active_tab_idx = startup_session.active_tab_idx

    def __iter__(self):
        return iter(self.tabs)

    def __len__(self):
        return len(self.tabs)

    @property
    def active_tab(self):
        return self.tabs[self.active_tab_idx] if self.tabs else None

    @property
    def tab_bar_height(self):
        return 0 if len(self.tabs) < 2 else cell_size.height

    def remove(self, tab):
        ' Must be called in the GUI thread '
        self.tabs.remove(tab)
        tab.destroy()
