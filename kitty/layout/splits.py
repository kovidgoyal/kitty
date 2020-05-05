#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import (
    Collection, Dict, Generator, Optional, Sequence, Tuple, Union
)

from kitty.constants import Edges, WindowGeometry
from kitty.typing import EdgeLiteral, WindowType
from kitty.window_list import WindowList

from .base import (
    Borders, InternalNeighborsMap, Layout, LayoutOpts, all_borders,
    blank_rects_for_window, lgd, no_borders, window_geometry_from_layouts
)


class Pair:

    def __init__(self, horizontal: bool = True):
        self.horizontal = horizontal
        self.one: Optional[Union[Pair, int]] = None
        self.two: Optional[Union[Pair, int]] = None
        self.bias = 0.5
        self.between_border: Optional[Edges] = None

    def __repr__(self) -> str:
        return 'Pair(horizontal={}, bias={:.2f}, one={}, two={}, between_border={})'.format(
                self.horizontal, self.bias, self.one, self.two, self.between_border)

    def all_window_ids(self) -> Generator[int, None, None]:
        if self.one is not None:
            if isinstance(self.one, Pair):
                yield from self.one.all_window_ids()
            else:
                yield self.one
        if self.two is not None:
            if isinstance(self.two, Pair):
                yield from self.two.all_window_ids()
            else:
                yield self.two

    def self_and_descendants(self) -> Generator['Pair', None, None]:
        yield self
        if isinstance(self.one, Pair):
            yield from self.one.self_and_descendants()
        if isinstance(self.two, Pair):
            yield from self.two.self_and_descendants()

    def pair_for_window(self, window_id: int) -> Optional['Pair']:
        if self.one == window_id or self.two == window_id:
            return self
        ans = None
        if isinstance(self.one, Pair):
            ans = self.one.pair_for_window(window_id)
        if ans is None and isinstance(self.two, Pair):
            ans = self.two.pair_for_window(window_id)
        return ans

    def parent(self, root: 'Pair') -> Optional['Pair']:
        for q in root.self_and_descendants():
            if q.one is self or q.two is self:
                return q

    def remove_windows(self, window_ids: Collection[int]) -> None:
        if isinstance(self.one, int) and self.one in window_ids:
            self.one = None
        if isinstance(self.two, int) and self.two in window_ids:
            self.two = None
        if self.one is None and self.two is not None:
            self.one, self.two = self.two, None

    @property
    def is_redundant(self) -> bool:
        return self.one is None or self.two is None

    def collapse_redundant_pairs(self) -> None:
        while isinstance(self.one, Pair) and self.one.is_redundant:
            self.one = self.one.one or self.one.two
        while isinstance(self.two, Pair) and self.two.is_redundant:
            self.two = self.two.one or self.two.two
        if isinstance(self.one, Pair):
            self.one.collapse_redundant_pairs()
        if isinstance(self.two, Pair):
            self.two.collapse_redundant_pairs()

    def balanced_add(self, window_id: int) -> 'Pair':
        if self.one is None or self.two is None:
            if self.one is None:
                if self.two is None:
                    self.one = window_id
                    return self
                self.one, self.two = self.two, self.one
            self.two = window_id
            return self
        if isinstance(self.one, Pair) and isinstance(self.two, Pair):
            one_count = sum(1 for _ in self.one.all_window_ids())
            two_count = sum(1 for _ in self.two.all_window_ids())
            q = self.one if one_count < two_count else self.two
            return q.balanced_add(window_id)
        if not isinstance(self.one, Pair) and not isinstance(self.two, Pair):
            pair = Pair(horizontal=self.horizontal)
            pair.balanced_add(self.one)
            pair.balanced_add(self.two)
            self.one, self.two = pair, window_id
            return self
        if isinstance(self.one, Pair):
            window_to_be_split = self.two
            self.two = pair = Pair(horizontal=self.horizontal)
        else:
            window_to_be_split = self.one
            self.one = pair = Pair(horizontal=self.horizontal)
        assert isinstance(window_to_be_split, int)
        pair.balanced_add(window_to_be_split)
        pair.balanced_add(window_id)
        return pair

    def split_and_add(self, existing_window_id: int, new_window_id: int, horizontal: bool, after: bool) -> 'Pair':
        q = (existing_window_id, new_window_id) if after else (new_window_id, existing_window_id)
        if self.is_redundant:
            pair = self
            pair.horizontal = horizontal
            self.one, self.two = q
        else:
            pair = Pair(horizontal=horizontal)
            if self.one == existing_window_id:
                self.one = pair
            else:
                self.two = pair
            tuple(map(pair.balanced_add, q))
        return pair

    def apply_window_geometry(
        self, window_id: int,
        window_geometry: WindowGeometry,
        id_window_map: Dict[int, WindowType],
        id_idx_map: Dict[int, int],
        layout_object: Layout
    ) -> None:
        w = id_window_map[window_id]
        w.set_geometry(id_idx_map[window_id], window_geometry)
        if w.overlay_window_id is not None:
            q = id_window_map.get(w.overlay_window_id)
            if q is not None:
                q.set_geometry(id_idx_map[q.id], window_geometry)
        layout_object.blank_rects.extend(blank_rects_for_window(window_geometry))

    def effective_border(self, id_window_map: Dict[int, WindowType]) -> int:
        for wid in self.all_window_ids():
            return id_window_map[wid].effective_border()
        return 0

    def layout_pair(
        self,
        left: int, top: int, width: int, height: int,
        id_window_map: Dict[int, WindowType],
        id_idx_map: Dict[int, int],
        layout_object: Layout
    ) -> None:
        self.between_border = None
        if self.one is None or self.two is None:
            q = self.one or self.two
            if isinstance(q, Pair):
                return q.layout_pair(left, top, width, height, id_window_map, id_idx_map, layout_object)
            if q is None:
                return
            w = id_window_map[q]
            xl = next(layout_object.xlayout([w], start=left, size=width))
            yl = next(layout_object.ylayout([w], start=top, size=height))
            geom = window_geometry_from_layouts(xl, yl)
            self.apply_window_geometry(q, geom, id_window_map, id_idx_map, layout_object)
            return
        bw = self.effective_border(id_window_map) if lgd.draw_minimal_borders else 0
        b1 = bw // 2
        b2 = bw - b1
        if self.horizontal:
            w1 = max(2*lgd.cell_width + 1, int(self.bias * width) - b1)
            w2 = max(2*lgd.cell_width + 1, width - w1 - b1 - b2)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, w1, height, id_window_map, id_idx_map, layout_object)
            else:
                w = id_window_map[self.one]
                yl = next(layout_object.ylayout([w], start=top, size=height))
                xl = next(layout_object.xlayout([w], start=left, size=w1))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.one, geom, id_window_map, id_idx_map, layout_object)
            if b1 + b2:
                self.between_border = Edges(left + w1, top, left + w1 + b1 + b2, top + height)
            left += b1 + b2
            if isinstance(self.two, Pair):
                self.two.layout_pair(left + w1, top, w2, height, id_window_map, id_idx_map, layout_object)
            else:
                w = id_window_map[self.two]
                xl = next(layout_object.xlayout([w], start=left + w1, size=w2))
                yl = next(layout_object.ylayout([w], start=top, size=height))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.two, geom, id_window_map, id_idx_map, layout_object)
        else:
            h1 = max(2*lgd.cell_height + 1, int(self.bias * height) - b1)
            h2 = max(2*lgd.cell_height + 1, height - h1 - b1 - b2)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, width, h1, id_window_map, id_idx_map, layout_object)
            else:
                w = id_window_map[self.one]
                xl = next(layout_object.xlayout([w], start=left, size=width))
                yl = next(layout_object.ylayout([w], start=top, size=h1))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.one, geom, id_window_map, id_idx_map, layout_object)
            if b1 + b2:
                self.between_border = Edges(left, top + h1, left + width, top + h1 + b1 + b2)
            top += b1 + b2
            if isinstance(self.two, Pair):
                self.two.layout_pair(left, top + h1, width, h2, id_window_map, id_idx_map, layout_object)
            else:
                w = id_window_map[self.two]
                xl = next(layout_object.xlayout([w], start=left, size=width))
                yl = next(layout_object.ylayout([w], start=top + h1, size=h2))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.two, geom, id_window_map, id_idx_map, layout_object)

    def modify_size_of_child(self, which: int, increment: float, is_horizontal: bool, layout_object: 'Splits') -> bool:
        if is_horizontal == self.horizontal and not self.is_redundant:
            if which == 2:
                increment *= -1
            new_bias = max(0.1, min(self.bias + increment, 0.9))
            if new_bias != self.bias:
                self.bias = new_bias
                return True
            return False
        parent = self.parent(layout_object.pairs_root)
        if parent is not None:
            which = 1 if parent.one is self else 2
            return parent.modify_size_of_child(which, increment, is_horizontal, layout_object)
        return False

    def neighbors_for_window(self, window_id: int, ans: InternalNeighborsMap, layout_object: 'Splits') -> None:

        def quadrant(is_horizontal: bool, is_first: bool) -> Tuple[EdgeLiteral, EdgeLiteral]:
            if is_horizontal:
                if is_first:
                    return 'left', 'right'
                return 'right', 'left'
            if is_first:
                return 'top', 'bottom'
            return 'bottom', 'top'

        def extend(other: Union[int, 'Pair', None], edge: EdgeLiteral, which: EdgeLiteral) -> None:
            if not ans[which] and other:
                if isinstance(other, Pair):
                    ans[which].extend(other.edge_windows(edge))
                else:
                    ans[which].append(other)

        other = self.two if self.one == window_id else self.one
        extend(other, *quadrant(self.horizontal, self.one == window_id))

        child = self
        while True:
            parent = child.parent(layout_object.pairs_root)
            if parent is None:
                break
            other = parent.two if child is parent.one else parent.one
            extend(other, *quadrant(parent.horizontal, child is parent.one))
            child = parent

    def edge_windows(self, edge: str) -> Generator[int, None, None]:
        if self.is_redundant:
            q = self.one or self.two
            if q:
                if isinstance(q, Pair):
                    yield from q.edge_windows(edge)
                else:
                    yield q
        edges = ('left', 'right') if self.horizontal else ('top', 'bottom')
        if edge in edges:
            q = self.one if edge in ('left', 'top') else self.two
            if q:
                if isinstance(q, Pair):
                    yield from q.edge_windows(edge)
                else:
                    yield q
        else:
            for q in (self.one, self.two):
                if q:
                    if isinstance(q, Pair):
                        yield from q.edge_windows(edge)
                    else:
                        yield q


class SplitsLayoutOpts(LayoutOpts):

    default_axis_is_horizontal: bool = True

    def __init__(self, data: Dict[str, str]):
        self.default_axis_is_horizontal = data.get('split_axis', 'horizontal') == 'horizontal'


class Splits(Layout):
    name = 'splits'
    needs_all_windows = True
    layout_opts = SplitsLayoutOpts({})

    @property
    def default_axis_is_horizontal(self) -> bool:
        return self.layout_opts.default_axis_is_horizontal

    @property
    def pairs_root(self) -> Pair:
        root: Optional[Pair] = getattr(self, '_pairs_root', None)
        if root is None:
            self._pairs_root = root = Pair(horizontal=self.default_axis_is_horizontal)
        return root

    @pairs_root.setter
    def pairs_root(self, root: Pair) -> None:
        self._pairs_root = root

    def do_layout_all_windows(self, windows: WindowList, active_window_idx: int, all_windows: WindowList) -> None:
        window_count = len(windows)
        root = self.pairs_root
        all_present_window_ids = frozenset(w.overlay_for or w.id for w in windows)
        already_placed_window_ids = frozenset(root.all_window_ids())
        windows_to_remove = already_placed_window_ids - all_present_window_ids

        if windows_to_remove:
            for pair in root.self_and_descendants():
                pair.remove_windows(windows_to_remove)
            root.collapse_redundant_pairs()
            if root.one is None or root.two is None:
                q = root.one or root.two
                if isinstance(q, Pair):
                    root = self.pairs_root = q
        id_window_map = {w.id: w for w in all_windows}
        id_idx_map = {w.id: i for i, w in enumerate(all_windows)}
        windows_to_add = all_present_window_ids - already_placed_window_ids
        if windows_to_add:
            for wid in sorted(windows_to_add, key=id_idx_map.__getitem__):
                root.balanced_add(wid)

        if window_count == 1:
            self.layout_single_window(windows[0])
        else:
            root.layout_pair(lgd.central.left, lgd.central.top, lgd.central.width, lgd.central.height, id_window_map, id_idx_map, self)

    def do_add_window(
        self,
        all_windows: WindowList,
        window: WindowType,
        current_active_window_idx: Optional[int],
        location: Optional[str]
    ) -> int:
        horizontal = self.default_axis_is_horizontal
        after = True
        if location is not None:
            if location == 'vsplit':
                horizontal = True
            elif location == 'hsplit':
                horizontal = False
            if location in ('before', 'first'):
                after = False
        active_window_idx = None
        if current_active_window_idx is not None and 0 <= current_active_window_idx < len(all_windows):
            cw = all_windows[current_active_window_idx]
            window_id = cw.overlay_for or cw.id
            pair = self.pairs_root.pair_for_window(window_id)
            if pair is not None:
                pair.split_and_add(window_id, window.id, horizontal, after)
                active_window_idx = current_active_window_idx
                if after:
                    active_window_idx += 1
                for i in range(len(all_windows), active_window_idx, -1):
                    self.swap_windows_in_os_window(i, i - 1)
                all_windows.insert(active_window_idx, window)
        if active_window_idx is None:
            active_window_idx = len(all_windows)
            all_windows.append(window)
        return active_window_idx

    def modify_size_of_window(
        self,
        all_windows: WindowList,
        window_id: int,
        increment: float,
        is_horizontal: bool = True
    ) -> bool:
        idx = idx_for_id(window_id, all_windows)
        if idx is None:
            return False
        w = all_windows[idx]
        window_id = w.overlay_for or w.id
        pair = self.pairs_root.pair_for_window(window_id)
        if pair is None:
            return False
        which = 1 if pair.one == window_id else 2
        return pair.modify_size_of_child(which, increment, is_horizontal, self)

    def remove_all_biases(self) -> bool:
        for pair in self.pairs_root.self_and_descendants():
            pair.bias = 0.5
        return True

    def window_independent_borders(self, windows: WindowList, active_window: Optional[WindowType] = None) -> Generator[Edges, None, None]:
        if not lgd.draw_minimal_borders:
            return
        for pair in self.pairs_root.self_and_descendants():
            if pair.between_border is not None:
                yield pair.between_border

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> InternalNeighborsMap:
        window_id = window.overlay_for or window.id
        pair = self.pairs_root.pair_for_window(window_id)
        ans: InternalNeighborsMap = {'left': [], 'right': [], 'top': [], 'bottom': []}
        if pair is not None:
            pair.neighbors_for_window(window_id, ans, self)
        return ans

    def swap_windows_in_layout(self, all_windows: WindowList, a: int, b: int) -> None:
        w1_, w2_ = all_windows[a], all_windows[b]
        super().swap_windows_in_layout(all_windows, a, b)
        w1 = w1_.overlay_for or w1_.id
        w2 = w2_.overlay_for or w2_.id
        p1 = self.pairs_root.pair_for_window(w1)
        p2 = self.pairs_root.pair_for_window(w2)
        if p1 and p2:
            if p1 is p2:
                p1.one, p1.two = p1.two, p1.one
            else:
                if p1.one == w1:
                    p1.one = w2
                else:
                    p1.two = w2
                if p2.one == w2:
                    p2.one = w1
                else:
                    p2.two = w1

    def minimal_borders(self, windows: WindowList, active_window: Optional[WindowType], needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        for w in windows:
            if (w is active_window and lgd.draw_active_borders) or w.needs_attention:
                yield all_borders
            else:
                yield no_borders

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList, active_window_idx: int) -> Optional[bool]:
        if action_name == 'rotate':
            args = args or ('90',)
            try:
                amt = int(args[0])
            except Exception:
                amt = 90
            if amt not in (90, 180, 270):
                amt = 90
            rotate = amt in (90, 270)
            swap = amt in (180, 270)
            w = all_windows[active_window_idx]
            wid = w.overlay_for or w.id
            pair = self.pairs_root.pair_for_window(wid)
            if pair is not None and not pair.is_redundant:
                if rotate:
                    pair.horizontal = not pair.horizontal
                if swap:
                    pair.one, pair.two = pair.two, pair.one
                return True
