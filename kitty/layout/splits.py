#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Collection, Generator, Sequence
from typing import Any, NamedTuple, Optional, Union

from kitty.borders import BorderColor
from kitty.types import Edges, WindowGeometry
from kitty.typing_compat import EdgeLiteral, WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import BorderLine, Layout, LayoutOpts, NeighborsMap, blank_rects_for_window, lgd, window_geometry_from_layouts


class Extent(NamedTuple):
    start: int = 0
    end: int = 0


class Pair:

    def __init__(self, horizontal: bool = True):
        self.horizontal = horizontal
        self.one: Pair | int | None = None
        self.two: Pair | int | None = None
        self.bias = 0.5
        self.top = self.left = self.width = self.height = 0
        self.between_borders: list[Edges] = []
        self.first_extent = self.second_extent = Extent()

    def __repr__(self) -> str:
        return 'Pair(horizontal={}, bias={:.2f}, one={}, two={}, between_borders={})'.format(
                self.horizontal, self.bias, self.one, self.two, self.between_borders)

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

    def swap_windows(self, a: int, b: int) -> None:
        pa = self.pair_for_window(a)
        pb = self.pair_for_window(b)
        if pa is None or pb is None:
            return
        if pa.one == a:
            if pb.one == b:
                pa.one, pb.one = pb.one, pa.one
            else:
                pa.one, pb.two = pb.two, pa.one
        else:
            if pb.one == b:
                pa.two, pb.one = pb.one, pa.two
            else:
                pa.two, pb.two = pb.two, pa.two

    def parent(self, root: 'Pair') -> Optional['Pair']:
        for q in root.self_and_descendants():
            if q.one is self or q.two is self:
                return q
        return None

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
            final_pair = pair

        else:
            pair = Pair(horizontal=horizontal)
            if self.one == existing_window_id:
                self.one = pair
            else:
                self.two = pair
            for wid in q:
                qp = pair.balanced_add(wid)
                if wid == new_window_id:
                    final_pair = qp
        return final_pair

    def apply_window_geometry(
        self, window_id: int,
        window_geometry: WindowGeometry,
        id_window_map: dict[int, WindowGroup],
        layout_object: Layout
    ) -> None:
        wg = id_window_map[window_id]
        wg.set_geometry(window_geometry)
        layout_object.blank_rects.extend(blank_rects_for_window(window_geometry))

    def effective_border(self, id_window_map: dict[int, WindowGroup]) -> int:
        for wid in self.all_window_ids():
            return id_window_map[wid].effective_border()
        return 0

    def minimum_width(self, id_window_map: dict[int, WindowGroup]) -> int:
        if self.one is None or self.two is None or not self.horizontal:
            return lgd.cell_width
        bw = self.effective_border(id_window_map) if lgd.draw_minimal_borders else 0
        ans = 2 * bw
        if isinstance(self.one, Pair):
            ans += self.one.minimum_width(id_window_map)
        else:
            ans += lgd.cell_width
        if isinstance(self.two, Pair):
            ans += self.two.minimum_width(id_window_map)
        else:
            ans += lgd.cell_width
        return ans

    def minimum_height(self, id_window_map: dict[int, WindowGroup]) -> int:
        if self.one is None or self.two is None or self.horizontal:
            return lgd.cell_height
        bw = self.effective_border(id_window_map) if lgd.draw_minimal_borders else 0
        ans = 2 * bw
        if isinstance(self.one, Pair):
            ans += self.one.minimum_height(id_window_map)
        else:
            ans += lgd.cell_height
        if isinstance(self.two, Pair):
            ans += self.two.minimum_height(id_window_map)
        else:
            ans += lgd.cell_height
        return ans

    def layout_pair(
        self,
        left: int, top: int, width: int, height: int,
        id_window_map: dict[int, WindowGroup],
        layout_object: Layout
    ) -> None:
        self.between_borders = []
        self.left, self.top, self.width, self.height = left, top, width, height
        bw = self.effective_border(id_window_map) if lgd.draw_minimal_borders else 0
        border_mult = 0 if lgd.draw_minimal_borders else 1
        bw2 = bw * 2
        self.first_extent = self.second_extent = Extent()
        if self.one is None or self.two is None:
            q = self.one or self.two
            if isinstance(q, Pair):
                return q.layout_pair(left, top, width, height, id_window_map, layout_object)
            if q is None:
                return
            wg = id_window_map[q]
            xl = next(layout_object.xlayout(iter((wg,)), start=left, size=width, border_mult=border_mult))
            yl = next(layout_object.ylayout(iter((wg,)), start=top, size=height, border_mult=border_mult))
            geom = window_geometry_from_layouts(xl, yl)
            self.first_extent = Extent(left, left + width)
            self.apply_window_geometry(q, geom, id_window_map, layout_object)
            return
        if self.horizontal:
            min_w1 = self.one.minimum_width(id_window_map) if isinstance(self.one, Pair) else lgd.cell_width
            min_w2 = self.two.minimum_width(id_window_map) if isinstance(self.two, Pair) else lgd.cell_width
            w1 = max(min_w1, int(self.bias * width) - bw)
            w2 = width - w1 - bw2
            if w2 < min_w2 and w1 >= min_w1 + bw2:
                w2 = min_w2
                w1 = width - w2
            self.first_extent = Extent(max(0, left - bw), left + w1 + bw)
            self.second_extent = Extent(left + w1 + bw, left + width + bw)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, w1, height, id_window_map, layout_object)
            else:
                wg = id_window_map[self.one]
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=height, border_mult=border_mult))
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=w1, border_mult=border_mult))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.one, geom, id_window_map, layout_object)
            self.between_borders = [
                Edges(left + w1, top, left + w1 + bw, top + height),
                Edges(left + w1 + bw, top, left + w1 + bw2, top + height),
            ]
            left += bw2
            if isinstance(self.two, Pair):
                self.two.layout_pair(left + w1, top, w2, height, id_window_map, layout_object)
            else:
                wg = id_window_map[self.two]
                xl = next(layout_object.xlayout(iter((wg,)), start=left + w1, size=w2, border_mult=border_mult))
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=height, border_mult=border_mult))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.two, geom, id_window_map, layout_object)
        else:
            min_h1 = self.one.minimum_height(id_window_map) if isinstance(self.one, Pair) else lgd.cell_height
            min_h2 = self.two.minimum_height(id_window_map) if isinstance(self.two, Pair) else lgd.cell_height
            h1 = max(min_h1, int(self.bias * height) - bw)
            h2 = height - h1 - bw2
            if h2 < min_h2 and h1 >= min_h1 + bw2:
                h2 = min_h2
                h1 = height - h2
            self.first_extent = Extent(max(0, top - bw), top + h1 + bw)
            self.second_extent = Extent(top + h1 + bw, top + height + bw)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, width, h1, id_window_map, layout_object)
            else:
                wg = id_window_map[self.one]
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=width, border_mult=border_mult))
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=h1, border_mult=border_mult))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.one, geom, id_window_map, layout_object)
            self.between_borders = [
                Edges(left, top + h1, left + width, top + h1 + bw),
                Edges(left, top + h1 + bw, left + width, top + h1 + bw2),
            ]
            top += bw2
            if isinstance(self.two, Pair):
                self.two.layout_pair(left, top + h1, width, h2, id_window_map, layout_object)
            else:
                wg = id_window_map[self.two]
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=width, border_mult=border_mult))
                yl = next(layout_object.ylayout(iter((wg,)), start=top + h1, size=h2, border_mult=border_mult))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.two, geom, id_window_map, layout_object)

    def set_bias(self, window_id: int, bias: int) -> None:
        b = max(0, min(bias, 100)) / 100
        self.bias = b if window_id == self.one else (1. - b)

    def modify_size_of_child(self, which: int, increment: float, is_horizontal: bool, layout_object: 'Splits') -> bool:
        if is_horizontal == self.horizontal and not self.is_redundant:
            if which == 2:
                increment *= -1
            new_bias = max(0, min(self.bias + increment, 1))
            if new_bias != self.bias:
                self.bias = new_bias
                return True
            return False
        parent = self.parent(layout_object.pairs_root)
        if parent is not None:
            which = 1 if parent.one is self else 2
            return parent.modify_size_of_child(which, increment, is_horizontal, layout_object)
        return False

    def borders_for_window(self, layout_object: 'Splits', window_id: int) -> Generator[Edges, None, None]:
        is_first = self.one == window_id
        if self.between_borders:
            yield self.between_borders[0 if is_first else 1]
        q = self
        found_same_direction = found_transverse1 = found_transverse2 = False
        while not (found_same_direction and found_transverse1 and found_transverse2):
            parent = q.parent(layout_object.pairs_root)
            if parent is None:
                break
            q = parent
            if not q.between_borders:
                continue
            if q.horizontal == self.horizontal:
                if not found_same_direction:
                    if self.horizontal:
                        is_before = q.between_borders[0].left <= self.left
                    else:
                        is_before = q.between_borders[0].top <= self.top
                    if is_before == is_first:
                        found_same_direction = True
                        edges = q.between_borders[1 if is_before else 0]
                        if self.horizontal:
                            yield edges._replace(top=self.top, bottom=self.top + self.height)
                        else:
                            yield edges._replace(left=self.left, right=self.left + self.width)
            else:
                if self.horizontal:
                    is_before = q.between_borders[0].top <= self.top
                else:
                    is_before = q.between_borders[0].left <= self.left
                extent = self.first_extent if is_first else self.second_extent
                if is_before:
                    if not found_transverse1:
                        found_transverse1 = True
                        edges = q.between_borders[1]
                        if self.horizontal:
                            yield edges._replace(left=extent.start, right=extent.end)
                        else:
                            yield edges._replace(top=extent.start, bottom=extent.end)
                else:
                    if not found_transverse2:
                        found_transverse2 = True
                        edges = q.between_borders[0]
                        if self.horizontal:
                            yield edges._replace(left=extent.start, right=extent.end)
                        else:
                            yield edges._replace(top=extent.start, bottom=extent.end)

    def neighbors_for_window(self, window_id: int, ans: NeighborsMap, layout_object: 'Splits', all_windows: WindowList) -> None:

        def quadrant(is_horizontal: bool, is_first: bool) -> tuple[EdgeLiteral, EdgeLiteral]:
            if is_horizontal:
                if is_first:
                    return 'left', 'right'
                return 'right', 'left'
            if is_first:
                return 'top', 'bottom'
            return 'bottom', 'top'

        geometries = {group.id: group.geometry for group in all_windows.groups if group.geometry}

        def extend(other: Union[int, 'Pair', None], edge: EdgeLiteral, which: EdgeLiteral) -> None:
            if not ans[which] and other:
                if isinstance(other, Pair):
                    neighbors = (
                        w for w in other.edge_windows(edge)
                        if is_neighbouring_geometry(geometries[w], geometries[window_id], which))
                    ans[which].extend(neighbors)
                else:
                    ans[which].append(other)

        def is_neighbouring_geometry(a: WindowGeometry, b: WindowGeometry, direction: str) -> bool:
            def edges(g: WindowGeometry) -> tuple[int, int]:
                return (g.top, g.bottom) if direction in ['left', 'right'] else (g.left, g.right)

            a1, a2 = edges(a)
            b1, b2 = edges(b)

            return a1 < b2 and a2 > b1

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

    default_axis_is_horizontal: bool | None = True

    def __init__(self, data: dict[str, str]):
        q = data.get('split_axis', 'horizontal')
        if q == 'auto':
            self.default_axis_is_horizontal = None
        else:
            self.default_axis_is_horizontal = q == 'horizontal'

    def serialized(self) -> dict[str, Any]:
        return {'default_axis_is_horizontal': self.default_axis_is_horizontal}


class Splits(Layout):
    name = 'splits'
    needs_all_windows = True
    layout_opts = SplitsLayoutOpts({})
    no_minimal_window_borders = True

    @property
    def default_axis_is_horizontal(self) -> bool | None:
        return self.layout_opts.default_axis_is_horizontal

    @property
    def pairs_root(self) -> Pair:
        root: Pair | None = getattr(self, '_pairs_root', None)
        if root is None:
            horizontal = self.default_axis_is_horizontal
            if horizontal is None:
                horizontal = True
            self._pairs_root = root = Pair(horizontal=horizontal)
        return root

    @pairs_root.setter
    def pairs_root(self, root: Pair) -> None:
        self._pairs_root = root

    def remove_windows(self, *windows_to_remove: int) -> None:
        root = self.pairs_root
        for pair in root.self_and_descendants():
            pair.remove_windows(windows_to_remove)
        root.collapse_redundant_pairs()
        if root.one is None or root.two is None:
            q = root.one or root.two
            if isinstance(q, Pair):
                self.pairs_root = q

    def do_layout(self, all_windows: WindowList) -> None:
        groups = tuple(all_windows.iter_all_layoutable_groups())
        window_count = len(groups)
        root = self.pairs_root
        all_present_window_ids = frozenset(w.id for w in groups)
        already_placed_window_ids = frozenset(root.all_window_ids())
        windows_to_remove = already_placed_window_ids - all_present_window_ids
        if windows_to_remove:
            self.remove_windows(*windows_to_remove)
        id_window_map = {w.id: w for w in groups}
        id_idx_map = {w.id: i for i, w in enumerate(groups)}
        windows_to_add = all_present_window_ids - already_placed_window_ids
        if windows_to_add:
            for wid in sorted(windows_to_add, key=id_idx_map.__getitem__):
                root.balanced_add(wid)

        if window_count == 1:
            self.layout_single_window_group(groups[0])
        else:
            root.layout_pair(lgd.central.left, lgd.central.top, lgd.central.width, lgd.central.height, id_window_map, self)

    def add_non_overlay_window(
        self,
        all_windows: WindowList,
        window: WindowType,
        location: str | None,
        bias: float | None = None,
        next_to: WindowType | None = None,
    ) -> None:
        horizontal = self.default_axis_is_horizontal
        after = True
        if location == 'vsplit':
            horizontal = True
        elif location == 'hsplit':
            horizontal = False
        elif location in ('before', 'first'):
            after = False
        aw = next_to or all_windows.active_window
        if bias:
            bias = max(0, min(abs(bias), 100)) / 100
        if aw is not None and (ag := all_windows.group_for_window(aw)) is not None:
            group_id = ag.id
            pair = self.pairs_root.pair_for_window(group_id)
            if pair is not None:
                if location == 'split' or horizontal is None:
                    wwidth = aw.geometry.right - aw.geometry.left
                    wheight = aw.geometry.bottom - aw.geometry.top
                    horizontal = wwidth >= wheight
                target_group = all_windows.add_window(window, next_to=aw, before=not after)
                parent_pair = pair.split_and_add(group_id, target_group.id, horizontal, after)
                if bias is not None:
                    parent_pair.bias = bias if parent_pair.one == target_group.id else (1 - bias)
                return
        all_windows.add_window(window)
        p = self.pairs_root.balanced_add(window.id)
        if bias is not None:
            p.bias = bias

    def modify_size_of_window(
        self,
        all_windows: WindowList,
        window_id: int,
        increment: float,
        is_horizontal: bool = True
    ) -> bool:
        grp = all_windows.group_for_window(window_id)
        if grp is None:
            return False
        pair = self.pairs_root.pair_for_window(grp.id)
        if pair is None:
            return False
        which = 1 if pair.one == grp.id else 2
        return pair.modify_size_of_child(which, increment, is_horizontal, self)

    def remove_all_biases(self) -> bool:
        for pair in self.pairs_root.self_and_descendants():
            pair.bias = 0.5
        return True

    def minimal_borders(self, all_windows: WindowList) -> Generator[BorderLine, None, None]:
        groups = tuple(all_windows.iter_all_layoutable_groups())
        window_count = len(groups)
        if not lgd.draw_minimal_borders or window_count < 2:
            return
        for pair in self.pairs_root.self_and_descendants():
            for edges in pair.between_borders:
                yield BorderLine(edges)
        needs_borders_map = all_windows.compute_needs_borders_map(lgd.draw_active_borders)
        ag = all_windows.active_group
        active_group_id = -1 if ag is None else ag.id
        for grp_id, needs_borders in needs_borders_map.items():
            if needs_borders:
                qpair = self.pairs_root.pair_for_window(grp_id)
                if qpair is not None:
                    color = BorderColor.active if grp_id is active_group_id else BorderColor.bell
                    for edges in qpair.borders_for_window(self, grp_id):
                        yield BorderLine(edges, color)

    def neighbors_for_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        wg = all_windows.group_for_window(window)
        assert wg is not None
        pair = self.pairs_root.pair_for_window(wg.id)
        ans: NeighborsMap = {'left': [], 'right': [], 'top': [], 'bottom': []}
        if pair is not None:
            pair.neighbors_for_window(wg.id, ans, self, all_windows)
        return ans

    def move_window(self, all_windows: WindowList, delta: int = 1) -> bool:
        before = all_windows.active_group
        if before is None:
            return False
        before_idx = all_windows.active_group_idx
        moved = super().move_window(all_windows, delta)
        after = all_windows.groups[before_idx]
        if moved and before.id != after.id:
            self.pairs_root.swap_windows(before.id, after.id)
        return moved

    def move_window_to_group(self, all_windows: WindowList, group: int) -> bool:
        before = all_windows.active_group
        if before is None:
            return False
        before_idx = all_windows.active_group_idx
        moved = super().move_window_to_group(all_windows, group)
        after = all_windows.groups[before_idx]
        if moved and before.id != after.id:
            self.pairs_root.swap_windows(before.id, after.id)
        return moved

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> bool | None:
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
            wg = all_windows.active_group
            if wg is not None:
                pair = self.pairs_root.pair_for_window(wg.id)
                if pair is not None and not pair.is_redundant:
                    if rotate:
                        pair.horizontal = not pair.horizontal
                    if swap:
                        pair.one, pair.two = pair.two, pair.one
                    return True
        elif action_name == 'move_to_screen_edge':
            count = 0
            for wid in self.pairs_root.all_window_ids():
                count += 1
                if count > 2:
                    break
            if count > 1:
                args = args or ('left',)
                which = args[0]
                horizontal = which in ('left', 'right')
                wg = all_windows.active_group
                if wg is not None:
                    if count == 2:  # special case, a single split
                        pair = self.pairs_root.pair_for_window(wg.id)
                        if pair is not None:
                            pair.horizontal = horizontal
                            if which in ('left', 'top'):
                                if pair.one != wg.id:
                                    pair.one, pair.two = pair.two, pair.one
                                    pair.bias = 1. - pair.bias
                            else:
                                if pair.one == wg.id:
                                    pair.one, pair.two = pair.two, pair.one
                                    pair.bias = 1. - pair.bias
                            return True
                    else:
                        self.remove_windows(wg.id)
                        new_root = Pair(horizontal)
                        if which in ('left', 'top'):
                            new_root.balanced_add(wg.id)
                            new_root.two = self.pairs_root
                        else:
                            new_root.one = self.pairs_root
                            new_root.two = wg.id
                        self.pairs_root = new_root
                        return True
        elif action_name == 'bias':
            args = args or ('50',)
            bias = int(args[0])
            wg = all_windows.active_group
            if wg is not None:
                pair = self.pairs_root.pair_for_window(wg.id)
                if pair is not None:
                    pair.set_bias(wg.id, bias)
                    return True

        return None

    def layout_state(self) -> dict[str, Any]:

        def add_pair(p: Pair) -> dict[str, Any]:
            ans: dict[str, Any] = {}
            ans['horizontal'] = p.horizontal
            ans['bias'] = p.bias
            if isinstance(p.one, Pair):
                ans['one'] = add_pair(p.one)
            elif p.one is not None:
                ans['one'] = p.one
            if isinstance(p.two, Pair):
                ans['two'] = add_pair(p.two)
            elif p.two is not None:
                ans['two'] = p.two
            return ans

        return {'pairs': add_pair(self.pairs_root)}
