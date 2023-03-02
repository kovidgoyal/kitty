#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import stat
import weakref
from collections import deque
from contextlib import suppress
from operator import attrgetter
from time import monotonic
from typing import (
    Any,
    Deque,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from .borders import Border, Borders
from .child import Child
from .cli_stub import CLIOptions
from .constants import appname, kitten_exe
from .fast_data_types import (
    GLFW_MOUSE_BUTTON_LEFT,
    GLFW_MOUSE_BUTTON_MIDDLE,
    GLFW_PRESS,
    GLFW_RELEASE,
    add_tab,
    attach_window,
    current_focused_os_window_id,
    detach_window,
    get_boss,
    get_click_interval,
    get_options,
    last_focused_os_window_id,
    mark_tab_bar_dirty,
    next_window_id,
    remove_tab,
    remove_window,
    ring_bell,
    set_active_tab,
    set_active_window,
    swap_tabs,
    sync_os_window_title,
)
from .layout.base import Layout
from .layout.interface import create_layout_object_for, evict_cached_layouts
from .tab_bar import TabBar, TabBarData
from .types import ac
from .typing import EdgeLiteral, SessionTab, SessionType, TypedDict
from .utils import log_error, platform_window_id, resolved_shell
from .window import CwdRequest, Watchers, Window, WindowDict, window_focus_may_change
from .window_list import WindowList


class TabMouseEvent(NamedTuple):
    button: int
    modifiers: int
    action: int
    at: float
    tab_idx: Optional[int]


class TabDict(TypedDict):
    id: int
    is_focused: bool
    is_active: bool
    title: str
    layout: str
    layout_state: Dict[str, Any]
    layout_opts: Dict[str, Any]
    enabled_layouts: List[str]
    windows: List[WindowDict]
    active_window_history: List[int]


class SpecialWindowInstance(NamedTuple):
    cmd: Optional[List[str]]
    stdin: Optional[bytes]
    override_title: Optional[str]
    cwd_from: Optional[CwdRequest]
    cwd: Optional[str]
    overlay_for: Optional[int]
    env: Optional[Dict[str, str]]
    watchers: Optional[Watchers]
    overlay_behind: bool


def SpecialWindow(
    cmd: Optional[List[str]],
    stdin: Optional[bytes] = None,
    override_title: Optional[str] = None,
    cwd_from: Optional[CwdRequest] = None,
    cwd: Optional[str] = None,
    overlay_for: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    watchers: Optional[Watchers] = None,
    overlay_behind: bool = False
) -> SpecialWindowInstance:
    return SpecialWindowInstance(cmd, stdin, override_title, cwd_from, cwd, overlay_for, env, watchers, overlay_behind)


def add_active_id_to_history(items: Deque[int], item_id: int, maxlen: int = 64) -> None:
    with suppress(ValueError):
        items.remove(item_id)
    items.append(item_id)
    if len(items) > maxlen:
        items.popleft()


class Tab:  # {{{

    active_fg: Optional[int] = None
    active_bg: Optional[int] = None
    inactive_fg: Optional[int] = None
    inactive_bg: Optional[int] = None

    def __init__(
        self,
        tab_manager: 'TabManager',
        session_tab: Optional['SessionTab'] = None,
        special_window: Optional[SpecialWindowInstance] = None,
        cwd_from: Optional[CwdRequest] = None,
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
        self.windows = WindowList(self)
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

    def set_enabled_layouts(self, val: Iterable[str]) -> None:
        self.enabled_layouts = [x.lower() for x in val] or ['tall']
        if self.current_layout.name not in self.enabled_layouts:
            self._set_current_layout(self.enabled_layouts[0])
        self.relayout()

    def apply_options(self) -> None:
        for window in self:
            window.apply_options()
        self.set_enabled_layouts(get_options().enabled_layouts)

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
        self.active_window_changed()
        self.relayout()

    def _set_current_layout(self, layout_name: str) -> None:
        self._last_used_layout = self._current_layout_name
        self.current_layout = self.create_layout_object(layout_name)
        self._current_layout_name = layout_name
        self.mark_tab_bar_dirty()

    def startup(self, session_tab: 'SessionTab') -> None:
        for window in session_tab.windows:
            spec = window.launch_spec
            if isinstance(spec, SpecialWindowInstance):
                self.new_special_window(spec)
            else:
                from .launch import launch
                launch(get_boss(), spec.opts, spec.args, target_tab=self, force_target_tab=True)
            if window.resize_spec is not None:
                self.resize_window(*window.resize_spec)

        self.windows.set_active_window_group_for(self.windows.all_windows[session_tab.active_window_idx])

    def serialize_state(self) -> Dict[str, Any]:
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
    def active_window(self) -> Optional[Window]:
        return self.windows.active_window

    @property
    def active_window_for_cwd(self) -> Optional[Window]:
        return self.windows.active_group_main

    @property
    def title(self) -> str:
        w = self.active_window
        return w.title if w else appname

    @property
    def effective_title(self) -> str:
        return self.name or self.title

    @property
    def number_of_windows_with_running_programs(self) -> int:
        ans = 0
        for window in self:
            if window.has_running_program:
                ans += 1
        return ans

    def get_cwd_of_active_window(self, oldest: bool = False) -> Optional[str]:
        w = self.active_window
        return w.get_cwd_of_child(oldest) if w else None

    def get_exe_of_active_window(self, oldest: bool = False) -> Optional[str]:
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
            w = self.active_window
            ly = self.current_layout
            self.borders(
                all_windows=self.windows,
                current_layout=ly, tab_bar_rects=tm.tab_bar_rects,
                draw_window_borders=(ly.needs_window_borders and self.windows.num_visble_groups > 1) or ly.must_draw_borders
            )
            if w is not None:
                w.change_titlebar_color()

    def create_layout_object(self, name: str) -> Layout:
        return create_layout_object_for(name, self.os_window_id, self.id)

    @ac('lay', 'Go to the next enabled layout')
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

    @ac('lay', 'Go to the previously used layout')
    def last_used_layout(self) -> None:
        if len(self.enabled_layouts) > 1 and self._last_used_layout and self._last_used_layout != self._current_layout_name:
            self._set_current_layout(self._last_used_layout)
            self.relayout()

    @ac('lay', '''
        Switch to the named layout

        For example::

            map f1 goto_layout tall
        ''')
    def goto_layout(self, layout_name: str, raise_exception: bool = False) -> None:
        layout_name = layout_name.lower()
        if layout_name not in self.enabled_layouts:
            if raise_exception:
                raise ValueError(layout_name)
            log_error(f'Unknown or disabled layout: {layout_name}')
            return
        self._set_current_layout(layout_name)
        self.relayout()

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

    def resize_window_by(self, window_id: int, increment: float, is_horizontal: bool) -> Optional[str]:
        increment_as_percent = self.current_layout.bias_increment_for_cell(self.windows, window_id, is_horizontal) * increment
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
                ring_bell()

    @ac('win', 'Reset window sizes undoing any dynamic resizing of windows')
    def reset_window_sizes(self) -> None:
        if self.current_layout.remove_all_biases():
            self.relayout()

    @ac('lay', 'Perform a layout specific action. See :doc:`layouts` for details')
    def layout_action(self, action_name: str, args: Sequence[str]) -> None:
        ret = self.current_layout.layout_action(action_name, args, self.windows)
        if ret is None:
            if get_options().enable_audio_bell:
                ring_bell()
            return
        self.relayout()

    def launch_child(
        self,
        use_shell: bool = False,
        cmd: Optional[List[str]] = None,
        stdin: Optional[bytes] = None,
        cwd_from: Optional[CwdRequest] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        is_clone_launch: str = '',
        add_listen_on_env_var: bool = True,
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
                from .utils import which
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
                        import shlex
                        with suppress(OSError):
                            with open(old_exe) as f:
                                if f.read(2) == '#!':
                                    line = f.read(4096).splitlines()[0]
                                    cmd[:0] = shlex.split(line)
                                else:
                                    cmd[:0] = [resolved_shell(get_options())[0]]
                                cmd[0] = which(cmd[0]) or cmd[0]
                                cmd[:0] = [kitten_exe(), '__hold_till_enter__']
        fenv: Dict[str, str] = {}
        if env:
            fenv.update(env)
        fenv['KITTY_WINDOW_ID'] = str(next_window_id())
        pwid = platform_window_id(self.os_window_id)
        if pwid is not None:
            fenv['WINDOWID'] = str(pwid)
        ans = Child(cmd, cwd or self.cwd, stdin, fenv, cwd_from, is_clone_launch=is_clone_launch, add_listen_on_env_var=add_listen_on_env_var)
        ans.fork()
        return ans

    def _add_window(self, window: Window, location: Optional[str] = None, overlay_for: Optional[int] = None, overlay_behind: bool = False) -> None:
        self.current_layout.add_window(self.windows, window, location, overlay_for, put_overlay_behind=overlay_behind)
        self.mark_tab_bar_dirty()
        self.relayout()

    def new_window(
        self,
        use_shell: bool = True,
        cmd: Optional[List[str]] = None,
        stdin: Optional[bytes] = None,
        override_title: Optional[str] = None,
        cwd_from: Optional[CwdRequest] = None,
        cwd: Optional[str] = None,
        overlay_for: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        location: Optional[str] = None,
        copy_colors_from: Optional[Window] = None,
        allow_remote_control: bool = False,
        marker: Optional[str] = None,
        watchers: Optional[Watchers] = None,
        overlay_behind: bool = False,
        is_clone_launch: str = '',
        remote_control_passwords: Optional[Dict[str, Sequence[str]]] = None,
    ) -> Window:
        child = self.launch_child(
            use_shell=use_shell, cmd=cmd, stdin=stdin, cwd_from=cwd_from, cwd=cwd, env=env,
            is_clone_launch=is_clone_launch, add_listen_on_env_var=False if allow_remote_control and remote_control_passwords else True
        )
        window = Window(
            self, child, self.args, override_title=override_title,
            copy_colors_from=copy_colors_from, watchers=watchers,
            allow_remote_control=allow_remote_control, remote_control_passwords=remote_control_passwords
        )
        # Must add child before laying out so that resize_pty succeeds
        get_boss().add_child(window)
        self._add_window(window, location=location, overlay_for=overlay_for, overlay_behind=overlay_behind)
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
            allow_remote_control=allow_remote_control, watchers=special_window.watchers, overlay_behind=special_window.overlay_behind
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

    def overlay_parent(self, window: Window) -> Optional[Window]:
        prev: Optional[Window] = None
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

    def set_active_window(self, x: Union[Window, int], for_keep_focus: Optional[Window] = None) -> None:
        self.windows.set_active_window_group_for(x, for_keep_focus=for_keep_focus)

    def get_nth_window(self, n: int) -> Optional[Window]:
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
    @window_focus_may_change
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

    @window_focus_may_change
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

    def most_recent_group(self, groups: Sequence[int]) -> Optional[int]:
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

    def neighboring_group_id(self, which: EdgeLiteral) -> Optional[int]:
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
    @window_focus_may_change
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
    @window_focus_may_change
    def move_window(self, delta: Union[EdgeLiteral, int] = 1) -> None:
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
    def all_window_ids_except_active_window(self) -> Set[int]:
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
        @window_focus_may_change
        def callback(tab: Optional[Tab], window: Optional[Window]) -> None:
            if tab and window:
                tab.set_active_window(window)

        get_boss().visual_window_select_action(self, callback, 'Choose window to switch to', only_window_ids=self.all_window_ids_except_active_window)

    @ac('win', 'Swap the current window with another window in the current tab, selected visually. See :opt:`visual_window_select_characters`')
    def swap_with_window(self) -> None:
        @window_focus_may_change
        def callback(tab: Optional[Tab], window: Optional[Window]) -> None:
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

    def list_windows(self, self_window: Optional[Window] = None) -> Generator[WindowDict, None, None]:
        active_window = self.active_window
        for w in self:
            yield w.as_dict(
                is_active=w is active_window,
                is_focused=w.os_window_id == current_focused_os_window_id() and w is active_window,
                is_self=w is self_window)

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

    def __init__(self, os_window_id: int, args: CLIOptions, wm_class: str, wm_name: str, startup_session: Optional[SessionType] = None):
        self.os_window_id = os_window_id
        self.wm_class = wm_class
        self.recent_mouse_events: Deque[TabMouseEvent] = deque()
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
        new_active_tab_idx = max(0, min(val, len(self.tabs) - 1))
        if new_active_tab_idx == self._active_tab_idx:
            return
        try:
            old_active_tab: Optional[Tab] = self.tabs[self._active_tab_idx]
        except Exception:
            old_active_tab = None
        else:
            assert old_active_tab is not None
            add_active_id_to_history(self.active_tab_history, old_active_tab.id)
        self._active_tab_idx = new_active_tab_idx
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

    def set_active_tab(self, tab: Tab, for_keep_focus: Optional[Tab] = None) -> bool:
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

    def tab_at_location(self, loc: str) -> Optional[Tab]:
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
        else:
            try:
                old_active_tab_id = self.active_tab_history[tab_num]
            except IndexError:
                return
            for idx, tab in enumerate(self.tabs):
                if tab.id == old_active_tab_id:
                    self.set_active_tab_idx(idx)
                    break

    def nth_active_tab(self, n: int = 0) -> Optional[Tab]:
        if n <= 0:
            return self.active_tab
        tab_ids = tuple(reversed(self.active_tab_history))
        return self.tab_for_id(tab_ids[min(n - 1, len(tab_ids) - 1)]) if tab_ids else None

    def __iter__(self) -> Iterator[Tab]:
        return iter(self.tabs)

    def __len__(self) -> int:
        return len(self.tabs)

    def list_tabs(self, self_window: Optional[Window] = None) -> Generator[TabDict, None, None]:
        active_tab = self.active_tab
        for tab in self:
            yield {
                'id': tab.id,
                'is_focused': tab is active_tab and tab.os_window_id == current_focused_os_window_id(),
                'is_active': tab is active_tab,
                'title': tab.name or tab.title,
                'layout': str(tab.current_layout.name),
                'layout_state': tab.current_layout.layout_state(),
                'layout_opts': tab.current_layout.layout_opts.serialized(),
                'enabled_layouts': tab.enabled_layouts,
                'windows': list(tab.list_windows(self_window)),
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
        return None

    @property
    def number_of_windows_with_running_programs(self) -> int:
        count = 0
        for tab in self:
            count += tab.number_of_windows_with_running_programs
        return count

    @property
    def number_of_windows(self) -> int:
        count = 0
        for tab in self:
            count += len(tab)
        return count

    def tab_for_id(self, tab_id: int) -> Optional[Tab]:
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
        special_window: Optional[SpecialWindowInstance] = None,
        cwd_from: Optional[CwdRequest] = None,
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

        if active_tab_needs_to_change:
            next_active_tab = -1
            tss = get_options().tab_switch_strategy
            if tss == 'previous':
                while self.active_tab_history and next_active_tab < 0:
                    tab_id = self.active_tab_history.pop()
                    next_active_tab = idx_for_id(tab_id)
            elif tss == 'left':
                next_active_tab = max(0, self.active_tab_idx - 1)
            elif tss == 'right':
                next_active_tab = min(self.active_tab_idx, len(self.tabs) - 1)
            elif tss == 'last':
                next_active_tab = len(self.tabs) - 1

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
    def tab_bar_data(self) -> List[TabBarData]:
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
                t.inactive_fg, t.inactive_bg
            ))
        return ans

    @window_focus_may_change
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

    @property
    def tab_bar_rects(self) -> Tuple[Border, ...]:
        return self.tab_bar.blank_rects if self.tab_bar_should_be_visible else ()

    def destroy(self) -> None:
        for t in self:
            t.destroy()
        self.tab_bar.destroy()
        del self.tab_bar
        del self.tabs

    def apply_options(self) -> None:
        for tab in self:
            tab.apply_options()
        self.tab_bar_hidden = get_options().tab_bar_style == 'hidden'
        self.tab_bar.apply_options()
        self.update_tab_bar_data()
        self.mark_tab_bar_dirty()
        self.tab_bar.layout()
# }}}
