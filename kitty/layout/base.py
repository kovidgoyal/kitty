#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial
from itertools import repeat
from typing import (
    Any, Dict, Generator, Iterable, Iterator, List, NamedTuple, Optional,
    Sequence, Tuple
)

from kitty.borders import BorderColor
from kitty.fast_data_types import (
    Region, set_active_window, viewport_for_window
)
from kitty.options_stub import Options
from kitty.types import Edges, WindowGeometry
from kitty.typing import TypedDict, WindowType
from kitty.window_list import WindowGroup, WindowList


class BorderLine(NamedTuple):
    edges: Edges = Edges()
    color: BorderColor = BorderColor.inactive


class LayoutOpts:

    def __init__(self, data: Dict[str, str]):
        pass


class LayoutData(NamedTuple):
    content_pos: int = 0
    cells_per_window: int = 0
    space_before: int = 0
    space_after: int = 0
    content_size: int = 0


DecorationPairs = Sequence[Tuple[int, int]]
LayoutDimension = Generator[LayoutData, None, None]
ListOfWindows = List[WindowType]


class NeighborsMap(TypedDict):
    left: List[int]
    top: List[int]
    right: List[int]
    bottom: List[int]


class LayoutGlobalData:
    draw_minimal_borders: bool = True
    draw_active_borders: bool = True
    align_top_left: bool = False

    central: Region = Region((0, 0, 199, 199, 200, 200))
    cell_width: int = 20
    cell_height: int = 20


lgd = LayoutGlobalData()


def idx_for_id(win_id: int, windows: Iterable[WindowType]) -> Optional[int]:
    for i, w in enumerate(windows):
        if w.id == win_id:
            return i


def set_layout_options(opts: Options) -> None:
    lgd.draw_minimal_borders = opts.draw_minimal_borders and sum(opts.window_margin_width) == 0
    lgd.draw_active_borders = opts.active_border_color is not None
    lgd.align_top_left = opts.placement_strategy == 'top-left'


def calculate_cells_map(bias: Optional[Sequence[float]], number_of_windows: int, number_of_cells: int) -> List[int]:
    cells_per_window = number_of_cells // number_of_windows
    if bias is not None and 1 < number_of_windows == len(bias) and cells_per_window > 5:
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
    start_at: int, length: int, cell_length: int,
    decoration_pairs: DecorationPairs,
    left_align: bool = False,
    bias: Optional[Sequence[float]] = None
) -> LayoutDimension:
    number_of_windows = len(decoration_pairs)
    number_of_cells = length // cell_length
    space_needed_for_decorations: int = sum(map(sum, decoration_pairs))
    extra = length - number_of_cells * cell_length
    while extra < space_needed_for_decorations:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    cells_map = calculate_cells_map(bias, number_of_windows, number_of_cells)
    assert sum(cells_map) == number_of_cells

    extra = length - number_of_cells * cell_length - space_needed_for_decorations
    pos = start_at
    if not left_align:
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
        yield LayoutData(pos, cells_per_window, before_space, after_space, content_size)
        pos += content_size + after_space


class Rect(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int


def blank_rects_for_window(wg: WindowGeometry) -> Generator[Rect, None, None]:
    left_width, right_width = wg.spaces.left, wg.spaces.right
    top_height, bottom_height = wg.spaces.top, wg.spaces.bottom
    if left_width > 0:
        yield Rect(wg.left - left_width, wg.top - top_height, wg.left, wg.bottom + bottom_height)
    if top_height > 0:
        yield Rect(wg.left, wg.top - top_height, wg.right + right_width, wg.top)
    if right_width > 0:
        yield Rect(wg.right, wg.top, wg.right + right_width, wg.bottom + bottom_height)
    if bottom_height > 0:
        yield Rect(wg.left, wg.bottom, wg.right, wg.bottom + bottom_height)


def window_geometry(xstart: int, xnum: int, ystart: int, ynum: int, left: int, top: int, right: int, bottom: int) -> WindowGeometry:
    return WindowGeometry(
        left=xstart, top=ystart, xnum=xnum, ynum=ynum,
        right=xstart + lgd.cell_width * xnum, bottom=ystart + lgd.cell_height * ynum,
        spaces=Edges(left, top, right, bottom)
    )


def window_geometry_from_layouts(x: LayoutData, y: LayoutData) -> WindowGeometry:
    return window_geometry(x.content_pos, x.cells_per_window, y.content_pos, y.cells_per_window, x.space_before, y.space_before, x.space_after, y.space_after)


def layout_single_window(xdecoration_pairs: DecorationPairs, ydecoration_pairs: DecorationPairs, left_align: bool = False) -> WindowGeometry:
    x = next(layout_dimension(lgd.central.left, lgd.central.width, lgd.cell_width, xdecoration_pairs, left_align=lgd.align_top_left))
    y = next(layout_dimension(lgd.central.top, lgd.central.height, lgd.cell_height, ydecoration_pairs, left_align=lgd.align_top_left))
    return window_geometry_from_layouts(x, y)


def safe_increment_bias(old_val: float, increment: float) -> float:
    return max(0.1, min(old_val + increment, 0.9))


def normalize_biases(biases: List[float]) -> List[float]:
    s = sum(biases)
    if s == 1:
        return biases
    return [x/s for x in biases]


def distribute_indexed_bias(base_bias: Sequence[float], index_bias_map: Dict[int, float]) -> Sequence[float]:
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


def variable_bias(num_windows: int, candidate: Dict[int, float]) -> Sequence[float]:
    return distribute_indexed_bias(list(repeat(1/(num_windows), num_windows)), candidate)


class Layout:

    name: Optional[str] = None
    needs_window_borders = True
    must_draw_borders = False  # can be overridden to customize behavior from kittens
    layout_opts = LayoutOpts({})
    only_active_window_visible = False

    def __init__(self, os_window_id: int, tab_id: int, layout_opts: str = '') -> None:
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.set_active_window_in_os_window = partial(set_active_window, os_window_id, tab_id)
        # A set of rectangles corresponding to the blank spaces at the edges of
        # this layout, i.e. spaces that are not covered by any window
        self.blank_rects: List[Rect] = []
        self.layout_opts = self.parse_layout_opts(layout_opts)
        assert self.name is not None
        self.full_name = self.name + ((':' + layout_opts) if layout_opts else '')
        self.remove_all_biases()

    def bias_increment_for_cell(self, is_horizontal: bool) -> float:
        self._set_dimensions()
        if is_horizontal:
            return (lgd.cell_width + 1) / lgd.central.width
        return (lgd.cell_height + 1) / lgd.central.height

    def apply_bias(self, window_id: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        return False

    def remove_all_biases(self) -> bool:
        return False

    def modify_size_of_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> bool:
        idx = all_windows.group_idx_for_window(window_id)
        if idx is None:
            return False
        return self.apply_bias(idx, increment, all_windows, is_horizontal)

    def parse_layout_opts(self, layout_opts: Optional[str] = None) -> LayoutOpts:
        data: Dict[str, str] = {}
        if layout_opts:
            for x in layout_opts.split(';'):
                k, v = x.partition('=')[::2]
                if k and v:
                    data[k] = v
        return type(self.layout_opts)(data)

    def nth_window(self, all_windows: WindowList, num: int) -> Optional[WindowType]:
        return all_windows.active_window_in_nth_group(num, clamp=True)

    def activate_nth_window(self, all_windows: WindowList, num: int) -> None:
        all_windows.set_active_group_idx(num)

    def next_window(self, all_windows: WindowList, delta: int = 1) -> None:
        all_windows.activate_next_window_group(delta)

    def neighbors(self, all_windows: WindowList) -> NeighborsMap:
        w = all_windows.active_window
        assert w is not None
        return self.neighbors_for_window(w, all_windows)

    def move_window(self, all_windows: WindowList, delta: int = 1) -> bool:
        if all_windows.num_groups < 2 or not delta:
            return False

        return all_windows.move_window_group(by=delta)

    def move_window_to_group(self, all_windows: WindowList, group: int) -> bool:
        return all_windows.move_window_group(to_group=group)

    def add_window(self, all_windows: WindowList, window: WindowType, location: Optional[str] = None, overlay_for: Optional[int] = None) -> None:
        if overlay_for is not None and overlay_for in all_windows:
            all_windows.add_window(window, group_of=overlay_for)
            return
        if location == 'neighbor':
            location = 'after'
        self.add_non_overlay_window(all_windows, window, location)

    def add_non_overlay_window(self, all_windows: WindowList, window: WindowType, location: Optional[str]) -> None:
        next_to: Optional[WindowType] = None
        before = False
        next_to = all_windows.active_window
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

    def update_visibility(self, all_windows: WindowList) -> None:
        active_window = all_windows.active_window
        for window, is_group_leader in all_windows.iter_windows_with_visibility():
            is_visible = window is active_window or (is_group_leader and not self.only_active_window_visible)
            window.set_visible_in_layout(is_visible)

    def _set_dimensions(self) -> None:
        lgd.central, tab_bar, vw, vh, lgd.cell_width, lgd.cell_height = viewport_for_window(self.os_window_id)

    def __call__(self, all_windows: WindowList) -> None:
        self._set_dimensions()
        self.update_visibility(all_windows)
        self.blank_rects = []
        self.do_layout(all_windows)

    def layout_single_window_group(self, wg: WindowGroup, add_blank_rects: bool = True) -> None:
        bw = 1 if self.must_draw_borders else 0
        xdecoration_pairs = ((
            wg.decoration('left', border_mult=bw, is_single_window=True),
            wg.decoration('right', border_mult=bw, is_single_window=True),
        ),)
        ydecoration_pairs = ((
            wg.decoration('top', border_mult=bw, is_single_window=True),
            wg.decoration('bottom', border_mult=bw, is_single_window=True),
        ),)
        geom = layout_single_window(xdecoration_pairs, ydecoration_pairs, left_align=lgd.align_top_left)
        wg.set_geometry(geom)
        if add_blank_rects and wg:
            self.blank_rects.extend(blank_rects_for_window(geom))

    def xlayout(
        self,
        groups: Iterator[WindowGroup],
        bias: Optional[Sequence[float]] = None,
        start: Optional[int] = None,
        size: Optional[int] = None,
        offset: int = 0,
        border_mult: int = 1
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (g.decoration('left', border_mult=border_mult), g.decoration('right', border_mult=border_mult)) for i, g in
            enumerate(groups) if i >= offset
        )
        if start is None:
            start = lgd.central.left
        if size is None:
            size = lgd.central.width
        return layout_dimension(start, size, lgd.cell_width, decoration_pairs, bias=bias, left_align=lgd.align_top_left)

    def ylayout(
        self,
        groups: Iterator[WindowGroup],
        bias: Optional[Sequence[float]] = None,
        start: Optional[int] = None,
        size: Optional[int] = None,
        offset: int = 0,
        border_mult: int = 1
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (g.decoration('top', border_mult=border_mult), g.decoration('bottom', border_mult=border_mult)) for i, g in
            enumerate(groups) if i >= offset
        )
        if start is None:
            start = lgd.central.top
        if size is None:
            size = lgd.central.height
        return layout_dimension(start, size, lgd.cell_height, decoration_pairs, bias=bias, left_align=lgd.align_top_left)

    def set_window_group_geometry(self, wg: WindowGroup, xl: LayoutData, yl: LayoutData) -> WindowGeometry:
        geom = window_geometry_from_layouts(xl, yl)
        wg.set_geometry(geom)
        self.blank_rects.extend(blank_rects_for_window(geom))
        return geom

    def do_layout(self, windows: WindowList) -> None:
        raise NotImplementedError()

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        return {'left': [], 'right': [], 'top': [], 'bottom': []}

    def compute_needs_borders_map(self, all_windows: WindowList) -> Dict[int, bool]:
        return all_windows.compute_needs_borders_map(lgd.draw_active_borders)

    def get_minimal_borders(self, windows: WindowList) -> Generator[BorderLine, None, None]:
        self._set_dimensions()
        yield from self.minimal_borders(windows)

    def minimal_borders(self, windows: WindowList) -> Generator[BorderLine, None, None]:
        return
        yield BorderLine()  # type: ignore

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList) -> Optional[bool]:
        pass

    def layout_state(self) -> Dict[str, Any]:
        return {}
