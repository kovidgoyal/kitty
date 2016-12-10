#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque
from functools import partial
from threading import Lock
from ctypes import addressof

from .child import Child
from .config import build_ansi_color_table
from .constants import get_boss, appname, shell_path, cell_size, queue_action, viewport_size, WindowGeometry, GLuint
from .fast_data_types import glfw_post_empty_event, Screen, DECAWM, DATA_CELL_SIZE, ColorProfile
from .char_grid import calculate_gl_geometry, render_cells
from .layout import all_layouts
from .utils import color_as_int
from .borders import Borders
from .window import Window


def SpecialWindow(cmd, stdin=None, override_title=None):
    return (cmd, stdin, override_title)


class Tab:

    def __init__(self, opts, args, on_title_change, session_tab=None, special_window=None):
        self.opts, self.args = opts, args
        self.name = getattr(session_tab, 'name', '')
        self.on_title_change = on_title_change
        self.enabled_layouts = list((session_tab or opts).enabled_layouts)
        self.borders = Borders(opts)
        self.windows = deque()
        self.active_window_idx = 0
        if session_tab is None:
            self.cwd = args.directory
            l = self.enabled_layouts[0]
            if special_window is None:
                queue_action(self.new_window)
            else:
                queue_action(self.new_special_window, special_window)
        else:
            self.cwd = session_tab.cwd or args.directory
            l = session_tab.layout
            queue_action(self.startup, session_tab)
        self.current_layout = all_layouts[l](opts, self.borders.border_width, self.windows)
        for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
            setattr(self, which + '_window', partial(self.nth_window, num=i))

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

    def title_changed(self, window):
        if window is self.active_window:
            self.on_title_change(window.title)

    def visible_windows(self):
        for w in self.windows:
            if w.is_visible_in_layout:
                yield w

    def relayout(self):
        if self.windows:
            self.current_layout(self.windows, self.active_window_idx)
        self.relayout_borders()

    def relayout_borders(self):
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

    def launch_child(self, use_shell=False, cmd=None, stdin=None):
        if cmd is None:
            if use_shell:
                cmd = [shell_path]
            else:
                cmd = self.args.args or [shell_path]
        ans = Child(cmd, self.cwd, self.opts, stdin)
        ans.fork()
        return ans

    def new_window(self, use_shell=True, cmd=None, stdin=None, override_title=None):
        child = self.launch_child(use_shell=use_shell, cmd=cmd, stdin=stdin)
        window = Window(self, child, self.opts, self.args)
        if override_title is not None:
            window.title = window.override_title = override_title
        get_boss().add_child_fd(child.child_fd, window.read_ready, window.write_ready)
        self.active_window_idx = self.current_layout.add_window(self.windows, window, self.active_window_idx)
        self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
        glfw_post_empty_event()
        return window

    def new_special_window(self, special_window):
        self.new_window(False, *special_window)

    def close_window(self):
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def remove_window(self, window):
        self.active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
        glfw_post_empty_event()

    def set_active_window_idx(self, idx):
        if idx != self.active_window_idx:
            self.current_layout.set_active_window(self.windows, idx)
            self.active_window_idx = idx
            self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
            glfw_post_empty_event()

    def set_active_window(self, window):
        try:
            idx = self.windows.index(window)
        except ValueError:
            return
        self.set_active_window_idx(idx)

    def nth_window(self, num=0):
        if self.windows:
            self.set_active_window_idx(min(num, len(self.windows) - 1))

    def _next_window(self, delta=1):
        if len(self.windows) > 1:
            self.active_window_idx = self.current_layout.next_window(self.windows, self.active_window_idx, delta)
            self.borders(self.windows, self.active_window, self.current_layout.needs_window_borders and len(self.windows) > 1)
            glfw_post_empty_event()

    def next_window(self):
        self._next_window()

    def previous_window(self):
        self._next_window(-1)

    def move_window(self, delta=1):
        if len(self.windows) > 1 and abs(delta) > 0:
            idx = self.active_window_idx
            nidx = (idx + len(self.windows) + delta) % len(self.windows)
            self.windows[nidx], self.windows[idx] = self.windows[idx], self.windows[nidx]
            self.active_window_idx = nidx
            self.relayout()

    def move_window_to_top(self):
        self.move_window(-self.active_window_idx)

    def move_window_forward(self):
        self.move_window()

    def move_window_backward(self):
        self.move_window(-1)

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

    def __repr__(self):
        return 'Tab(title={}, id={})'.format(self.name or self.title, hex(id(self)))


class TabManager:

    def __init__(self, opts, args, startup_session):
        self.opts, self.args = opts, args
        self.buffer_id = None
        self.tabs = [Tab(opts, args, self.title_changed, t) for t in startup_session.tabs]
        self.cell_ranges = []
        self.active_tab_idx = startup_session.active_tab_idx
        self.tabbar_lock = Lock()
        self.tabbar_dirty = True
        self.color_profile = ColorProfile()
        self.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        self.default_fg = color_as_int(opts.inactive_tab_foreground)
        self.default_bg = color_as_int(opts.inactive_tab_background)

        def as_rgb(x):
            return (x << 8) | 2

        self.active_bg = as_rgb(color_as_int(opts.active_tab_background))
        self.active_fg = as_rgb(color_as_int(opts.active_tab_foreground))
        self.can_render = False

    def resize(self, only_tabs=False):
        for tab in self.tabs:
            tab.relayout()
        if only_tabs:
            return
        self.can_render = False
        ncells = viewport_size.width // cell_size.width
        s = Screen(None, 1, ncells)
        s.reset_mode(DECAWM)
        self.sprite_map_type = (GLuint * (s.lines * s.columns * DATA_CELL_SIZE))
        with self.tabbar_lock:
            self.sprite_map = self.sprite_map_type()
            self.tab_bar_screen = s
            self.tabbar_dirty = True
        margin = (viewport_size.width - ncells * cell_size.width) // 2
        self.window_geometry = WindowGeometry(
            margin, viewport_size.height - cell_size.height, viewport_size.width - margin, viewport_size.height, s.columns, s.lines)
        self.screen_geometry = calculate_gl_geometry(self.window_geometry)
        self.screen = s
        self.can_render = True

    def set_active_tab(self, idx):
        self.active_tab_idx = idx
        self.tabbar_dirty = True
        self.active_tab.relayout_borders()
        glfw_post_empty_event()

    def next_tab(self, delta=1):
        if len(self.tabs) > 1:
            self.set_active_tab((self.active_tab_idx + len(self.tabs) + delta) % len(self.tabs))

    def __iter__(self):
        return iter(self.tabs)

    def __len__(self):
        return len(self.tabs)

    def new_tab(self, special_window=None):
        self.active_tab_idx = len(self.tabs)
        self.tabs.append(Tab(self.opts, self.args, self.title_changed, special_window=special_window))

    @property
    def active_tab(self):
        return self.tabs[self.active_tab_idx] if self.tabs else None

    @property
    def tab_bar_height(self):
        return 0 if len(self.tabs) < 2 else cell_size.height

    def move_tab(self, delta=1):
        if len(self.tabs) > 1:
            idx = self.active_tab_idx
            nidx = (idx + len(self.tabs) + delta) % len(self.tabs)
            self.tabs[idx], self.tabs[nidx] = self.tabs[nidx], self.tabs[idx]
            self.active_tab_idx = nidx
            glfw_post_empty_event()

    def title_changed(self, new_title):
        with self.tabbar_lock:
            self.tabbar_dirty = True

    def remove(self, tab):
        ' Must be called in the GUI thread '
        needs_resize = len(self.tabs) == 2
        self.tabs.remove(tab)
        self.active_tab_idx = max(0, min(self.active_tab_idx, len(self.tabs) - 1))
        self.tabbar_dirty = True
        tab.destroy()
        if needs_resize:
            queue_action(get_boss().tabbar_visibility_changed)

    def update_tab_bar_data(self, sprites):
        s = self.tab_bar_screen
        s.cursor.x = 0
        s.erase_in_line(2, False)
        at = self.active_tab
        max_title_length = (self.screen_geometry.xnum // len(self.tabs)) - 1
        self.cell_ranges = []

        for t in self.tabs:
            title = (t.name or t.title or appname) + ' '
            s.cursor.bg = self.active_bg if t is at else 0
            s.cursor.fg = self.active_fg if t is at else 0
            s.cursor.bold = s.cursor.italic = t is at
            before = s.cursor.x
            s.draw(title)
            extra = s.cursor.x - before - max_title_length
            if extra > 0:
                s.cursor.x -= extra + 1
                s.draw('…')
            self.cell_ranges.append((before, s.cursor.x))
            s.cursor.bold = s.cursor.italic = False
            s.cursor.fg = s.cursor.bg = 0
            s.draw('┇')
            if s.cursor.x > s.columns - max_title_length:
                s.draw('…')
                break
        s.update_cell_data(
            sprites.backend, self.color_profile, addressof(self.sprite_map), self.default_fg, self.default_bg, True)
        sprites.render_dirty_cells()
        if self.buffer_id is None:
            self.buffer_id = sprites.add_sprite_map()
        sprites.set_sprite_map(self.buffer_id, self.sprite_map)

    def activate_tab_at(self, x):
        x = (x - self.window_geometry.left) // cell_size.width
        for i, (a, b) in enumerate(self.cell_ranges):
            if a <= x <= b:
                queue_action(self.set_active_tab, i)
                return

    def render(self, cell_program, sprites):
        if not self.can_render or len(self.tabs) < 2:
            return
        with self.tabbar_lock:
            if self.tabbar_dirty:
                self.update_tab_bar_data(sprites)
        render_cells(self.buffer_id, self.screen_geometry, cell_program, sprites)
