#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, Generator, Iterator, List, Optional, Union

from .typing import WindowType


class WindowList:

    def __init__(self) -> None:
        self.all_windows: List[WindowType] = []
        self.id_map: Dict[int, WindowType] = {}
        self.overlay_stacks: Dict[int, List[int]] = {}
        self.id_to_idx_map: Dict[int, int] = {}
        self.idx_to_base_id_map: Dict[int, int] = {}
        self.max_active_idx = 0

    def __len__(self) -> int:
        return len(self.all_windows)

    def __bool__(self) -> bool:
        return bool(self.all_windows)

    def __iter__(self) -> Iterator[WindowType]:
        return iter(self.all_windows)

    def __contains__(self, window: WindowType) -> bool:
        return window.id in self.id_map

    def stack_for_window_id(self, q: int) -> List[int]:
        ' The stack of overlaid windows this window belongs to '
        w = self.id_map[q]
        if w.overlay_for is not None and w.overlay_for in self.id_map:
            q = self.id_map[w.overlay_for].id
        return self.overlay_stacks[q]

    def iter_top_level_windows(self) -> Generator[WindowType, None, None]:
        ' Iterator over all top level windows '
        for stack in self.overlay_stacks.values():
            yield self.id_map[stack[-1]]

    def iter_stack_for_window(self, x: Union[WindowType, int], reverse: bool = False) -> Generator[WindowType, None, None]:
        ' Iterator over all windows in the stack for this window '
        q = x if isinstance(x, int) else x.id
        stack = self.stack_for_window_id(q)
        y = reversed(stack) if reverse else iter(stack)
        for wid in y:
            yield self.id_map[wid]

    def overlay_for(self, x: Union[WindowType, int]) -> int:
        ' id of the top-most window overlaying this window, same as this window id if not overlaid '
        q = x if isinstance(x, int) else x.id
        return self.stack_for_window_id(q)[-1]

    def overlaid_window_for(self, x: Union[WindowType, int]) -> int:
        ' id of the bottom-most window in this windows overlay stack '
        q = x if isinstance(x, int) else x.id
        return self.stack_for_window_id(q)[0]

    def is_overlaid(self, x: Union[WindowType, int]) -> bool:
        ' Return False if there is a window overlaying this one '
        q = x if isinstance(x, int) else x.id
        return self.overlay_for(q) != q

    def idx_for_window(self, x: Union[WindowType, int]) -> Optional[int]:
        ' Return the index of the window in the list of top-level windows '
        q = x if isinstance(x, int) else x.id
        return self.id_to_idx_map[q]

    def active_window_for_idx(self, idx: int, clamp: bool = False) -> Optional[WindowType]:
        ' Return the active window at the specified index '
        if clamp:
            idx = max(0, min(idx, self.max_active_idx))
        q = self.idx_to_base_id_map.get(idx)
        if q is not None:
            return self.id_map[self.overlay_stacks[q][-1]]
        return None

    def next_id_in_stack_on_remove(self, x: Union[WindowType, int]) -> Optional[int]:
        ' The id of the window that should become active when this window is removed, or None if there is no other window in the stack '
        q = x if isinstance(x, int) else x.id
        stack = self.stack_for_window_id(q)
        idx = stack.index(q)
        if idx < len(stack) - 1:
            return stack[idx + 1]
        if idx > 0:
            return stack[idx - 1]
        return None
