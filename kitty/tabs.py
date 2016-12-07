#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque
from threading import Lock
from ctypes import addressof

from .child import Child
from .config import build_ansi_color_table
from .constants import get_boss, appname, shell_path, cell_size, queue_action, viewport_size, WindowGeometry, GLuint
from .fast_data_types import (
    glfw_post_empty_event, Screen, DECAWM, DATA_CELL_SIZE,
    ColorProfile, glUniform2ui, glUniform4f, glUniform1i, glUniform2f,
    glDrawArraysInstanced, GL_TRIANGLE_FAN
)
from .char_grid import calculate_gl_geometry
from .layout import all_layouts
from .borders import Borders
from .window import Window


class Tab:

    def __init__(self, opts, args, on_title_change, session_tab=None):
        self.opts, self.args = opts, args
        self.on_title_change = on_title_change
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
        self.tabs = [Tab(opts, args, self.title_changed, t) for t in startup_session.tabs]
        self.active_tab_idx = startup_session.active_tab_idx
        self.tabbar_lock = Lock()
        self.tabbar_dirty = True
        self.color_profile = ColorProfile()
        self.color_profile.update_ansi_color_table(build_ansi_color_table(opts))

    def resize(self):
        for tab in self.tabs:
            tab.relayout()
        ncells = viewport_size.width // cell_size.width
        s = Screen(None, 1, ncells)
        s.reset_mode(DECAWM)
        self.sprite_map_type = (GLuint * (s.lines * s.columns * DATA_CELL_SIZE))
        with self.tabbar_lock:
            self.sprite_map = self.sprite_map_type()
            self.tab_bar_screen = s
            self.tabbar_dirty = True
        margin = (viewport_size.width - ncells * cell_size.width) // 2
        self.screen_geometry = calculate_gl_geometry(WindowGeometry(
            margin, viewport_size.height - cell_size.height, viewport_size.width - margin, viewport_size.height, s.columns, s.lines))
        self.screen = s

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

    def title_changed(self, new_title):
        with self.tabbar_lock:
            self.tabbar_dirty = True

    def remove(self, tab):
        ' Must be called in the GUI thread '
        self.tabs.remove(tab)
        tab.destroy()

    def update_tab_bar_data(self, sprites):
        s = self.tab_bar_screen
        for t in self.tabs:
            title = (t.title or appname)
            s.draw(title)
            if s.cursor.x > s.columns - 3:
                # TODO: Handle trailing wide character
                s.cursor.x = s.columns - 4
                s.draw('…')
            s.draw(' X┇')
            if s.cursor.x > s.columns - 5:
                s.draw('…')
                break
        s.update_cell_data(
            sprites.backend, self.color_profile, addressof(self.sprite_map), self.default_fg, self.default_bg, True)
        if self.buffer_id is None:
            self.buffer_id = sprites.add_sprite_map()
        sprites.set_sprite_map(self.buffer_id, self.sprite_map)

    def render(self, cell_program, sprites):
        if not hasattr(self, 'screen_geometry') or len(self.tabs) < 2:
            return
        with self.tabbar_lock:
            if self.tabbar_dirty:
                self.update_tab_bar_data(sprites)
        sprites.bind_sprite_map(self.buffer_id)
        ul, sg = cell_program.uniform_location, self.screen_geometry
        ul = cell_program.uniform_location
        glUniform2ui(ul('dimensions'), sg.xnum, sg.ynum)
        glUniform4f(ul('steps'), sg.xstart, sg.ystart, sg.dx, sg.dy)
        glUniform1i(ul('sprites'), sprites.sampler_num)
        glUniform1i(ul('sprite_map'), sprites.buffer_sampler_num)
        glUniform2f(ul('sprite_layout'), *(sprites.layout))
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, sg.xnum * sg.ynum)
