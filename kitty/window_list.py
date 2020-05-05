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

from .typing import TabType, WindowType

WindowOrId = Union[WindowType, int]
group_id_counter = count()


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
            g = gid_map[gid]
            w = g.active_window_id
            if w > 0 and w not in seen:
                seen.add(w)
                ans.append(w)
        return ans

    def set_active_group_idx(self, i: int) -> None:
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
                if old_active_window is not None:
                    old_active_window.focus_changed(False)
                if new_active_window is not None:
                    new_active_window.focus_changed(True)
                tab = self.tabref()
                if tab is not None:
                    tab.active_window_changed()

    def change_tab(self, tab: TabType) -> None:
        self.tabref = weakref.ref(tab)

    def iter_windows_with_visibility(self) -> Generator[Tuple[WindowType, bool], None, None]:
        for g in self.groups:
            aw = g.active_window_id
            for window in g:
                yield window, window.id == aw

    def iter_all_layoutable_windows(self) -> Generator[WindowType, None, None]:
        for g in self.groups:
            yield from g

    def make_previous_group_active(self, which: int = 1) -> None:
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
                    self.set_active_group_idx(x)
                    return
        self.set_active_group_idx(len(self.groups) - 1)

    @property
    def num_groups(self) -> int:
        return len(self.groups)

    def group_for_window(self, x: WindowOrId) -> Optional[WindowGroup]:
        q = self.id_map[x] if isinstance(x, int) else x
        for g in self.groups:
            if q in g:
                return g
        return None

    def windows_in_group_of(self, x: WindowOrId) -> Iterator[WindowType]:
        g = self.group_for_window(x)
        if g is not None:
            return iter(g)

    @property
    def active_group(self) -> Optional[WindowGroup]:
        try:
            return self.groups[self.active_group_idx]
        except IndexError:
            pass
        return None

    @property
    def active_window(self) -> Optional[WindowType]:
        try:
            return self.id_map[self.groups[self.active_group_idx].active_window_id]
        except IndexError:
            pass
        return None

    @property
    def active_group_base(self) -> Optional[WindowType]:
        try:
            return self.id_map[self.groups[self.active_group_idx].base_window_id]
        except IndexError:
            pass
        return None

    def set_active_window_group_for(self, x: WindowOrId) -> None:
        q = self.id_map[x] if isinstance(x, int) else x
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
    ) -> None:
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

        target_group.add_window(window)
        if make_active:
            for i, g in enumerate(self.groups):
                if g is target_group:
                    self.set_active_group_idx(i)
                    break

    def remove_window(self, x: WindowOrId) -> None:
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
                        self.make_previous_group_active()
                else:
                    self._active_group_idx = -1
                return

    def active_window_in_nth_group(self, n: int, clamp: bool = False) -> Optional[WindowType]:
        if clamp:
            n = max(0, min(n, self.num_groups - 1))
        if 0 <= n < self.num_groups:
            return self.id_map.get(self.groups[n].active_window_id)

    def activate_next_window_group(self, delta: int) -> None:
        self.set_active_group_idx(wrap_increment(self.active_group_idx, self.num_groups, delta))

    def move_window_group(self, by: Optional[int] = None, to_group_with_window_id: Optional[int] = None) -> bool:
        if self.active_group_idx < 0 or not self.groups:
            return False
        target = -1
        if by is not None:
            target = wrap_increment(self.active_group_idx, self.num_groups, by)
        if to_group_with_window_id is not None:
            q = self.id_map[to_group_with_window_id]
            for i, group in enumerate(self.groups):
                if q in group:
                    target = i
                    break
        if target > -1:
            if target == self.active_group_idx:
                return False
            self.groups[self.active_group_idx], self.groups[target] = self.groups[target], self.groups[self.active_group_idx]
            self.set_active_group_idx(target)
            return True
        return False
