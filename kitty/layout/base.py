#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from enum import Enum
from functools import partial
from itertools import repeat
from typing import Any, ClassVar, NamedTuple, cast

from kitty.borders import BorderColor
from kitty.fast_data_types import BOTTOM_EDGE, RIGHT_EDGE, Region, get_options, set_active_window, viewport_for_window
from kitty.options.types import Options
from kitty.types import Edges, NeighborsMap, WindowGeometry, WindowMapper, WindowResizeDragData
from kitty.typing_compat import WindowType
from kitty.window_list import WindowGroup, WindowList

from .constraints import FixedConstraintModel, FixedSize, LinearConstraintModel


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
CellBias = None | Sequence[float] | dict[int, float]
CellAllocator = Callable[[CellBias, int, int], list[int]]


def region(left: int, top: int, width: int, height: int) -> Region:
    width, height = max(0, width), max(0, height)
    return Region((left, top, left + width - 1, top + height - 1, width, height))


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


def calculate_cells_map(bias: CellBias, number_of_windows: int, number_of_cells: int) -> list[int]:
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
    start_at: int,
    length: int,
    cell_length: int,
    decoration_pairs: DecorationPairs,
    alignment: int = 0,
    bias: CellBias = None,
    cell_allocator: CellAllocator = calculate_cells_map,
) -> LayoutDimension:
    number_of_windows = len(decoration_pairs)
    number_of_cells = max(0, length // cell_length)
    dec_vals: Iterable[int] = map(sum, decoration_pairs)
    space_needed_for_decorations = sum(dec_vals)
    extra = length - number_of_cells * cell_length
    while extra < space_needed_for_decorations and number_of_cells > 0:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    cells_map = cell_allocator(bias, number_of_windows, number_of_cells) if number_of_cells > 0 else [0] * number_of_windows
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
    x_cell_allocator: CellAllocator = calculate_cells_map,
    y_cell_allocator: CellAllocator = calculate_cells_map,
) -> WindowGeometry:
    x = next(layout_dimension(lgd.central.left, lgd.central.width, lgd.cell_width, xdecoration_pairs, alignment=xalignment, cell_allocator=x_cell_allocator))
    y = next(layout_dimension(lgd.central.top, lgd.central.height, lgd.cell_height, ydecoration_pairs, alignment=yalignment, cell_allocator=y_cell_allocator))
    return window_geometry_from_layouts(x, y)


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
        self.layout_opts = self.parse_layout_opts(layout_opts)
        assert self.name is not None
        self.full_name = f'{self.name}:{layout_opts}' if layout_opts else self.name
        self.remove_all_biases()
        self._dock_constraint_models: dict[tuple[int, str], FixedConstraintModel] = {}
        self._dock_x_constraint_model = LinearConstraintModel()
        self._dock_y_constraint_model = LinearConstraintModel()
        self._full_central = lgd.central
        self._tab_dock_regions: dict[int, Region] = {}

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
            return (lgd.cell_width + 1) / max(1, lgd.central.width)
        return (lgd.cell_height + 1) / max(1, lgd.central.height)

    def apply_bias(self, window_id: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        return False

    def remove_all_biases(self) -> bool:
        return False

    def modify_size_of_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> bool:
        idx = all_windows.main_group_idx_for_window(window_id)
        if idx is None or not increment:
            return False
        return self.apply_bias(idx, increment, all_windows, is_horizontal)

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
        if window := all_windows.active_window_in_nth_group(num, clamp=True):
            all_windows.set_active_window_group_for(window)

    def next_window(self, all_windows: WindowList, delta: int = 1) -> None:
        all_windows.activate_next_window_group(delta)

    def neighbors(self, all_windows: WindowList) -> NeighborsMap:
        w = all_windows.active_window
        assert w is not None
        return self.neighbors_for_window_with_docks(w, all_windows)

    def neighbors_for_window_with_docks(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        source_group = all_windows.group_for_window(window)
        if source_group is None:
            return {}
        dock = source_group.dock_data
        if dock is not None:
            if not dock.focusable or not source_group.is_visible_in_layout:
                return {}
            return self._geometry_neighbors(window, all_windows)
        if source_group.is_visible_in_layout and any(
            group.dock_data and group.dock_data.focusable for group in all_windows.iter_dock_groups(only_visible=True)
        ):
            return self._geometry_neighbors(window, all_windows)
        return self.neighbors_for_window(window, all_windows)

    def _geometry_neighbors(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        source_group = all_windows.group_for_window(window)
        if source_group is None or source_group.geometry is None:
            return {}

        def bounds(group: WindowGroup) -> tuple[int, int, int, int]:
            geom = group.geometry
            assert geom is not None
            return (
                geom.left - geom.spaces.left,
                geom.top - geom.spaces.top,
                geom.right + geom.spaces.right,
                geom.bottom + geom.spaces.bottom,
            )

        left, top, right, bottom = bounds(source_group)
        sx, sy = (left + right) / 2, (top + bottom) / 2
        candidates: dict[str, list[tuple[float, float, int]]] = {'left': [], 'top': [], 'right': [], 'bottom': []}
        for group in all_windows.iter_all_layoutable_groups(only_visible=True, include_docks=True):
            dock = group.dock_data
            if group is source_group or (dock is not None and not dock.focusable) or group.geometry is None:
                continue
            cleft, ctop, cright, cbottom = bounds(group)
            cx, cy = (cleft + cright) / 2, (ctop + cbottom) / 2
            if cright <= left:
                candidates['left'].append((left - cright, abs(cy - sy), group.id))
            if cbottom <= top:
                candidates['top'].append((top - cbottom, abs(cx - sx), group.id))
            if cleft >= right:
                candidates['right'].append((cleft - right, abs(cy - sy), group.id))
            if ctop >= bottom:
                candidates['bottom'].append((ctop - bottom, abs(cx - sx), group.id))
        ans: NeighborsMap = {}
        if items := candidates['left']:
            ans['left'] = [item[2] for item in sorted(items)]
        if items := candidates['top']:
            ans['top'] = [item[2] for item in sorted(items)]
        if items := candidates['right']:
            ans['right'] = [item[2] for item in sorted(items)]
        if items := candidates['bottom']:
            ans['bottom'] = [item[2] for item in sorted(items)]
        return ans

    def move_window(self, all_windows: WindowList, delta: int = 1) -> bool:
        if all_windows.num_main_groups < 2 or not delta or (all_windows.active_group and all_windows.active_group.dock_data):
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
        if src_wg is None or dest_wg is None or src_wg.id == dest_wg.id or src_wg.dock_data or dest_wg.dock_data:
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
    ) -> WindowType | None:
        dock = getattr(window, 'dock_data', None)
        if overlay_for is not None and dock is None:
            underlay = all_windows.id_map.get(overlay_for)
            if underlay is not None:
                window.margin, window.padding = underlay.margin.copy(), underlay.padding.copy()
                if group := all_windows.group_for_window(underlay):
                    window.dock_data = group.dock_data
                all_windows.add_window(window, group_of=overlay_for, head_of_group=put_overlay_behind)
                return underlay
        if dock is not None:
            all_windows.add_window(window, make_active=dock.focusable)
            return None
        if location == 'neighbor':
            location = 'after'
        self.add_non_overlay_window(all_windows, window, location, bias, next_to)
        return None

    def add_non_overlay_window(
        self, all_windows: WindowList, window: WindowType, location: str | None, bias: float | None = None, next_to: WindowType | None = None
    ) -> None:
        before = False
        if next_to is None or all_windows.is_docked(next_to):
            next_to = all_windows.active_main_window
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
            idx = all_windows.main_group_idx_for_window(window)
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
        active_main_window = all_windows.active_main_window
        for group in all_windows.iter_main_groups():
            for window in group:
                is_visible = window is active_main_window or (window.id == group.active_window_id and not self.only_active_window_visible)
                window.set_visible_in_layout(is_visible)
        for group in all_windows.iter_dock_groups():
            dock = group.dock_data
            is_visible = bool(dock and dock.scope == 'tab')
            if dock and dock.scope == 'window':
                owner = all_windows.group_for_window(dock.owner_window_id)
                is_visible = bool(owner and owner.is_visible_in_layout)
            for window in group:
                window.set_visible_in_layout(is_visible and window.id == group.active_window_id)

    def _dock_constraint_model(self, owner_group_id: int, axis: str) -> FixedConstraintModel:
        # Keep one model per tab/owner axis. Its size-specification signature
        # handles dock changes, while viewport changes use its edit variable.
        key = owner_group_id, axis
        ans = self._dock_constraint_models.get(key)
        if ans is None:
            self._dock_constraint_models[key] = ans = FixedConstraintModel()
        return ans

    def _dock_size(self, group: WindowGroup) -> FixedSize:
        dock = group.dock_data
        assert dock is not None
        if dock.size_unit == 'percent':
            return FixedSize(fraction=float(dock.size) / 100)
        if dock.edge in ('top', 'bottom'):
            return FixedSize(
                int(dock.size) * lgd.cell_height + group.decoration('top', is_single_window=True) + group.decoration('bottom', is_single_window=True)
            )
        return FixedSize(int(dock.size) * lgd.cell_width + group.decoration('left', is_single_window=True) + group.decoration('right', is_single_window=True))

    def _allocate_dock_regions(self, groups: Sequence[WindowGroup], area: Region, owner_group_id: int) -> tuple[Region, dict[int, Region]]:
        ans: dict[int, Region] = {}
        vertical = tuple(g for g in groups if g.dock_data and g.dock_data.edge in ('top', 'bottom'))
        sizes, remaining_height = self._dock_constraint_model(owner_group_id, 'vertical')(area.height, tuple(map(self._dock_size, vertical)))
        top, bottom = area.top, area.top + area.height
        for group, size in zip(vertical, sizes):
            if group.dock_data and group.dock_data.edge == 'top':
                ans[group.id] = region(area.left, top, area.width, size)
                top += size
            else:
                bottom -= size
                ans[group.id] = region(area.left, bottom, area.width, size)
        content = region(area.left, top, area.width, remaining_height)

        horizontal = tuple(g for g in groups if g.dock_data and g.dock_data.edge in ('left', 'right'))
        sizes, remaining_width = self._dock_constraint_model(owner_group_id, 'horizontal')(content.width, tuple(map(self._dock_size, horizontal)))
        left, right = content.left, content.left + content.width
        for group, size in zip(horizontal, sizes):
            if group.dock_data and group.dock_data.edge == 'left':
                ans[group.id] = region(left, content.top, size, content.height)
                left += size
            else:
                right -= size
                ans[group.id] = region(right, content.top, size, content.height)
        return region(left, content.top, remaining_width, content.height), ans

    def _calculate_tab_dock_regions(self, all_windows: WindowList) -> Region:
        groups = tuple(g for g in all_windows.iter_dock_groups() if g.dock_data and g.dock_data.scope == 'tab')
        content, self._tab_dock_regions = self._allocate_dock_regions(groups, self._full_central, 0)
        return content

    def _layout_group_in_region(self, group: WindowGroup, area: Region) -> None:
        xdecoration_pairs = ((group.decoration('left', is_single_window=True), group.decoration('right', is_single_window=True)),)
        ydecoration_pairs = ((group.decoration('top', is_single_window=True), group.decoration('bottom', is_single_window=True)),)
        x = next(
            layout_dimension(
                area.left,
                area.width,
                lgd.cell_width,
                xdecoration_pairs,
                alignment=lgd.alignment_x,
                cell_allocator=self._dock_x_constraint_model,
            )
        )
        y = next(
            layout_dimension(
                area.top,
                area.height,
                lgd.cell_height,
                ydecoration_pairs,
                alignment=lgd.alignment_y,
                cell_allocator=self._dock_y_constraint_model,
            )
        )
        group.set_geometry(window_geometry_from_layouts(x, y))

    def _layout_tab_docks(self, all_windows: WindowList) -> None:
        for group in all_windows.iter_dock_groups(only_visible=True):
            if area := self._tab_dock_regions.get(group.id):
                self._layout_group_in_region(group, area)

    def _layout_window_docks(self, all_windows: WindowList) -> None:
        visible_docks = tuple(all_windows.iter_dock_groups(only_visible=True))
        for owner in all_windows.iter_main_groups(only_visible=True):
            owner_docks = tuple(
                group
                for group in visible_docks
                if (dock := group.dock_data) and dock.scope == 'window' and all_windows.group_for_window(dock.owner_window_id) is owner
            )
            geom = owner.geometry
            if not owner_docks or geom is None:
                continue
            area = region(
                geom.left - geom.spaces.left,
                geom.top - geom.spaces.top,
                geom.right - geom.left + geom.spaces.left + geom.spaces.right,
                geom.bottom - geom.top + geom.spaces.top + geom.spaces.bottom,
            )
            content, dock_regions = self._allocate_dock_regions(owner_docks, area, owner.id)
            self._layout_group_in_region(owner, content)
            for group in owner_docks:
                self._layout_group_in_region(group, dock_regions[group.id])

    def _set_dimensions(self, all_windows: WindowList) -> None:
        self._full_central, tab_bar, vw, vh, lgd.cell_width, lgd.cell_height = viewport_for_window(self.os_window_id)
        lgd.central = self._calculate_tab_dock_regions(all_windows)
        # Update lgd.draw_minimal_borders based on the current number of visible windows
        # and the draw_window_borders_for_single_window option
        opts = get_options()
        lgd.draw_minimal_borders = effective_draw_minimal_borders(opts, all_windows.has_more_than_one_visible_group)

    def __call__(self, all_windows: WindowList) -> None:
        self._set_dimensions(all_windows)
        self.update_visibility(all_windows)
        self.blank_rects = []
        # Set show_title_bar flag on each visible window before layout
        min_windows = get_options().window_title_bar_min_windows
        visible_groups = tuple(all_windows.iter_all_layoutable_groups(only_visible=True, include_docks=True))
        force_show = all_windows.force_show_title_bars
        show_title_bar = force_show or (min_windows > 0 and len(visible_groups) >= min_windows)
        for wg in visible_groups:
            for w in wg.windows:
                w.show_title_bar = show_title_bar
        if all_windows.num_main_groups:
            self.do_layout(all_windows)
        self._layout_tab_docks(all_windows)
        self._layout_window_docks(all_windows)
        self.blank_rects = []
        for group in all_windows.iter_all_layoutable_groups(only_visible=True, include_docks=True):
            if geom := group.geometry:
                self.blank_rects.extend(blank_rects_for_window(geom))

    def layout_single_window_group(
        self,
        wg: WindowGroup,
        add_blank_rects: bool = True,
        x_cell_allocator: CellAllocator = calculate_cells_map,
        y_cell_allocator: CellAllocator = calculate_cells_map,
    ) -> None:
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
        geom = layout_single_window(
            xdecoration_pairs,
            ydecoration_pairs,
            xalignment=lgd.alignment_x,
            yalignment=lgd.alignment_y,
            x_cell_allocator=x_cell_allocator,
            y_cell_allocator=y_cell_allocator,
        )
        wg.set_geometry(geom)
        if add_blank_rects:
            self.blank_rects.extend(blank_rects_for_window(geom))

    def xlayout(
        self,
        groups: Iterator[WindowGroup],
        bias: CellBias = None,
        start: int | None = None,
        size: int | None = None,
        offset: int = 0,
        border_mult: int = 1,
        cell_allocator: CellAllocator = calculate_cells_map,
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (g.decoration('left', border_mult=border_mult), g.decoration('right', border_mult=border_mult)) for i, g in enumerate(groups) if i >= offset
        )
        if start is None:
            start = lgd.central.left
        if size is None:
            size = lgd.central.width
        return layout_dimension(start, size, lgd.cell_width, decoration_pairs, bias=bias, alignment=lgd.alignment_x, cell_allocator=cell_allocator)

    def ylayout(
        self,
        groups: Iterator[WindowGroup],
        bias: CellBias = None,
        start: int | None = None,
        size: int | None = None,
        offset: int = 0,
        border_mult: int = 1,
        cell_allocator: CellAllocator = calculate_cells_map,
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (g.decoration('top', border_mult=border_mult), g.decoration('bottom', border_mult=border_mult)) for i, g in enumerate(groups) if i >= offset
        )
        if start is None:
            start = lgd.central.top
        if size is None:
            size = lgd.central.height
        return layout_dimension(start, size, lgd.cell_height, decoration_pairs, bias=bias, alignment=lgd.alignment_y, cell_allocator=cell_allocator)

    def set_window_group_geometry(self, wg: WindowGroup, xl: LayoutData, yl: LayoutData) -> WindowGeometry:
        geom = window_geometry_from_layouts(xl, yl)
        wg.set_geometry(geom)
        self.blank_rects.extend(blank_rects_for_window(geom))
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
        if not lgd.draw_minimal_borders:
            return
        active_group = windows.active_group
        needs_borders_map = windows.compute_needs_borders_map(lgd.draw_active_borders)
        for group in windows.iter_dock_groups(only_visible=True):
            geom, dock = group.geometry, group.dock_data
            if geom is None or dock is None or not (bw := group.effective_border()):
                continue
            left = geom.left - geom.spaces.left
            top = geom.top - geom.spaces.top
            right = geom.right + geom.spaces.right
            bottom = geom.bottom + geom.spaces.bottom
            if dock.edge == 'top':
                edges, horizontal, window_id = Edges(left, bottom - bw, right, bottom), True, group.active_window_id
            elif dock.edge == 'bottom':
                edges, horizontal, window_id = Edges(left, top, right, top + bw), True, -group.active_window_id
            elif dock.edge == 'left':
                edges, horizontal, window_id = Edges(right - bw, top, right, bottom), False, group.active_window_id
            else:
                edges, horizontal, window_id = Edges(left, top, left + bw, bottom), False, -group.active_window_id
            color = BorderColor.inactive
            if needs_borders_map.get(group.id):
                color = BorderColor.active if group is active_group else BorderColor.bell
            yield BorderLine(edges, color, window_id, horizontal)

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
