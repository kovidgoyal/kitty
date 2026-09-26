#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Collection, Generator, Iterator, Sequence
from typing import Any, Optional, TypedDict, Union

from kitty.borders import BorderColor
from kitty.conf.utils import to_bool
from kitty.fast_data_types import BOTTOM_EDGE, LEFT_EDGE, RIGHT_EDGE, TOP_EDGE
from kitty.types import Edges, NeighborsMap, WindowGeometry, WindowMapper, WindowResizeDragData
from kitty.typing_compat import EdgeLiteral, WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import BorderLine, CellAllocator, DragOverlayMode, Layout, LayoutOpts, blank_rects_for_window, calculate_cells_map, lgd, window_geometry_from_layouts
from .constraints import LinearConstraintModel, SplitConstraintModel


def child_axis_units(child: 'Pair | int | None', horizontal: bool) -> int:
    if isinstance(child, Pair):
        return child.count_axis_units(horizontal)
    return 1 if child is not None else 0


class SerializedPair(TypedDict, total=False):
    horizontal: bool  # default to True if absent
    bias: float  # default to 0.5 if absent
    one: Union[int, 'SerializedPair']  # default to None if absent
    two: Union[int, 'SerializedPair']  # default to None if absent


class Pair:
    def __init__(self, horizontal: bool = True):
        self.horizontal = horizontal
        self.one: Pair | int | None = None
        self.two: Pair | int | None = None
        self.bias = 0.5
        self.top = self.left = self.width = self.height = 0
        self.between_borders: tuple[Sequence[BorderLine], Sequence[BorderLine]] | None = None
        self.first_extent = self.second_extent = Edges()  # not including between_borders
        self.border_width: int = 0
        # The model lives with this topology node, so ordinary viewport resizes
        # reuse it. Replacing a Pair naturally creates a fresh model.
        self._constraint_model = SplitConstraintModel()

    def serialize(self) -> SerializedPair:
        ans: SerializedPair = {}
        if not self.horizontal:
            ans['horizontal'] = False
        if self.bias != 0.5:
            ans['bias'] = self.bias
        if self.one is not None:
            ans['one'] = self.one.serialize() if isinstance(self.one, Pair) else self.one
        if self.two is not None:
            ans['two'] = self.two.serialize() if isinstance(self.two, Pair) else self.two
        return ans

    def unserialize(self, s: SerializedPair, map_window_id: WindowMapper) -> None:
        self.bias = s.get('bias', 0.5)
        self.horizontal = s.get('horizontal', True)

        def unserialize(x: int | SerializedPair | None) -> int | Pair | None:
            if x is None:
                return None
            if isinstance(x, int):
                return map_window_id(x)
            ans = Pair()
            ans.unserialize(x, map_window_id)
            return ans if ans.one or ans.two else None

        self.one = unserialize(s.get('one'))
        self.two = unserialize(s.get('two'))

    def __repr__(self) -> str:
        return 'Pair(horizontal={}, bias={:.2f}, one={}, two={}, between_borders={})'.format(
            self.horizontal, self.bias, self.one, self.two, self.between_borders
        )

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

    def count_axis_units(self, horizontal: bool) -> int:
        if self.horizontal != horizontal:
            return 1
        return child_axis_units(self.one, horizontal) + child_axis_units(self.two, horizontal)

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

    def window_weights(self) -> dict[int, float]:
        "Map every window in this sub-tree to its fraction of this pair, obtained by multiplying the biases along the path to it"
        weights: dict[int, float] = {}

        def walk(child: Pair | int | None, weight: float) -> None:
            if isinstance(child, Pair):
                if child.is_redundant:
                    walk(child.one or child.two, weight)
                else:
                    walk(child.one, weight * child.bias)
                    walk(child.two, weight * (1 - child.bias))
            elif child is not None:
                weights[child] = weight

        walk(self, 1.0)
        return weights

    def set_window_weights(self, weights: dict[int, float]) -> None:
        "The inverse of :meth:`window_weights`: set the biases in this sub-tree so the windows end up with the specified relative sizes"

        def tune(child: Pair | int | None) -> float:
            if isinstance(child, Pair):
                one, two = tune(child.one), tune(child.two)
                if one > 0 and two > 0:
                    child.bias = one / (one + two)
                return one + two
            return weights.get(child, 0.0) if child is not None else 0.0

        tune(self)

    def preserve_weights_on_removal(self, removed: Collection[int]) -> bool:
        """
        Adjust the biases in this sub-tree so that the windows surviving the removal of
        ``removed`` keep their current sizes relative to each other. Returns True if this
        sub-tree still contains at least one surviving window.
        """

        # Each perpendicular subtree is one unit along this split axis. If
        # some of its windows survive, retain its full share on this axis.
        def tune(child: Pair | int | None, weight: float) -> tuple[float, bool]:
            if isinstance(child, Pair):
                if child.horizontal != self.horizontal:
                    alive = child.preserve_weights_on_removal(removed)
                    return (weight, True) if alive else (0.0, False)
                if child.is_redundant:
                    return tune(child.one or child.two, weight)
                one, one_alive = tune(child.one, weight * child.bias)
                two, two_alive = tune(child.two, weight * (1 - child.bias))
                if not one_alive and not two_alive:
                    return 0.0, False
                total = one + two
                if one_alive and two_alive and total > 0:
                    child.bias = one / total
                # A window squeezed to zero size (by maximize or an extreme bias) has zero
                # weight. Falling back to the incoming share keeps such survivors from
                # having their space handed to unrelated windows.
                return (total if total > 0 else weight), True
            if child is None or child in removed:
                return 0.0, False
            return weight, True

        return tune(self, 1.0)[1]

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
        # Collapse depth first, otherwise a child that only becomes redundant
        # because all of its own descendants were removed is never re-examined
        # and is left in the tree, consuming its share of the available space.
        if isinstance(self.one, Pair):
            self.one.collapse_redundant_pairs()
        if isinstance(self.two, Pair):
            self.two.collapse_redundant_pairs()
        while isinstance(self.one, Pair) and self.one.is_redundant:
            self.one = self.one.one or self.one.two
        while isinstance(self.two, Pair) and self.two.is_redundant:
            self.two = self.two.one or self.two.two
        if self.one is None and self.two is not None:
            self.one, self.two = self.two, None

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

    def apply_window_geometry(self, window_id: int, window_geometry: WindowGeometry, id_window_map: dict[int, WindowGroup], layout_object: Layout) -> None:
        wg = id_window_map[window_id]
        layout_object._set_group_geometry(wg, window_geometry)
        if layout_object._pending_geometries is None:
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
        left: int,
        top: int,
        width: int,
        height: int,
        id_window_map: dict[int, WindowGroup],
        layout_object: Layout,
        x_cell_allocator: CellAllocator = calculate_cells_map,
        y_cell_allocator: CellAllocator = calculate_cells_map,
    ) -> None:
        self.between_borders = None
        self.left, self.top, self.width, self.height = left, top, width, height
        self.first_extent = self.second_extent = Edges(left, top, left + width, top + height)
        self.border_width = bw = self.effective_border(id_window_map) if lgd.draw_minimal_borders else 0
        border_mult = 0 if lgd.draw_minimal_borders else 1
        bw2 = bw * 2
        if self.one is None or self.two is None:
            q = self.one or self.two
            if isinstance(q, Pair):
                return q.layout_pair(left, top, width, height, id_window_map, layout_object, x_cell_allocator, y_cell_allocator)
            if q is None:
                return
            wg = id_window_map[q]
            xl = next(layout_object.xlayout(iter((wg,)), start=left, size=width, border_mult=border_mult, cell_allocator=x_cell_allocator))
            yl = next(layout_object.ylayout(iter((wg,)), start=top, size=height, border_mult=border_mult, cell_allocator=y_cell_allocator))
            geom = window_geometry_from_layouts(xl, yl)
            self.apply_window_geometry(q, geom, id_window_map, layout_object)
            return
        one: list[BorderLine] = []
        two: list[BorderLine] = []
        self.between_borders = one, two
        if self.horizontal:
            min_w1 = self.one.minimum_width(id_window_map) if isinstance(self.one, Pair) else lgd.cell_width
            min_w2 = self.two.minimum_width(id_window_map) if isinstance(self.two, Pair) else lgd.cell_width
            w1, w2 = self._constraint_model(width, self.bias, bw, min_w1, min_w2)
            bleft = left + w1
            self.first_extent = Edges(left, top, left + w1, top + height)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, w1, height, id_window_map, layout_object, x_cell_allocator, y_cell_allocator)
                if bw:
                    for etop, ebottom, window_id in self.one.edge_border(RIGHT_EDGE, id_window_map):
                        one.append(BorderLine(Edges(bleft, etop, bleft + bw, ebottom), window_id=window_id, horizontal=False))
            else:
                wg = id_window_map[self.one]
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=height, border_mult=border_mult, cell_allocator=y_cell_allocator))
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=w1, border_mult=border_mult, cell_allocator=x_cell_allocator))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.one, geom, id_window_map, layout_object)
                if bw:
                    one.append(BorderLine(Edges(bleft, top, bleft + bw, top + height), window_id=wg.active_window_id, horizontal=False))
            left += w1 + bw2
            self.second_extent = Edges(left, top, left + w2, top + height)
            if isinstance(self.two, Pair):
                self.two.layout_pair(left, top, w2, height, id_window_map, layout_object, x_cell_allocator, y_cell_allocator)
                if bw:
                    for etop, ebottom, window_id in self.two.edge_border(LEFT_EDGE, id_window_map):
                        two.append(BorderLine(Edges(left - bw, etop, left, ebottom), window_id=window_id, horizontal=False))
            else:
                wg = id_window_map[self.two]
                if bw:
                    two.append(BorderLine(Edges(left - bw, top, left, top + height), window_id=-wg.active_window_id, horizontal=False))
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=w2, border_mult=border_mult, cell_allocator=x_cell_allocator))
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=height, border_mult=border_mult, cell_allocator=y_cell_allocator))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.two, geom, id_window_map, layout_object)
        else:
            min_h1 = self.one.minimum_height(id_window_map) if isinstance(self.one, Pair) else lgd.cell_height
            min_h2 = self.two.minimum_height(id_window_map) if isinstance(self.two, Pair) else lgd.cell_height
            h1, h2 = self._constraint_model(height, self.bias, bw, min_h1, min_h2)
            btop = top + h1
            self.first_extent = Edges(left, top, left + width, top + h1)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, width, h1, id_window_map, layout_object, x_cell_allocator, y_cell_allocator)
                if bw:
                    for eleft, eright, window_id in self.one.edge_border(BOTTOM_EDGE, id_window_map):
                        one.append(BorderLine(Edges(eleft, btop, eright, btop + bw), window_id=window_id, horizontal=True))
            else:
                wg = id_window_map[self.one]
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=width, border_mult=border_mult, cell_allocator=x_cell_allocator))
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=h1, border_mult=border_mult, cell_allocator=y_cell_allocator))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.one, geom, id_window_map, layout_object)
                if bw:
                    one.append(BorderLine(Edges(left, btop, left + width, btop + bw), window_id=wg.active_window_id, horizontal=True))
            top += bw2 + h1
            self.second_extent = Edges(left, top, left + width, top + h2)
            if isinstance(self.two, Pair):
                self.two.layout_pair(left, top, width, h2, id_window_map, layout_object, x_cell_allocator, y_cell_allocator)
                if bw:
                    for eleft, eright, window_id in self.two.edge_border(TOP_EDGE, id_window_map):
                        two.append(BorderLine(Edges(eleft, top - bw, eright, top), window_id=window_id, horizontal=True))
            else:
                wg = id_window_map[self.two]
                if bw:
                    two.append(BorderLine(Edges(left, top - bw, left + width, top), window_id=-wg.active_window_id, horizontal=True))
                xl = next(layout_object.xlayout(iter((wg,)), start=left, size=width, border_mult=border_mult, cell_allocator=x_cell_allocator))
                yl = next(layout_object.ylayout(iter((wg,)), start=top, size=h2, border_mult=border_mult, cell_allocator=y_cell_allocator))
                geom = window_geometry_from_layouts(xl, yl)
                self.apply_window_geometry(self.two, geom, id_window_map, layout_object)

    def move_divider(self, pixels: int) -> int:
        """Move this divider, keeping every other divider along the same axis in place.

        Only the two units adjacent to this divider change size. A unit that is a
        perpendicular subtree is resized as a whole, so dividers nested inside it
        that happen to run along this axis do move, proportionally.
        """
        if self.is_redundant or not pixels or self.width <= 0 or self.height <= 0:
            return 0
        horizontal = self.horizontal
        cell = lgd.cell_width if horizontal else lgd.cell_height

        def minimum_size(child: Pair | int | None) -> int:
            if not isinstance(child, Pair):
                return cell if child is not None else 0
            if child.is_redundant:
                return minimum_size(child.one or child.two)
            one, two = minimum_size(child.one), minimum_size(child.two)
            return one + two + 2 * child.border_width if child.horizontal == horizontal else max(one, two)

        def shrink_room(child: Pair | int | None, extent: Edges, trailing: bool) -> int:
            # A perpendicular subtree is one unit in the enclosing splitter.
            # Only the unit touching this divider may give up space.
            while isinstance(child, Pair) and child.horizontal == horizontal and not child.is_redundant:
                extent = child.second_extent if trailing else child.first_extent
                child = child.two if trailing else child.one
            size = extent.right - extent.left if horizontal else extent.bottom - extent.top
            return max(0, size - minimum_size(child))

        pixels = max(-shrink_room(self.one, self.first_extent, True), min(pixels, shrink_room(self.two, self.second_extent, False)))
        if not pixels:
            return 0

        def update(pair: Pair, start: int, size: int) -> None:
            divider = (pair.first_extent.right if horizontal else pair.first_extent.bottom) + pair.border_width
            if pair is self:
                divider += pixels
            # layout_pair truncates to integer pixels. Use the middle of that
            # pixel so floating-point rounding cannot shift a fixed divider.
            pair.bias = (divider - start + 0.5) / size
            for child, child_start, child_size in (
                (pair.one, start, divider - start - pair.border_width),
                (pair.two, divider + pair.border_width, start + size - divider - pair.border_width),
            ):
                if isinstance(child, Pair) and child.horizontal == horizontal and not child.is_redundant:
                    old_start, old_size = (child.left, child.width) if horizontal else (child.top, child.height)
                    if (child_start, child_size) != (old_start, old_size):
                        update(child, child_start, child_size)

        update(self, self.left if horizontal else self.top, self.width if horizontal else self.height)
        return pixels

    def edge_border(self, which: int, id_group_map: dict[int, WindowGroup]) -> Iterator[tuple[int, int, int]]:
        mult = 1 if which & (RIGHT_EDGE | BOTTOM_EDGE) else -1

        def edge(x: int, p: Pair) -> tuple[int, int, int]:
            wid = id_group_map[x].active_window_id * mult
            if which & (LEFT_EDGE | RIGHT_EDGE):
                return p.top, p.top + p.height, wid
            return p.left, p.left + p.width, wid

        def edges(x: int | Pair, parent: Pair) -> Iterator[tuple[int, int, int]]:
            if isinstance(x, int):
                yield edge(x, parent)
            else:
                yield from x.edge_border(which, id_group_map)

        if self.two is None or self.one is None:
            x = self.one or self.two
            if x is not None:
                yield from edges(x, self)
            return

        def as_pair(e: Edges, gid: int) -> Pair:
            g1 = Pair()
            g1.one = g1.two = gid
            g1.left, g1.top, g1.width, g1.height = e.left, e.top, e.right - e.left, e.bottom - e.top
            return g1

        needs_vertical_edges = which in (LEFT_EDGE, RIGHT_EDGE)
        if self.horizontal == needs_vertical_edges:
            yield from edges(self.one if which in (LEFT_EDGE, TOP_EDGE) else self.two, self)
        else:
            g1 = as_pair(self.first_extent, self.one) if isinstance(self.one, int) else self.one
            g2 = as_pair(self.second_extent, self.two) if isinstance(self.two, int) else self.two
            yield from edges(self.one, g1)
            first_id = second_id = 0
            if isinstance(self.one, int):
                first_id = self.one
            if isinstance(self.two, int):
                second_id = self.two
            if self.horizontal:
                start = g1.left + g1.width
                if isinstance(self.one, Pair):
                    first_id = self.one.corner_group_id(which | RIGHT_EDGE)
                if isinstance(self.two, Pair):
                    second_id = self.two.corner_group_id(which | LEFT_EDGE)
            else:
                start = g1.top + g1.height
                if isinstance(self.one, Pair):
                    first_id = self.one.corner_group_id(which | BOTTOM_EDGE)
                if isinstance(self.two, Pair):
                    second_id = self.two.corner_group_id(which | TOP_EDGE)
            if g := id_group_map.get(first_id):
                first_id = g.active_window_id
            if g := id_group_map.get(second_id):
                second_id = g.active_window_id
            yield start, start + self.border_width, first_id * mult
            yield start + self.border_width, start + 2 * self.border_width, second_id * mult
            yield from edges(self.two, g2)

    def corner_group_id(self, which: int) -> int:
        if self.is_redundant:
            q = self.one or self.two
        elif self.horizontal:
            q = self.one if which & LEFT_EDGE else self.two
        else:
            q = self.one if which & TOP_EDGE else self.two
        if q is None:
            return 0
        return q if isinstance(q, int) else q.corner_group_id(which)

    def set_bias(self, window_id: int, bias: int) -> None:
        b = max(0, min(bias, 100)) / 100
        self.bias = b if window_id == self.one else (1.0 - b)

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
            if not ans.get(which) and other:
                if isinstance(other, Pair):
                    neighbors = (w for w in other.edge_windows(edge) if is_neighbouring_geometry(geometries[w], geometries[window_id], which))
                    ans.setdefault(which, []).extend(neighbors)
                else:
                    ans.setdefault(which, []).append(other)

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

    def is_group_on_second(self, gid: int) -> bool:
        if self.one == gid:
            return False
        if self.two == gid:
            return True
        if isinstance(self.two, Pair):
            return self.two.pair_for_window(gid) is not None
        return False

    def find_window_in_tree(self, window_id: int) -> 'list[tuple[Pair, bool]] | None':
        # Returns list of (pair, is_in_one) from self down to the pair containing window_id.
        if self.one == window_id:
            return [(self, True)]
        if self.two == window_id:
            return [(self, False)]
        if isinstance(self.one, Pair):
            path = self.one.find_window_in_tree(window_id)
            if path is not None:
                return [(self, True)] + path
        if isinstance(self.two, Pair):
            path = self.two.find_window_in_tree(window_id)
            if path is not None:
                return [(self, False)] + path
        return None

    def path_from_root(self, target: 'Pair') -> 'list[str] | None':
        if self is target:
            return []
        if isinstance(self.one, Pair):
            sub = self.one.path_from_root(target)
            if sub is not None:
                return ['one'] + sub
        if isinstance(self.two, Pair):
            sub = self.two.path_from_root(target)
            if sub is not None:
                return ['two'] + sub
        return None

    def pair_at_path(self, path: 'list[str]') -> 'Pair | None':
        current: Pair = self
        for step in path:
            child = current.one if step == 'one' else current.two
            if not isinstance(child, Pair):
                return None
            current = child
        return current


class SplitsLayoutOpts(LayoutOpts):
    default_axis_is_horizontal: bool | None = True
    equalize_on_close: bool = False
    proportional: bool = False

    def __init__(self, data: dict[str, str]):
        q = data.get('split_axis', 'horizontal')
        if q == 'auto':
            self.default_axis_is_horizontal = None
        else:
            self.default_axis_is_horizontal = q == 'horizontal'
        self.equalize_on_close = to_bool(data.get('equalize_on_window_close', 'n'))
        self.proportional = to_bool(data.get('proportional', 'n'))

    def serialized(self) -> dict[str, str]:
        return {
            'split_axis': 'auto' if self.default_axis_is_horizontal is None else ('horizontal' if self.default_axis_is_horizontal else 'vertical'),
            'equalize_on_window_close': 'y' if self.equalize_on_close else 'n',
            'proportional': 'y' if self.proportional else 'n',
        }


class Splits(Layout):
    name = 'splits'
    needs_all_windows = True
    layout_opts: SplitsLayoutOpts = SplitsLayoutOpts({})
    no_minimal_window_borders = True
    drag_overlay_mode = DragOverlayMode.free

    def __init__(self, os_window_id: int, tab_id: int, layout_opts: str = '') -> None:
        super().__init__(os_window_id, tab_id, layout_opts)
        self._x_constraint_model = LinearConstraintModel()
        self._y_constraint_model = LinearConstraintModel()

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
        if self.layout_opts.proportional and len(windows_to_remove) > 1:
            # Apply the sizing policy one window at a time, so that pruning a
            # batch of windows (which happens when they are closed while a
            # different layout is active) gives the same result as closing them
            # one by one. The policy is not idempotent over a batch because a
            # perpendicular sub-tree stops being perpendicular once removals
            # collapse it down to a single child.
            for window_id in windows_to_remove:
                self.remove_windows(window_id)
            return
        root = self.pairs_root
        if self.layout_opts.proportional:
            root.preserve_weights_on_removal(frozenset(windows_to_remove))
        for pair in root.self_and_descendants():
            pair.remove_windows(windows_to_remove)
        root.collapse_redundant_pairs()
        if root.one is None or root.two is None:
            q = root.one or root.two
            if isinstance(q, Pair):
                self.pairs_root = q

    def proportional_container(self, group_id: int, horizontal: bool) -> Pair | None:
        "The outermost pair that splits along ``horizontal`` and has the window as one of its leaves"
        path = self.pairs_root.find_window_in_tree(group_id)
        if not path or path[-1][0].horizontal != horizontal:
            return None
        container = path[-1][0]
        for pair, _ in reversed(path[:-1]):
            if pair.horizontal != horizontal:
                break
            container = pair
        return container

    def split_and_add_window(self, pair: Pair, group_id: int, new_id: int, horizontal: bool, after: bool, bias: float | None = None) -> None:
        container = self.proportional_container(group_id, horizontal) if self.layout_opts.proportional and bias is None else None
        weights = container.window_weights() if container is not None else {}
        parent = pair.split_and_add(group_id, new_id, horizontal, after)
        if bias is not None:
            parent.bias = bias if parent.one == new_id else (1 - bias)
        elif container is not None and (weight := weights.get(group_id, 0.0)) > 0:
            weights[new_id] = weight
            container.set_window_weights(weights)

    def balanced_add_window(self, new_id: int) -> Pair:
        "Add a window at a balanced position, applying the proportional sizing policy, if enabled"
        root = self.pairs_root
        if not self.layout_opts.proportional:
            return root.balanced_add(new_id)
        weights = root.window_weights()
        pair = root.balanced_add(new_id)
        # There is no window being split here, so the new window takes the share
        # of whatever it ended up being paired with.
        sibling = pair.two if pair.one == new_id else pair.one
        if isinstance(sibling, Pair):
            weight = sum(weights.get(wid, 0.0) for wid in sibling.all_window_ids())
        else:
            weight = 0.0 if sibling is None else weights.get(sibling, 0.0)
        if weight > 0 and (container := self.proportional_container(new_id, pair.horizontal)) is not None:
            weights[new_id] = weight
            container.set_window_weights(weights)
        return pair

    def do_layout(self, windows: WindowList) -> None:
        groups = tuple(windows.iter_main_groups())
        root = self.pairs_root
        all_present_group_ids = {g.id for g in groups}
        already_placed_group_ids = frozenset(root.all_window_ids())
        if groups_to_remove := already_placed_group_ids - all_present_group_ids:
            self.remove_windows(*groups_to_remove)
            # removing windows can collapse the tree, replacing the root
            root = self.pairs_root
        if groups_to_add := all_present_group_ids - already_placed_group_ids:
            id_idx_map = {g.id: i for i, g in enumerate(groups)}
            for gid in sorted(groups_to_add, key=id_idx_map.__getitem__):
                self.balanced_add_window(gid)

        if len(groups) == 1:
            self.layout_single_window_group(groups[0], x_cell_allocator=self._x_constraint_model, y_cell_allocator=self._y_constraint_model)
        else:
            id_group_map = {g.id: g for g in groups}
            root.layout_pair(
                lgd.central.left,
                lgd.central.top,
                lgd.central.width,
                lgd.central.height,
                id_group_map,
                self,
                self._x_constraint_model,
                self._y_constraint_model,
            )

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
        aw = next_to
        if aw is None or all_windows.is_docked(aw):
            aw = all_windows.active_main_window
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
                self.split_and_add_window(pair, group_id, target_group.id, horizontal, after, bias)
                return
        all_windows.add_window(window)
        g = all_windows.group_for_window(window)
        assert g is not None
        p = self.pairs_root.balanced_add(g.id) if bias is not None else self.balanced_add_window(g.id)
        if bias is not None:
            p.bias = bias

    def modify_size_of_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> bool:
        if all_windows.is_docked(window_id):
            return False
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

    def equalize_biases(self) -> bool:
        for pair in self.pairs_root.self_and_descendants():
            if pair.is_redundant:
                # A redundant pair has no geometry, but its bias is retained for
                # when it is split again, so make that split an even one.
                pair.bias = 0.5
                continue
            left = child_axis_units(pair.one, pair.horizontal)
            right = child_axis_units(pair.two, pair.horizontal)
            total = left + right
            if total > 0:
                pair.bias = left / total
        return True

    def on_window_removed(self, all_windows: WindowList) -> bool:
        if self.layout_opts.equalize_on_close:
            return self.equalize_biases()
        return False

    def minimal_borders(self, windows: WindowList) -> Iterator[BorderLine]:
        groups = tuple(windows.iter_main_groups())
        window_count = len(groups)
        if not lgd.draw_minimal_borders or window_count < 2:
            return
        needs_borders_map = windows.compute_needs_borders_map(lgd.draw_active_borders)
        ag = windows.active_group
        active_group_id = -1 if ag is None else ag.id

        border_color_map = {}
        for grp_id, needs_borders in needs_borders_map.items():
            if needs_borders:
                wid = g.active_window_id if (g := windows.group_for_id(grp_id)) else 0
                if wid:
                    color = BorderColor.active if grp_id is active_group_id else BorderColor.bell
                    border_color_map[wid] = color

        for pair in self.pairs_root.self_and_descendants():
            if pair.between_borders:
                for which in pair.between_borders:
                    for bb in which:
                        yield bb._replace(color=border_color_map.get(abs(bb.window_id), BorderColor.inactive))

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        wg = windows.group_for_window(window)
        assert wg is not None
        pair = self.pairs_root.pair_for_window(wg.id)
        ans: NeighborsMap = {}
        if pair is not None:
            pair.neighbors_for_window(wg.id, ans, self, windows)
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

    def insert_window_next_to(self, all_windows: WindowList, window: 'WindowType', next_to: 'WindowType', horizontal: bool, after: bool) -> None:
        """Reposition an existing window as a split adjacent to next_to"""
        src_wg = all_windows.group_for_window(window)
        dest_wg = all_windows.group_for_window(next_to)
        if src_wg is None or dest_wg is None or src_wg.id == dest_wg.id or src_wg.dock_data or dest_wg.dock_data:
            return
        # Remove from current position in pairs_root
        self.remove_windows(src_wg.id)
        # Re-insert next to dest
        pair = self.pairs_root.pair_for_window(dest_wg.id)
        if pair is not None:
            self.split_and_add_window(pair, dest_wg.id, src_wg.id, horizontal, after)
        else:
            self.balanced_add_window(src_wg.id)

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> bool | None:
        active_group = all_windows.active_group
        if action_name in ('rotate', 'move_to_screen_edge', 'bias', 'maximize') and active_group is not None and active_group.dock_data:
            return False
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
                                    pair.bias = 1.0 - pair.bias
                            else:
                                if pair.one == wg.id:
                                    pair.one, pair.two = pair.two, pair.one
                                    pair.bias = 1.0 - pair.bias
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
        elif action_name == 'maximize':
            args = args or ('horizontal',)
            axis = args[0]
            is_horizontal = axis == 'horizontal'
            wg = all_windows.active_group
            if wg is not None:
                key = (wg.id, is_horizontal)
                maximized_biases: dict[tuple[int, bool], list[tuple[Pair, float]]] = getattr(self, '_maximized_biases', {})
                if key in maximized_biases:
                    # Already maximized along this axis for this window — toggle back
                    current_pair_ids = {id(p) for p in self.pairs_root.self_and_descendants()}
                    for pair_ref, saved_bias in maximized_biases.pop(key):
                        if id(pair_ref) in current_pair_ids:
                            pair_ref.bias = saved_bias
                    self._maximized_biases = maximized_biases
                    return True
                else:
                    # Undo any existing maximize along the same axis (different window)
                    stale_keys = [k for k in maximized_biases if k[1] == is_horizontal]
                    if stale_keys:
                        current_pair_ids = {id(p) for p in self.pairs_root.self_and_descendants()}
                        for k in stale_keys:
                            for pair_ref, saved_bias in maximized_biases.pop(k):
                                if id(pair_ref) in current_pair_ids:
                                    pair_ref.bias = saved_bias
                    # Maximize: set biases along the path to give maximum space to active window
                    # Only adjust pairs whose split axis matches the requested direction:
                    # horizontal maximize expands width (affects horizontal/side-by-side splits),
                    # vertical maximize expands height (affects vertical/top-bottom splits).
                    tree_path = self.pairs_root.find_window_in_tree(wg.id)
                    if tree_path is not None:
                        saved_biases: list[tuple[Pair, float]] = []
                        for pair, is_in_one in tree_path:
                            if pair.horizontal == is_horizontal and not pair.is_redundant:
                                saved_biases.append((pair, pair.bias))
                                pair.bias = 1.0 if is_in_one else 0.0
                        if saved_biases:
                            maximized_biases[key] = saved_biases
                            self._maximized_biases = maximized_biases
                    return True
        elif action_name == 'equalize':
            return self.equalize_biases()

        return None

    def drag_resize_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> float:
        self._set_dimensions(all_windows)
        for pair in self.pairs_root.self_and_descendants():
            if id(pair) == window_id:
                if pair.horizontal != is_horizontal:
                    break
                cell = lgd.cell_width if is_horizontal else lgd.cell_height
                return pair.move_divider(round(increment * cell)) / cell if cell > 0 else 0.0
        return 0.0

    def drag_resize_target_windows(
        self,
        click_window: WindowType,
        x: float,
        y: float,
        edges: int,
        all_windows: WindowList,
    ) -> WindowResizeDragData:
        right, bottom = bool(edges & RIGHT_EDGE), bool(edges & BOTTOM_EDGE)
        ans = WindowResizeDragData(None, right, None, bottom)
        group = all_windows.group_for_window(click_window)
        if group is None:
            return ans
        path = self.pairs_root.find_window_in_tree(group.id)
        if path is None:
            return ans

        def target(horizontal: bool, trailing: bool) -> tuple[int | None, bool]:
            fallback = None
            for pair, in_one in reversed(path):
                if pair.is_redundant or pair.horizontal != horizontal:
                    continue
                if fallback is None:
                    fallback = id(pair)
                # The right/bottom edge of the first child, or left/top edge
                # of the second child, belongs to this divider. Otherwise keep
                # climbing, even across ancestors with the same split axis.
                if in_one == trailing:
                    return id(pair), True
            # Preserve native resizing from the outside edge of a layout.
            return fallback, False

        if edges & (LEFT_EDGE | RIGHT_EDGE):
            horizontal_id, forwards = target(True, right)
            ans = ans._replace(horizontal_id=horizontal_id, width_increases_rightwards=forwards)
        if edges & (TOP_EDGE | BOTTOM_EDGE):
            vertical_id, forwards = target(False, bottom)
            ans = ans._replace(vertical_id=vertical_id, height_increases_downwards=forwards)
        return ans

    def layout_state(self) -> dict[str, Any]:
        ans: dict[str, Any] = {'pairs': self.pairs_root.serialize()}
        maximized_biases: dict[tuple[int, bool], list[tuple[Pair, float]]] = getattr(self, '_maximized_biases', {})
        if maximized_biases:
            serialized_maximized = []
            for (window_id, is_horizontal), saved_biases_list in maximized_biases.items():
                entries = []
                for pair_ref, saved_bias in saved_biases_list:
                    path = self.pairs_root.path_from_root(pair_ref)
                    if path is not None:
                        entries.append({'path': path, 'bias': saved_bias})
                if entries:
                    serialized_maximized.append(
                        {
                            'window_id': window_id,
                            'is_horizontal': is_horizontal,
                            'saved_biases': entries,
                        }
                    )
            if serialized_maximized:
                ans['maximized'] = serialized_maximized
        return ans

    def set_layout_state(self, layout_state: dict[str, Any], map_group_id: WindowMapper) -> bool:
        new_root = Pair()
        new_root.unserialize(layout_state['pairs'], map_group_id)
        before = frozenset(self.pairs_root.all_window_ids())
        # An empty tree means this layout has not laid out any windows yet, which is
        # the case when restoring the state of a layout that was not the active one.
        # do_layout() places any groups the restored tree is missing.
        if not before or before == frozenset(new_root.all_window_ids()):
            self.pairs_root = new_root
            self.layout_opts = SplitsLayoutOpts(layout_state['opts'])
            if 'maximized' in layout_state:
                maximized_biases: dict[tuple[int, bool], list[tuple[Pair, float]]] = {}
                for entry in layout_state['maximized']:
                    new_window_id = map_group_id(entry['window_id'])
                    if new_window_id is None:
                        continue
                    is_horizontal: bool = entry['is_horizontal']
                    saved_biases_list: list[tuple[Pair, float]] = []
                    for saved in entry['saved_biases']:
                        pair = new_root.pair_at_path(saved['path'])
                        if pair is not None:
                            saved_biases_list.append((pair, saved['bias']))
                    if saved_biases_list:
                        maximized_biases[(new_window_id, is_horizontal)] = saved_biases_list
                if maximized_biases:
                    self._maximized_biases = maximized_biases
            return True
        return False
