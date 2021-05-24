#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import stat
import weakref
from collections import deque
from contextlib import suppress
from functools import partial
from operator import attrgetter
from typing import (
    Any, Deque, Dict, Generator, Iterator, List, NamedTuple, Optional, Pattern,
    Sequence, Tuple, Union, cast
)

from .borders import Borders
from .child import Child
from .cli_stub import CLIOptions
from .constants import appname, kitty_exe
from .fast_data_types import (
    add_tab, attach_window, detach_window, get_boss, get_options,
    mark_tab_bar_dirty, next_window_id, remove_tab, remove_window, ring_bell,
    set_active_tab, set_active_window, swap_tabs, sync_os_window_title
)
from .layout.base import Layout, Rect
from .layout.interface import create_layout_object_for, evict_cached_layouts
from .tab_bar import TabBar, TabBarData
from .typing import EdgeLiteral, SessionTab, SessionType, TypedDict
from .utils import log_error, platform_window_id, resolved_shell
from .window import Watchers, Window, WindowDict
from .window_list import WindowList


class TabDict(TypedDict):
    id: int
    is_focused: bool
    title: str
    layout: str
    layout_state: Dict[str, Any]
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
    watchers: Optional[Watchers]


def SpecialWindow(
    cmd: Optional[List[str]],
    stdin: Optional[bytes] = None,
    override_title: Optional[str] = None,
    cwd_from: Optional[int] = None,
    cwd: Optional[str] = None,
    overlay_for: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    watchers: Optional[Watchers] = None
) -> SpecialWindowInstance:
    return SpecialWindowInstance(cmd, stdin, override_title, cwd_from, cwd, overlay_for, env, watchers)


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
        self.tab_manager_ref = weakref.ref(tab_manager)
        self.os_window_id: int = tab_manager.os_window_id
        self.id: int = add_tab(self.os_window_id)
        if not self.id:
            raise Exception('No OS window with id {} found, or tab counter has wrapped'.format(self.os_window_id))
        self.args = tab_manager.args
        self.name = getattr(session_tab, 'name', '')
        self.enabled_layouts = [x.lower() for x in getattr(session_tab, 'enabled_layouts', None) or get_options().enabled_layouts]
        self.borders = Borders(self.os_window_id, self.id)
        self.windows = WindowList(self)
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

    def take_over_from(self, other_tab: 'Tab') -> None:
        self.name, self.cwd = other_tab.name, other_tab.cwd
        self.enabled_layouts = list(other_tab.enabled_layouts)
        if other_tab._current_layout_name:
            self._set_current_layout(other_tab._current_layout_name)
        self._last_used_layout = other_tab._last_used_layout
        for window in other_tab.windows:
            detach_window(other_tab.os_window_id, other_tab.id, window.id)
        self.windows = other_tab.windows
        self.windows.change_tab(self)
        other_tab.windows = WindowList(other_tab)
        for window in self.windows:
            window.change_tab(self)
            attach_window(self.os_window_id, self.id, window.id)
        self.relayout()

    def _set_current_layout(self, layout_name: str) -> None:
        self._last_used_layout = self._current_layout_name
        self.current_layout = self.create_layout_object(layout_name)
        self._current_layout_name = layout_name
        self.mark_tab_bar_dirty()

    def startup(self, session_tab: 'SessionTab') -> None:
        for cmd in session_tab.windows:
            if isinstance(cmd, SpecialWindowInstance):
                self.new_special_window(cmd)
            else:
                from .launch import launch
                launch(get_boss(), cmd.opts, cmd.args, target_tab=self, force_target_tab=True)
        self.windows.set_active_window_group_for(self.windows.all_windows[session_tab.active_window_idx])

    def serialize_state(self) -> Dict[str, Any]:
        return {
            'version': 1,
            'id': self.id,
            'window_list': self.windows.serialize_state(),
            'current_layout': self._current_layout_name,
            'last_used_layout': self._last_used_layout,
            'name': self.name,
        }

    def active_window_changed(self) -> None:
        w = self.active_window
        set_active_window(self.os_window_id, self.id, 0 if w is None else w.id)
        self.mark_tab_bar_dirty()
        self.relayout_borders()
        self.current_layout.update_visibility(self.windows)

    def mark_tab_bar_dirty(self) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.mark_tab_bar_dirty()

    @property
    def active_window(self) -> Optional[Window]:
        return self.windows.active_window

    @property
    def active_window_for_cwd(self) -> Optional[Window]:
        return self.windows.active_group_base

    @property
    def title(self) -> str:
        return cast(str, getattr(self.active_window, 'title', appname))

    def set_title(self, title: str) -> None:
        self.name = title or ''
        self.mark_tab_bar_dirty()

    def title_changed(self, window: Window) -> None:
        if window is self.active_window:
            tm = self.tab_manager_ref()
            if tm is not None:
                tm.title_changed(self)

    def on_bell(self, window: Window) -> None:
        self.mark_tab_bar_dirty()

    def relayout(self) -> None:
        if self.windows:
            self.current_layout(self.windows)
        self.relayout_borders()

    def relayout_borders(self) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            w = self.active_window
            ly = self.current_layout
            self.borders(
                all_windows=self.windows,
                current_layout=ly, extra_blank_rects=tm.blank_rects,
                draw_window_borders=(ly.needs_window_borders and self.windows.num_visble_groups > 1) or ly.must_draw_borders
            )
            if w is not None:
                w.change_titlebar_color()

    def create_layout_object(self, name: str) -> Layout:
        return create_layout_object_for(name, self.os_window_id, self.id)

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
        w = self.active_window
        if w is not None and self.resize_window_by(
                w.id, increment, is_horizontal) is not None:
            ring_bell()

    def reset_window_sizes(self) -> None:
        if self.current_layout.remove_all_biases():
            self.relayout()

    def layout_action(self, action_name: str, args: Sequence[str]) -> None:
        ret = self.current_layout.layout_action(action_name, args, self.windows)
        if ret is None:
            ring_bell()
            return
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
        check_for_suitability = True
        if cmd is None:
            if use_shell:
                cmd = resolved_shell(get_options())
                check_for_suitability = False
            else:
                if self.args.args:
                    cmd = list(self.args.args)
                else:
                    cmd = resolved_shell(get_options())
                    check_for_suitability = False
                cmd = self.args.args or resolved_shell(get_options())
        if check_for_suitability:
            old_exe = cmd[0]
            if not os.path.isabs(old_exe):
                import shutil
                actual_exe = shutil.which(old_exe)
                old_exe = actual_exe if actual_exe else os.path.abspath(old_exe)
            try:
                is_executable = os.access(old_exe, os.X_OK)
            except OSError:
                pass
            else:
                try:
                    st = os.stat(old_exe)
                except OSError:
                    pass
                else:
                    if stat.S_ISDIR(st.st_mode):
                        cwd = old_exe
                        cmd = resolved_shell(get_options())
                    elif not is_executable:
                        import shlex
                        with suppress(OSError):
                            with open(old_exe) as f:
                                cmd = [kitty_exe(), '+hold']
                                if f.read(2) == '#!':
                                    line = f.read(4096).splitlines()[0]
                                    cmd += shlex.split(line) + [old_exe]
                                else:
                                    cmd += [resolved_shell(get_options())[0], cmd[0]]
        fenv: Dict[str, str] = {}
        if env:
            fenv.update(env)
        fenv['KITTY_WINDOW_ID'] = str(next_window_id())
        pwid = platform_window_id(self.os_window_id)
        if pwid is not None:
            fenv['WINDOWID'] = str(pwid)
        ans = Child(cmd, cwd or self.cwd, stdin, fenv, cwd_from, allow_remote_control=allow_remote_control)
        ans.fork()
        return ans

    def _add_window(self, window: Window, location: Optional[str] = None, overlay_for: Optional[int] = None) -> None:
        self.current_layout.add_window(self.windows, window, location, overlay_for)
        self.mark_tab_bar_dirty()
        self.relayout()

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
            self, child, self.args, override_title=override_title,
            copy_colors_from=copy_colors_from, watchers=watchers
        )
        # Must add child before laying out so that resize_pty succeeds
        get_boss().add_child(window)
        self._add_window(window, location=location, overlay_for=overlay_for)
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
            allow_remote_control: bool = False,
    ) -> Window:
        return self.new_window(
            use_shell=False, cmd=special_window.cmd, stdin=special_window.stdin,
            override_title=special_window.override_title,
            cwd_from=special_window.cwd_from, cwd=special_window.cwd, overlay_for=special_window.overlay_for,
            env=special_window.env, location=location, copy_colors_from=copy_colors_from,
            allow_remote_control=allow_remote_control, watchers=special_window.watchers
        )

    def close_window(self) -> None:
        w = self.active_window
        if w is not None:
            self.remove_window(w)

    def close_other_windows_in_tab(self) -> None:
        if len(self.windows) > 1:
            active_window = self.active_window
            for window in tuple(self.windows):
                if window is not active_window:
                    self.remove_window(window)

    def remove_window(self, window: Window, destroy: bool = True) -> None:
        self.windows.remove_window(window)
        if destroy:
            remove_window(self.os_window_id, self.id, window.id)
        else:
            detach_window(self.os_window_id, self.id, window.id)
        self.mark_tab_bar_dirty()
        self.relayout()
        active_window = self.active_window
        if active_window:
            self.title_changed(active_window)

    def detach_window(self, window: Window) -> Tuple[Window, ...]:
        windows = list(self.windows.windows_in_group_of(window))
        windows.sort(key=attrgetter('id'))  # since ids increase in order of creation
        for w in reversed(windows):
            self.remove_window(w, destroy=False)
        return tuple(windows)

    def attach_window(self, window: Window) -> None:
        window.change_tab(self)
        attach_window(self.os_window_id, self.id, window.id)
        self._add_window(window)

    def set_active_window(self, x: Union[Window, int]) -> None:
        self.windows.set_active_window_group_for(x)

    def get_nth_window(self, n: int) -> Optional[Window]:
        if self.windows:
            return self.current_layout.nth_window(self.windows, n)

    def nth_window(self, num: int = 0) -> None:
        if self.windows:
            if num < 0:
                self.windows.make_previous_group_active(-num)
            else:
                self.current_layout.activate_nth_window(self.windows, num)
            self.relayout_borders()

    def _next_window(self, delta: int = 1) -> None:
        if len(self.windows) > 1:
            self.current_layout.next_window(self.windows, delta)
            self.relayout_borders()

    def next_window(self) -> None:
        self._next_window()

    def previous_window(self) -> None:
        self._next_window(-1)

    prev_window = previous_window

    def most_recent_group(self, groups: Sequence[int]) -> Optional[int]:
        groups_set = frozenset(groups)

        for window_id in reversed(self.windows.active_window_history):
            group = self.windows.group_for_window(window_id)
            if group and group.id in groups_set:
                return group.id

        if groups:
            return groups[0]

    def neighboring_group_id(self, which: EdgeLiteral) -> Optional[int]:
        neighbors = self.current_layout.neighbors(self.windows)
        candidates = neighbors.get(which)
        if candidates:
            return self.most_recent_group(candidates)

    def neighboring_window(self, which: EdgeLiteral) -> None:
        neighbor = self.neighboring_group_id(which)
        if neighbor:
            self.windows.set_active_group(neighbor)

    def move_window(self, delta: Union[EdgeLiteral, int] = 1) -> None:
        if isinstance(delta, int):
            if self.current_layout.move_window(self.windows, delta):
                self.relayout()
        elif isinstance(delta, str):
            neighbor = self.neighboring_group_id(delta)
            if neighbor:
                if self.current_layout.move_window_to_group(self.windows, neighbor):
                    self.relayout()

    def move_window_to_top(self) -> None:
        n = self.windows.active_group_idx
        if n > 0:
            self.move_window(-n)

    def move_window_forward(self) -> None:
        self.move_window()

    def move_window_backward(self) -> None:
        self.move_window(-1)

    def list_windows(self, active_window: Optional[Window], self_window: Optional[Window] = None) -> Generator[WindowDict, None, None]:
        for w in self:
            yield w.as_dict(is_focused=w is active_window, is_self=w is self_window)

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
        self.windows = WindowList(self)

    def __repr__(self) -> str:
        return 'Tab(title={}, id={})'.format(self.name or self.title, hex(id(self)))

    def make_active(self) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.set_active_tab(self)
# }}}


class TabManager:  # {{{

    def __init__(self, os_window_id: int, args: CLIOptions, wm_class: str, wm_name: str, startup_session: Optional[SessionType] = None):
        self.os_window_id = os_window_id
        self.wm_class = wm_class
        self.wm_name = wm_name
        self.last_active_tab_id = None
        self.args = args
        self.tab_bar_hidden = get_options().tab_bar_style == 'hidden'
        self.tabs: List[Tab] = []
        self.active_tab_history: Deque[int] = deque()
        self.tab_bar = TabBar(self.os_window_id)
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
        return len(self.tabs) >= get_options().tab_bar_min_tabs

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

    def title_changed(self, tab: Tab) -> None:
        self.mark_tab_bar_dirty()
        if tab is self.active_tab:
            sync_os_window_title(self.os_window_id)

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

    def list_tabs(self, active_tab: Optional[Tab], active_window: Optional[Window], self_window: Optional[Window] = None) -> Generator[TabDict, None, None]:
        for tab in self:
            yield {
                'id': tab.id,
                'is_focused': tab is active_tab,
                'title': tab.name or tab.title,
                'layout': str(tab.current_layout.name),
                'layout_state': tab.current_layout.layout_state(),
                'windows': list(tab.list_windows(active_window, self_window)),
                'active_window_history': list(tab.windows.active_window_history),
            }

    def serialize_state(self) -> Dict[str, Any]:
        return {
            'version': 1,
            'id': self.os_window_id,
            'tabs': [tab.serialize_state() for tab in self],
            'active_tab_idx': self.active_tab_idx,
        }

    @property
    def active_tab(self) -> Optional[Tab]:
        try:
            return self.tabs[self.active_tab_idx] if self.tabs else None
        except Exception:
            return None

    @property
    def active_window(self) -> Optional[Window]:
        t = self.active_tab
        if t is not None:
            return t.active_window

    @property
    def number_of_windows(self) -> int:
        count = 0
        for tab in self:
            for window in tab:
                count += 1
        return count

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
        active_tab_before_removal = self.active_tab
        self._remove_tab(tab)
        active_tab = self.active_tab
        active_tab_needs_to_change = (active_tab is None and (active_tab_before_removal is None or active_tab_before_removal is tab)) or active_tab is tab
        while True:
            try:
                self.active_tab_history.remove(tab.id)
            except ValueError:
                break

        if active_tab_needs_to_change:
            next_active_tab = -1
            if get_options().tab_switch_strategy == 'previous':
                while self.active_tab_history and next_active_tab < 0:
                    tab_id = self.active_tab_history.pop()
                    for idx, qtab in enumerate(self.tabs):
                        if qtab.id == tab_id:
                            next_active_tab = idx
                            break
            elif get_options().tab_switch_strategy == 'left':
                next_active_tab = max(0, self.active_tab_idx - 1)
            elif get_options().tab_switch_strategy == 'right':
                next_active_tab = min(self.active_tab_idx, len(self.tabs) - 1)

            if next_active_tab < 0:
                next_active_tab = max(0, min(self.active_tab_idx, len(self.tabs) - 1))

            self._set_active_tab(next_active_tab)
        elif active_tab_before_removal is not None:
            try:
                idx = self.tabs.index(active_tab_before_removal)
            except Exception:
                pass
            else:
                self._active_tab_idx = idx
        self.mark_tab_bar_dirty()
        tab.destroy()

    @property
    def tab_bar_data(self) -> List[TabBarData]:
        at = self.active_tab
        ans = []
        for t in self.tabs:
            title = (t.name or t.title or appname).strip()
            needs_attention = False
            has_activity_since_last_focus = False
            for w in t:
                if w.needs_attention:
                    needs_attention = True
                if w.has_activity_since_last_focus:
                    has_activity_since_last_focus = True
            ans.append(TabBarData(
                title, t is at, needs_attention,
                len(t), t.current_layout.name or '',
                has_activity_since_last_focus
            ))
        return ans

    def activate_tab_at(self, x: int, is_double: bool = False) -> None:
        i = self.tab_bar.tab_at(x)
        if i is None:
            if is_double:
                self.new_tab()
        else:
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
