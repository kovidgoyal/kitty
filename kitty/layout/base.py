#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from functools import partial
from itertools import repeat
from typing import (
    Dict, FrozenSet, Generator, Iterable, List, NamedTuple, Optional, Sequence,
    Tuple, Union, cast
)

from kitty.constants import Edges, WindowGeometry
from kitty.fast_data_types import (
    Region, set_active_window, swap_windows, viewport_for_window
)
from kitty.options_stub import Options
from kitty.typing import TypedDict, WindowType
from kitty.window_list import WindowList


class Borders(NamedTuple):
    left: bool
    top: bool
    right: bool
    bottom: bool


class LayoutOpts:

    def __init__(self, data: Dict[str, str]):
        pass


class LayoutData(NamedTuple):
    content_pos: int
    cells_per_window: int
    space_before: int
    space_after: int
    content_size: int


all_borders = Borders(True, True, True, True)
no_borders = Borders(False, False, False, False)
DecorationPairs = Sequence[Tuple[int, int]]
LayoutDimension = Generator[LayoutData, None, None]
ListOfWindows = List[WindowType]


class InternalNeighborsMap(TypedDict):
    left: List[int]
    top: List[int]
    right: List[int]
    bottom: List[int]


class NeighborsMap(TypedDict):
    left: Tuple[int, ...]
    top: Tuple[int, ...]
    right: Tuple[int, ...]
    bottom: Tuple[int, ...]


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
    needs_all_windows = False
    layout_opts = LayoutOpts({})
    only_active_window_visible = False

    def __init__(self, os_window_id: int, tab_id: int, layout_opts: str = '') -> None:
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.set_active_window_in_os_window = partial(set_active_window, os_window_id, tab_id)
        self.swap_windows_in_os_window = partial(swap_windows, os_window_id, tab_id)
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

    def apply_bias(self, idx: int, increment: float, top_level_windows: ListOfWindows, is_horizontal: bool = True) -> bool:
        return False

    def remove_all_biases(self) -> bool:
        return False

    def modify_size_of_window(self, all_windows: WindowList, window_id: int, increment: float, is_horizontal: bool = True) -> bool:
        idx = all_windows.idx_for_window(window_id)
        if idx is None:
            return False
        return self.apply_bias(idx, increment, list(all_windows.iter_top_level_windows()), is_horizontal)

    def parse_layout_opts(self, layout_opts: Optional[str] = None) -> LayoutOpts:
        data: Dict[str, str] = {}
        if layout_opts:
            for x in layout_opts.split(';'):
                k, v = x.partition('=')[::2]
                if k and v:
                    data[k] = v
        return type(self.layout_opts)(data)

    def nth_window(self, all_windows: WindowList, num: int) -> Optional[WindowType]:
        return all_windows.active_window_for_idx(num, clamp=True)

    def activate_nth_window(self, all_windows: WindowList, num: int) -> int:
        w = self.nth_window(all_windows, num)
        assert w is not None
        active_window_idx = all_windows.idx_for_window(w)
        assert active_window_idx is not None
        return self.set_active_window(all_windows, active_window_idx)

    def next_window(self, all_windows: WindowList, active_window_idx: int, delta: int = 1) -> int:
        w = self.nth_window(all_windows, active_window_idx)
        assert w is not None
        idx = all_windows.idx_for_window(w)
        assert idx is not None
        num_slots = all_windows.max_active_idx + 1
        aidx = (idx + num_slots + delta) % num_slots
        return self.set_active_window(all_windows, aidx)

    def neighbors(self, all_windows: WindowList, active_window_idx: int) -> NeighborsMap:
        w = all_windows.active_window_for_idx(active_window_idx)
        assert w is not None
        n = self.neighbors_for_window(w, all_windows)

        def as_indices(windows: Iterable[int]) -> Generator[int, None, None]:
            for w in windows:
                idx = all_windows.idx_for_window(w)
                if idx is not None:
                    yield idx

        ans: NeighborsMap = {
            'left': tuple(as_indices(n['left'])),
            'top': tuple(as_indices(n['top'])),
            'right': tuple(as_indices(n['right'])),
            'bottom': tuple(as_indices(n['bottom']))
        }
        return ans

    def move_window(self, all_windows: WindowList, active_window_idx: int, delta: Union[str, int] = 1) -> int:
        # delta can be either a number or a string such as 'left', 'top', etc
        # for neighborhood moves
        if len(windows) < 2 or not delta:
            return active_window_idx
        wgd = WindowGroupingData(all_windows)
        w = wgd.base_window_for_idx(active_window_idx)
        if w is None:
            return active_window_idx

        idx = idx_for_id(w.id, windows)
        if idx is None and w.overlay_window_id is not None:
            idx = idx_for_id(w.overlay_window_id, windows)
        assert idx is not None
        if isinstance(delta, int):
            nidx = (idx + len(windows) + delta) % len(windows)
        else:
            delta = delta.lower()
            delta = {'up': 'top', 'down': 'bottom'}.get(delta, delta)
            neighbors = self.neighbors_for_window(w, all_windows if self.needs_all_windows else windows)
            q = cast(WindowList, neighbors.get(cast(str, delta), ()))
            if not q:
                return active_window_idx
            w = q[0]
            qidx = idx_for_id(getattr(w, 'id', w), windows)
            assert qidx is not None
            nidx = qidx

        nw = windows[nidx]
        qidx = idx_for_id(nw.id, all_windows)
        assert qidx is not None
        nidx = qidx
        idx = active_window_idx
        self.swap_windows_in_layout(all_windows, nidx, idx)
        self.swap_windows_in_os_window(nidx, idx)
        return self.set_active_window(all_windows, nidx)

    def swap_windows_in_layout(self, all_windows: WindowList, a: int, b: int) -> None:
        all_windows[a], all_windows[b] = all_windows[b], all_windows[a]

    def add_window(self, all_windows: WindowList, window: WindowType, current_active_window_idx: int, location: Optional[str] = None) -> int:
        active_window_idx = None
        if window.overlay_for is not None:
            i = idx_for_id(window.overlay_for, all_windows)
            if i is not None:
                # put the overlay window in the position occupied by the
                # overlaid window and move the overlaid window to the end
                self.swap_windows_in_os_window(len(all_windows), i)
                all_windows.append(all_windows[i])
                all_windows[i] = window
                active_window_idx = i
        if active_window_idx is None:
            if location == 'neighbor':
                location = 'after'
            active_window_idx = self.do_add_window(all_windows, window, current_active_window_idx, location)

        self(all_windows, active_window_idx)
        self.set_active_window_in_os_window(active_window_idx)
        return active_window_idx

    def do_add_window(self, all_windows: WindowList, window: WindowType, current_active_window_idx: Optional[int], location: Optional[str]) -> int:
        active_window_idx = None
        if location is not None:
            if location in ('after', 'vsplit', 'hsplit') and current_active_window_idx is not None and len(all_windows) > 1:
                active_window_idx = min(current_active_window_idx + 1, len(all_windows))
            elif location == 'before' and current_active_window_idx is not None and len(all_windows) > 1:
                active_window_idx = current_active_window_idx
            elif location == 'first':
                active_window_idx = 0
            if active_window_idx is not None:
                for i in range(len(all_windows), active_window_idx, -1):
                    self.swap_windows_in_os_window(i, i - 1)
                all_windows.insert(active_window_idx, window)

        if active_window_idx is None:
            active_window_idx = len(all_windows)
            all_windows.append(window)
        return active_window_idx

    def remove_window(self, all_windows: WindowList, window: WindowType, current_active_window_idx: int, swapped: bool = False) -> int:
        try:
            active_window = all_windows[current_active_window_idx]
        except Exception:
            active_window = window
        if not swapped and window.overlay_for is not None:
            nidx = idx_for_id(window.overlay_for, all_windows)
            if nidx is not None:
                idx = all_windows.index(window)
                all_windows[nidx], all_windows[idx] = all_windows[idx], all_windows[nidx]
                self.swap_windows_in_os_window(nidx, idx)
                return self.remove_window(all_windows, window, current_active_window_idx, swapped=True)

        position = all_windows.index(window)
        del all_windows[position]
        active_window_idx = None
        if window.overlay_for is not None:
            i = idx_for_id(window.overlay_for, all_windows)
            if i is not None:
                overlaid_window = all_windows[i]
                overlaid_window.overlay_window_id = None
                if active_window is window:
                    active_window = overlaid_window
                    active_window_idx = idx_for_id(active_window.id, all_windows)
        if active_window_idx is None:
            if active_window is window:
                active_window_idx = max(0, min(current_active_window_idx, len(all_windows) - 1))
            else:
                active_window_idx = idx_for_id(active_window.id, all_windows)
                assert active_window_idx is not None
        if all_windows:
            self(all_windows, active_window_idx)
        return self.set_active_window(all_windows, active_window_idx)

    def update_visibility(self, all_windows: WindowList, active_window: WindowType, overlaid_windows: Optional[FrozenSet[WindowType]] = None) -> None:
        if overlaid_windows is None:
            overlaid_windows = process_overlaid_windows(all_windows)[0]
        for i, w in enumerate(all_windows):
            w.set_visible_in_layout(i, w is active_window or (not self.only_active_window_visible and w not in overlaid_windows))

    def set_active_window(self, all_windows: WindowList, active_window_idx: int) -> int:
        if not all_windows:
            self.set_active_window_in_os_window(0)
            return 0
        w = all_windows[active_window_idx]
        if w.overlay_window_id is not None:
            i = idx_for_id(w.overlay_window_id, all_windows)
            if i is not None:
                active_window_idx = i
        self.update_visibility(all_windows, all_windows[active_window_idx])
        self.set_active_window_in_os_window(active_window_idx)
        return active_window_idx

    def _set_dimensions(self) -> None:
        lgd.central, tab_bar, vw, vh, lgd.cell_width, lgd.cell_height = viewport_for_window(self.os_window_id)

    def __call__(self, all_windows: WindowList, active_window_idx: int) -> int:
        self._set_dimensions()
        active_window = all_windows[active_window_idx]
        overlaid_windows, windows = process_overlaid_windows(all_windows)
        if overlaid_windows:
            windows = [w for w in all_windows if w not in overlaid_windows]
            q = idx_for_id(active_window.id, windows)
            if q is None:
                if active_window.overlay_window_id is not None:
                    active_window_idx = idx_for_id(active_window.overlay_window_id, windows) or 0
                else:
                    active_window_idx = 0
            else:
                active_window_idx = q
            active_window = windows[active_window_idx]
        else:
            windows = all_windows
        self.update_visibility(all_windows, active_window, overlaid_windows)
        self.blank_rects = []
        if self.needs_all_windows:
            self.do_layout_all_windows(windows, active_window_idx, all_windows)
        else:
            self.do_layout(windows, active_window_idx)
        return cast(int, idx_for_id(active_window.id, all_windows))

    # Utils {{{

    def layout_single_window(self, w: WindowType, return_geometry: bool = False, left_align: bool = False) -> Optional[WindowGeometry]:
        bw = w.effective_border() if self.must_draw_borders else 0
        xdecoration_pairs = ((
            w.effective_padding('left') + w.effective_margin('left', is_single_window=True) + bw,
            w.effective_padding('right') + w.effective_margin('right', is_single_window=True) + bw,
        ),)
        ydecoration_pairs = ((
            w.effective_padding('top') + w.effective_margin('top', is_single_window=True) + bw,
            w.effective_padding('bottom') + w.effective_margin('bottom', is_single_window=True) + bw,
        ),)
        wg = layout_single_window(xdecoration_pairs, ydecoration_pairs, left_align=left_align)
        if return_geometry:
            return wg
        w.set_geometry(0, wg)
        self.blank_rects = list(blank_rects_for_window(wg))
        return None

    def xlayout(
        self,
        windows: WindowList,
        bias: Optional[Sequence[float]] = None,
        start: Optional[int] = None,
        size: Optional[int] = None
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (
                w.effective_margin('left') + w.effective_border() + w.effective_padding('left'),
                w.effective_margin('right') + w.effective_border() + w.effective_padding('right'),
            ) for w in windows
        )
        if start is None:
            start = lgd.central.left
        if size is None:
            size = lgd.central.width
        return layout_dimension(start, size, lgd.cell_width, decoration_pairs, bias=bias, left_align=lgd.align_top_left)

    def ylayout(
        self,
        windows: WindowList,
        bias: Optional[Sequence[float]] = None,
        start: Optional[int] = None,
        size: Optional[int] = None
    ) -> LayoutDimension:
        decoration_pairs = tuple(
            (
                w.effective_margin('top') + w.effective_border() + w.effective_padding('top'),
                w.effective_margin('bottom') + w.effective_border() + w.effective_padding('bottom'),
            ) for w in windows
        )
        if start is None:
            start = lgd.central.top
        if size is None:
            size = lgd.central.height
        return layout_dimension(start, size, lgd.cell_height, decoration_pairs, bias=bias, left_align=lgd.align_top_left)

    def set_window_geometry(self, w: WindowType, idx: int, xl: LayoutData, yl: LayoutData) -> None:
        wg = window_geometry_from_layouts(xl, yl)
        w.set_geometry(idx, wg)
        self.blank_rects.extend(blank_rects_for_window(wg))

    # }}}

    def do_layout(self, windows: WindowList, active_window_idx: int) -> None:
        raise NotImplementedError()

    def do_layout_all_windows(self, windows: WindowList, active_window_idx: int, all_windows: WindowList) -> None:
        raise NotImplementedError()

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> InternalNeighborsMap:
        return {'left': [], 'right': [], 'top': [], 'bottom': []}

    def compute_needs_borders_map(self, windows: WindowList, active_window: Optional[WindowType]) -> Dict[int, bool]:
        return {w.id: ((w is active_window and lgd.draw_active_borders) or w.needs_attention) for w in windows}

    def resolve_borders(self, windows: WindowList, active_window: Optional[WindowType]) -> Generator[Borders, None, None]:
        if lgd.draw_minimal_borders:
            needs_borders_map = self.compute_needs_borders_map(windows, active_window)
            yield from self.minimal_borders(windows, active_window, needs_borders_map)
        else:
            yield from Layout.minimal_borders(self, windows, active_window, {})

    def window_independent_borders(self, windows: WindowList, active_window: Optional[WindowType] = None) -> Generator[Edges, None, None]:
        return
        yield Edges()  # type: ignore

    def minimal_borders(self, windows: WindowList, active_window: Optional[WindowType], needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        for w in windows:
            if w is not active_window or lgd.draw_active_borders or w.needs_attention:
                yield all_borders
            else:
                yield no_borders

    def layout_action(self, action_name: str, args: Sequence[str], all_windows: WindowList, active_window_idx: int) -> Optional[Union[bool, int]]:
        pass
