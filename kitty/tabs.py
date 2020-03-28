#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import weakref
from collections import deque
from contextlib import suppress
from functools import partial
from typing import (
    Deque, Dict, Generator, Iterator, List, NamedTuple,
    Optional, Pattern, Sequence, Tuple, cast
)

from .borders import Borders
from .child import Child
from .cli_stub import CLIOptions
from .constants import appname, is_macos, is_wayland
from .fast_data_types import (
    add_tab, attach_window, detach_window, get_boss, mark_tab_bar_dirty,
    next_window_id, pt_to_px, remove_tab, remove_window, ring_bell,
    set_active_tab, swap_tabs, x11_window_id
)
from .layout import (
    Layout, Rect, create_layout_object_for, evict_cached_layouts
)
from .options_stub import Options
from .tab_bar import TabBar, TabBarData
from .utils import log_error, resolved_shell
from .window import Window, WindowDict, Watchers
from .typing import TypedDict, SessionTab, SessionType


class TabDict(TypedDict):
    id: int
    is_focused: bool
    title: str
    layout: str
    windows: List[WindowDict]
    active_window_history: List[int]


class SpecialWindowInstance(NamedTuple):
    cmd: Optional[List[str]]
    stdin: Optional[bytes]
    override_title: Optional[str]
    cwd_from: Optional[int]
    cwd: Optional[str]
    overlay_for: Optional[int]
    env: Optional[Dict[str, str]]


def SpecialWindow(
    cmd: Optional[List[str]],
    stdin: Optional[bytes] = None,
    override_title: Optional[str] = None,
    cwd_from: Optional[int] = None,
    cwd: Optional[str] = None,
    overlay_for: Optional[int] = None,
    env: Optional[Dict[str, str]] = None
) -> SpecialWindowInstance:
    return SpecialWindowInstance(cmd, stdin, override_title, cwd_from, cwd, overlay_for, env)


def add_active_id_to_history(items: Deque[int], item_id: int, maxlen: int = 64) -> None:
    with suppress(ValueError):
        items.remove(item_id)
    items.append(item_id)
    if len(items) > maxlen:
        items.popleft()


class Tab:  # {{{

    def __init__(
        self,
        tab_manager: 'TabManager',
        session_tab: Optional['SessionTab'] = None,
        special_window: Optional[SpecialWindowInstance] = None,
        cwd_from: Optional[int] = None,
        no_initial_window: bool = False
    ):
        self._active_window_idx = 0
        self.tab_manager_ref = weakref.ref(tab_manager)
        self.os_window_id: int = tab_manager.os_window_id
        self.id: int = add_tab(self.os_window_id)
        self.active_window_history: Deque[int] = deque()
        if not self.id:
            raise Exception('No OS window with id {} found, or tab counter has wrapped'.format(self.os_window_id))
        self.opts, self.args = tab_manager.opts, tab_manager.args
        self.recalculate_sizes(update_layout=False)
        self.name = getattr(session_tab, 'name', '')
        self.enabled_layouts = [x.lower() for x in getattr(session_tab, 'enabled_layouts', None) or self.opts.enabled_layouts]
        self.borders = Borders(self.os_window_id, self.id, self.opts)
        self.windows: Deque[Window] = deque()
        for i, which in enumerate('first second third fourth fifth sixth seventh eighth ninth tenth'.split()):
            setattr(self, which + '_window', partial(self.nth_window, num=i))
        self._last_used_layout: Optional[str] = None
        self._current_layout_name: Optional[str] = None
        self.cwd = self.args.directory
        if no_initial_window:
            self._set_current_layout(self.enabled_layouts[0])
        elif session_tab is None:
            sl = self.enabled_layouts[0]
            self._set_current_layout(sl)
            if special_window is None:
                self.new_window(cwd_from=cwd_from)
            else:
                self.new_special_window(special_window)
        else:
            if session_tab.cwd:
                self.cwd = session_tab.cwd
            l0 = session_tab.layout
            self._set_current_layout(l0)
            self.startup(session_tab)

    def recalculate_sizes(self, update_layout: bool = True) -> None:
        self.margin_width, self.padding_width, self.single_window_margin_width = map(
            lambda x: pt_to_px(getattr(self.opts, x), self.os_window_id), (
                'window_margin_width', 'window_padding_width', 'single_window_margin_width'))
        self.border_width = pt_to_px(self.opts.window_border_width, self.os_window_id)
        if update_layout and self.current_layout:
            self.current_layout.update_sizes(
                self.margin_width, self.single_window_margin_width, self.padding_width, self.border_width)

    def take_over_from(self, other_tab: 'Tab') -> None:
        self.name, self.cwd = other_tab.name, other_tab.cwd
        self.enabled_layouts = list(other_tab.enabled_layouts)
        if other_tab._current_layout_name:
            self._set_current_layout(other_tab._current_layout_name)
        self._last_used_layout = other_tab._last_used_layout

        orig_windows = deque(other_tab.windows)
        orig_history = deque(other_tab.active_window_history)
        orig_active = other_tab._active_window_idx
        for window in other_tab.windows:
            detach_window(other_tab.os_window_id, other_tab.id, window.id)
        other_tab.windows = deque()
        other_tab._active_window_idx = 0
        self.active_window_history = orig_history
        self.windows = orig_windows
        self._active_window_idx = orig_active
        for window in self.windows:
            window.change_tab(self)
            attach_window(self.os_window_id, self.id, window.id)
        self.relayout()

    def _set_current_layout(self, layout_name: str) -> None:
        self._last_used_layout = self._current_layout_name
        self.current_layout = self.create_layout_object(layout_name)
        self._current_layout_name = layout_name

    def startup(self, session_tab: 'SessionTab') -> None:
        for cmd in session_tab.windows:
            if isinstance(cmd, (SpecialWindowInstance,)):
                self.new_special_window(cmd)
            else:
                self.new_window(cmd=cmd)
        self.set_active_window_idx(session_tab.active_window_idx)

    @property
    def active_window_idx(self) -> int:
        return self._active_window_idx

    @active_window_idx.setter
    def active_window_idx(self, val: int) -> None:
        try:
            old_active_window: Optional[Window] = self.windows[self._active_window_idx]
        except Exception:
            old_active_window = None
        else:
            assert old_active_window is not None
            wid = old_active_window.id if old_active_window.overlay_for is None else old_active_window.overlay_for
            add_active_id_to_history(self.active_window_history, wid)
        self._active_window_idx = max(0, min(val, len(self.windows) - 1))
        try:
            new_active_window: Optional[Window] = self.windows[self._active_window_idx]
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
    def active_window(self) -> Optional[Window]:
        return self.windows[self.active_window_idx] if self.windows else None

    @property
    def title(self) -> str:
        return cast(str, getattr(self.active_window, 'title', appname))

    def set_title(self, title: str) -> None:
        self.name = title or ''
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.mark_tab_bar_dirty()

    def title_changed(self, window: Window) -> None:
        if window is self.active_window:
            tm = self.tab_manager_ref()
            if tm is not None:
                tm.mark_tab_bar_dirty()

    def on_bell(self, window: Window) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            self.relayout_borders()
            tm.mark_tab_bar_dirty()

    def visible_windows(self) -> Generator[Window, None, None]:
        for w in self.windows:
            if w.is_visible_in_layout:
                yield w

    def relayout(self) -> None:
        if self.windows:
            self.active_window_idx = self.current_layout(self.windows, self.active_window_idx)
        self.relayout_borders()

    def relayout_borders(self) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            visible_windows = [w for w in self.windows if w.is_visible_in_layout]
            w = self.active_window
            self.borders(
                windows=visible_windows, active_window=w,
                current_layout=self.current_layout, extra_blank_rects=tm.blank_rects,
                padding_width=self.padding_width, border_width=self.border_width,
                draw_window_borders=self.current_layout.needs_window_borders and len(visible_windows) > 1
            )
            if w is not None:
                w.change_titlebar_color()

    def create_layout_object(self, name: str) -> Layout:
        return create_layout_object_for(
            name, self.os_window_id, self.id, self.margin_width,
            self.single_window_margin_width, self.padding_width,
            self.border_width)

    def next_layout(self) -> None:
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

    def last_used_layout(self) -> None:
        if len(self.enabled_layouts) > 1 and self._last_used_layout and self._last_used_layout != self._current_layout_name:
            self._set_current_layout(self._last_used_layout)
            self.relayout()

    def goto_layout(self, layout_name: str, raise_exception: bool = False) -> None:
        layout_name = layout_name.lower()
        if layout_name not in self.enabled_layouts:
            if raise_exception:
                raise ValueError(layout_name)
            log_error('Unknown or disabled layout: {}'.format(layout_name))
            return
        self._set_current_layout(layout_name)
        self.relayout()

    def resize_window_by(self, window_id: int, increment: float, is_horizontal: bool) -> Optional[str]:
        increment_as_percent = self.current_layout.bias_increment_for_cell(is_horizontal) * increment
        if self.current_layout.modify_size_of_window(self.windows, window_id, increment_as_percent, is_horizontal):
            self.relayout()
            return None
        return 'Could not resize'

    def resize_window(self, quality: str, increment: int) -> None:
        if increment < 1:
            raise ValueError(increment)
        is_horizontal = quality in ('wider', 'narrower')
        increment *= 1 if quality in ('wider', 'taller') else -1
        if self.resize_window_by(
                self.windows[self.active_window_idx].id,
                increment, is_horizontal) is not None:
            ring_bell()

    def reset_window_sizes(self) -> None:
        if self.current_layout.remove_all_biases():
            self.relayout()

    def layout_action(self, action_name: str, args: Sequence[str]) -> None:
        ret = self.current_layout.layout_action(action_name, args, self.windows, self.active_window_idx)
        if ret is None:
            ring_bell()
            return
        if not isinstance(ret, bool) and isinstance(ret, int):
            self.active_window_idx = ret
        self.relayout()

    def launch_child(
        self,
        use_shell: bool = False,
        cmd: Optional[List[str]] = None,
        stdin: Optional[bytes] = None,
        cwd_from: Optional[int] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        allow_remote_control: bool = False
    ) -> Child:
        if cmd is None:
            if use_shell:
                cmd = resolved_shell(self.opts)
            else:
                cmd = self.args.args or resolved_shell(self.opts)
        fenv: Dict[str, str] = {}
        if env:
            fenv.update(env)
        fenv['KITTY_WINDOW_ID'] = str(next_window_id())
        if not is_macos and not is_wayland():
            try:
                fenv['WINDOWID'] = str(x11_window_id(self.os_window_id))
            except Exception:
                import traceback
                traceback.print_exc()
        ans = Child(cmd, cwd or self.cwd, self.opts, stdin, fenv, cwd_from, allow_remote_control=allow_remote_control)
        ans.fork()
        return ans

    def _add_window(self, window: Window, location: Optional[str] = None) -> None:
        self.active_window_idx = self.current_layout.add_window(self.windows, window, self.active_window_idx, location)
        self.relayout_borders()

    def new_window(
        self,
        use_shell: bool = True,
        cmd: Optional[List[str]] = None,
        stdin: Optional[bytes] = None,
        override_title: Optional[str] = None,
        cwd_from: Optional[int] = None,
        cwd: Optional[str] = None,
        overlay_for: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        location: Optional[str] = None,
        copy_colors_from: Optional[Window] = None,
        allow_remote_control: bool = False,
        marker: Optional[str] = None,
        watchers: Optional[Watchers] = None
    ) -> Window:
        child = self.launch_child(
            use_shell=use_shell, cmd=cmd, stdin=stdin, cwd_from=cwd_from, cwd=cwd, env=env, allow_remote_control=allow_remote_control)
        window = Window(
            self, child, self.opts, self.args, override_title=override_title,
            copy_colors_from=copy_colors_from, watchers=watchers
        )
        if overlay_for is not None:
            overlaid = next(w for w in self.windows if w.id == overlay_for)
            window.overlay_for = overlay_for
            overlaid.overlay_window_id = window.id
        # Must add child before laying out so that resize_pty succeeds
        get_boss().add_child(window)
        self._add_window(window, location=location)
        if marker:
            try:
                window.set_marker(marker)
            except Exception:
                import traceback
                traceback.print_exc()
        return window

    def new_special_window(
            self,
            special_window: SpecialWindowInstance,
            location: Optional[str] = None,
            copy_colors_from: Optional[Window] = None,
            allow_remote_control: bool = False
    ) -> Window:
        return self.new_window(
            use_shell=False, cmd=special_window.cmd, stdin=special_window.stdin,
            override_title=special_window.override_title,
            cwd_from=special_window.cwd_from, cwd=special_window.cwd, overlay_for=special_window.overlay_for,
            env=special_window.env, location=location, copy_colors_from=copy_colors_from,
            allow_remote_control=allow_remote_control
        )

    def close_window(self) -> None:
        if self.windows:
            self.remove_window(self.windows[self.active_window_idx])

    def close_other_windows_in_tab(self) -> None:
        if len(self.windows) > 1:
            active_window = self.windows[self.active_window_idx]
            for window in tuple(self.windows):
                if window is not active_window:
                    self.remove_window(window)

    def previous_active_window_idx(self, num: int) -> Optional[int]:
        try:
            old_window_id = self.active_window_history[-num]
        except IndexError:
            return None
        for idx, w in enumerate(self.windows):
            if w.id == old_window_id:
                return idx

    def remove_window(self, window: Window, destroy: bool = True) -> None:
        idx = self.previous_active_window_idx(1)
        next_window_id = None
        if idx is not None:
            next_window_id = self.windows[idx].id
        active_window_idx = self.current_layout.remove_window(self.windows, window, self.active_window_idx)
        if destroy:
            remove_window(self.os_window_id, self.id, window.id)
        else:
            detach_window(self.os_window_id, self.id, window.id)
        if window.overlay_for is not None:
            for idx, q in enumerate(self.windows):
                if q.id == window.overlay_for:
                    active_window_idx = idx
                    next_window_id = q.id
                    break
        if next_window_id is None and len(self.windows) > active_window_idx:
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

    def detach_window(self, window: Window) -> Tuple[Optional[Window], Optional[Window]]:
        underlaid_window: Optional[Window] = None
        overlaid_window: Optional[Window] = window
        if window.overlay_for:
            for x in self.windows:
                if x.id == window.overlay_for:
                    underlaid_window = x
                    break
        elif window.overlay_window_id:
            underlaid_window = window
            overlaid_window = None
            for x in self.windows:
                if x.id == window.overlay_window_id:
                    overlaid_window = x
                    break
        if overlaid_window is not None:
            self.remove_window(overlaid_window, destroy=False)
        if underlaid_window is not None:
            self.remove_window(underlaid_window, destroy=False)
        return underlaid_window, overlaid_window

    def attach_window(self, window: Window) -> None:
        window.change_tab(self)
        attach_window(self.os_window_id, self.id, window.id)
        self._add_window(window)

    def set_active_window_idx(self, idx: int) -> None:
        if idx != self.active_window_idx:
            self.active_window_idx = self.current_layout.set_active_window(self.windows, idx)
            self.relayout_borders()

    def set_active_window(self, window: Window) -> None:
        try:
            idx = self.windows.index(window)
        except ValueError:
            return
        self.set_active_window_idx(idx)

    def get_nth_window(self, n: int) -> Optional[Window]:
        if self.windows:
            return self.current_layout.nth_window(self.windows, n)

    def nth_window(self, num: int = 0) -> None:
        if self.windows:
            if num < 0:
                idx = self.previous_active_window_idx(-num)
                if idx is None:
                    return
                self.active_window_idx = self.current_layout.set_active_window(self.windows, idx)
            else:
                self.active_window_idx = self.current_layout.activate_nth_window(self.windows, num)
            self.relayout_borders()

    def _next_window(self, delta: int = 1) -> None:
        if len(self.windows) > 1:
            self.active_window_idx = self.current_layout.next_window(self.windows, self.active_window_idx, delta)
            self.relayout_borders()

    def next_window(self) -> None:
        self._next_window()

    def previous_window(self) -> None:
        self._next_window(-1)

    prev_window = previous_window

    def neighboring_window(self, which: str) -> None:
        neighbors = self.current_layout.neighbors(self.windows, self.active_window_idx)
        candidates = cast(Optional[Tuple[int, ...]], neighbors.get(which))
        if candidates:
            self.active_window_idx = self.current_layout.set_active_window(self.windows, candidates[0])
            self.relayout_borders()

    def move_window(self, delta: int = 1) -> None:
        self.active_window_idx = self.current_layout.move_window(self.windows, self.active_window_idx, delta)
        self.relayout()

    def move_window_to_top(self) -> None:
        self.move_window(-self.active_window_idx)

    def move_window_forward(self) -> None:
        self.move_window()

    def move_window_backward(self) -> None:
        self.move_window(-1)

    def list_windows(self, active_window: Optional[Window]) -> Generator[WindowDict, None, None]:
        for w in self:
            yield w.as_dict(is_focused=w is active_window)

    def matches(self, field: str, pat: Pattern) -> bool:
        if field == 'id':
            return bool(pat.pattern == str(self.id))
        if field == 'title':
            return pat.search(self.name or self.title) is not None
        return False

    def __iter__(self) -> Iterator[Window]:
        return iter(self.windows)

    def __len__(self) -> int:
        return len(self.windows)

    def __contains__(self, window: Window) -> bool:
        return window in self.windows

    def destroy(self) -> None:
        evict_cached_layouts(self.id)
        for w in self.windows:
            w.destroy()
        self.windows = deque()

    def __repr__(self) -> str:
        return 'Tab(title={}, id={})'.format(self.name or self.title, hex(id(self)))

    def make_active(self) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.set_active_tab(self)
# }}}


class TabManager:  # {{{

    def __init__(self, os_window_id: int, opts: Options, args: CLIOptions, startup_session: Optional[SessionType] = None):
        self.os_window_id = os_window_id
        self.last_active_tab_id = None
        self.opts, self.args = opts, args
        self.tab_bar_hidden = self.opts.tab_bar_style == 'hidden'
        self.tabs: List[Tab] = []
        self.active_tab_history: Deque[int] = deque()
        self.tab_bar = TabBar(self.os_window_id, opts)
        self._active_tab_idx = 0

        if startup_session is not None:
            for t in startup_session.tabs:
                self._add_tab(Tab(self, session_tab=t))
            self._set_active_tab(max(0, min(startup_session.active_tab_idx, len(self.tabs) - 1)))

    @property
    def active_tab_idx(self) -> int:
        return self._active_tab_idx

    @active_tab_idx.setter
    def active_tab_idx(self, val: int) -> None:
        try:
            old_active_tab: Optional[Tab] = self.tabs[self._active_tab_idx]
        except Exception:
            old_active_tab = None
        else:
            assert old_active_tab is not None
            add_active_id_to_history(self.active_tab_history, old_active_tab.id)
        self._active_tab_idx = max(0, min(val, len(self.tabs) - 1))
        try:
            new_active_tab: Optional[Tab] = self.tabs[self._active_tab_idx]
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

    def refresh_sprite_positions(self) -> None:
        if not self.tab_bar_hidden:
            self.tab_bar.screen.refresh_sprite_positions()

    @property
    def tab_bar_should_be_visible(self) -> bool:
        return len(self.tabs) >= self.opts.tab_bar_min_tabs

    def _add_tab(self, tab: Tab) -> None:
        visible_before = self.tab_bar_should_be_visible
        self.tabs.append(tab)
        if not visible_before and self.tab_bar_should_be_visible:
            self.tabbar_visibility_changed()

    def _remove_tab(self, tab: Tab) -> None:
        visible_before = self.tab_bar_should_be_visible
        remove_tab(self.os_window_id, tab.id)
        self.tabs.remove(tab)
        if visible_before and not self.tab_bar_should_be_visible:
            self.tabbar_visibility_changed()

    def _set_active_tab(self, idx: int) -> None:
        self.active_tab_idx = idx
        set_active_tab(self.os_window_id, idx)

    def tabbar_visibility_changed(self) -> None:
        if not self.tab_bar_hidden:
            self.tab_bar.layout()
            self.resize(only_tabs=True)

    def mark_tab_bar_dirty(self) -> None:
        if self.tab_bar_should_be_visible and not self.tab_bar_hidden:
            mark_tab_bar_dirty(self.os_window_id)

    def update_tab_bar_data(self) -> None:
        self.tab_bar.update(self.tab_bar_data)

    def update_dpi_based_sizes(self) -> None:
        for tab in self.tabs:
            tab.recalculate_sizes()

    def resize(self, only_tabs: bool = False) -> None:
        if not only_tabs:
            if not self.tab_bar_hidden:
                self.tab_bar.layout()
                self.mark_tab_bar_dirty()
        for tab in self.tabs:
            tab.relayout()

    def set_active_tab_idx(self, idx: int) -> None:
        self._set_active_tab(idx)
        tab = self.active_tab
        if tab is not None:
            tab.relayout_borders()
        self.mark_tab_bar_dirty()

    def set_active_tab(self, tab: Tab) -> bool:
        try:
            idx = self.tabs.index(tab)
        except Exception:
            return False
        self.set_active_tab_idx(idx)
        return True

    def next_tab(self, delta: int = 1) -> None:
        if len(self.tabs) > 1:
            self.set_active_tab_idx((self.active_tab_idx + len(self.tabs) + delta) % len(self.tabs))

    def goto_tab(self, tab_num: int) -> None:
        if tab_num >= len(self.tabs):
            tab_num = max(0, len(self.tabs) - 1)
        if tab_num >= 0:
            self.set_active_tab_idx(tab_num)
        else:
            try:
                old_active_tab_id = self.active_tab_history[tab_num]
            except IndexError:
                return
            for idx, tab in enumerate(self.tabs):
                if tab.id == old_active_tab_id:
                    self.set_active_tab_idx(idx)
                    break

    def __iter__(self) -> Iterator[Tab]:
        return iter(self.tabs)

    def __len__(self) -> int:
        return len(self.tabs)

    def list_tabs(self, active_tab: Optional[Tab], active_window: Optional[Window]) -> Generator[TabDict, None, None]:
        for tab in self:
            yield {
                'id': tab.id,
                'is_focused': tab is active_tab,
                'title': tab.name or tab.title,
                'layout': str(tab.current_layout.name),
                'windows': list(tab.list_windows(active_window)),
                'active_window_history': list(tab.active_window_history),
            }

    @property
    def active_tab(self) -> Optional[Tab]:
        return self.tabs[self.active_tab_idx] if self.tabs else None

    @property
    def active_window(self) -> Optional[Window]:
        t = self.active_tab
        if t is not None:
            return t.active_window

    def tab_for_id(self, tab_id: int) -> Optional[Tab]:
        for t in self.tabs:
            if t.id == tab_id:
                return t

    def move_tab(self, delta: int = 1) -> None:
        if len(self.tabs) > 1:
            idx = self.active_tab_idx
            nidx = (idx + len(self.tabs) + delta) % len(self.tabs)
            step = 1 if idx < nidx else -1
            for i in range(idx, nidx, step):
                self.tabs[i], self.tabs[i + step] = self.tabs[i + step], self.tabs[i]
                swap_tabs(self.os_window_id, i, i + step)
            self._set_active_tab(nidx)
            self.mark_tab_bar_dirty()

    def new_tab(
        self,
        special_window: Optional[SpecialWindowInstance] = None,
        cwd_from: Optional[int] = None,
        as_neighbor: bool = False,
        empty_tab: bool = False,
        location: str = 'last'
    ) -> Tab:
        idx = len(self.tabs)
        orig_active_tab_idx = self.active_tab_idx
        self._add_tab(Tab(self, no_initial_window=True) if empty_tab else Tab(self, special_window=special_window, cwd_from=cwd_from))
        self._set_active_tab(idx)
        if as_neighbor:
            location = 'after'
        if location == 'neighbor':
            location = 'after'
        if len(self.tabs) > 1 and location != 'last':
            if location == 'first':
                desired_idx = 0
            else:
                desired_idx = orig_active_tab_idx + (0 if location == 'before' else 1)
            if idx != desired_idx:
                for i in range(idx, desired_idx, -1):
                    self.tabs[i], self.tabs[i-1] = self.tabs[i-1], self.tabs[i]
                    swap_tabs(self.os_window_id, i, i-1)
                self._set_active_tab(desired_idx)
                idx = desired_idx
        self.mark_tab_bar_dirty()
        return self.tabs[idx]

    def remove(self, tab: Tab) -> None:
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
    def tab_bar_data(self) -> List[TabBarData]:
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

    def activate_tab_at(self, x: int) -> None:
        i = self.tab_bar.tab_at(x)
        if i is not None:
            self.set_active_tab_idx(i)

    @property
    def blank_rects(self) -> Tuple[Rect, ...]:
        return self.tab_bar.blank_rects if self.tab_bar_should_be_visible else ()

    def destroy(self) -> None:
        for t in self:
            t.destroy()
        self.tab_bar.destroy()
        del self.tab_bar
        del self.tabs
# }}}
