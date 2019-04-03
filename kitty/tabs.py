#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import weakref
from collections import deque, namedtuple
from functools import partial

from .borders import Borders
from .child import Child
from .constants import appname, get_boss, is_macos, is_wayland
from .fast_data_types import (
    add_tab, mark_tab_bar_dirty, next_window_id,
    pt_to_px, remove_tab, remove_window, ring_bell, set_active_tab, swap_tabs,
    x11_window_id
)
from .layout import create_layout_object_for, evict_cached_layouts
from .session import resolved_shell
from .tab_bar import TabBar, TabBarData
from .utils import log_error
from .window import Window

SpecialWindowInstance = namedtuple('SpecialWindow', 'cmd stdin override_title cwd_from cwd overlay_for env')


def SpecialWindow(cmd, stdin=None, override_title=None, cwd_from=None, cwd=None, overlay_for=None, env=None):
    return SpecialWindowInstance(cmd, stdin, override_title, cwd_from, cwd, overlay_for, env)


def add_active_id_to_history(items, item_id, maxlen=64):
    try:
        items.remove(item_id)
    except ValueError:
        pass
    items.append(item_id)
    if len(items) > maxlen:
        items.popleft()


class Tab:  # {{{

    def __init__(self, tab_manager, session_tab=None, special_window=None, cwd_from=None):
        self._active_window_idx = 0
        self.tab_manager_ref = weakref.ref(tab_manager)
        self.os_window_id = tab_manager.os_window_id
        self.id = add_tab(self.os_window_id)
        self.active_window_history = deque()
        if not self.id:
            raise Exception('No OS window with id {} found, or tab counter has wrapped'.format(self.os_window_id))
        self.opts, self.args = tab_manager.opts, tab_manager.args
        self.margin_width, self.padding_width, self.single_window_margin_width = map(
            lambda x: pt_to_px(getattr(self.opts, x), self.os_window_id), (
                'window_margin_width', 'window_padding_width', 'single_window_margin_width'))
        self.name = getattr(session_tab, 'name', '')
        self.enabled_layouts = [x.lower() for x in getattr(session_tab, 'enabled_layouts', None) or self.opts.enabled_layouts]
        self.borders = Borders(self.os_window_id, self.id, self.opts, pt_to_px(self.opts.window_border_width, self.os_window_id), self.padding_width)
        self.windows = deque()
        for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
            setattr(self, which + '_window', partial(self.nth_window, num=i))
        self._last_used_layout = self._current_layout_name = None
        if session_tab is None:
            self.cwd = self.args.directory
            sl = self.enabled_layouts[0]
            self._set_current_layout(sl)
            if special_window is None:
                self.new_window(cwd_from=cwd_from)
            else:
                self.new_special_window(special_window)
        else:
            self.cwd = session_tab.cwd or self.args.directory
            l0 = session_tab.layout
            self._set_current_layout(l0)
            self.startup(session_tab)

    def _set_current_layout(self, layout_name):
        self._last_used_layout = self._current_layout_name
        self.current_layout = self.create_layout_object(layout_name)
        self._current_layout_name = layout_name

    def startup(self, session_tab):
        for cmd in session_tab.windows:
            if isinstance(cmd, (SpecialWindowInstance,)):
                self.new_special_window(cmd)
            else:
                self.new_window(cmd=cmd)
        self.set_active_window_idx(session_tab.active_window_idx)

    @property
    def active_window_idx(self):
        return self._active_window_idx

    @active_window_idx.setter
    def active_window_idx(self, val):
        try:
            old_active_window = self.windows[self._active_window_idx]
        except Exception:
            old_active_window = None
        else:
            wid = old_active_window.id if old_active_window.overlay_for is None else old_active_window.overlay_for
            add_active_id_to_history(self.active_window_history, wid)
        self._active_window_idx = max(0, min(val, len(self.windows) - 1))
        try:
            new_active_window = self.windows[self._active_window_idx]
        except Exception:
            new_active_window = None
        if old_active_window is not new_active_window:
            if old_active_window is not None:
                old_active_window.focus_changed(False)
            if new_active_window is not None:
                new_active_window.focus_changed(True)
            tm = self.tab_manager_ref()
            if tm is not None:
                self.relayout_borders()
                tm.mark_tab_bar_dirty()

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
            tm.mark_tab_bar_dirty()

    def title_changed(self, window):
        if window is self.active_window:
            tm = self.tab_manager_ref()
            if tm is not None:
                tm.mark_tab_bar_dirty()

    def on_bell(self, window):
        tm = self.tab_manager_ref()
        if tm is not None:
            self.relayout_borders()
            tm.mark_tab_bar_dirty()

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
            w = self.active_window
            self.borders(visible_windows, w, self.current_layout,
                         tm.blank_rects, self.current_layout.needs_window_borders and len(visible_windows) > 1)
            if w is not None:
                w.change_titlebar_color()

    def create_layout_object(self, name):
        return create_layout_object_for(
            name, self.os_window_id, self.id, self.margin_width,
            self.single_window_margin_width, self.padding_width,
            self.borders.border_width)

    def next_layout(self):
        if len(self.enabled_layouts) > 1:
            for i, layout_name in enumerate(self.enabled_layouts):
                if layout_name == self.current_layout.full_name:
                    idx = i
                    break
            else:
                idx = -1
            nl = self.enabled_layouts[(idx + 1) % len(self.enabled_layouts)]
            self._set_current_layout(nl)
            self.relayout()

    def last_used_layout(self):
        if len(self.enabled_layouts) > 1 and self._last_used_layout and self._last_used_layout != self._current_layout_name:
            self._set_current_layout(self._last_used_layout)
            self.relayout()

    def goto_layout(self, layout_name, raise_exception=False):
        layout_name = layout_name.lower()
        if layout_name not in self.enabled_layouts:
            if raise_exception:
                raise ValueError(layout_name)
            log_error('Unknown or disabled layout: {}'.format(layout_name))
            return
        self._set_current_layout(layout_name)
        self.relayout()

    def resize_window_by(self, window_id, increment, is_horizontal):
        increment_as_percent = self.current_layout.bias_increment_for_cell(is_horizontal) * increment
        if self.current_layout.modify_size_of_window(self.windows, window_id, increment_as_percent, is_horizontal):
            self.relayout()
            return
        return 'Could not resize'

    def resize_window(self, quality, increment):
        if increment < 1:
            raise ValueError(increment)
        is_horizontal = quality in ('wider', 'narrower')
        increment *= 1 if quality in ('wider', 'taller') else -1
        if self.resize_window_by(
                self.windows[self.active_window_idx].id,
                increment, is_horizontal) is not None:
            ring_bell()

    def reset_window_sizes(self):
        if self.current_layout.remove_all_biases():
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
        fenv['KITTY_WINDOW_ID'] = str(next_window_id())
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
        return window

    def new_special_window(self, special_window):
        return self.new_window(False, *special_window)

    def close_window(self):
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def previous_active_window_idx(self, num):
        try:
            old_window_id = self.active_window_history[-num]
        except IndexError:
            return
        for idx, w in enumerate(self.windows):
            if w.id == old_window_id:
                return idx

    def remove_window(self, window):
        idx = self.previous_active_window_idx(1)
        next_window_id = None
        if idx is not None:
            next_window_id = self.windows[idx].id
        active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        remove_window(self.os_window_id, self.id, window.id)
        if next_window_id is None and active_window_idx is not None and len(self.windows) > active_window_idx:
            next_window_id = self.windows[active_window_idx].id
        if next_window_id is not None:
            for idx, window in enumerate(self.windows):
                if window.id == next_window_id:
                    self.active_window_idx = self.current_layout.set_active_window(self.windows, idx)
                    break
            else:
                self.active_window_idx = active_window_idx
        else:
            self.active_window_idx = active_window_idx
        self.relayout_borders()
        active_window = self.active_window
        if active_window:
            self.title_changed(active_window)

    def set_active_window_idx(self, idx):
        if idx != self.active_window_idx:
            self.active_window_idx = self.current_layout.set_active_window(self.windows, idx)
            self.relayout_borders()

    def set_active_window(self, window):
        try:
            idx = self.windows.index(window)
        except ValueError:
            return
        self.set_active_window_idx(idx)

    def get_nth_window(self, n):
        if self.windows:
            return self.current_layout.nth_window(self.windows, n, make_active=False)

    def nth_window(self, num=0):
        if self.windows:
            if num < 0:
                idx = self.previous_active_window_idx(-num)
                if idx is None:
                    return
                self.active_window_idx = self.current_layout.set_active_window(self.windows, idx)
            else:
                self.active_window_idx = self.current_layout.nth_window(self.windows, num)
            self.relayout_borders()

    def _next_window(self, delta=1):
        if len(self.windows) > 1:
            self.active_window_idx = self.current_layout.next_window(self.windows, self.active_window_idx, delta)
            self.relayout_borders()

    def next_window(self):
        self._next_window()

    def previous_window(self):
        self._next_window(-1)

    prev_window = previous_window

    def neighboring_window(self, which):
        neighbors = self.current_layout.neighbors(self.windows, self.active_window_idx)
        candidates = neighbors.get(which)
        if candidates:
            self.active_window_idx = self.current_layout.set_active_window(self.windows, candidates[0])
            self.relayout_borders()

    def move_window(self, delta=1):
        self.active_window_idx = self.current_layout.move_window(self.windows, self.active_window_idx, delta)
        self.relayout()

    def move_window_to_top(self):
        self.move_window(-self.active_window_idx)

    def move_window_forward(self):
        self.move_window()

    def move_window_backward(self):
        self.move_window(-1)

    def list_windows(self, active_window):
        for w in self:
            yield w.as_dict(is_focused=w is active_window)

    def matches(self, field, pat):
        if field == 'id':
            return pat.pattern == str(self.id)
        if field == 'title':
            return pat.search(self.name or self.title) is not None
        return False

    def __iter__(self):
        return iter(self.windows)

    def __len__(self):
        return len(self.windows)

    def __contains__(self, window):
        return window in self.windows

    def destroy(self):
        evict_cached_layouts(self.id)
        for w in self.windows:
            w.destroy()
        self.windows = deque()

    def __repr__(self):
        return 'Tab(title={}, id={})'.format(self.name or self.title, hex(id(self)))
# }}}


class TabManager:  # {{{

    def __init__(self, os_window_id, opts, args, startup_session):
        self.os_window_id = os_window_id
        self.last_active_tab_id = None
        self.opts, self.args = opts, args
        self.tab_bar_hidden = self.opts.tab_bar_style == 'hidden'
        self.tabs = []
        self.active_tab_history = deque()
        self.tab_bar = TabBar(self.os_window_id, opts)
        self._active_tab_idx = 0

        for t in startup_session.tabs:
            self._add_tab(Tab(self, session_tab=t))
        self._set_active_tab(max(0, min(startup_session.active_tab_idx, len(self.tabs) - 1)))

    @property
    def active_tab_idx(self):
        return self._active_tab_idx

    @active_tab_idx.setter
    def active_tab_idx(self, val):
        try:
            old_active_tab = self.tabs[self._active_tab_idx]
        except Exception:
            old_active_tab = None
        else:
            add_active_id_to_history(self.active_tab_history, old_active_tab.id)
        self._active_tab_idx = max(0, min(val, len(self.tabs) - 1))
        try:
            new_active_tab = self.tabs[self._active_tab_idx]
        except Exception:
            new_active_tab = None
        if old_active_tab is not new_active_tab:
            if old_active_tab is not None:
                w = old_active_tab.active_window
                if w is not None:
                    w.focus_changed(False)
            if new_active_tab is not None:
                w = new_active_tab.active_window
                if w is not None:
                    w.focus_changed(True)

    def refresh_sprite_positions(self):
        if not self.tab_bar_hidden:
            self.tab_bar.screen.refresh_sprite_positions()

    @property
    def tab_bar_should_be_visible(self):
        return len(self.tabs) >= self.opts.tab_bar_min_tabs

    def _add_tab(self, tab):
        visible_before = self.tab_bar_should_be_visible
        self.tabs.append(tab)
        if not visible_before and self.tab_bar_should_be_visible:
            self.tabbar_visibility_changed()

    def _remove_tab(self, tab):
        visible_before = self.tab_bar_should_be_visible
        remove_tab(self.os_window_id, tab.id)
        self.tabs.remove(tab)
        if visible_before and not self.tab_bar_should_be_visible:
            self.tabbar_visibility_changed()

    def _set_active_tab(self, idx):
        self.active_tab_idx = idx
        set_active_tab(self.os_window_id, idx)

    def tabbar_visibility_changed(self):
        if not self.tab_bar_hidden:
            self.tab_bar.layout()
            self.resize(only_tabs=True)

    def mark_tab_bar_dirty(self):
        if self.tab_bar_should_be_visible and not self.tab_bar_hidden:
            mark_tab_bar_dirty(self.os_window_id)

    def update_tab_bar_data(self):
        self.tab_bar.update(self.tab_bar_data)

    def resize(self, only_tabs=False):
        if not only_tabs:
            if not self.tab_bar_hidden:
                self.tab_bar.layout()
                self.mark_tab_bar_dirty()
        for tab in self.tabs:
            tab.relayout()

    def set_active_tab_idx(self, idx):
        self._set_active_tab(idx)
        self.active_tab.relayout_borders()
        self.mark_tab_bar_dirty()

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
        elif tab_num < 0:
            try:
                old_active_tab_id = self.active_tab_history[tab_num]
            except IndexError:
                return
            for idx, tab in enumerate(self.tabs):
                if tab.id == old_active_tab_id:
                    self.set_active_tab_idx(idx)
                    break

    def __iter__(self):
        return iter(self.tabs)

    def __len__(self):
        return len(self.tabs)

    def list_tabs(self, active_tab, active_window):
        for tab in self:
            yield {
                'id': tab.id,
                'is_focused': tab is active_tab,
                'title': tab.name or tab.title,
                'layout': tab.current_layout.name,
                'windows': list(tab.list_windows(active_window)),
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
            step = 1 if idx < nidx else -1
            for i in range(idx, nidx, step):
                self.tabs[i], self.tabs[i + step] = self.tabs[i + step], self.tabs[i]
                swap_tabs(self.os_window_id, i, i + step)
            self._set_active_tab(nidx)
            self.mark_tab_bar_dirty()

    def new_tab(self, special_window=None, cwd_from=None, as_neighbor=False):
        nidx = self.active_tab_idx + 1
        idx = len(self.tabs)
        self._add_tab(Tab(self, special_window=special_window, cwd_from=cwd_from))
        self._set_active_tab(idx)
        if len(self.tabs) > 2 and as_neighbor and idx != nidx:
            for i in range(idx, nidx, -1):
                self.tabs[i], self.tabs[i-1] = self.tabs[i-1], self.tabs[i]
                swap_tabs(self.os_window_id, i, i-1)
            self._set_active_tab(nidx)
            idx = nidx
        self.mark_tab_bar_dirty()
        return self.tabs[idx]

    def remove(self, tab):
        self._remove_tab(tab)
        next_active_tab = -1
        while True:
            try:
                self.active_tab_history.remove(tab.id)
            except ValueError:
                break

        if self.opts.tab_switch_strategy == 'previous':
            while self.active_tab_history and next_active_tab < 0:
                tab_id = self.active_tab_history.pop()
                for idx, qtab in enumerate(self.tabs):
                    if qtab.id == tab_id:
                        next_active_tab = idx
                        break
        elif self.opts.tab_switch_strategy == 'left':
            next_active_tab = max(0, self.active_tab_idx - 1)

        if next_active_tab < 0:
            next_active_tab = max(0, min(self.active_tab_idx, len(self.tabs) - 1))

        self._set_active_tab(next_active_tab)
        self.mark_tab_bar_dirty()
        tab.destroy()

    @property
    def tab_bar_data(self):
        at = self.active_tab
        ans = []
        for t in self.tabs:
            title = (t.name or t.title or appname).strip()
            needs_attention = False
            for w in t:
                if w.needs_attention:
                    needs_attention = True
                    break
            ans.append(TabBarData(title, t is at, needs_attention))
        return ans

    def activate_tab_at(self, x):
        i = self.tab_bar.tab_at(x)
        if i is not None:
            self.set_active_tab_idx(i)

    @property
    def blank_rects(self):
        return self.tab_bar.blank_rects if self.tab_bar_should_be_visible else ()

    def destroy(self):
        for t in self:
            t.destroy()
        self.tab_bar.destroy()
        del self.tab_bar
        del self.tabs
# }}}
