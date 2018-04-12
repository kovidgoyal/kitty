#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import weakref
from collections import deque, namedtuple
from functools import partial

from .borders import Borders
from .child import Child
from .config import build_ansi_color_table
from .constants import WindowGeometry, appname, get_boss, is_macos, is_wayland
from .fast_data_types import (
    DECAWM, Screen, add_tab, glfw_post_empty_event, remove_tab, remove_window,
    set_active_tab, set_tab_bar_render_data, swap_tabs, viewport_for_window,
    x11_window_id
)
from .layout import Rect, all_layouts
from .session import resolved_shell
from .utils import color_as_int, log_error
from .window import Window, calculate_gl_geometry

TabbarData = namedtuple('TabbarData', 'title is_active is_last')
SpecialWindowInstance = namedtuple('SpecialWindow', 'cmd stdin override_title cwd_from cwd overlay_for env')


def SpecialWindow(cmd, stdin=None, override_title=None, cwd_from=None, cwd=None, overlay_for=None, env=None):
    return SpecialWindowInstance(cmd, stdin, override_title, cwd_from, cwd, overlay_for, env)


class Tab:  # {{{

    def __init__(self, tab_manager, session_tab=None, special_window=None, cwd_from=None):
        self.tab_manager_ref = weakref.ref(tab_manager)
        self.os_window_id = tab_manager.os_window_id
        self.id = add_tab(self.os_window_id)
        if not self.id:
            raise Exception('No OS window with id {} found, or tab counter has wrapped'.format(self.os_window_id))
        self.opts, self.args = tab_manager.opts, tab_manager.args
        self.name = getattr(session_tab, 'name', '')
        self.enabled_layouts = [x.lower() for x in getattr(session_tab, 'enabled_layouts', None) or self.opts.enabled_layouts]
        self.borders = Borders(self.os_window_id, self.id, self.opts)
        self.windows = deque()
        self.active_window_idx = 0
        for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
            setattr(self, which + '_window', partial(self.nth_window, num=i))
        if session_tab is None:
            self.cwd = self.args.directory
            sl = self.enabled_layouts[0]
            self.current_layout = self.create_layout_object(sl)
            if special_window is None:
                self.new_window(cwd_from=cwd_from)
            else:
                self.new_special_window(special_window)
        else:
            self.cwd = session_tab.cwd or self.args.directory
            l0 = session_tab.layout
            self.current_layout = self.create_layout_object(l0)
            self.startup(session_tab)

    def startup(self, session_tab):
        for cmd in session_tab.windows:
            if isinstance(cmd, (SpecialWindowInstance,)):
                self.new_special_window(cmd)
            else:
                self.new_window(cmd=cmd)
        self.set_active_window_idx(session_tab.active_window_idx)

    @property
    def active_window(self):
        return self.windows[self.active_window_idx] if self.windows else None

    @property
    def title(self):
        return getattr(self.active_window, 'title', appname)

    def set_title(self, title):
        self.name = title or ''
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.title_changed(self.name)

    def title_changed(self, window):
        if window is self.active_window:
            tm = self.tab_manager_ref()
            if tm is not None:
                tm.title_changed(window.title)

    def visible_windows(self):
        for w in self.windows:
            if w.is_visible_in_layout:
                yield w

    def relayout(self):
        if self.windows:
            self.active_window_idx = self.current_layout(self.windows, self.active_window_idx)
        self.relayout_borders()

    def relayout_borders(self):
        tm = self.tab_manager_ref()
        if tm is not None:
            visible_windows = [w for w in self.windows if w.is_visible_in_layout]
            self.borders(visible_windows, self.active_window, self.current_layout,
                         tm.blank_rects, self.current_layout.needs_window_borders and len(visible_windows) > 1)

    def create_layout_object(self, idx):
        return all_layouts[idx](self.os_window_id, self.id, self.opts, self.borders.border_width)

    def next_layout(self):
        if len(self.enabled_layouts) > 1:
            try:
                idx = self.enabled_layouts.index(self.current_layout.name)
            except Exception:
                idx = -1
            nl = self.enabled_layouts[(idx + 1) % len(self.enabled_layouts)]
            self.current_layout = self.create_layout_object(nl)
            self.relayout()

    def goto_layout(self, layout_name):
        layout_name = layout_name.lower()
        if layout_name not in self.enabled_layouts:
            log_error('Unknown or disabled layout: {}'.format(layout_name))
            return
        self.current_layout = self.create_layout_object(layout_name)
        self.relayout()

    def launch_child(self, use_shell=False, cmd=None, stdin=None, cwd_from=None, cwd=None, env=None):
        if cmd is None:
            if use_shell:
                cmd = resolved_shell(self.opts)
            else:
                cmd = self.args.args or resolved_shell(self.opts)
        fenv = {}
        if env:
            fenv.update(env)
        if not is_macos and not is_wayland:
            try:
                fenv['WINDOWID'] = str(x11_window_id(self.os_window_id))
            except Exception:
                import traceback
                traceback.print_exc()
        ans = Child(cmd, cwd or self.cwd, self.opts, stdin, fenv, cwd_from)
        ans.fork()
        return ans

    def new_window(self, use_shell=True, cmd=None, stdin=None, override_title=None, cwd_from=None, cwd=None, overlay_for=None, env=None):
        child = self.launch_child(use_shell=use_shell, cmd=cmd, stdin=stdin, cwd_from=cwd_from, cwd=cwd, env=env)
        window = Window(self, child, self.opts, self.args, override_title=override_title)
        if overlay_for is not None:
            overlaid = next(w for w in self.windows if w.id == overlay_for)
            window.overlay_for = overlay_for
            overlaid.overlay_window_id = window.id
        # Must add child before laying out so that resize_pty succeeds
        get_boss().add_child(window)
        self.active_window_idx = self.current_layout.add_window(self.windows, window, self.active_window_idx)
        self.relayout_borders()
        glfw_post_empty_event()
        return window

    def new_special_window(self, special_window):
        return self.new_window(False, *special_window)

    def close_window(self):
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def remove_window(self, window):
        self.active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        remove_window(self.os_window_id, self.id, window.id)
        self.relayout_borders()
        glfw_post_empty_event()

    def set_active_window_idx(self, idx):
        if idx != self.active_window_idx:
            self.active_window_idx = self.current_layout.set_active_window(self.windows, idx)
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
            self.active_window_idx = self.current_layout.nth_window(self.windows, num)
            self.relayout_borders()
            glfw_post_empty_event()

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
        self.active_window_idx = self.current_layout.move_window(self.windows, self.active_window_idx, delta)
        self.relayout()
        glfw_post_empty_event()

    def move_window_to_top(self):
        self.move_window(-self.active_window_idx)

    def move_window_forward(self):
        self.move_window()

    def move_window_backward(self):
        self.move_window(-1)

    def list_windows(self):
        for w in self:
            yield w.as_dict()

    def matches(self, field, pat):
        if field == 'id':
            return pat.pattern == str(self.id)
        if field == 'title':
            return pat.search(self.name or self.title) is not None
        return False

    def __iter__(self):
        yield from iter(self.windows)

    def __len__(self):
        return len(self.windows)

    def __contains__(self, window):
        return window in self.windows

    def destroy(self):
        for w in self.windows:
            w.destroy()
        self.windows = deque()

    def __repr__(self):
        return 'Tab(title={}, id={})'.format(self.name or self.title, hex(id(self)))
# }}}


class TabBar:  # {{{

    def __init__(self, os_window_id, opts):
        self.os_window_id = os_window_id
        self.opts = opts
        self.num_tabs = 1
        self.cell_width = 1
        self.data_buffer_size = 0
        self.laid_out_once = False
        self.dirty = True
        self.screen = s = Screen(None, 1, 10)
        s.color_profile.update_ansi_color_table(build_ansi_color_table(opts))
        s.color_profile.set_configured_colors(
            color_as_int(opts.inactive_tab_foreground),
            color_as_int(opts.inactive_tab_background)
        )
        self.blank_rects = ()
        sep = opts.tab_separator
        self.trailing_spaces = self.leading_spaces = 0
        while sep and sep[0] == ' ':
            sep = sep[1:]
            self.trailing_spaces += 1
        while sep and sep[-1] == ' ':
            self.leading_spaces += 1
            sep = sep[:-1]
        self.sep = sep
        self.active_font_style = opts.active_tab_font_style
        self.inactive_font_style = opts.inactive_tab_font_style

        def as_rgb(x):
            return (x << 8) | 2

        self.active_bg = as_rgb(color_as_int(opts.active_tab_background))
        self.active_fg = as_rgb(color_as_int(opts.active_tab_foreground))

    def patch_colors(self, spec):
        if 'active_tab_foreground' in spec:
            self.active_fg = (spec['active_tab_foreground'] << 8) | 2
        if 'active_tab_background' in spec:
            self.active_bg = (spec['active_tab_background'] << 8) | 2
        self.screen.color_profile.set_configured_colors(
                spec.get('inactive_tab_foreground', color_as_int(self.opts.inactive_tab_foreground)),
                spec.get('inactive_tab_background', color_as_int(self.opts.inactive_tab_background))
        )

    def layout(self):
        central, tab_bar, vw, vh, cell_width, cell_height = viewport_for_window(self.os_window_id)
        if tab_bar.width < 2:
            return
        self.cell_width = cell_width
        s = self.screen
        viewport_width = tab_bar.width
        ncells = viewport_width // cell_width
        s.resize(1, ncells)
        s.reset_mode(DECAWM)
        self.laid_out_once = True
        margin = (viewport_width - ncells * cell_width) // 2
        self.window_geometry = g = WindowGeometry(
            margin, tab_bar.top, viewport_width - margin, tab_bar.bottom, s.columns, s.lines)
        if margin > 0:
            self.blank_rects = (Rect(0, g.top, g.left, g.bottom + 1), Rect(g.right - 1, g.top, viewport_width, g.bottom + 1))
        else:
            self.blank_rects = ()
        self.screen_geometry = sg = calculate_gl_geometry(g, vw, vh, cell_width, cell_height)
        set_tab_bar_render_data(self.os_window_id, sg.xstart, sg.ystart, sg.dx, sg.dy, self.screen)

    def update(self, data):
        if not self.laid_out_once:
            return
        s = self.screen
        s.cursor.x = 0
        s.erase_in_line(2, False)
        max_title_length = (self.screen_geometry.xnum // max(1, len(data))) - 1
        cr = []

        for t in data:
            s.cursor.bg = self.active_bg if t.is_active else 0
            s.cursor.fg = self.active_fg if t.is_active else 0
            s.cursor.bold, s.cursor.italic = self.active_font_style if t.is_active else self.inactive_font_style
            before = s.cursor.x
            s.draw(' ' * self.leading_spaces + t.title + ' ' * self.trailing_spaces)
            extra = s.cursor.x - before - max_title_length
            if extra > 0:
                s.cursor.x -= extra + 1
                s.draw('…')
            cr.append((before, s.cursor.x))
            s.cursor.bold = s.cursor.italic = False
            s.cursor.fg = s.cursor.bg = 0
            s.draw(self.sep)
            if s.cursor.x > s.columns - max_title_length and not t.is_last:
                s.draw('…')
                break
        s.erase_in_line(0, False)  # Ensure no long titles bleed after the last tab
        self.cell_ranges = cr
        glfw_post_empty_event()

    def destroy(self):
        self.screen.reset_callbacks()
        del self.screen

    def tab_at(self, x):
        x = (x - self.window_geometry.left) // self.cell_width
        for i, (a, b) in enumerate(self.cell_ranges):
            if a <= x <= b:
                return i
# }}}


class TabManager:  # {{{

    def __init__(self, os_window_id, opts, args, startup_session):
        self.os_window_id = os_window_id
        self.opts, self.args = opts, args
        self.tabs = []
        self.tab_bar = TabBar(self.os_window_id, opts)
        self.active_tab_idx = 0

        for t in startup_session.tabs:
            self._add_tab(Tab(self, session_tab=t))
        self._set_active_tab(max(0, min(startup_session.active_tab_idx, len(self.tabs) - 1)))
        self.update_tab_bar()

    def refresh_sprite_positions(self):
        self.tab_bar.screen.refresh_sprite_positions()

    def _add_tab(self, tab):
        before = len(self.tabs)
        self.tabs.append(tab)
        if len(self.tabs) > 1 and before < 2:
            self.tabbar_visibility_changed()

    def _remove_tab(self, tab):
        before = len(self.tabs)
        remove_tab(self.os_window_id, tab.id)
        self.tabs.remove(tab)
        if len(self.tabs) < 2 and before > 1:
            self.tabbar_visibility_changed()

    def _set_active_tab(self, idx):
        self.active_tab_idx = idx
        set_active_tab(self.os_window_id, idx)

    def tabbar_visibility_changed(self):
        self.tab_bar.layout()
        self.resize(only_tabs=True)
        glfw_post_empty_event()

    def update_tab_bar(self):
        if len(self.tabs) > 1:
            self.tab_bar.update(self.tab_bar_data)

    def resize(self, only_tabs=False):
        if not only_tabs:
            self.tab_bar.layout()
            self.update_tab_bar()
        for tab in self.tabs:
            tab.relayout()

    def set_active_tab_idx(self, idx):
        self._set_active_tab(idx)
        self.active_tab.relayout_borders()
        self.update_tab_bar()

    def set_active_tab(self, tab):
        try:
            idx = self.tabs.index(tab)
        except Exception:
            return
        self.set_active_tab_idx(idx)

    def next_tab(self, delta=1):
        if len(self.tabs) > 1:
            self.set_active_tab_idx((self.active_tab_idx + len(self.tabs) + delta) % len(self.tabs))

    def goto_tab(self, tab_num):
        if tab_num < len(self.tabs) and 0 <= tab_num:
            self.set_active_tab_idx(tab_num)

    def __iter__(self):
        return iter(self.tabs)

    def __len__(self):
        return len(self.tabs)

    def list_tabs(self):
        for tab in self:
            yield {
                'id': tab.id,
                'title': tab.name or tab.title,
                'windows': list(tab.list_windows()),
            }

    @property
    def active_tab(self):
        return self.tabs[self.active_tab_idx] if self.tabs else None

    @property
    def active_window(self):
        t = self.active_tab
        if t is not None:
            return t.active_window

    def tab_for_id(self, tab_id):
        for t in self.tabs:
            if t.id == tab_id:
                return t

    def move_tab(self, delta=1):
        if len(self.tabs) > 1:
            idx = self.active_tab_idx
            nidx = (idx + len(self.tabs) + delta) % len(self.tabs)
            self.tabs[idx], self.tabs[nidx] = self.tabs[nidx], self.tabs[idx]
            swap_tabs(self.os_window_id, idx, nidx)
            self._set_active_tab(nidx)
            self.update_tab_bar()

    def title_changed(self, new_title):
        self.update_tab_bar()

    def new_tab(self, special_window=None, cwd_from=None):
        idx = len(self.tabs)
        self._add_tab(Tab(self, special_window=special_window, cwd_from=cwd_from))
        self._set_active_tab(idx)
        self.update_tab_bar()
        return self.tabs[idx]

    def remove(self, tab):
        self._remove_tab(tab)
        self._set_active_tab(max(0, min(self.active_tab_idx, len(self.tabs) - 1)))
        self.update_tab_bar()
        tab.destroy()

    @property
    def tab_bar_data(self):
        at = self.active_tab
        ans = []
        for t in self.tabs:
            title = (t.name or t.title or appname).strip()
            ans.append(TabbarData(title, t is at, t is self.tabs[-1]))
        return ans

    def activate_tab_at(self, x):
        i = self.tab_bar.tab_at(x)
        if i is not None:
            self.set_active_tab_idx(i)

    @property
    def blank_rects(self):
        return self.tab_bar.blank_rects if len(self.tabs) > 1 else ()

    def destroy(self):
        for t in self:
            t.destroy()
        self.tab_bar.destroy()
        del self.tab_bar
        del self.tabs
# }}}
