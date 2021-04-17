#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache
from itertools import repeat
from math import ceil, floor
from typing import (
    Any, Callable, Dict, Generator, List, Optional, Sequence, Set, Tuple
)

from kitty.borders import BorderColor
from kitty.types import Edges
from kitty.typing import WindowType
from kitty.window_list import WindowGroup, WindowList

from .base import (
    BorderLine, Layout, LayoutData, LayoutDimension, ListOfWindows,
    NeighborsMap, layout_dimension, lgd, variable_bias
)
from .tall import neighbors_for_tall_window


@lru_cache()
def calc_grid_size(n: int) -> Tuple[int, int, int, int]:
    if n <= 5:
        ncols = 1 if n == 1 else 2
    else:
        for ncols in range(3, (n // 2) + 1):
            if ncols * ncols >= n:
                break
    nrows = n // ncols
    special_rows = n - (nrows * (ncols - 1))
    special_col = 0 if special_rows < nrows else ncols - 1
    return ncols, nrows, special_rows, special_col


class Grid(Layout):

    name = 'grid'
    no_minimal_window_borders = True

    def remove_all_biases(self) -> bool:
        self.biased_rows: Dict[int, float] = {}
        self.biased_cols: Dict[int, float] = {}
        return True

    def column_layout(
        self,
        num: int,
        bias: Optional[Sequence[float]] = None,
    ) -> LayoutDimension:
        decoration_pairs = tuple(repeat((0, 0), num))
        return layout_dimension(lgd.central.left, lgd.central.width, lgd.cell_width, decoration_pairs, bias=bias, left_align=lgd.align_top_left)

    def row_layout(
        self,
        num: int,
        bias: Optional[Sequence[float]] = None,
    ) -> LayoutDimension:
        decoration_pairs = tuple(repeat((0, 0), num))
        return layout_dimension(lgd.central.top, lgd.central.height, lgd.cell_height, decoration_pairs, bias=bias, left_align=lgd.align_top_left)

    def variable_layout(self, layout_func: Callable[..., LayoutDimension], num_windows: int, biased_map: Dict[int, float]) -> LayoutDimension:
        return layout_func(num_windows, bias=variable_bias(num_windows, biased_map) if num_windows > 1 else None)

    def apply_bias(self, idx: int, increment: float, all_windows: WindowList, is_horizontal: bool = True) -> bool:
        b = self.biased_cols if is_horizontal else self.biased_rows
        num_windows = all_windows.num_groups
        ncols, nrows, special_rows, special_col = calc_grid_size(num_windows)

        def position_for_window_idx(idx: int) -> Tuple[int, int]:
            row_num = col_num = 0

            def on_col_done(col_windows: List[int]) -> None:
                nonlocal col_num, row_num
                row_num = 0
                col_num += 1

            for window_idx, xl, yl in self.layout_windows(
                    num_windows, nrows, ncols, special_rows, special_col, on_col_done):
                if idx == window_idx:
                    return row_num, col_num
                row_num += 1

        row_num, col_num = position_for_window_idx(idx)

        if is_horizontal:
            b = self.biased_cols
            if ncols < 2:
                return False
            bias_idx = col_num
            attr = 'biased_cols'

            def layout_func(windows: ListOfWindows, bias: Optional[Sequence[float]] = None) -> LayoutDimension:
                return self.column_layout(num_windows, bias=bias)

        else:
            b = self.biased_rows
            if max(nrows, special_rows) < 2:
                return False
            bias_idx = row_num
            attr = 'biased_rows'

            def layout_func(windows: ListOfWindows, bias: Optional[Sequence[float]] = None) -> LayoutDimension:
                return self.row_layout(num_windows, bias=bias)

        before_layout = list(self.variable_layout(layout_func, num_windows, b))
        candidate = b.copy()
        before = candidate.get(bias_idx, 0)
        candidate[bias_idx] = before + increment
        if before_layout == list(self.variable_layout(layout_func, num_windows, candidate)):
            return False
        setattr(self, attr, candidate)
        return True

    def layout_windows(
        self,
        num_windows: int,
        nrows: int, ncols: int,
        special_rows: int, special_col: int,
        on_col_done: Callable[[List[int]], None] = lambda col_windows: None
    ) -> Generator[Tuple[int, LayoutData, LayoutData], None, None]:
        # Distribute windows top-to-bottom, left-to-right (i.e. in columns)
        xlayout = self.variable_layout(self.column_layout, ncols, self.biased_cols)
        yvals_normal = tuple(self.variable_layout(self.row_layout, nrows, self.biased_rows))
        yvals_special = yvals_normal if special_rows == nrows else tuple(self.variable_layout(self.row_layout, special_rows, self.biased_rows))
        pos = 0
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            yls = yvals_special if col == special_col else yvals_normal
            xl = next(xlayout)
            col_windows = []
            for i, yl in enumerate(yls):
                window_idx = pos + i
                yield window_idx, xl, yl
                col_windows.append(window_idx)
            pos += rows
            on_col_done(col_windows)

    def do_layout(self, all_windows: WindowList) -> None:
        n = all_windows.num_groups
        if n == 1:
            self.layout_single_window_group(next(all_windows.iter_all_layoutable_groups()))
            return
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
        groups = tuple(all_windows.iter_all_layoutable_groups())
        win_col_map: List[List[WindowGroup]] = []

        def on_col_done(col_windows: List[int]) -> None:
            col_windows_w = [groups[i] for i in col_windows]
            win_col_map.append(col_windows_w)

        def extents(ld: LayoutData) -> Tuple[int, int]:
            start = ld.content_pos - ld.space_before
            size = ld.space_before + ld.space_after + ld.content_size
            return start, size

        def layout(ld: LayoutData, cell_length: int, before_dec: int, after_dec: int) -> LayoutData:
            start, size = extents(ld)
            space_needed_for_decorations = before_dec + after_dec
            content_size = size - space_needed_for_decorations
            number_of_cells = content_size // cell_length
            cell_area = number_of_cells * cell_length
            extra = content_size - cell_area
            if extra > 0 and not lgd.align_top_left:
                before_dec += extra // 2
            return LayoutData(start + before_dec, number_of_cells, before_dec, size - cell_area - before_dec, cell_area)

        def position_window_in_grid_cell(window_idx: int, xl: LayoutData, yl: LayoutData) -> None:
            wg = groups[window_idx]
            edges = Edges(wg.decoration('left'), wg.decoration('top'), wg.decoration('right'), wg.decoration('bottom'))
            xl = layout(xl, lgd.cell_width, edges.left, edges.right)
            yl = layout(yl, lgd.cell_height, edges.top, edges.bottom)
            self.set_window_group_geometry(wg, xl, yl)

        for window_idx, xl, yl in self.layout_windows(
                n, nrows, ncols, special_rows, special_col, on_col_done):
            position_window_in_grid_cell(window_idx, xl, yl)

    def minimal_borders(self, all_windows: WindowList) -> Generator[BorderLine, None, None]:
        n = all_windows.num_groups
        if not lgd.draw_minimal_borders or n < 2:
            return
        needs_borders_map = all_windows.compute_needs_borders_map(lgd.draw_active_borders)
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
        is_first_row: Set[int] = set()
        is_last_row: Set[int] = set()
        is_first_column: Set[int] = set()
        is_last_column: Set[int] = set()
        groups = tuple(all_windows.iter_all_layoutable_groups())
        bw = groups[0].effective_border()
        if not bw:
            return
        xl: LayoutData = LayoutData()
        yl: LayoutData = LayoutData()
        prev_col_windows: List[int] = []
        layout_data_map: Dict[int, Tuple[LayoutData, LayoutData]] = {}

        def on_col_done(col_windows: List[int]) -> None:
            nonlocal prev_col_windows, is_first_column
            if col_windows:
                is_first_row.add(groups[col_windows[0]].id)
                is_last_row.add(groups[col_windows[-1]].id)
            if not prev_col_windows:
                is_first_column = {groups[x].id for x in col_windows}
            prev_col_windows = col_windows

        all_groups_in_order: List[WindowGroup] = []
        for window_idx, xl, yl in self.layout_windows(n, nrows, ncols, special_rows, special_col, on_col_done):
            wg = groups[window_idx]
            all_groups_in_order.append(wg)
            layout_data_map[wg.id] = xl, yl
        is_last_column = {groups[x].id for x in prev_col_windows}
        active_group = all_windows.active_group

        def ends(yl: LayoutData) -> Tuple[int, int]:
            return yl.content_pos - yl.space_before, yl.content_pos + yl.content_size + yl.space_after

        def borders_for_window(gid: int) -> Generator[Edges, None, None]:
            xl, yl = layout_data_map[gid]
            left, right = ends(xl)
            top, bottom = ends(yl)
            first_row, last_row = gid in is_first_row, gid in is_last_row
            first_column, last_column = gid in is_first_column, gid in is_last_column

            # Horizontal
            if not first_row:
                yield Edges(left, top, right, top + bw)
            if not last_row:
                yield Edges(left, bottom - bw, right, bottom)

            # Vertical
            if not first_column:
                yield Edges(left, top, left + bw, bottom)
            if not last_column:
                yield Edges(right - bw, top, right, bottom)

        for wg in all_groups_in_order:
            for edges in borders_for_window(wg.id):
                yield BorderLine(edges)
        for wg in all_groups_in_order:
            if needs_borders_map.get(wg.id):
                color = BorderColor.active if wg is active_group else BorderColor.bell
                for edges in borders_for_window(wg.id):
                    yield BorderLine(edges, color)

    def neighbors_for_window(self, window: WindowType, all_windows: WindowList) -> NeighborsMap:
        n = all_windows.num_groups
        if n < 4:
            return neighbors_for_tall_window(1, window, all_windows)

        wg = all_windows.group_for_window(window)
        assert wg is not None
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
        blank_row: List[Optional[int]] = [None for i in range(ncols)]
        matrix = tuple(blank_row[:] for j in range(max(nrows, special_rows)))
        wi = all_windows.iter_all_layoutable_groups()
        pos_map: Dict[int, Tuple[int, int]] = {}
        col_counts: List[int] = []
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            for row in range(rows):
                w = next(wi)
                matrix[row][col] = wid = w.id
                pos_map[wid] = row, col
            col_counts.append(rows)
        row, col = pos_map[wg.id]

        def neighbors(row: int, col: int) -> List[int]:
            try:
                ans = matrix[row][col]
            except IndexError:
                ans = None
            return [] if ans is None else [ans]

        def side(row: int, col: int, delta: int) -> List[int]:
            neighbor_col = col + delta
            neighbor_nrows = col_counts[neighbor_col]
            nrows = col_counts[col]
            if neighbor_nrows == nrows:
                return neighbors(row, neighbor_col)

            start_row = floor(neighbor_nrows * row / nrows)
            end_row = ceil(neighbor_nrows * (row + 1) / nrows)
            xs = []
            for neighbor_row in range(start_row, end_row):
                xs.extend(neighbors(neighbor_row, neighbor_col))
            return xs

        return {
            'top': neighbors(row-1, col) if row else [],
            'bottom': neighbors(row + 1, col),
            'left': side(row, col, -1) if col else [],
            'right': side(row, col, 1) if col < ncols - 1 else [],
        }

    def layout_state(self) -> Dict[str, Any]:
        return {
            'biased_cols': self.biased_cols,
            'biased_rows': self.biased_rows
        }
