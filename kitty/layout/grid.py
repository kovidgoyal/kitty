#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache
from itertools import repeat
from typing import Callable, Dict, Generator, List, Optional, Sequence, Tuple

from kitty.constants import Edges
from kitty.typing import WindowType
from kitty.window_list import WindowList

from .base import (
    Borders, NeighborsMap, Layout, LayoutData, LayoutDimension,
    ListOfWindows, all_borders, layout_dimension, lgd, no_borders,
    variable_bias
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

    def apply_bias(self, idx: int, increment: float, top_level_windows: ListOfWindows, is_horizontal: bool = True) -> bool:
        b = self.biased_cols if is_horizontal else self.biased_rows
        num_windows = len(top_level_windows)
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

    def do_layout(self, windows: WindowList, active_window_idx: int) -> None:
        n = len(windows)
        if n == 1:
            self.layout_single_window(windows[0])
            return
        ncols, nrows, special_rows, special_col = calc_grid_size(n)

        win_col_map = []

        def on_col_done(col_windows: List[int]) -> None:
            col_windows_w = [windows[i] for i in col_windows]
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
            w = windows[window_idx]
            bw = w.effective_border()
            edges = Edges(
                w.effective_margin('left') + w.effective_padding('left') + bw,
                w.effective_margin('right') + w.effective_padding('right') + bw,
                w.effective_margin('top') + w.effective_padding('top') + bw,
                w.effective_margin('bottom') + w.effective_padding('bottom') + bw,
            )
            xl = layout(xl, lgd.cell_width, edges.left, edges.right)
            yl = layout(yl, lgd.cell_height, edges.top, edges.bottom)
            self.set_window_geometry(w, window_idx, xl, yl)

        for window_idx, xl, yl in self.layout_windows(
                n, nrows, ncols, special_rows, special_col, on_col_done):
            position_window_in_grid_cell(window_idx, xl, yl)

    def minimal_borders(self, windows: WindowList, active_window: Optional[WindowType], needs_borders_map: Dict[int, bool]) -> Generator[Borders, None, None]:
        for w in windows:
            if needs_borders_map[w.id]:
                yield all_borders
            else:
                yield no_borders

    def window_independent_borders(self, windows: WindowList, active_window: Optional[WindowType] = None) -> Generator[Edges, None, None]:
        n = len(windows)
        if not lgd.draw_minimal_borders or n < 2:
            return
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
        row_borders: List[List[Edges]] = [[]]
        col_borders: List[Edges] = []
        bw = windows[0].effective_border()

        def on_col_done(col_windows: List[int]) -> None:
            left = xl.content_pos + xl.content_size + xl.space_after - bw // 2
            col_borders.append(Edges(left, lgd.central.top, left + bw, lgd.central.bottom))
            row_borders.append([])

        for window_idx, xl, yl in self.layout_windows(n, nrows, ncols, special_rows, special_col, on_col_done):
            top = yl.content_pos + yl.content_size + yl.space_after - bw // 2
            right = xl.content_pos + xl.content_size + xl.space_after
            row_borders[-1].append(Edges(xl.content_pos - xl.space_before, top, right, top + bw))

        for border in col_borders[:-1]:
            yield border

        for rows in row_borders:
            for border in rows[:-1]:
                yield border

    def neighbors_for_window(self, window: WindowType, windows: WindowList) -> NeighborsMap:
        n = len(windows)
        if n < 4:
            return neighbors_for_tall_window(1, window, windows)
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
        blank_row: List[Optional[int]] = [None for i in range(ncols)]
        matrix = tuple(blank_row[:] for j in range(max(nrows, special_rows)))
        wi = iter(windows)
        pos_map: Dict[int, Tuple[int, int]] = {}
        col_counts: List[int] = []
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            for row in range(rows):
                w = next(wi)
                matrix[row][col] = wid = w.id
                pos_map[wid] = row, col
            col_counts.append(rows)
        row, col = pos_map[window.id]

        def neighbors(row: int, col: int) -> List[int]:
            try:
                ans = matrix[row][col]
            except IndexError:
                ans = None
            return [] if ans is None else [ans]

        def side(row: int, col: int, delta: int) -> List[int]:
            neighbor_col = col + delta
            if col_counts[neighbor_col] == col_counts[col]:
                return neighbors(row, neighbor_col)
            return neighbors(min(row, col_counts[neighbor_col] - 1), neighbor_col)

        return {
            'top': neighbors(row-1, col) if row else [],
            'bottom': neighbors(row + 1, col),
            'left': side(row, col, -1) if col else [],
            'right': side(row, col, 1) if col < ncols - 1 else [],
        }
