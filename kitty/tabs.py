#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque, namedtuple
from ctypes import addressof
from functools import partial
from queue import Queue, Empty

from .borders import Borders
from .char_grid import calculate_gl_geometry, render_cells
from .child import Child
from .config import build_ansi_color_table
from .constants import (
    GLuint, WindowGeometry, appname, cell_size, get_boss, queue_action,
    shell_path, viewport_size
)
from .fast_data_types import (
    DATA_CELL_SIZE, DECAWM, Screen, glfw_post_empty_event
)
from .layout import Rect, all_layouts
from .utils import color_as_int
from .window import Window


TabbarData = namedtuple('TabbarData', 'title is_active is_last')


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
        for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
            setattr(self, which + '_window', partial(self.nth_window, num=i))
        if session_tab is None:
            self.cwd = args.directory
            l = self.enabled_layouts[0]
            self.current_layout = all_layouts[l](opts, self.borders.border_width, self.windows)
            if special_window is None:
                queue_action(self.new_window)
            else:
                queue_action(self.new_special_window, special_window)
        else:
            self.cwd = session_tab.cwd or args.directory
            l = session_tab.layout
            self.current_layout = all_layouts[l](opts, self.borders.border_width, self.windows)
            queue_action(self.startup, session_tab)

    def startup(self, session_tab):
        for cmd in session_tab.windows:
            self.new_window(cmd=cmd)
        self.set_active_window_idx(session_tab.active_window_idx)

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
        tm = get_boss().tab_manager
        self.borders(self.windows, self.active_window, self.current_layout, tm.blank_rects,
                     self.current_layout.needs_window_borders and len(self.windows) > 1)

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
        get_boss().add_child_fd(child.child_fd, window)
        self.active_window_idx = self.current_layout.add_window(self.windows, window, self.active_window_idx)
        self.relayout_borders()
        glfw_post_empty_event()
        return window

    def new_special_window(self, special_window):
        self.new_window(False, *special_window)

    def close_window(self):
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def remove_window(self, window):
        self.active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        self.relayout_borders()
        glfw_post_empty_event()

    def set_active_window_idx(self, idx):
        if idx != self.active_window_idx:
            self.current_layout.set_active_window(self.windows, idx)
            self.active_window_idx = idx
            self.relayout_borders()
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
            self.relayout_borders()
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


class TabBar:

    def __init__(self, data, opts):
        self.num_tabs = 1
        self.cell_width = 1
        self.queue = Queue()
        self.vao_id = None
        self.render_buf = self.selection_buf = None
        self.selection_buf_changed = True
        self.dirty = True
        self.screen = s = Screen(None, 1, 10)
        s.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        s.color_profile.set_configured_colors(
            color_as_int(opts.inactive_tab_foreground),
            color_as_int(opts.inactive_tab_background)
        )
        s.color_profile.dirty = True
        self.blank_rects = ()
        self.current_data = data

        def as_rgb(x):
            return (x << 8) | 2

        self.active_bg = as_rgb(color_as_int(opts.active_tab_background))
        self.active_fg = as_rgb(color_as_int(opts.active_tab_foreground))

    def layout(self, viewport_width, viewport_height, cell_width, cell_height):
        ' Must be called in the child thread '
        self.cell_width = cell_width
        s = self.screen
        ncells = viewport_width // cell_width
        s.resize(1, ncells)
        s.reset_mode(DECAWM)
        self.render_buf = (GLuint * (s.lines * s.columns * DATA_CELL_SIZE))()
        self.selection_buf = (GLuint * (s.lines * s.columns))()
        self.selection_buf_changed = True
        margin = (viewport_width - ncells * cell_width) // 2
        self.window_geometry = g = WindowGeometry(
            margin, viewport_height - cell_height, viewport_width - margin, viewport_height, s.columns, s.lines)
        if margin > 0:
            self.tab_bar_blank_rects = (Rect(0, g.top, g.left, g.bottom), Rect(g.right - 1, g.top, viewport_width, g.bottom))
        else:
            self.tab_bar_blank_rects = ()
        self.screen_geometry = calculate_gl_geometry(g, viewport_width, viewport_height, cell_width, cell_height)
        self.update()

    def update(self):
        ' Must be called in the child thread '
        if self.render_buf is None:
            return
        s = self.screen
        s.cursor.x = 0
        s.erase_in_line(2, False)
        while True:
            try:
                self.current_data = self.queue.get_nowait()
            except Empty:
                break
        max_title_length = (self.screen_geometry.xnum // len(self.current_data)) - 1
        cr = []

        for t in self.current_data:
            s.cursor.bg = self.active_bg if t.is_active else 0
            s.cursor.fg = self.active_fg if t.is_active else 0
            s.cursor.bold = s.cursor.italic = t.is_active
            before = s.cursor.x
            s.draw(t.title)
            extra = s.cursor.x - before - max_title_length
            if extra > 0:
                s.cursor.x -= extra + 1
                s.draw('…')
            cr.append((before, s.cursor.x))
            s.cursor.bold = s.cursor.italic = False
            s.cursor.fg = s.cursor.bg = 0
            s.draw('┇')
            if s.cursor.x > s.columns - max_title_length and not t.is_last:
                s.draw('…')
                break
        s.erase_in_line(0, False)  # Ensure no long titles bleed after the last tab
        sprites = get_boss().sprites
        s.update_cell_data(sprites.backend, addressof(self.render_buf), True)
        self.cell_ranges = cr
        self.dirty = True
        glfw_post_empty_event()

    def schedule_layout(self, data):
        ' Must be called in the GUI thread '
        queue_action(self.layout, *data)

    def schedule_update(self, data):
        ' Must be called in the GUI thread '
        self.queue.put(data)
        queue_action(self.update)

    def render(self, cell_program, sprites):
        ' Must be called in the GUI thread '
        if self.render_buf is not None:
            sprites.render_dirty_cells()
            if self.vao_id is None:
                self.vao_id = cell_program.create_sprite_map()
            if self.dirty:
                cell_program.send_vertex_data(self.vao_id, self.render_buf)
                if self.selection_buf_changed:
                    cell_program.send_vertex_data(self.vao_id, self.selection_buf, bufnum=1)
                    self.selection_buf_changed = False
                self.dirty = False
            render_cells(self.vao_id, self.screen_geometry, cell_program, sprites, self.screen.color_profile)

    def tab_at(self, x):
        ' Must be called in the GUI thread '
        x = (x - self.window_geometry.left) // self.cell_width
        for i, (a, b) in enumerate(self.cell_ranges):
            if a <= x <= b:
                return i


class TabManager:

    def __init__(self, opts, args, startup_session):
        self.opts, self.args = opts, args
        self.tabs = [Tab(opts, args, self.title_changed, t) for t in startup_session.tabs]
        self.active_tab_idx = startup_session.active_tab_idx
        self.tab_bar = TabBar(self.tab_bar_data, opts)
        self.tab_bar.schedule_layout(self.tab_bar_layout_data)

    def update_tab_bar(self):
        if len(self.tabs) > 1:
            self.tab_bar.schedule_update(self.tab_bar_data)

    def resize(self, only_tabs=False):
        if not only_tabs:
            self.tab_bar.schedule_layout(self.tab_bar_layout_data)
        for tab in self.tabs:
            tab.relayout()

    def set_active_tab(self, idx):
        self.active_tab_idx = idx
        self.active_tab.relayout_borders()
        self.update_tab_bar()

    def next_tab(self, delta=1):
        if len(self.tabs) > 1:
            self.set_active_tab((self.active_tab_idx + len(self.tabs) + delta) % len(self.tabs))

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

    def move_tab(self, delta=1):
        if len(self.tabs) > 1:
            idx = self.active_tab_idx
            nidx = (idx + len(self.tabs) + delta) % len(self.tabs)
            self.tabs[idx], self.tabs[nidx] = self.tabs[nidx], self.tabs[idx]
            self.active_tab_idx = nidx
            self.update_tab_bar()

    def title_changed(self, new_title):
        self.update_tab_bar()

    def new_tab(self, special_window=None):
        ' Must be called in the GUI thread '
        needs_resize = len(self.tabs) == 1
        self.active_tab_idx = len(self.tabs)
        self.tabs.append(Tab(self.opts, self.args, self.title_changed, special_window=special_window))
        self.update_tab_bar()
        if needs_resize:
            queue_action(get_boss().tabbar_visibility_changed)

    def remove(self, tab):
        ' Must be called in the GUI thread '
        needs_resize = len(self.tabs) == 2
        self.tabs.remove(tab)
        self.active_tab_idx = max(0, min(self.active_tab_idx, len(self.tabs) - 1))
        self.update_tab_bar()
        tab.destroy()
        if needs_resize:
            queue_action(get_boss().tabbar_visibility_changed)

    @property
    def tab_bar_layout_data(self):
        ' Must be called in the GUI thread '
        return viewport_size.width, viewport_size.height, cell_size.width, cell_size.height

    @property
    def tab_bar_data(self):
        at = self.active_tab
        ans = []
        for t in self.tabs:
            title = (t.name or t.title or appname) + ' '
            ans.append(TabbarData(title, t is at, t is self.tabs[-1]))
        return ans

    def activate_tab_at(self, x):
        i = self.tab_bar.tab_at(x)
        if i is not None:
            self.set_active_tab(i)

    @property
    def blank_rects(self):
        return self.tab_bar.blank_rects if len(self.tabs) < 2 else ()

    def render(self, cell_program, sprites):
        ' Must be called in the GUI thread '
        if len(self.tabs) < 2:
            return
        self.tab_bar.render(cell_program, sprites)
