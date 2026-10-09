#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from copy import copy, deepcopy
from enum import Enum
from functools import partial
from itertools import repeat
from math import ceil, isfinite
from typing import Any, ClassVar, NamedTuple, cast

from kitty.borders import BorderColor
from kitty.fast_data_types import BOTTOM_EDGE, RIGHT_EDGE, Region, get_options, set_active_window, viewport_for_window
from kitty.options.types import Options
from kitty.types import DockEdge, DockSpec, Edges, NeighborsMap, WindowGeometry, WindowMapper, WindowResizeDragData, dock_edges, opposite_dock_edge
from kitty.typing_compat import EdgeLiteral, WindowType
from kitty.window_list import WindowGroup, WindowList, collapsed_margin


class BorderLine(NamedTuple):
    edges: Edges = Edges()
    color: BorderColor = BorderColor.inactive
    window_id: int = 0
    horizontal: bool = False


class LayoutOpts:
    def __init__(self, data: dict[str, str]):
        pass

    def serialized(self) -> dict[str, Any]:
        return {}


class LayoutData(NamedTuple):
    content_pos: int = 0
    cells_per_window: int = 0
    space_before: int = 0
    space_after: int = 0
    content_size: int = 0
    # The portion of space_before/space_after that is compensatory padding
    # arising from the window size not being an exact multiple of the cell size
    # (as opposed to the intentional margin/border/padding decoration).
    compensatory_before: int = 0
    compensatory_after: int = 0


DecorationPairs = Sequence[tuple[int, int]]
LayoutDimension = Generator[LayoutData, None, None]
ListOfWindows = list[WindowType]


class LayoutGlobalData:
    draw_minimal_borders: bool = True
    draw_active_borders: bool = True
    fill_padding_with_neighboring_cell: bool = False
    alignment_x: int = 0
    alignment_y: int = 0

    central: Region = Region((0, 0, 199, 199, 200, 200))
    cell_width: int = 20
    cell_height: int = 20


lgd = LayoutGlobalData()


def fractional_resize_steps(remaining: int, fraction: float) -> int:
    return max(1, ceil(remaining * fraction - 1e-9)) if remaining > 0 else 0


def idx_for_id(win_id: int, windows: Iterable[WindowType]) -> int | None:
    for i, w in enumerate(windows):
        if w.id == win_id:
            return i
    return None


def effective_draw_minimal_borders(opts: Options, has_more_than_one_visible_group: bool = True) -> bool:
    ans = opts.draw_minimal_borders and sum(opts.window_margin_width) == 0
    if not has_more_than_one_visible_group and opts.draw_window_borders_for_single_window:
        ans = False
    return ans


def set_layout_options(opts: Options) -> None:
    lgd.draw_minimal_borders = effective_draw_minimal_borders(opts)
    lgd.draw_active_borders = opts.active_border_color is not None
    lgd.fill_padding_with_neighboring_cell = opts.padding_fill_strategy == 'neighboring_cell'
    lgd.alignment_x = -1 if opts.placement_strategy.endswith('left') else 1 if opts.placement_strategy.endswith('right') else 0
    lgd.alignment_y = -1 if opts.placement_strategy.startswith('top') else 1 if opts.placement_strategy.startswith('bottom') else 0


def convert_bias_map(bias: dict[int, float], number_of_windows: int, number_of_cells: int) -> Sequence[float]:
    cells_per_window, extra = divmod(number_of_cells, number_of_windows)
    cell_map = list(repeat(cells_per_window, number_of_windows))
    cell_map[-1] += extra
    base_bias = [x / number_of_cells for x in cell_map]
    return distribute_indexed_bias(base_bias, bias)


def calculate_cells_map(bias: None | Sequence[float] | dict[int, float], number_of_windows: int, number_of_cells: int) -> list[int]:
    if isinstance(bias, dict):
        b: dict[int, float] = cast(dict[int, float], bias)
        bias = convert_bias_map(b, number_of_windows, number_of_cells)
    cells_per_window = number_of_cells // number_of_windows
    if bias is not None and number_of_windows > 1 and number_of_windows == len(bias) and cells_per_window > 5:
        cells_map = [int(b * number_of_cells) for b in bias]
        while min(cells_map) < 5:
            maxi, mini = map(cells_map.index, (max(cells_map), min(cells_map)))
            if maxi == mini:
                break
            cells_map[mini] += 1
            cells_map[maxi] -= 1
    else:
        cells_map = list(repeat(cells_per_window, number_of_windows))
    extra = number_of_cells - sum(cells_map)
    if extra > 0:
        cells_map[-1] += extra
    return cells_map


def layout_dimension(
    start_at: int, length: int, cell_length: int, decoration_pairs: DecorationPairs, alignment: int = 0, bias: None | Sequence[float] | dict[int, float] = None
) -> LayoutDimension:
    number_of_windows = len(decoration_pairs)
    number_of_cells = max(0, length // cell_length)
    dec_vals: Iterable[int] = map(sum, decoration_pairs)
    space_needed_for_decorations = sum(dec_vals)
    extra = length - number_of_cells * cell_length
    while extra < space_needed_for_decorations and number_of_cells > 0:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    cells_map = calculate_cells_map(bias, number_of_windows, number_of_cells) if number_of_cells > 0 else [0] * number_of_windows
    assert sum(cells_map) == number_of_cells

    extra = length - number_of_cells * cell_length - space_needed_for_decorations
    pos = start_at  # start
    if alignment > 0:  # end
        pos += extra
    elif alignment == 0:  # center
        pos += extra // 2
    last_i = len(cells_map) - 1

    for i, cells_per_window in enumerate(cells_map):
        before_dec, after_dec = decoration_pairs[i]
        pos += before_dec
        if i == 0:
            before_space = pos - start_at
        else:
            before_space = before_dec
        content_size = cells_per_window * cell_length
        if i == last_i:
            after_space = (start_at + length) - (pos + content_size)
        else:
            after_space = after_dec
        # Whatever space is present beyond the intentional decoration is the
        # compensatory padding from the size mismatch (only ever non-zero for
        # the first/last windows, which absorb the leading/trailing remainder).
        yield LayoutData(pos, cells_per_window, before_space, after_space, content_size, before_space - before_dec, after_space - after_dec)
        pos += content_size + after_space


class Rect(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int


def blank_rects_for_window(wg: WindowGeometry) -> Generator[Rect, None, None]:
    left, top, right, bottom = wg.left, wg.top, wg.right, wg.bottom
    left_width, top_height, right_width, bottom_height = wg.spaces
    if lgd.fill_padding_with_neighboring_cell:
        # The compensatory padding is the innermost slice of the spaces, adjacent
        # to the cells. It is drawn separately by the padding shader so that it
        # matches its neighboring cell. Exclude it here by expanding the content
        # box over it and only painting the remaining outer decoration frame in
        # the background color.
        c = wg.compensatory
        left -= c.left
        top -= c.top
        right += c.right
        bottom += c.bottom
        left_width -= c.left
        top_height -= c.top
        right_width -= c.right
        bottom_height -= c.bottom
    if left_width > 0:
        yield Rect(left - left_width, top - top_height, left, bottom + bottom_height)
    if top_height > 0:
        yield Rect(left, top - top_height, right + right_width, top)
    if right_width > 0:
        yield Rect(right, top, right + right_width, bottom + bottom_height)
    if bottom_height > 0:
        yield Rect(left, bottom, right, bottom + bottom_height)


def window_geometry(
    xstart: int,
    xnum: int,
    ystart: int,
    ynum: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    compensatory: Edges = Edges(),
) -> WindowGeometry:
    return WindowGeometry(
        left=xstart,
        top=ystart,
        xnum=max(0, xnum),
        ynum=max(0, ynum),
        right=xstart + lgd.cell_width * xnum,
        bottom=ystart + lgd.cell_height * ynum,
        spaces=Edges(left, top, right, bottom),
        compensatory=compensatory,
    )


def window_geometry_from_layouts(x: LayoutData, y: LayoutData) -> WindowGeometry:
    return window_geometry(
        x.content_pos,
        x.cells_per_window,
        y.content_pos,
        y.cells_per_window,
        x.space_before,
        y.space_before,
        x.space_after,
        y.space_after,
        Edges(x.compensatory_before, y.compensatory_before, x.compensatory_after, y.compensatory_after),
    )


def layout_single_window(
    xdecoration_pairs: DecorationPairs,
    ydecoration_pairs: DecorationPairs,
    xalignment: int = 0,
    yalignment: int = 0,
) -> WindowGeometry:
    x = next(layout_dimension(lgd.central.left, lgd.central.width, lgd.cell_width, xdecoration_pairs, alignment=xalignment))
    y = next(layout_dimension(lgd.central.top, lgd.central.height, lgd.cell_height, ydecoration_pairs, alignment=yalignment))
    return window_geometry_from_layouts(x, y)


def region(left: int, top: int, width: int, height: int) -> Region:
    width, height = max(0, width), max(0, height)
    return Region((left, top, left + width - 1, top + height - 1, width, height))


def outer_region_of(geom: WindowGeometry) -> Region:
    "The region occupied by a window including its decorations"
    s = geom.spaces
    return region(geom.left - s.left, geom.top - s.top, geom.right - geom.left + s.left + s.right, geom.bottom - geom.top + s.top + s.bottom)


def carve_docks(area: Region, docks: Iterable[WindowGroup], cell_width: int, cell_height: int) -> tuple[Region, list[tuple[WindowGroup, Region]]]:
    """
    Give each docked group a slice of area at its edge, in order, so earlier
    docks are further out and span the full extent of whatever area remains when
    they are placed. Returns the area left over for the content and the regions of
    the docks. When space runs out, later docks are shrunk first.
    """
    left, top, right, bottom = area.left, area.top, area.left + area.width, area.top + area.height
    placements: list[tuple[WindowGroup, Region]] = []
    for g in docks:
        d = g.dock
        if d is None:
            continue
        if d.is_horizontal:
            total, available, cell, dec = area.height, bottom - top, cell_height, g.decoration('top') + g.decoration('bottom')
        else:
            total, available, cell, dec = area.width, right - left, cell_width, g.decoration('left') + g.decoration('right')
        wanted = int(total * d.size / 100) if d.size_is_percent else int(d.size) * cell + dec
        size = max(0, min(wanted, available))
        match d.edge:
            case 'top':
                placements.append((g, region(left, top, right - left, size)))
                top += size
            case 'bottom':
                bottom -= size
                placements.append((g, region(left, bottom, right - left, size)))
            case 'left':
                placements.append((g, region(left, top, size, bottom - top)))
                left += size
            case 'right':
                right -= size
                placements.append((g, region(right, top, size, bottom - top)))
    return region(left, top, right - left, bottom - top), placements


def safe_increment_bias(old_val: float, increment: float = 0) -> float:
    return max(0.1, min(old_val + increment, 0.9))


def normalize_biases(biases: list[float]) -> list[float]:
    s = sum(biases)
    if s == 1.0:
        return biases
    return [x / s for x in biases]


def distribute_indexed_bias(base_bias: Sequence[float], index_bias_map: dict[int, float]) -> Sequence[float]:
    if not index_bias_map:
        return base_bias
    ans = list(base_bias)
    limit = len(ans)
    for row, increment in index_bias_map.items():
        if row >= limit or not increment:
            continue
        other_increment = -increment / (limit - 1)
        ans = [safe_increment_bias(b, increment if i == row else other_increment) for i, b in enumerate(ans)]
    return normalize_biases(ans)


def is_focusable_dock(g: WindowGroup) -> bool:
    return g.dock is not None and g.dock.focusable and g.is_visible_in_layout


def innermost_focusable_dock(docks: Sequence[WindowGroup], edge: DockEdge) -> WindowGroup | None:
    for d in reversed(docks):
        if d.dock is not None and d.dock.edge == edge and is_focusable_dock(d):
            return d
    return None


def set_neighbors(ans: NeighborsMap, edge: DockEdge, val: list[int]) -> None:
    # NeighborsMap is a TypedDict so it cannot be indexed by a variable
    match edge:
        case 'left':
            ans['left'] = val
        case 'top':
            ans['top'] = val
        case 'right':
            ans['right'] = val
        case 'bottom':
            ans['bottom'] = val


def create_window_id_map_for_unserialize(all_windows: WindowList) -> dict[int, int]:
    window_id_map = {}
    for w in all_windows:
        if w.serialized_id:
            window_id_map[w.serialized_id] = w.id
    return window_id_map


class DragOverlayMode(Enum):
    "Controls drag-and-drop overlay display and valid direction axis for body drops"

    full = 'full'  # full-window overlay, positional swap (Stack and any unrecognised layout)
    axis_x = 'axis_x'  # top/bottom halves only (Vertical, Tall, Grid)
    axis_y = 'axis_y'  # left/right halves only (Horizontal, Fat)
    free = 'free'  # 4-way free direction (Splits; handled by its own insert_window_next_to override)


class Layout:
    name: str = ''
    needs_window_borders = True
    must_draw_borders = False  # can be overridden to customize behavior from kittens
    layout_opts = LayoutOpts({})
    only_active_window_visible = False
    drag_overlay_mode: ClassVar[DragOverlayMode] = DragOverlayMode.full

    def __init__(self, os_window_id: int, tab_id: int, layout_opts: str = '') -> None:
        self.set_owner(os_window_id, tab_id)
        # A set of rectangles corresponding to the blank spaces at the edges of
        # this layout, i.e. spaces that are not covered by any window
        self.blank_rects: list[Rect] = []
        self.tab_dock_placements: list[tuple[WindowGroup, Region]] = []
        # The blank strips at the edges of the layout area when margins are collapsed
        self.collapsed_margin_rects: list[Rect] = []
        self.layout_opts = self.parse_layout_opts(layout_opts)
        assert self.name is not None
        self.full_name = f'{self.name}:{layout_opts}' if layout_opts else self.name
        self.remove_all_biases()

    def set_owner(self, os_window_id: int, tab_id: int) -> None:
        # Useful when moving a layout from one tab to another typically a detached tab being re-attached
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.set_active_window_in_os_window = partial(set_active_window, os_window_id, tab_id)

    def bias_increment_for_cell(self, all_windows: WindowList, is_horizontal: bool) -> float:
        self._set_dimensions(all_windows)
        return self.calculate_bias_increment_for_a_single_cell(all_windows, is_horizontal)

    def calculate_bias_increment_for_a_single_cell(self, all_windows: WindowList, is_horizontal: bool) -> float:
        if is_horizontal:
            return (lgd.cell_width + 1) / lgd.central.width
        return (lgd.cell_height + 1) / lgd.central.height

    def apply_bias(self, window_id: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        return False

    def remove_all_biases(self) -> bool:
        return False

    def modify_size_of_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> bool:
        idx = all_windows.group_idx_for_window(window_id)
        if idx is None or not increment:
            return False
        return self.apply_bias(idx, increment, all_windows, is_horizontal)

    def apply_fractional_bias(self, window_idx: int, increment: float, all_windows: WindowList, is_horizontal: bool) -> bool:
        return self.apply_bias(window_idx, increment, all_windows, is_horizontal)

    def modify_size_of_window_by_fraction(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool, fraction: float) -> bool:
        if window_id not in all_windows.id_map:
            return False
        idx = all_windows.group_idx_for_window(window_id)
        if idx is None or all_windows.num_groups < 2 or not increment or not isfinite(increment) or not 0 < fraction <= 1:
            return False
        # Probe private layout state, without changing windows or rendering every
        # intermediate step. This follows each layout's ordinary resize rules.
        probe = copy(self)
        state = deepcopy(self.layout_state())
        state['opts'] = self.layout_opts.serialized()
        if not probe.set_layout_state(state, lambda group_id: group_id):
            return False
        # The state after each step, so that the chosen number of steps can be
        # adopted without repeating them.
        states: list[dict[str, Any]] = []
        # Biases span at most one unit; allow two for clamping/normalization.
        # The bound also prevents future layout implementations from looping.
        for _ in range(max(1, ceil(2 / abs(increment)))):
            if not probe.apply_fractional_bias(idx, increment, all_windows, is_horizontal):
                break
            states.append(deepcopy(probe.layout_state()))
        steps = fractional_resize_steps(len(states), fraction)
        if not steps:
            return False
        state = states[steps - 1]
        state['opts'] = self.layout_opts.serialized()
        return self.set_layout_state(state, lambda group_id: group_id)

    def drag_resize_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> float:
        """Resize by a number of cells, returning the number of cells actually applied.

        Layouts that can apply an increment only partially should override this and
        report what they really did, so that the caller can keep the dragged divider
        locked to the pointer. This generic implementation has no way to tell how much
        apply_bias() clamped, so it reports all or nothing.
        """
        increment_as_percent = self.bias_increment_for_cell(all_windows, is_horizontal) * increment
        return increment if self.modify_size_of_window(all_windows, window_id, increment_as_percent, is_horizontal) else 0.0

    def parse_layout_opts(self, layout_opts: str | None = None) -> LayoutOpts:
        data: dict[str, str] = {}
        if layout_opts:
            for x in layout_opts.split(';'):
                k, v = x.partition('=')[::2]
                if k and v:
                    data[k] = v
        return type(self.layout_opts)(data)

    def nth_window(self, all_windows: WindowList, num: int) -> WindowType | None:
        return all_windows.active_window_in_nth_group(num, clamp=True)

    def activate_nth_window(self, all_windows: WindowList, num: int) -> None:
        all_windows.set_active_group_idx(num)

    def next_window(self, all_windows: WindowList, delta: int = 1) -> None:
        all_windows.activate_next_window_group(delta)

    def neighbors(self, all_windows: WindowList) -> NeighborsMap:
        w = all_windows.active_window
        assert w is not None
        return self.neighbors_for_any_window(w, all_windows)

    def neighbors_for_any_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        """
        Like neighbors_for_window() but also works for docked windows and takes
        docks into account. A docked group is a neighbor of the group it is
        docked to and of the docks next to it at the same edge.
        """
        group = all_windows.group_for_window(window)
        if group is None:
            return {}
        if group.dock is None:
            return self._neighbors_with_docks(window, group, all_windows)
        owner = all_windows.dock_owner(group)
        siblings = [d for d in (all_windows.tab_docks if owner is None else owner.docks) if d.dock is not None and d.dock.edge == group.dock.edge]
        idx = siblings.index(group)
        outer = [d for d in siblings[:idx] if is_focusable_dock(d)]
        inner = [d for d in siblings[idx + 1 :] if is_focusable_dock(d)]
        ans: NeighborsMap = {}
        if owner is not None and (w := all_windows.id_map.get(owner.active_window_id)) is not None:
            # The rest of the neighbors are those of the owner
            ans = self._neighbors_with_docks(w, owner, all_windows, skip_own_docks=True)
        inwards: list[int] = []
        if inner:
            inwards = [inner[0].id]
        elif owner is not None:
            inwards = [owner.id]
        elif (mg := all_windows.active_main_group) is not None:
            inwards = [mg.id]
        set_neighbors(ans, opposite_dock_edge[group.dock.edge], inwards)
        if outer:
            set_neighbors(ans, group.dock.edge, [outer[-1].id])
        return ans

    def _neighbors_with_docks(self, window: WindowType, group: WindowGroup, all_windows: WindowList, skip_own_docks: bool = False) -> NeighborsMap:
        ans: NeighborsMap = {}
        ans.update(self.neighbors_for_window(window, all_windows))
        for edge in dock_edges:
            # The innermost dock at an edge is next to the group, so it takes
            # precedence. The tab docks are next to whichever groups have no
            # neighbors in that direction.
            if not skip_own_docks and (d := innermost_focusable_dock(group.docks, edge)) is not None:
                set_neighbors(ans, edge, [d.id])
            elif not ans.get(edge) and (d := innermost_focusable_dock(all_windows.tab_docks, edge)) is not None:
                set_neighbors(ans, edge, [d.id])
        return ans

    def move_window(self, all_windows: WindowList, delta: int = 1) -> bool:
        if all_windows.num_groups < 2 or not delta or all_windows.active_dock is not None:
            return False

        return all_windows.move_window_group(by=delta)

    def move_window_to_group(self, all_windows: WindowList, group: int) -> bool:
        return all_windows.move_window_group(to_group=group)

    def insert_window_next_to(
        self,
        all_windows: WindowList,
        window: WindowType,
        next_to: WindowType,
        horizontal: bool,
        after: bool,
    ) -> None:
        """
        Reposition window as a linear neighbour of next_to.

        For axis_x/axis_y layouts this performs a positional insert that preserves
        the order of all other groups. For 'full' layouts it falls back to a swap.
        The Splits layout overrides this with tree-based logic.
        """
        src_wg = all_windows.group_for_window(window)
        dest_wg = all_windows.group_for_window(next_to)
        if src_wg is None or dest_wg is None or src_wg.id == dest_wg.id or src_wg.dock is not None or dest_wg.dock is not None:
            return
        all_windows.set_active_window_group_for(window)
        if self.drag_overlay_mode in (DragOverlayMode.axis_x, DragOverlayMode.axis_y):
            all_windows.insert_window_group_next_to(dest_wg.id, after)
        else:
            # 'full' fallback: swap (preserves existing behaviour for Stack etc.)
            self.move_window_to_group(all_windows, dest_wg.id)

    def add_window(
        self,
        all_windows: WindowList,
        window: WindowType,
        location: str | None = None,
        overlay_for: int | None = None,
        put_overlay_behind: bool = False,
        bias: float | None = None,
        next_to: WindowType | None = None,
        dock: DockSpec | None = None,
        dock_owner: WindowGroup | None = None,
    ) -> WindowType | None:
        if dock is not None:
            all_windows.add_window(window, dock=dock, dock_owner=dock_owner)
            return None
        if overlay_for is not None:
            underlay = all_windows.id_map.get(overlay_for)
            if underlay is not None:
                window.margin, window.padding = underlay.margin.copy(), underlay.padding.copy()
                all_windows.add_window(window, group_of=overlay_for, head_of_group=put_overlay_behind)
                return underlay
        if location == 'neighbor':
            location = 'after'
        self.add_non_overlay_window(all_windows, window, location, bias, next_to)
        return None

    def add_non_overlay_window(
        self, all_windows: WindowList, window: WindowType, location: str | None, bias: float | None = None, next_to: WindowType | None = None
    ) -> None:
        before = False
        next_to = next_to or all_windows.active_window
        if next_to is not None:
            # New windows are never placed next to docked windows
            next_to = all_windows.main_window_for(next_to)
        if location is not None:
            if location in ('after', 'vsplit', 'hsplit'):
                pass
            elif location == 'before':
                before = True
            elif location == 'first':
                before = True
                next_to = None
            elif location == 'last':
                next_to = None
        all_windows.add_window(window, next_to=next_to, before=before)
        if bias is not None:
            idx = all_windows.group_idx_for_window(window)
            if idx is not None:
                self._set_dimensions(all_windows)
                self._bias_slot(all_windows, idx, bias)

    def _bias_slot(self, all_windows: WindowList, idx: int, bias: float) -> bool:
        fractional_bias = max(10, min(abs(bias), 90)) / 100
        h, v = self.calculate_bias_increment_for_a_single_cell(all_windows, True), self.calculate_bias_increment_for_a_single_cell(all_windows, False)
        nh, nv = lgd.central.width / lgd.cell_width, lgd.central.height / lgd.cell_height
        f = max(-90, min(bias, 90)) / 100.0
        return self.bias_slot(all_windows, idx, fractional_bias, h * nh * f, v * nv * f)

    def bias_slot(self, all_windows: WindowList, idx: int, fractional_bias: float, cell_increment_bias_h: float, cell_increment_bias_v: float) -> bool:
        return False

    def update_visibility(self, all_windows: WindowList) -> None:
        active_window = all_windows.active_main_window
        for window, is_group_leader in all_windows.iter_windows_with_visibility():
            is_visible = window is active_window or (is_group_leader and not self.only_active_window_visible)
            window.set_visible_in_layout(is_visible)
        # Docked groups are visible when their owner is, tab docks are always visible
        for dock in all_windows.tab_docks:
            for window in dock:
                window.set_visible_in_layout(window.id == dock.active_window_id)
        for group in all_windows.groups:
            owner_is_visible = group.is_visible_in_layout
            for dock in group.docks:
                for window in dock:
                    window.set_visible_in_layout(owner_is_visible and window.id == dock.active_window_id)
        for dock in all_windows.orphaned_docks:
            for window in dock:
                window.set_visible_in_layout(False)

    def _set_dimensions(self, all_windows: WindowList) -> None:
        full_area, tab_bar, vw, vh, lgd.cell_width, lgd.cell_height = viewport_for_window(self.os_window_id)
        opts = get_options()
        self.collapsed_margin_rects = []
        if opts.collapse_window_margins and (w := next(iter(all_windows), None)) is not None:
            # Windows use only part of their margins, see collapsed_margin(),
            # so supply the rest at the edges of the layout area
            def inset(edge: EdgeLiteral) -> int:
                m = w.default_margin(edge)
                return m - collapsed_margin(m, edge)

            ml, mt, mr, mb = inset('left'), inset('top'), inset('right'), inset('bottom')
            left, top, right, bottom = full_area.left, full_area.top, full_area.left + full_area.width, full_area.top + full_area.height
            full_area = region(left + ml, top + mt, full_area.width - ml - mr, full_area.height - mt - mb)
            il, it = full_area.left, full_area.top
            ir, ib = il + full_area.width, it + full_area.height
            self.collapsed_margin_rects = [
                r
                for r in (Rect(left, top, right, it), Rect(left, ib, right, bottom), Rect(left, it, il, ib), Rect(ir, it, right, ib))
                if r.right > r.left and r.bottom > r.top
            ]
        # The tab docks reduce the area available to the layout
        lgd.central, self.tab_dock_placements = carve_docks(full_area, all_windows.tab_docks, lgd.cell_width, lgd.cell_height)
        # Update lgd.draw_minimal_borders based on the current number of visible windows
        # and the draw_window_borders_for_single_window option
        lgd.draw_minimal_borders = effective_draw_minimal_borders(opts, all_windows.has_more_than_one_visible_group)

    def __call__(self, all_windows: WindowList) -> None:
        self._set_dimensions(all_windows)
        self.update_visibility(all_windows)
        # Set show_title_bar flag on each visible window before layout
        min_windows = get_options().window_title_bar_min_windows
        visible_groups = tuple(all_windows.iter_all_layoutable_groups(only_visible=True))
        force_show = all_windows.force_show_title_bars
        show_title_bar = force_show or (min_windows > 0 and len(visible_groups) >= min_windows)
        for wg in visible_groups:
            for w in wg.windows:
                w.show_title_bar = show_title_bar
        for wg in all_windows.iter_dock_groups():
            for w in wg.windows:
                w.show_title_bar = False
        if all_windows.groups:
            self.do_layout(all_windows)
        self.layout_docks(all_windows)
        # Computed from the final geometry of the windows, as it can differ
        # from what the layout gave them, see WindowGroup.set_content_geometry()
        self.blank_rects = list(self.collapsed_margin_rects)
        for group in all_windows.iter_visible_groups():
            if (geom := group.geometry) is not None:
                self.blank_rects.extend(blank_rects_for_window(geom))

    def layout_docks(self, all_windows: WindowList) -> None:
        for dock, area in self.tab_dock_placements:
            self.layout_docked_group(dock, area)
        for group in all_windows.groups:
            if group.docks and (geom := group.allocated_geometry) is not None:
                self.dock_into_group(group, geom)

    def dock_into_group(self, owner: WindowGroup, geom: WindowGeometry) -> None:
        """
        Make room for the docks of owner within the area the layout gave it. The
        decorations the layout chose for owner are preserved.
        """
        content, placements = carve_docks(outer_region_of(geom), owner.docks, lgd.cell_width, lgd.cell_height)
        s, c = geom.spaces, geom.compensatory
        x = next(layout_dimension(content.left, content.width, lgd.cell_width, ((s.left - c.left, s.right - c.right),), alignment=lgd.alignment_x))
        y = next(layout_dimension(content.top, content.height, lgd.cell_height, ((s.top - c.top, s.bottom - c.bottom),), alignment=lgd.alignment_y))
        owner.set_content_geometry(window_geometry_from_layouts(x, y))
        for dock, area in placements:
            self.layout_docked_group(dock, area)

    def layout_docked_group(self, dock: WindowGroup, area: Region) -> None:
        xdecoration_pairs = ((dock.decoration('left'), dock.decoration('right')),)
        ydecoration_pairs = ((dock.decoration('top'), dock.decoration('bottom')),)
        x = next(layout_dimension(area.left, area.width, lgd.cell_width, xdecoration_pairs, alignment=lgd.alignment_x))
        y = next(layout_dimension(area.top, area.height, lgd.cell_height, ydecoration_pairs, alignment=lgd.alignment_y))
        dock.set_geometry(window_geometry_from_layouts(x, y))

    def layout_single_window_group(self, wg: WindowGroup) -> None:
        bw = 1 if self.must_draw_borders else 0
        xdecoration_pairs = (
            (
                wg.decoration('left', border_mult=bw, is_single_window=True),
                wg.decoration('right', border_mult=bw, is_single_window=True),
            ),
        )
        ydecoration_pairs = (
            (
                wg.decoration('top', border_mult=bw, is_single_window=True),
                wg.decoration('bottom', border_mult=bw, is_single_window=True),
            ),
        )
        wg.set_geometry(layout_single_window(xdecoration_pairs, ydecoration_pairs, xalignment=lgd.alignment_x, yalignment=lgd.alignment_y))

    def xlayout(
        self,
        groups: Iterator[WindowGroup],
        bias: None | Sequence[float] | dict[int, float] = None,
        start: int | None = None,
        size: int | None = None,
        offset: int = 0,
        border_mult: int = 1,
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (g.decoration('left', border_mult=border_mult), g.decoration('right', border_mult=border_mult)) for i, g in enumerate(groups) if i >= offset
        )
        if start is None:
            start = lgd.central.left
        if size is None:
            size = lgd.central.width
        return layout_dimension(start, size, lgd.cell_width, decoration_pairs, bias=bias, alignment=lgd.alignment_x)

    def ylayout(
        self,
        groups: Iterator[WindowGroup],
        bias: None | Sequence[float] | dict[int, float] = None,
        start: int | None = None,
        size: int | None = None,
        offset: int = 0,
        border_mult: int = 1,
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (g.decoration('top', border_mult=border_mult), g.decoration('bottom', border_mult=border_mult)) for i, g in enumerate(groups) if i >= offset
        )
        if start is None:
            start = lgd.central.top
        if size is None:
            size = lgd.central.height
        return layout_dimension(start, size, lgd.cell_height, decoration_pairs, bias=bias, alignment=lgd.alignment_y)

    def set_window_group_geometry(self, wg: WindowGroup, xl: LayoutData, yl: LayoutData) -> WindowGeometry:
        geom = window_geometry_from_layouts(xl, yl)
        wg.set_geometry(geom)
        return geom

    def do_layout(self, windows: WindowList) -> None:
        raise NotImplementedError()

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        return {}

    def compute_needs_borders_map(self, all_windows: WindowList) -> dict[int, bool]:
        return all_windows.compute_needs_borders_map(lgd.draw_active_borders)

    def get_minimal_borders(self, windows: WindowList) -> Iterator[BorderLine]:
        self._set_dimensions(windows)
        yield from self.minimal_borders(windows)
        if lgd.draw_minimal_borders:
            yield from self.dock_borders(windows)

    def dock_borders(self, windows: WindowList) -> Iterator[BorderLine]:
        "Borders on the inner edges of docked groups, separating them from the content they are docked to"
        needs_borders_map = windows.compute_needs_borders_map(lgd.draw_active_borders)
        active_group = windows.active_group
        for g in windows.iter_dock_groups(only_visible=True):
            if g.dock is None or (geom := g.geometry) is None or not (bw := g.effective_border()):
                continue
            outer = outer_region_of(geom)
            left, top, right, bottom = outer.left, outer.top, outer.left + outer.width, outer.top + outer.height
            edge = opposite_dock_edge[g.dock.edge]
            margin = max(0, g.decoration(edge) - bw - g.effective_padding(edge))
            wid = g.active_window_id
            # A positive window id means the border is on the right or bottom of the window
            match edge:
                case 'bottom':
                    edges, horizontal = Edges(left, bottom - margin - bw, right, bottom - margin), True
                case 'top':
                    edges, horizontal, wid = Edges(left, top + margin, right, top + margin + bw), True, -wid
                case 'right':
                    edges, horizontal = Edges(right - margin - bw, top, right - margin, bottom), False
                case _:
                    edges, horizontal, wid = Edges(left + margin, top, left + margin + bw, bottom), False, -wid
            color = BorderColor.inactive
            if needs_borders_map.get(g.id):
                color = BorderColor.active if g is active_group else BorderColor.bell
            yield BorderLine(edges, color, wid, horizontal)

    def minimal_borders(self, windows: WindowList) -> Iterator[BorderLine]:
        yield from ()

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> bool | None:
        pass

    def on_window_removed(self, all_windows: WindowList) -> bool:
        return False

    def layout_state(self) -> dict[str, Any]:
        return {}

    def set_layout_state(self, layout_state: dict[str, Any], map_group_id: WindowMapper) -> bool:
        return True

    def drag_resize_target_windows(
        self,
        click_window: WindowType,
        x: float,
        y: float,
        edges: int,
        all_windows: WindowList,
    ) -> WindowResizeDragData:
        return WindowResizeDragData(click_window.id, bool(edges & RIGHT_EDGE), click_window.id, bool(edges & BOTTOM_EDGE))

    def serialize(self, all_windows: WindowList) -> dict[str, Any]:
        ans = self.layout_state()
        ans['opts'] = self.layout_opts.serialized()
        ans['class'] = self.__class__.__name__
        ans['all_windows'] = all_windows.serialize_layout_state()
        return ans

    def unserialize(
        self,
        s: dict[str, Any],
        all_windows: WindowList,
        window_id_mapper: Callable[[WindowList], dict[int, int]] = create_window_id_map_for_unserialize,
        apply_to_window_list: bool = True,
    ) -> bool:
        """
        apply_to_window_list=False computes the group id mapping without changing the
        window list. Needed when restoring the state of more than one layout, since
        only the layout being made current should order the windows.
        """
        if s.get('class') != self.__class__.__name__:
            return False
        if 'all_windows' not in s:
            return False
        window_id_map = window_id_mapper(all_windows)
        m = all_windows.unserialize_layout_state(s['all_windows'], window_id_map, apply=apply_to_window_list)
        if m is None:
            return False
        return self.set_layout_state(s, m.get)
