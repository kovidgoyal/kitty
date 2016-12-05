#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque

from .child import Child
from .constants import get_boss, appname, shell_path
from .fast_data_types import glfw_post_empty_event
from .layout import all_layouts
from .borders import Borders
from .window import Window


class Tab:

    def __init__(self, opts, args):
        self.opts, self.args = opts, args
        self.enabled_layouts = opts.enabled_layouts
        self.borders = Borders(opts)
        self.windows = deque()
        if args.window_layout:
            if args.window_layout not in self.enabled_layouts:
                self.enabled_layouts.insert(0, args.window_layout)
            self.current_layout = all_layouts[args.window_layout]
        else:
            self.current_layout = all_layouts[self.enabled_layouts[0]]
        self.active_window_idx = 0
        self.current_layout = self.current_layout(opts, self.borders.border_width, self.windows)

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
            idx = self.opts.enabled_layouts.index(self.current_layout.name)
            nl = self.opts.enabled_layouts[(idx + 1) % len(self.opts.enabled_layouts)]
            self.current_layout = all_layouts[nl](self.opts, self.borders.border_width, self.windows)
            for w in self.windows:
                w.is_visible_in_layout = True
            self.relayout()

    def launch_child(self, use_shell=False):
        if use_shell:
            cmd = [shell_path]
        else:
            cmd = self.args.args or [shell_path]
        ans = Child(cmd, self.args.directory, self.opts)
        ans.fork()
        return ans

    def new_window(self, use_shell=True):
        child = self.launch_child(use_shell=use_shell)
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
        for w in self.windows:
            w.destroy()
        del self.windows

    def render(self):
        self.borders.render(get_boss().borders_program)


class TabManager:

    def __init__(self, opts, args):
        self.opts, self.args = opts, args
        self.tabs = [Tab(opts, args)]

    def __iter__(self):
        return iter(self.tabs)

    def __len__(self):
        return len(self.tabs)

    @property
    def active_tab(self):
        return self.tabs[0] if self.tabs else None

    def remove(self, tab):
        ' Must be called in the GUI thread '
        self.tabs.remove(tab)
        tab.destroy()
