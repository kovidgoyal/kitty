#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import deque, namedtuple
from functools import partial
from itertools import count

from .borders import Borders
from .child import Child
from .config import build_ansi_color_table
from .constants import (
    WindowGeometry, appname, cell_size, get_boss, shell_path, viewport_size
)
from .fast_data_types import (
    DECAWM, Screen, add_tab, add_window, create_cell_vao,
    glfw_post_empty_event, remove_tab, remove_window, set_active_tab,
    set_active_window, set_tab_bar_render_data, swap_tabs, swap_windows
)
from .layout import Rect, all_layouts
from .utils import color_as_int
from .window import Window, calculate_gl_geometry

TabbarData = namedtuple('TabbarData', 'title is_active is_last')
borders = None
tab_counter = count()
next(tab_counter)


def SpecialWindow(cmd, stdin=None, override_title=None):
    return (cmd, stdin, override_title)


class Tab:  # {{{

    def __init__(self, opts, args, on_title_change, session_tab=None, special_window=None):
        global borders
        self.id = next(tab_counter)
        add_tab(self.id)
        self.opts, self.args = opts, args
        self.name = getattr(session_tab, 'name', '')
        self.on_title_change = on_title_change
        self.enabled_layouts = list(getattr(session_tab, 'enabled_layouts', None) or opts.enabled_layouts)
        if borders is None:
            borders = Borders(opts)
        self.windows = deque()
        self.active_window_idx = 0
        for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
            setattr(self, which + '_window', partial(self.nth_window, num=i))
        if session_tab is None:
            self.cwd = args.directory
            l = self.enabled_layouts[0]
            self.current_layout = all_layouts[l](opts, borders.border_width, self.windows)
            if special_window is None:
                self.new_window()
            else:
                self.new_special_window(special_window)
        else:
            self.cwd = session_tab.cwd or args.directory
            l = session_tab.layout
            self.current_layout = all_layouts[l](opts, borders.border_width, self.windows)
            self.startup(session_tab)

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
        borders(self.windows, self.active_window, self.current_layout, tm.blank_rects,
                self.current_layout.needs_window_borders and len(self.windows) > 1)

    def pipe_selection_to_new_tab(self, args):
        text = self.active_window.text_for_selection()
        if text:
          get_boss().tab_manager.new_tab(
              special_window=SpecialWindow(
                  cmd=args, stdin=text.encode('utf-8')))
        
    def next_layout(self):
        if len(self.opts.enabled_layouts) > 1:
            try:
                idx = self.opts.enabled_layouts.index(self.current_layout.name)
            except Exception:
                idx = -1
            nl = self.opts.enabled_layouts[(idx + 1) % len(self.opts.enabled_layouts)]
            self.current_layout = all_layouts[nl](self.opts, borders.border_width, self.windows)
            for i, w in enumerate(self.windows):
                w.set_visible_in_layout(i, True)
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
        # Must add child before laying out so that resize_pty succeeds
        get_boss().add_child(window)
        add_window(self.id, window.id, window.override_title or window.title or appname)
        self.active_window_idx = self.current_layout.add_window(self.windows, window, self.active_window_idx)
        set_active_window(self.id, self.active_window_idx)
        self.relayout_borders()
        glfw_post_empty_event()
        return window

    def new_special_window(self, special_window):
        self.new_window(False, *special_window)

    def close_window(self):
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def remove_window(self, window):
        remove_window(self.id, window.id)
        self.active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        set_active_window(self.id, self.active_window_idx)
        self.relayout_borders()
        glfw_post_empty_event()

    def set_active_window_idx(self, idx):
        if idx != self.active_window_idx:
            self.current_layout.set_active_window(self.windows, idx)
            self.active_window_idx = idx
            set_active_window(self.id, self.active_window_idx)
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
            set_active_window(self.id, self.active_window_idx)
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
            swap_windows(self.id, nidx, idx)
            self.active_window_idx = nidx
            set_active_window(self.id, self.active_window_idx)
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
        self.windows = deque()

    def __repr__(self):
        return 'Tab(title={}, id={})'.format(self.name or self.title, hex(id(self)))
# }}}


class TabBar:  # {{{

    def __init__(self, opts):
        self.num_tabs = 1
        self.cell_width = 1
        self.data_buffer_size = 0
        self.vao_id = create_cell_vao()
        self.layout_changed = None
        self.dirty = True
        self.screen = s = Screen(None, 1, 10)
        s.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        s.color_profile.set_configured_colors(
            color_as_int(opts.inactive_tab_foreground),
            color_as_int(opts.inactive_tab_background)
        )
        self.blank_rects = ()

        def as_rgb(x):
            return (x << 8) | 2

        self.active_bg = as_rgb(color_as_int(opts.active_tab_background))
        self.active_fg = as_rgb(color_as_int(opts.active_tab_foreground))

    def layout(self, viewport_width, viewport_height, cell_width, cell_height):
        self.cell_width = cell_width
        s = self.screen
        ncells = viewport_width // cell_width
        s.resize(1, ncells)
        s.reset_mode(DECAWM)
        self.layout_changed = True
        margin = (viewport_width - ncells * cell_width) // 2
        self.window_geometry = g = WindowGeometry(
            margin, viewport_height - cell_height, viewport_width - margin, viewport_height, s.columns, s.lines)
        if margin > 0:
            self.tab_bar_blank_rects = (Rect(0, g.top, g.left, g.bottom), Rect(g.right - 1, g.top, viewport_width, g.bottom))
        else:
            self.tab_bar_blank_rects = ()
        self.screen_geometry = sg = calculate_gl_geometry(g, viewport_width, viewport_height, cell_width, cell_height)
        set_tab_bar_render_data(self.vao_id, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen)

    def update(self, data):
        if self.layout_changed is None:
            return
        s = self.screen
        s.cursor.x = 0
        s.erase_in_line(2, False)
        max_title_length = (self.screen_geometry.xnum // max(1, len(data))) - 1
        cr = []

        for t in data:
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
        self.cell_ranges = cr
        glfw_post_empty_event()

    def tab_at(self, x):
        x = (x - self.window_geometry.left) // self.cell_width
        for i, (a, b) in enumerate(self.cell_ranges):
            if a <= x <= b:
                return i
# }}}


class TabManager:  # {{{

    def __init__(self, opts, args):
        self.opts, self.args = opts, args
        self.tabs = []
        self.tab_bar = TabBar(opts)
        self.refresh_sprite_positions = self.tab_bar.screen.refresh_sprite_positions
        self.tab_bar.layout(*self.tab_bar_layout_data)
        self.active_tab_idx = 0

    def _add_tab(self, tab):
        self.tabs.append(tab)

    def _remove_tab(self, tab):
        remove_tab(tab.id)
        self.tabs.remove(tab)

    def _set_active_tab(self, idx):
        self.active_tab_idx = idx
        set_active_tab(idx)

    def init(self, startup_session):
        for t in startup_session.tabs:
            self._add_tab(Tab(self.opts, self.args, self.title_changed, t))
        self._set_active_tab(max(0, min(startup_session.active_tab_idx, len(self.tabs) - 1)))
        if len(self.tabs) > 1:
            get_boss().tabbar_visibility_changed()
        self.update_tab_bar()

    def update_tab_bar(self):
        if len(self.tabs) > 1:
            self.tab_bar.update(self.tab_bar_data)

    def resize(self, only_tabs=False):
        if not only_tabs:
            self.tab_bar.layout(*self.tab_bar_layout_data)
            self.update_tab_bar()
        for tab in self.tabs:
            tab.relayout()

    def set_active_tab(self, idx):
        self._set_active_tab(idx)
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
            swap_tabs(idx, nidx)
            self._set_active_tab(nidx)
            self.update_tab_bar()

    def title_changed(self, new_title):
        self.update_tab_bar()

    def new_tab(self, special_window=None):
        needs_resize = len(self.tabs) == 1
        idx = len(self.tabs)
        self._add_tab(Tab(self.opts, self.args, self.title_changed, special_window=special_window))
        self._set_active_tab(idx)
        self.update_tab_bar()
        if needs_resize:
            get_boss().tabbar_visibility_changed()

    def remove(self, tab):
        needs_resize = len(self.tabs) == 2
        self._remove_tab(tab)
        self._set_active_tab(max(0, min(self.active_tab_idx, len(self.tabs) - 1)))
        self.update_tab_bar()
        tab.destroy()
        if needs_resize:
            get_boss().tabbar_visibility_changed()

    @property
    def tab_bar_layout_data(self):
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
        return self.tab_bar.blank_rects if len(self.tabs) > 1 else ()

    def render(self):
        if len(self.tabs) < 2:
            return
        self.tab_bar.render()
# }}}
