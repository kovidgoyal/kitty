#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import weakref
from collections import deque
from contextlib import suppress
from itertools import count
from typing import (
    Any, Deque, Dict, Generator, Iterator, List, Optional, Tuple, Union
)

from .types import WindowGeometry
from .typing import EdgeLiteral, TabType, WindowType

WindowOrId = Union[WindowType, int]
group_id_counter = count(start=1)


def reset_group_id_counter() -> None:
    global group_id_counter
    group_id_counter = count(start=1)


def wrap_increment(val: int, num: int, delta: int) -> int:
    mult = -1 if delta < 0 else 1
    delta = mult * (abs(delta) % num)
    return (val + num + delta) % num


class WindowGroup:

    def __init__(self) -> None:
        self.windows: List[WindowType] = []
        self.id = next(group_id_counter)

    def __len__(self) -> int:
        return len(self.windows)

    def __bool__(self) -> bool:
        return bool(self.windows)

    def __iter__(self) -> Iterator[WindowType]:
        return iter(self.windows)

    def __contains__(self, window: WindowType) -> bool:
        for w in self.windows:
            if w is window:
                return True
        return False

    @property
    def needs_attention(self) -> bool:
        for w in self.windows:
            if w.needs_attention:
                return True
        return False

    @property
    def base_window_id(self) -> int:
        return self.windows[0].id if self.windows else 0

    @property
    def active_window_id(self) -> int:
        return self.windows[-1].id if self.windows else 0

    def add_window(self, window: WindowType) -> None:
        self.windows.append(window)

    def remove_window(self, window: WindowType) -> None:
        with suppress(ValueError):
            self.windows.remove(window)

    def serialize_state(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'windows': [w.serialize_state() for w in self.windows]
        }

    def decoration(self, which: EdgeLiteral, border_mult: int = 1, is_single_window: bool = False) -> int:
        if not self.windows:
            return 0
        w = self.windows[0]
        return w.effective_margin(which, is_single_window=is_single_window) + w.effective_border() * border_mult + w.effective_padding(which)

    def effective_padding(self, which: EdgeLiteral) -> int:
        if not self.windows:
            return 0
        w = self.windows[0]
        return w.effective_padding(which)

    def effective_border(self) -> int:
        if not self.windows:
            return 0
        w = self.windows[0]
        return w.effective_border()

    def set_geometry(self, geom: WindowGeometry) -> None:
        for w in self.windows:
            w.set_geometry(geom)

    @property
    def default_bg(self) -> int:
        if self.windows:
            w: WindowType = self.windows[-1]
            return w.screen.color_profile.default_bg
        return 0

    @property
    def geometry(self) -> Optional[WindowGeometry]:
        if self.windows:
            w: WindowType = self.windows[-1]
            return w.geometry

    @property
    def is_visible_in_layout(self) -> bool:
        if self.windows:
            w: WindowType = self.windows[-1]
            return w.is_visible_in_layout
        return False


class WindowList:

    def __init__(self, tab: TabType) -> None:
        self.all_windows: List[WindowType] = []
        self.id_map: Dict[int, WindowType] = {}
        self.groups: List[WindowGroup] = []
        self._active_group_idx: int = -1
        self.active_group_history: Deque[int] = deque((), 64)
        self.tabref = weakref.ref(tab)

    def __len__(self) -> int:
        return len(self.all_windows)

    def __bool__(self) -> bool:
        return bool(self.all_windows)

    def __iter__(self) -> Iterator[WindowType]:
        return iter(self.all_windows)

    def __contains__(self, window: WindowOrId) -> bool:
        q = window if isinstance(window, int) else window.id
        return q in self.id_map

    def serialize_state(self) -> Dict[str, Any]:
        return {
            'active_group_idx': self.active_group_idx,
            'active_group_history': list(self.active_group_history),
            'window_groups': [g.serialize_state() for g in self.groups]
        }

    @property
    def active_group_idx(self) -> int:
        return self._active_group_idx

    @property
    def active_window_history(self) -> List[int]:
        ans = []
        seen = set()
        gid_map = {g.id: g for g in self.groups}
        for gid in self.active_group_history:
            g = gid_map.get(gid)
            if g is not None:
                w = g.active_window_id
                if w > 0 and w not in seen:
                    seen.add(w)
                    ans.append(w)
        return ans

    def notify_on_active_window_change(self, old_active_window: Optional[WindowType], new_active_window: Optional[WindowType]) -> None:
        if old_active_window is not None:
            old_active_window.focus_changed(False)
        if new_active_window is not None:
            new_active_window.focus_changed(True)
        tab = self.tabref()
        if tab is not None:
            tab.active_window_changed()

    def set_active_group_idx(self, i: int, notify: bool = True) -> bool:
        changed = False
        if i != self._active_group_idx and 0 <= i < len(self.groups):
            old_active_window = self.active_window
            g = self.active_group
            if g is not None:
                with suppress(ValueError):
                    self.active_group_history.remove(g.id)
                self.active_group_history.append(g.id)
            self._active_group_idx = i
            new_active_window = self.active_window
            if old_active_window is not new_active_window:
                if notify:
                    self.notify_on_active_window_change(old_active_window, new_active_window)
                changed = True
        return changed

    def set_active_group(self, group_id: int) -> bool:
        for i, gr in enumerate(self.groups):
            if gr.id == group_id:
                return self.set_active_group_idx(i)

    def change_tab(self, tab: TabType) -> None:
        self.tabref = weakref.ref(tab)

    def iter_windows_with_visibility(self) -> Generator[Tuple[WindowType, bool], None, None]:
        for g in self.groups:
            aw = g.active_window_id
            for window in g:
                yield window, window.id == aw

    def iter_all_layoutable_groups(self, only_visible: bool = False) -> Iterator[WindowGroup]:
        return iter(g for g in self.groups if g.is_visible_in_layout) if only_visible else iter(self.groups)

    def make_previous_group_active(self, which: int = 1, notify: bool = True) -> None:
        which = max(1, which)
        gid_map = {g.id: i for i, g in enumerate(self.groups)}
        num = len(self.active_group_history)
        for i in range(num):
            idx = num - i - 1
            gid = self.active_group_history[idx]
            x = gid_map.get(gid)
            if x is not None:
                which -= 1
                if which < 1:
                    self.set_active_group_idx(x, notify=notify)
                    return
        self.set_active_group_idx(len(self.groups) - 1, notify=notify)

    @property
    def num_groups(self) -> int:
        return len(self.groups)

    def group_for_window(self, x: WindowOrId) -> Optional[WindowGroup]:
        q = self.id_map[x] if isinstance(x, int) else x
        for g in self.groups:
            if q in g:
                return g

    def group_idx_for_window(self, x: WindowOrId) -> Optional[int]:
        q = self.id_map[x] if isinstance(x, int) else x
        for i, g in enumerate(self.groups):
            if q in g:
                return i

    def windows_in_group_of(self, x: WindowOrId) -> Iterator[WindowType]:
        g = self.group_for_window(x)
        if g is not None:
            return iter(g)

    @property
    def active_group(self) -> Optional[WindowGroup]:
        with suppress(Exception):
            return self.groups[self.active_group_idx]

    @property
    def active_window(self) -> Optional[WindowType]:
        with suppress(Exception):
            return self.id_map[self.groups[self.active_group_idx].active_window_id]

    @property
    def active_group_base(self) -> Optional[WindowType]:
        with suppress(Exception):
            return self.id_map[self.groups[self.active_group_idx].base_window_id]

    def set_active_window_group_for(self, x: WindowOrId) -> None:
        try:
            q = self.id_map[x] if isinstance(x, int) else x
        except KeyError:
            return
        for i, group in enumerate(self.groups):
            if q in group:
                self.set_active_group_idx(i)
                break

    def add_window(
        self,
        window: WindowType,
        group_of: Optional[WindowOrId] = None,
        next_to: Optional[WindowOrId] = None,
        before: bool = False,
        make_active: bool = True
    ) -> WindowGroup:
        self.all_windows.append(window)
        self.id_map[window.id] = window
        target_group: Optional[WindowGroup] = None

        if group_of is not None:
            target_group = self.group_for_window(group_of)
        if target_group is None and next_to is not None:
            q = self.id_map[next_to] if isinstance(next_to, int) else next_to
            pos = -1
            for i, g in enumerate(self.groups):
                if q in g:
                    pos = i
                    break
            if pos > -1:
                target_group = WindowGroup()
                self.groups.insert(pos + (0 if before else 1), target_group)
        if target_group is None:
            target_group = WindowGroup()
            if before:
                self.groups.insert(0, target_group)
            else:
                self.groups.append(target_group)

        old_active_window = self.active_window
        target_group.add_window(window)
        if make_active:
            for i, g in enumerate(self.groups):
                if g is target_group:
                    self.set_active_group_idx(i, notify=False)
                    break
        new_active_window = self.active_window
        if new_active_window is not old_active_window:
            self.notify_on_active_window_change(old_active_window, new_active_window)
        return target_group

    def remove_window(self, x: WindowOrId) -> None:
        old_active_window = self.active_window
        q = self.id_map[x] if isinstance(x, int) else x
        try:
            self.all_windows.remove(q)
        except ValueError:
            pass
        self.id_map.pop(q.id, None)
        for i, g in enumerate(tuple(self.groups)):
            g.remove_window(q)
            if not g:
                del self.groups[i]
                if self.groups:
                    if self.active_group_idx == i:
                        self.make_previous_group_active(notify=False)
                    elif self.active_group_idx >= len(self.groups):
                        self._active_group_idx -= 1
                else:
                    self._active_group_idx = -1
                break
        new_active_window = self.active_window
        if old_active_window is not new_active_window:
            self.notify_on_active_window_change(old_active_window, new_active_window)

    def active_window_in_nth_group(self, n: int, clamp: bool = False) -> Optional[WindowType]:
        if clamp:
            n = max(0, min(n, self.num_groups - 1))
        if 0 <= n < self.num_groups:
            return self.id_map.get(self.groups[n].active_window_id)

    def activate_next_window_group(self, delta: int) -> None:
        self.set_active_group_idx(wrap_increment(self.active_group_idx, self.num_groups, delta))

    def move_window_group(self, by: Optional[int] = None, to_group: Optional[int] = None) -> bool:
        if self.active_group_idx < 0 or not self.groups:
            return False
        target = -1
        if by is not None:
            target = wrap_increment(self.active_group_idx, self.num_groups, by)
        if to_group is not None:
            for i, group in enumerate(self.groups):
                if group.id == to_group:
                    target = i
                    break
        if target > -1:
            if target == self.active_group_idx:
                return False
            self.groups[self.active_group_idx], self.groups[target] = self.groups[target], self.groups[self.active_group_idx]
            self.set_active_group_idx(target)
            return True
        return False

    def compute_needs_borders_map(self, draw_active_borders: bool) -> Dict[int, bool]:
        ag = self.active_group
        return {gr.id: ((gr is ag and draw_active_borders) or gr.needs_attention) for gr in self.groups}

    @property
    def num_visble_groups(self) -> int:
        ans = 0
        for gr in self.groups:
            if gr.is_visible_in_layout:
                ans += 1
        return ans
