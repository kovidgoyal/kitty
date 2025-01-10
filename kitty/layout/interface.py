#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from .base import Layout
from .grid import Grid
from .splits import Splits
from .stack import Stack
from .tall import Fat, Tall
from .vertical import Horizontal, Vertical

all_layouts: dict[str, type[Layout]] = {
    Stack.name: Stack,
    Tall.name: Tall,
    Fat.name: Fat,
    Vertical.name: Vertical,
    Horizontal.name: Horizontal,
    Grid.name: Grid,
    Splits.name: Splits,
}

KeyType = tuple[str, int, int, str]


class CreateLayoutObjectFor:
    cache: dict[KeyType, Layout] = {}

    def __call__(
        self,
        name: str,
        os_window_id: int,
        tab_id: int,
        layout_opts: str = ''
    ) -> Layout:
        key = name, os_window_id, tab_id, layout_opts
        ans = create_layout_object_for.cache.get(key)
        if ans is None:
            name, layout_opts = name.partition(':')[::2]
            ans = create_layout_object_for.cache[key] = all_layouts[name](
                os_window_id, tab_id, layout_opts)
        return ans


create_layout_object_for = CreateLayoutObjectFor()


def evict_cached_layouts(tab_id: int) -> None:
    remove = [key for key in create_layout_object_for.cache if key[2] == tab_id]
    for key in remove:
        del create_layout_object_for.cache[key]
