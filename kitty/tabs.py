#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import stat
import weakref
from collections import deque
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import suppress
from gettext import gettext as _
from operator import attrgetter
from typing import (
    Any,
    Deque,
    NamedTuple,
    Optional,
)

from .borders import Border, Borders
from .child import Child
from .cli_stub import CLIOptions
from .constants import appname
from .fast_data_types import (
    GLFW_MOUSE_BUTTON_LEFT,
    GLFW_MOUSE_BUTTON_MIDDLE,
    GLFW_PRESS,
    GLFW_RELEASE,
    add_tab,
    attach_window,
    buffer_keys_in_window,
    current_focused_os_window_id,
    detach_window,
    focus_os_window,
    get_boss,
    get_click_interval,
    get_options,
    last_focused_os_window_id,
    mark_tab_bar_dirty,
    monotonic,
    next_window_id,
    remove_tab,
    remove_window,
    ring_bell,
    set_active_tab,
    set_active_window,
    set_redirect_keys_to_overlay,
    swap_tabs,
    sync_os_window_title,
)
from .layout.base import Layout
from .layout.interface import create_layout_object_for, evict_cached_layouts
from .progress import ProgressState
from .tab_bar import TabBar, TabBarData
from .types import ac
from .typing_compat import EdgeLiteral, SessionTab, SessionType, TypedDict
from .utils import cmdline_for_hold, log_error, platform_window_id, resolved_shell, shlex_split, which
from .window import CwdRequest, Watchers, Window, WindowDict, global_watchers
from .window_list import WindowList


class TabMouseEvent(NamedTuple):
    button: int
    modifiers: int
    action: int
    at: float
    tab_idx: int | None


class TabDict(TypedDict):
    id: int
    is_focused: bool
    is_active: bool
    title: str
    layout: str
    layout_state: dict[str, Any]
    layout_opts: dict[str, Any]
    enabled_layouts: list[str]
    windows: list[WindowDict]
    groups: list[dict[str, Any]]
    active_window_history: list[int]


class SpecialWindowInstance(NamedTuple):
    cmd: list[str] | None
    stdin: bytes | None
    override_title: str | None
    cwd_from: CwdRequest | None
    cwd: str | None
    overlay_for: int | None
    env: dict[str, str] | None
    watchers: Watchers | None
    overlay_behind: bool
    hold: bool


def SpecialWindow(
    cmd: list[str] | None,
    stdin: bytes | None = None,
    override_title: str | None = None,
    cwd_from: CwdRequest | None = None,
    cwd: str | None = None,
    overlay_for: int | None = None,
    env: dict[str, str] | None = None,
    watchers: Watchers | None = None,
    overlay_behind: bool = False,
    hold: bool = False,
) -> SpecialWindowInstance:
    return SpecialWindowInstance(cmd, stdin, override_title, cwd_from, cwd, overlay_for, env, watchers, overlay_behind, hold)


def add_active_id_to_history(items: Deque[int], item_id: int, maxlen: int = 64) -> None:
    with suppress(ValueError):
        items.remove(item_id)
    items.append(item_id)
    if len(items) > maxlen:
        items.popleft()


class Tab:  # {{{

    active_fg: int | None = None
    active_bg: int | None = None
    inactive_fg: int | None = None
    inactive_bg: int | None = None
    confirm_close_window_id: int = 0
    num_of_windows_with_progress: int = 0
    total_progress: int = 0
    has_indeterminate_progress: bool = False
    last_focused_window_with_progress_id: int = 0

    def __init__(
        self,
        tab_manager: 'TabManager',
        session_tab: Optional['SessionTab'] = None,
        special_window: SpecialWindowInstance | None = None,
        cwd_from: CwdRequest | None = None,
        no_initial_window: bool = False
    ):
        self.tab_manager_ref = weakref.ref(tab_manager)
        self.os_window_id: int = tab_manager.os_window_id
        self.id: int = add_tab(self.os_window_id)
        if not self.id:
            raise Exception(f'No OS window with id {self.os_window_id} found, or tab counter has wrapped')
        self.args = tab_manager.args
        self.name = getattr(session_tab, 'name', '')
        self.enabled_layouts = [x.lower() for x in getattr(session_tab, 'enabled_layouts', None) or get_options().enabled_layouts]
        self.borders = Borders(self.os_window_id, self.id)
        self.windows: WindowList = WindowList(self)
        self._last_used_layout: str | None = None
        self._current_layout_name: str | None = None
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

    def update_progress(self) -> None:
        self.num_of_windows_with_progress = 0
        self.total_progress = 0
        self.last_focused_window_with_progress_id = 0
        self.has_indeterminate_progress = False
        focused_at = 0.
        for window in self:
            p = window.progress
            if p.state is ProgressState.unset:
                continue
            if p.state in (ProgressState.set, ProgressState.paused):
                self.total_progress += p.percent
                self.num_of_windows_with_progress += 1
            elif p.state is ProgressState.indeterminate:
                self.has_indeterminate_progress = True
            if window.last_focused_at > focused_at or (not window.last_focused_at and window.id > self.last_focused_window_with_progress_id):
                focused_at = window.last_focused_at
                self.last_focused_window_with_progress_id = window.id
        self.mark_tab_bar_dirty()
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.update_progress()

    def has_single_window_visible(self) -> bool:
        if self.current_layout.only_active_window_visible:
            return True
        for i, g in enumerate(self.windows.iter_all_layoutable_groups(only_visible=True)):
            if i > 0:
                return False
        return True

    def set_enabled_layouts(self, val: Iterable[str]) -> None:
        self.enabled_layouts = [x.lower() for x in val] or ['tall']
        if self.current_layout.name not in self.enabled_layouts:
            self._set_current_layout(self.enabled_layouts[0])
        self.relayout()

    def apply_options(self, is_active: bool) -> None:
        aw = self.active_window
        for window in self:
            window.apply_options(is_active and aw is window)
        self.set_enabled_layouts(get_options().enabled_layouts)

    def take_over_from(self, other_tab: 'Tab') -> None:
        self.name, self.cwd = other_tab.name, other_tab.cwd
        self.enabled_layouts = list(other_tab.enabled_layouts)
        self._last_used_layout = other_tab._last_used_layout
        if clname := other_tab._current_layout_name:
            cl = other_tab.current_layout
            other_tab._set_current_layout(clname)
            cl.set_owner(self.os_window_id, self.id)
            self.current_layout: Layout = cl
            self._current_layout_name = clname
            self.mark_tab_bar_dirty()
        for window in other_tab.windows:
            detach_window(other_tab.os_window_id, other_tab.id, window.id)
        self.windows = other_tab.windows
        self.windows.change_tab(self)
        other_tab.windows = WindowList(other_tab)
        for window in self.windows:
            window.change_tab(self)
            attach_window(self.os_window_id, self.id, window.id)
        self.active_window_changed()
        self.relayout()

    def _set_current_layout(self, layout_name: str) -> None:
        self._last_used_layout = self._current_layout_name
        self.current_layout = self.create_layout_object(layout_name)
        self._current_layout_name = layout_name
        self.mark_tab_bar_dirty()

    def startup(self, session_tab: 'SessionTab') -> None:
        target_tab = self
        boss = get_boss()
        for window in session_tab.windows:
            spec = window.launch_spec
            if isinstance(spec, SpecialWindowInstance):
                self.new_special_window(spec)
            else:
                from .launch import launch
                launched_window = launch(boss, spec.opts, spec.args, target_tab=target_tab, force_target_tab=True)
            if window.resize_spec is not None:
                self.resize_window(*window.resize_spec)
            if window.focus_matching_window_spec:
                for w in boss.match_windows(window.focus_matching_window_spec, launched_window or boss.active_window):
                    tab = w.tabref()
                    if tab:
                        target_tab = tab or self
                        tm = tab.tab_manager_ref()
                        if tm and boss.active_tab is not target_tab:
                            tm.set_active_tab(target_tab)
                        if target_tab.active_window is not w:
                            target_tab.set_active_window(w)
                        if current_focused_os_window_id() != w.os_window_id:
                            focus_os_window(w.os_window_id, True)

        with suppress(IndexError):
            self.windows.set_active_window_group_for(self.windows.all_windows[session_tab.active_window_idx])

    def serialize_state(self) -> dict[str, Any]:
        return {
            'version': 1,
            'id': self.id,
            'window_list': self.windows.serialize_state(),
            'current_layout': self._current_layout_name,
            'last_used_layout': self._last_used_layout,
            'layout_opts': self.current_layout.layout_opts,
            'layout_state': self.current_layout.layout_state,
            'enabled_layouts': self.enabled_layouts,
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
    def active_window(self) -> Window | None:
        return self.windows.active_window

    @property
    def active_window_for_cwd(self) -> Window | None:
        return self.windows.active_group_main

    @property
    def title(self) -> str:
        w = self.active_window
        return w.title if w else appname

    @property
    def effective_title(self) -> str:
        return self.name or self.title

    def get_cwd_of_active_window(self, oldest: bool = False) -> str | None:
        w = self.active_window
        return w.get_cwd_of_child(oldest) if w else None

    def get_exe_of_active_window(self, oldest: bool = False) -> str | None:
        w = self.active_window
        return w.get_exe_of_child(oldest) if w else None

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
            ly = self.current_layout
            self.borders(
                all_windows=self.windows,
                current_layout=ly, tab_bar_rects=tm.tab_bar_rects,
                draw_window_borders=(ly.needs_window_borders and self.windows.num_visble_groups > 1) or ly.must_draw_borders
            )

    def create_layout_object(self, name: str) -> Layout:
        return create_layout_object_for(name, self.os_window_id, self.id)

    @ac('lay', 'Go to the next enabled layout. Can optionally supply an integer to jump by the specified number.')
    def next_layout(self, delta: int = 1) -> None:
        if len(self.enabled_layouts) > 1:
            for i, layout_name in enumerate(self.enabled_layouts):
                if layout_name == self.current_layout.full_name:
                    idx = i
                    break
            else:
                idx = -1
            if abs(delta) >= len(self.enabled_layouts):
                mult = -1 if delta < 0 else 1
                delta = mult * (abs(delta) % len(self.enabled_layouts))
            nl = self.enabled_layouts[(idx + delta + len(self.enabled_layouts)) % len(self.enabled_layouts)]
            self._set_current_layout(nl)
            self.relayout()

    @ac('lay', 'Go to the previously used layout')
    def last_used_layout(self) -> None:
        if len(self.enabled_layouts) > 1 and self._last_used_layout and self._last_used_layout != self._current_layout_name:
            self._set_current_layout(self._last_used_layout)
            self.relayout()

    @ac('lay', '''
        Switch to the named layout
        In case there are multiple layouts with the same name and different options,
        specify the full layout definition or a unique prefix of the full definition.

        For example::

            map f1 goto_layout tall
            map f2 goto_layout fat:bias=20
        ''')
    def goto_layout(self, layout_name: str, raise_exception: bool = False) -> None:
        layout_name = layout_name.lower()
        q, has_colon, rest = layout_name.partition(':')
        matches = []
        prefix_matches = []
        matched_layout = ''
        for candidate in self.enabled_layouts:
            x, _, _ = candidate.partition(':')
            if x == q:
                if candidate == layout_name:
                    matched_layout = candidate
                    break
                if candidate.startswith(layout_name):
                    prefix_matches.append(candidate)
                matches.append(x)

        if not matched_layout:
            if len(prefix_matches) == 1:
                matched_layout = prefix_matches[0]
            elif len(matches) == 1:
                matched_layout = matches[0]
        if matched_layout:
            self._set_current_layout(matched_layout)
            self.relayout()
        else:
            if len(matches) == 0:
                if raise_exception:
                    raise ValueError(layout_name)
                log_error(f'Unknown or disabled layout: {layout_name}')
            elif len(matches) != 1:
                if raise_exception:
                    raise ValueError(layout_name)
                log_error(f'Multiple layouts match: {layout_name}')

    @ac('lay', '''
        Toggle the named layout

        Switches to the named layout if another layout is current, otherwise
        switches to the last used layout. Useful to "zoom" a window temporarily
        by switching to the stack layout. For example::

            map f1 toggle_layout stack
        ''')
    def toggle_layout(self, layout_name: str) -> None:
        if self._current_layout_name == layout_name:
            self.last_used_layout()
        else:
            self.goto_layout(layout_name)

    def resize_window_by(self, window_id: int, increment: float, is_horizontal: bool) -> str | None:
        increment_as_percent = self.current_layout.bias_increment_for_cell(self.windows, is_horizontal) * increment
        if self.current_layout.modify_size_of_window(self.windows, window_id, increment_as_percent, is_horizontal):
            self.relayout()
            return None
        return 'Could not resize'

    @ac('win', '''
        Resize the active window by the specified amount

        See :ref:`window_resizing` for details.
        ''')
    def resize_window(self, quality: str, increment: int) -> None:
        if quality == 'reset':
            self.reset_window_sizes()
            return
        if increment < 1:
            raise ValueError(increment)
        is_horizontal = quality in ('wider', 'narrower')
        increment *= 1 if quality in ('wider', 'taller') else -1
        w = self.active_window
        if w is not None and self.resize_window_by(
                w.id, increment, is_horizontal) is not None:
            if get_options().enable_audio_bell:
                ring_bell(self.os_window_id)

    @ac('win', 'Reset window sizes undoing any dynamic resizing of windows')
    def reset_window_sizes(self) -> None:
        if self.current_layout.remove_all_biases():
            self.relayout()

    @ac('lay', 'Perform a layout specific action. See :doc:`layouts` for details')
    def layout_action(self, action_name: str, args: Sequence[str]) -> None:
        ret = self.current_layout.layout_action(action_name, args, self.windows)
        if ret is None:
            if get_options().enable_audio_bell:
                ring_bell(self.os_window_id)
            return
        self.relayout()

    def launch_child(
        self,
        use_shell: bool = False,
        cmd: list[str] | None = None,
        stdin: bytes | None = None,
        cwd_from: CwdRequest | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        is_clone_launch: str = '',
        add_listen_on_env_var: bool = True,
        hold: bool = False,
        pass_fds: tuple[int, ...] = (),
        remote_control_fd: int = -1,
        hold_after_ssh: bool = False
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
        if check_for_suitability:
            old_exe = cmd[0]
            if not os.path.isabs(old_exe):
                actual_exe = which(old_exe)
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
                        with suppress(OSError):
                            with open(old_exe) as f:
                                if f.read(2) == '#!':
                                    line = f.read(4096).splitlines()[0]
                                    cmd[:0] = shlex_split(line)
                                else:
                                    cmd[:0] = [resolved_shell(get_options())[0]]
                                cmd[0] = which(cmd[0]) or cmd[0]
                                cmd = cmdline_for_hold(cmd)
        fenv: dict[str, str] = {}
        if env:
            fenv.update(env)
        fenv['KITTY_WINDOW_ID'] = str(next_window_id())
        pwid = platform_window_id(self.os_window_id)
        if pwid is not None:
            fenv['WINDOWID'] = str(pwid)
        ans = Child(
                cmd, cwd or self.cwd, stdin, fenv, cwd_from, is_clone_launch=is_clone_launch,
                add_listen_on_env_var=add_listen_on_env_var, hold=hold, pass_fds=pass_fds, remote_control_fd=remote_control_fd, hold_after_ssh=hold_after_ssh)
        ans.fork()
        return ans

    def _add_window(
        self, window: Window, location: str | None = None, overlay_for: int | None = None,
        overlay_behind: bool = False, bias: float | None = None, next_to: Window | None = None,
    ) -> None:
        self.current_layout.add_window(self.windows, window, location, overlay_for, put_overlay_behind=overlay_behind, bias=bias, next_to=next_to)
        if overlay_behind and (w := self.active_window):
            set_redirect_keys_to_overlay(self.os_window_id, self.id, w.id, window.id)
            buffer_keys_in_window(self.os_window_id, self.id, window.id, True)
            window.keys_redirected_till_ready_from = w.id
        self.mark_tab_bar_dirty()
        self.relayout()

    def new_window(
        self,
        use_shell: bool = True,
        cmd: list[str] | None = None,
        stdin: bytes | None = None,
        override_title: str | None = None,
        cwd_from: CwdRequest | None = None,
        cwd: str | None = None,
        overlay_for: int | None = None,
        env: dict[str, str] | None = None,
        location: str | None = None,
        copy_colors_from: Window | None = None,
        allow_remote_control: bool = False,
        marker: str | None = None,
        watchers: Watchers | None = None,
        overlay_behind: bool = False,
        is_clone_launch: str = '',
        remote_control_passwords: dict[str, Sequence[str]] | None = None,
        hold: bool = False,
        bias: float | None = None,
        pass_fds: tuple[int, ...] = (),
        remote_control_fd: int = -1,
        next_to: Window | None = None,
        hold_after_ssh: bool = False
    ) -> Window:
        child = self.launch_child(
            use_shell=use_shell, cmd=cmd, stdin=stdin, cwd_from=cwd_from, cwd=cwd, env=env,
            is_clone_launch=is_clone_launch, add_listen_on_env_var=False if allow_remote_control and remote_control_passwords else True,
            hold=hold, pass_fds=pass_fds, remote_control_fd=remote_control_fd, hold_after_ssh=hold_after_ssh
        )
        window = Window(
            self, child, self.args, override_title=override_title,
            copy_colors_from=copy_colors_from, watchers=watchers,
            allow_remote_control=allow_remote_control, remote_control_passwords=remote_control_passwords
        )
        # Must add child before laying out so that resize_pty succeeds
        get_boss().add_child(window)
        self._add_window(window, location=location, overlay_for=overlay_for, overlay_behind=overlay_behind, bias=bias, next_to=next_to)
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
            location: str | None = None,
            copy_colors_from: Window | None = None,
            allow_remote_control: bool = False,
            remote_control_passwords: dict[str, Sequence[str]] | None = None,
            pass_fds: tuple[int, ...] = (),
            remote_control_fd: int = -1,
    ) -> Window:
        return self.new_window(
            use_shell=False, cmd=special_window.cmd, stdin=special_window.stdin,
            override_title=special_window.override_title,
            cwd_from=special_window.cwd_from, cwd=special_window.cwd, overlay_for=special_window.overlay_for,
            env=special_window.env, location=location, copy_colors_from=copy_colors_from,
            allow_remote_control=allow_remote_control, watchers=special_window.watchers, overlay_behind=special_window.overlay_behind,
            hold=special_window.hold, remote_control_passwords=remote_control_passwords, pass_fds=pass_fds, remote_control_fd=remote_control_fd,
        )

    @ac('win', 'Close all windows in the tab other than the currently active window')
    def close_other_windows_in_tab(self) -> None:
        if len(self.windows) > 1:
            active_window = self.active_window
            for window in tuple(self.windows):
                if window is not active_window:
                    self.remove_window(window)

    def move_window_to_top_of_group(self, window: Window) -> bool:
        return self.windows.move_window_to_top_of_group(window)

    def overlay_parent(self, window: Window) -> Window | None:
        prev: Window | None = None
        for x in self.windows.windows_in_group_of(window):
            if x is window:
                break
            prev = x
        return prev

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

    def detach_window(self, window: Window) -> tuple[Window, ...]:
        windows = list(self.windows.windows_in_group_of(window))
        windows.sort(key=attrgetter('id'))  # since ids increase in order of creation
        for w in reversed(windows):
            self.remove_window(w, destroy=False)
        return tuple(windows)

    def attach_window(self, window: Window) -> None:
        window.change_tab(self)
        attach_window(self.os_window_id, self.id, window.id)
        self._add_window(window)

    def set_active_window(self, x: Window | int, for_keep_focus: Window | None = None) -> None:
        self.windows.set_active_window_group_for(x, for_keep_focus=for_keep_focus)

    def get_nth_window(self, n: int) -> Window | None:
        if self.windows:
            return self.current_layout.nth_window(self.windows, n)
        return None

    @ac('win', '''
        Focus the nth window if positive or the previously active windows if negative. When the number is larger
        than the number of windows focus the last window. For example::

            # focus the previously active window
            map ctrl+p nth_window -1
            # focus the first window
            map ctrl+1 nth_window 0
        ''')
    def nth_window(self, num: int = 0) -> None:
        if self.windows:
            if num < 0:
                self.windows.make_previous_group_active(-num)
            elif self.windows.num_groups:
                self.current_layout.activate_nth_window(self.windows, min(num, self.windows.num_groups - 1))
            self.relayout_borders()

    @ac('win', 'Focus the first window')
    def first_window(self) -> None:
        self.nth_window(0)

    @ac('win', 'Focus the second window')
    def second_window(self) -> None:
        self.nth_window(1)

    @ac('win', 'Focus the third window')
    def third_window(self) -> None:
        self.nth_window(2)

    @ac('win', 'Focus the fourth window')
    def fourth_window(self) -> None:
        self.nth_window(3)

    @ac('win', 'Focus the fifth window')
    def fifth_window(self) -> None:
        self.nth_window(4)

    @ac('win', 'Focus the sixth window')
    def sixth_window(self) -> None:
        self.nth_window(5)

    @ac('win', 'Focus the seventh window')
    def seventh_window(self) -> None:
        self.nth_window(6)

    @ac('win', 'Focus the eighth window')
    def eighth_window(self) -> None:
        self.nth_window(7)

    @ac('win', 'Focus the ninth window')
    def ninth_window(self) -> None:
        self.nth_window(8)

    @ac('win', 'Focus the tenth window')
    def tenth_window(self) -> None:
        self.nth_window(9)

    def _next_window(self, delta: int = 1) -> None:
        if len(self.windows) > 1:
            self.current_layout.next_window(self.windows, delta)
            self.relayout_borders()

    @ac('win', 'Focus the next window in the current tab')
    def next_window(self) -> None:
        self._next_window()

    @ac('win', 'Focus the previous window in the current tab')
    def previous_window(self) -> None:
        self._next_window(-1)

    prev_window = previous_window

    def most_recent_group(self, groups: Sequence[int]) -> int | None:
        groups_set = frozenset(groups)

        for window_id in reversed(self.windows.active_window_history):
            group = self.windows.group_for_window(window_id)
            if group and group.id in groups_set:
                return group.id

        if groups:
            return groups[0]
        return None

    def nth_active_window_id(self, n: int = 0) -> int:
        if n <= 0:
            return self.active_window.id if self.active_window else 0
        ids = tuple(reversed(self.windows.active_window_history))
        return ids[min(n - 1, len(ids) - 1)] if ids else 0

    def neighboring_group_id(self, which: EdgeLiteral) -> int | None:
        neighbors = self.current_layout.neighbors(self.windows)
        candidates = neighbors.get(which)
        if candidates:
            return self.most_recent_group(candidates)
        return None

    @ac('win', '''
        Focus the neighboring window in the current tab

        For example::

            map ctrl+left neighboring_window left
            map ctrl+down neighboring_window bottom
        ''')
    def neighboring_window(self, which: EdgeLiteral) -> None:
        neighbor = self.neighboring_group_id(which)
        if neighbor:
            self.windows.set_active_group(neighbor)

    @ac('win', '''
        Move the window in the specified direction

        For example::

            map ctrl+left move_window left
            map ctrl+down move_window bottom
        ''')
    def move_window(self, delta: EdgeLiteral | int = 1) -> None:
        if isinstance(delta, int):
            if self.current_layout.move_window(self.windows, delta):
                self.relayout()
        elif isinstance(delta, str):
            neighbor = self.neighboring_group_id(delta)
            if neighbor:
                if self.current_layout.move_window_to_group(self.windows, neighbor):
                    self.relayout()

    def swap_active_window_with(self, window_id: int) -> None:
        group = self.windows.group_for_window(window_id)
        if group is not None:
            w = self.active_window
            if w is not None and w.id != window_id:
                if self.current_layout.move_window_to_group(self.windows, group.id):
                    self.relayout()

    @property
    def all_window_ids_except_active_window(self) -> set[int]:
        all_window_ids = {w.id for w in self}
        aw = self.active_window
        if aw is not None:
            all_window_ids.discard(aw.id)
        return all_window_ids

    @ac('win', '''
        Focus a visible window by pressing the number of the window. Window numbers are displayed
        over the windows for easy selection in this mode. See :opt:`visual_window_select_characters`.
        ''')
    def focus_visible_window(self) -> None:
        def callback(tab: Tab | None, window: Window | None) -> None:
            if tab and window:
                tab.set_active_window(window)

        get_boss().visual_window_select_action(self, callback, 'Choose window to switch to', only_window_ids=self.all_window_ids_except_active_window)

    @ac('win', 'Swap the current window with another window in the current tab, selected visually. See :opt:`visual_window_select_characters`')
    def swap_with_window(self) -> None:
        def callback(tab: Tab | None, window: Window | None) -> None:
            if tab and window:
                tab.swap_active_window_with(window.id)
        get_boss().visual_window_select_action(self, callback, 'Choose window to swap with', only_window_ids=self.all_window_ids_except_active_window)

    @ac('win', 'Move active window to the top (make it the first window)')
    def move_window_to_top(self) -> None:
        n = self.windows.active_group_idx
        if n > 0:
            self.move_window(-n)

    @ac('win', 'Move active window forward (swap it with the next window)')
    def move_window_forward(self) -> None:
        self.move_window()

    @ac('win', 'Move active window backward (swap it with the previous window)')
    def move_window_backward(self) -> None:
        self.move_window(-1)

    def list_windows(self, self_window: Window | None = None, window_filter: Callable[[Window], bool] | None = None) -> Generator[WindowDict, None, None]:
        active_window = self.active_window
        for w in self:
            if window_filter is None or window_filter(w):
                yield w.as_dict(
                    is_active=w is active_window,
                    is_focused=w.os_window_id == current_focused_os_window_id() and w is active_window,
                    is_self=w is self_window)

    def list_groups(self) -> list[dict[str, Any]]:
        return [g.as_simple_dict() for g in self.windows.groups]

    def matches_query(self, field: str, query: str, active_tab_manager: Optional['TabManager'] = None) -> bool:
        if field == 'title':
            return re.search(query, self.effective_title) is not None
        if field == 'id':
            return query == str(self.id)
        if field in ('window_id', 'window_title'):
            field = field.partition('_')[-1]
            for w in self:
                if w.matches_query(field, query):
                    return True
            return False
        if field == 'index':
            if active_tab_manager and len(active_tab_manager.tabs):
                idx = (int(query) + len(active_tab_manager.tabs)) % len(active_tab_manager.tabs)
                return active_tab_manager.tabs[idx] is self
            return False
        if field == 'recent':
            if active_tab_manager and len(active_tab_manager.tabs):
                return self is active_tab_manager.nth_active_tab(int(query))
            return False
        if field == 'state':
            if query == 'active':
                tm = self.tab_manager_ref()
                return tm is not None and self is tm.active_tab
            if query == 'focused':
                return active_tab_manager is not None and self is active_tab_manager.active_tab and self.os_window_id == last_focused_os_window_id()
            if query == 'needs_attention':
                for w in self:
                    if w.needs_attention:
                        return True
            if query == 'parent_active':
                return active_tab_manager is not None and self.tab_manager_ref() is active_tab_manager
            if query == 'parent_focused':
                return active_tab_manager is not None and self.tab_manager_ref() is active_tab_manager and self.os_window_id == last_focused_os_window_id()
            return False
        return False

    def __iter__(self) -> Iterator[Window]:
        return iter(self.windows)

    def __len__(self) -> int:
        return len(self.windows)

    @property
    def num_window_groups(self) -> int:
        return self.windows.num_groups

    def __contains__(self, window: Window) -> bool:
        return window in self.windows

    def destroy(self) -> None:
        evict_cached_layouts(self.id)
        for w in self.windows:
            w.destroy()
        self.windows = WindowList(self)

    def __repr__(self) -> str:
        return f'Tab(title={self.effective_title}, id={self.id})'

    def make_active(self) -> None:
        tm = self.tab_manager_ref()
        if tm is not None:
            tm.set_active_tab(self)
# }}}


class TabManager:  # {{{

    confirm_close_window_id: int = 0
    num_of_windows_with_progress: int = 0
    total_progress: int = 0
    has_indeterminate_progress: bool = False

    def __init__(self, os_window_id: int, args: CLIOptions, wm_class: str, wm_name: str, startup_session: SessionType | None = None):
        self.os_window_id = os_window_id
        self.wm_class = wm_class
        self.recent_mouse_events: Deque[TabMouseEvent] = deque()
        self.wm_name = wm_name
        self.args = args
        self.tab_bar_hidden = get_options().tab_bar_style == 'hidden'
        self.tabs: list[Tab] = []
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
        new_active_tab_idx = max(0, min(val, len(self.tabs) - 1))
        if new_active_tab_idx == self._active_tab_idx:
            return
        try:
            old_active_tab: Tab | None = self.tabs[self._active_tab_idx]
        except Exception:
            old_active_tab = None
        else:
            assert old_active_tab is not None
            add_active_id_to_history(self.active_tab_history, old_active_tab.id)
        self._active_tab_idx = new_active_tab_idx
        try:
            new_active_tab: Tab | None = self.tabs[self._active_tab_idx]
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

    def _set_active_tab(self, idx: int, store_in_history: bool = True) -> None:
        if store_in_history:
            self.active_tab_idx = idx
        else:
            self._active_tab_idx = idx
        set_active_tab(self.os_window_id, idx)

    def tabbar_visibility_changed(self) -> None:
        if not self.tab_bar_hidden:
            self.tab_bar.layout()
            self.resize(only_tabs=True)

    @property
    def any_window(self) -> Window | None:
        for t in self:
            for w in t:
                return w
        return None

    def mark_tab_bar_dirty(self) -> None:
        if self.tab_bar_should_be_visible and not self.tab_bar_hidden:
            mark_tab_bar_dirty(self.os_window_id)
        w = self.active_window or self.any_window
        if w is not None:
            data = {'tab_manager': self}
            boss = get_boss()
            for watcher in global_watchers().on_tab_bar_dirty:
                watcher(boss, w, data)

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

    def set_active_tab(self, tab: Tab, for_keep_focus: Tab | None = None) -> bool:
        try:
            idx = self.tabs.index(tab)
        except Exception:
            return False
        self.set_active_tab_idx(idx)
        h = self.active_tab_history
        if for_keep_focus and len(h) > 2 and h[-2] == for_keep_focus.id and h[-1] != for_keep_focus.id:
            h.pop()
            h.pop()
        return True

    def next_tab(self, delta: int = 1) -> None:
        if len(self.tabs) > 1:
            self.set_active_tab_idx((self.active_tab_idx + len(self.tabs) + delta) % len(self.tabs))

    def toggle_tab(self, match_expression: str) -> None:
        tabs = set(get_boss().match_tabs(match_expression)) & set(self)
        if not tabs:
            get_boss().show_error(_('No matching tab'), _('No tab found matching the expression: {}').format(match_expression))
            return
        if self.active_tab and self.active_tab in tabs:
            self.goto_tab(-1)
        else:
            for x in self:
                if x in tabs:
                    self.set_active_tab(x)
                    break

    def tab_at_location(self, loc: str) -> Tab | None:
        if loc == 'prev':
            if self.active_tab_history:
                old_active_tab_id = self.active_tab_history[-1]
                for idx, tab in enumerate(self.tabs):
                    if tab.id == old_active_tab_id:
                        return tab
        elif loc in ('left', 'right'):
            delta = -1 if loc == 'left' else 1
            idx = (len(self.tabs) + self.active_tab_idx + delta) % len(self.tabs)
            return self.tabs[idx]
        return None

    def goto_tab(self, tab_num: int) -> None:
        if tab_num >= len(self.tabs):
            tab_num = max(0, len(self.tabs) - 1)
        if tab_num >= 0:
            self.set_active_tab_idx(tab_num)
        elif self.active_tab_history:
            try:
                old_active_tab_id = self.active_tab_history[tab_num]
            except IndexError:
                old_active_tab_id = self.active_tab_history[0]
            for idx, tab in enumerate(self.tabs):
                if tab.id == old_active_tab_id:
                    self.set_active_tab_idx(idx)
                    break

    def nth_active_tab(self, n: int = 0) -> Tab | None:
        if n <= 0:
            return self.active_tab
        tab_ids = tuple(reversed(self.active_tab_history))
        return self.tab_for_id(tab_ids[min(n - 1, len(tab_ids) - 1)]) if tab_ids else None

    def __iter__(self) -> Iterator[Tab]:
        return iter(self.tabs)

    def __len__(self) -> int:
        return len(self.tabs)

    def list_tabs(
        self, self_window: Window | None = None,
        tab_filter: Callable[[Tab], bool] | None = None,
        window_filter: Callable[[Window], bool] | None = None
    ) -> Generator[TabDict, None, None]:
        active_tab = self.active_tab
        for tab in self:
            if tab_filter is None or tab_filter(tab):
                windows = list(tab.list_windows(self_window, window_filter))
                if windows:
                    yield {
                        'id': tab.id,
                        'is_focused': tab is active_tab and tab.os_window_id == current_focused_os_window_id(),
                        'is_active': tab is active_tab,
                        'title': tab.name or tab.title,
                        'layout': str(tab.current_layout.name),
                        'layout_state': tab.current_layout.layout_state(),
                        'layout_opts': tab.current_layout.layout_opts.serialized(),
                        'enabled_layouts': tab.enabled_layouts,
                        'windows': windows,
                        'groups': tab.list_groups(),
                        'active_window_history': list(tab.windows.active_window_history),
                    }

    def serialize_state(self) -> dict[str, Any]:
        return {
            'version': 1,
            'id': self.os_window_id,
            'tabs': [tab.serialize_state() for tab in self],
            'active_tab_idx': self.active_tab_idx,
        }

    @property
    def active_tab(self) -> Tab | None:
        try:
            return self.tabs[self.active_tab_idx] if self.tabs else None
        except Exception:
            return None

    @property
    def active_window(self) -> Window | None:
        t = self.active_tab
        if t is not None:
            return t.active_window
        return None

    @property
    def number_of_windows(self) -> int:
        count = 0
        for tab in self:
            count += len(tab)
        return count

    def tab_for_id(self, tab_id: int) -> Tab | None:
        for t in self.tabs:
            if t.id == tab_id:
                return t
        return None

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
        special_window: SpecialWindowInstance | None = None,
        cwd_from: CwdRequest | None = None,
        as_neighbor: bool = False,
        empty_tab: bool = False,
        location: str = 'last'
    ) -> Tab:
        idx = len(self.tabs)
        orig_active_tab_idx = self.active_tab_idx
        self._add_tab(Tab(self, no_initial_window=True) if empty_tab else Tab(self, special_window=special_window, cwd_from=cwd_from))
        if as_neighbor:
            location = 'after'
        if location == 'neighbor':
            location = 'after'
        if location == 'default':
            location = 'last'
        if len(self.tabs) > 1 and location != 'last':
            if location == 'first':
                desired_idx = 0
            else:
                desired_idx = orig_active_tab_idx + (0 if location == 'before' else 1)
            if idx != desired_idx:
                for i in range(idx, desired_idx, -1):
                    self.tabs[i], self.tabs[i-1] = self.tabs[i-1], self.tabs[i]
                    swap_tabs(self.os_window_id, i, i-1)
                idx = desired_idx
        self._set_active_tab(idx)
        self.mark_tab_bar_dirty()
        return self.tabs[idx]

    def remove(self, tab: Tab) -> None:
        active_tab_before_removal = self.active_tab
        active_tab_needs_to_change = active_tab_before_removal is tab
        self._remove_tab(tab)
        while True:
            try:
                self.active_tab_history.remove(tab.id)
            except ValueError:
                break

        def idx_for_id(tab_id: int) -> int:
            for idx, qtab in enumerate(self.tabs):
                if qtab.id == tab_id:
                    return idx
            return -1

        def remove_from_end_of_active_history(idx: int) -> None:
            while self.active_tab_history and idx_for_id(self.active_tab_history[-1]) == idx:
                self.active_tab_history.pop()

        if active_tab_needs_to_change:
            next_active_tab = -1
            tss = get_options().tab_switch_strategy
            if tss == 'previous':
                while self.active_tab_history and next_active_tab < 0:
                    tab_id = self.active_tab_history.pop()
                    next_active_tab = idx_for_id(tab_id)
            elif tss == 'left':
                next_active_tab = max(0, self.active_tab_idx - 1)
                remove_from_end_of_active_history(next_active_tab)
            elif tss == 'right':
                next_active_tab = min(self.active_tab_idx, len(self.tabs) - 1)
                remove_from_end_of_active_history(next_active_tab)
            elif tss == 'last':
                next_active_tab = len(self.tabs) - 1
                remove_from_end_of_active_history(next_active_tab)

            if next_active_tab < 0:
                next_active_tab = max(0, min(self.active_tab_idx, len(self.tabs) - 1))

            self._set_active_tab(next_active_tab, store_in_history=False)
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
    def tab_bar_data(self) -> list[TabBarData]:
        at = self.active_tab
        ans = []
        for t in self.tabs:
            title = t.name or t.title or appname
            needs_attention = False
            has_activity_since_last_focus = False
            for w in t:
                if w.needs_attention:
                    needs_attention = True
                if w.has_activity_since_last_focus:
                    has_activity_since_last_focus = True
            ans.append(TabBarData(
                title, t is at, needs_attention, t.id,
                len(t), t.num_window_groups, t.current_layout.name or '',
                has_activity_since_last_focus, t.active_fg, t.active_bg,
                t.inactive_fg, t.inactive_bg, t.num_of_windows_with_progress,
                t.total_progress, t.last_focused_window_with_progress_id,
            ))
        return ans

    def handle_click_on_tab(self, x: int, button: int, modifiers: int, action: int) -> None:
        i = self.tab_bar.tab_at(x)
        now = monotonic()
        if i is None:
            if button == GLFW_MOUSE_BUTTON_LEFT and action == GLFW_RELEASE and len(self.recent_mouse_events) > 2:
                ci = get_click_interval()
                prev, prev2 = self.recent_mouse_events[-1], self.recent_mouse_events[-2]
                if (
                    prev.button == button and prev2.button == button and
                    prev.action == GLFW_PRESS and prev2.action == GLFW_RELEASE and
                    prev.tab_idx is None and prev2.tab_idx is None and
                    now - prev.at <= ci and now - prev2.at <= 2 * ci
                ):  # double click
                    self.new_tab()
                    self.recent_mouse_events.clear()
                    return
        else:
            if action == GLFW_PRESS and button == GLFW_MOUSE_BUTTON_LEFT:
                self.set_active_tab_idx(i)
            elif button == GLFW_MOUSE_BUTTON_MIDDLE and action == GLFW_RELEASE and self.recent_mouse_events:
                p = self.recent_mouse_events[-1]
                if p.button == button and p.action == GLFW_PRESS and p.tab_idx == i:
                    tab = self.tabs[i]
                    get_boss().close_tab(tab)
        self.recent_mouse_events.append(TabMouseEvent(button, modifiers, action, now, i))
        if len(self.recent_mouse_events) > 5:
            self.recent_mouse_events.popleft()

    def update_progress(self) -> None:
        self.num_of_windows_with_progress = 0
        self.total_progress = 0
        self.has_indeterminate_progress = False
        for tab in self:
            if tab.num_of_windows_with_progress:
                self.total_progress += tab.total_progress
                self.num_of_windows_with_progress += tab.num_of_windows_with_progress
            if tab.has_indeterminate_progress:
                self.has_indeterminate_progress = True
        get_boss().update_progress_in_dock()

    @property
    def tab_bar_rects(self) -> tuple[Border, ...]:
        return self.tab_bar.blank_rects if self.tab_bar_should_be_visible else ()

    def destroy(self) -> None:
        for t in self:
            t.destroy()
        self.tab_bar.destroy()
        del self.tab_bar
        del self.tabs

    def apply_options(self) -> None:
        at = self.active_tab
        for tab in self:
            tab.apply_options(at is tab)
        self.tab_bar_hidden = get_options().tab_bar_style == 'hidden'
        self.tab_bar.apply_options()
        self.update_tab_bar_data()
        self.mark_tab_bar_dirty()
        self.tab_bar.layout()
# }}}
