#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from functools import partial
from itertools import islice, repeat

from .constants import WindowGeometry
from .fast_data_types import (
    Region, set_active_window, swap_windows, viewport_for_window
)

# Utils {{{
central = Region((0, 0, 199, 199, 200, 200))
cell_width = cell_height = 20
all_borders = True, True, True, True
no_borders = False, False, False, False
draw_minimal_borders = False
draw_active_borders = True


def idx_for_id(win_id, windows):
    for i, w in enumerate(windows):
        if w.id == win_id:
            return i


def set_draw_borders_options(opts):
    global draw_minimal_borders, draw_active_borders
    draw_minimal_borders = opts.draw_minimal_borders and opts.window_margin_width == 0
    draw_active_borders = opts.active_border_color is not None


def layout_dimension(start_at, length, cell_length, decoration_pairs, left_align=False, bias=None):
    number_of_windows = len(decoration_pairs)
    number_of_cells = length // cell_length
    space_needed_for_decorations = sum(map(sum, decoration_pairs))
    extra = length - number_of_cells * cell_length
    while extra < space_needed_for_decorations:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    cells_per_window = number_of_cells // number_of_windows
    extra -= space_needed_for_decorations
    pos = start_at
    if not left_align:
        pos += extra // 2

    def calc_window_geom(i, cells_in_window):
        nonlocal pos
        pos += decoration_pairs[i][0]
        inner_length = cells_in_window * cell_length
        return inner_length + decoration_pairs[i][1]

    if bias is not None and number_of_windows > 1 and len(bias) == number_of_windows and cells_per_window > 5:
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
    for i, cells_per_window in enumerate(cells_map):
        window_length = calc_window_geom(i, cells_per_window)
        yield pos, cells_per_window
        pos += window_length


Rect = namedtuple('Rect', 'left top right bottom')


def process_overlaid_windows(all_windows):
    id_map = {w.id: w for w in all_windows}
    overlaid_windows = frozenset(w for w in all_windows if w.overlay_window_id is not None and w.overlay_window_id in id_map)
    windows = [w for w in all_windows if w not in overlaid_windows]
    return overlaid_windows, windows


def window_geometry(xstart, xnum, ystart, ynum):
    return WindowGeometry(left=xstart, top=ystart, xnum=xnum, ynum=ynum, right=xstart + cell_width * xnum, bottom=ystart + cell_height * ynum)


def layout_single_window(xdecoration_pairs, ydecoration_pairs):
    xstart, xnum = next(layout_dimension(central.left, central.width, cell_width, xdecoration_pairs))
    ystart, ynum = next(layout_dimension(central.top, central.height, cell_height, ydecoration_pairs))
    return window_geometry(xstart, xnum, ystart, ynum)


def left_blank_rect(w, rects):
    lt = w.geometry.left
    if lt > central.left:
        rects.append(Rect(central.left, central.top, lt, central.bottom + 1))


def right_blank_rect(w, rects):
    r = w.geometry.right
    if r < central.right:
        rects.append(Rect(r, central.top, central.right + 1, central.bottom + 1))


def top_blank_rect(w, rects):
    t = w.geometry.top
    if t > central.top:
        rects.append(Rect(central.left, central.top, central.right + 1, t))


def bottom_blank_rect(w, rects):
    b = w.geometry.bottom
    # Need to use <= here as otherwise a single pixel row at the bottom of the
    # window is sometimes not covered. See https://github.com/kovidgoyal/kitty/issues/506
    if b <= central.bottom:
        rects.append(Rect(central.left, b, central.right + 1, central.bottom + 1))


def blank_rects_for_window(w):
    ans = []
    left_blank_rect(w, ans), top_blank_rect(w, ans), right_blank_rect(w, ans), bottom_blank_rect(w, ans)
    return ans


def safe_increment_bias(old_val, increment):
    return max(0.1, min(old_val + increment, 0.9))


def normalize_biases(biases):
    s = sum(biases)
    if s == 1:
        return biases
    return [x/s for x in biases]


def distribute_indexed_bias(base_bias, index_bias_map):
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


def variable_bias(num_windows, candidate):
    return distribute_indexed_bias(list(repeat(1/(num_windows), num_windows)), candidate)


# }}}


class Layout:  # {{{

    name = None
    needs_window_borders = True
    only_active_window_visible = False

    def __init__(self, os_window_id, tab_id, margin_width, single_window_margin_width, padding_width, border_width, layout_opts=''):
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.set_active_window_in_os_window = partial(set_active_window, os_window_id, tab_id)
        self.swap_windows_in_os_window = partial(swap_windows, os_window_id, tab_id)
        self.border_width = border_width
        self.margin_width = margin_width
        self.single_window_margin_width = single_window_margin_width
        self.padding_width = padding_width
        # A set of rectangles corresponding to the blank spaces at the edges of
        # this layout, i.e. spaces that are not covered by any window
        self.blank_rects = []
        self.layout_opts = self.parse_layout_opts(layout_opts)
        self.full_name = self.name + ((':' + layout_opts) if layout_opts else '')
        self.remove_all_biases()

    def bias_increment_for_cell(self, is_horizontal):
        self._set_dimensions()
        if is_horizontal:
            return (cell_width + 1) / central.width
        return (cell_height + 1) / central.height

    def apply_bias(self, idx, increment_as_percent, num_windows, is_horizontal):
        return False

    def remove_all_biases(self):
        return False

    def modify_size_of_window(self, all_windows, window_id, increment, is_horizontal=True):
        idx = idx_for_id(window_id, all_windows)
        if idx is None:
            return False
        w = all_windows[idx]
        windows = process_overlaid_windows(all_windows)[1]
        idx = idx_for_id(w.id, windows)
        if idx is None:
            idx = idx_for_id(w.overlay_window_id, windows)
        if idx is not None:
            return self.apply_bias(idx, increment, len(windows), is_horizontal)
        return False

    def parse_layout_opts(self, layout_opts):
        if not layout_opts:
            return {}
        ans = {}
        for x in layout_opts.split(';'):
            k, v = x.partition('=')[::2]
            if k and v:
                ans[k] = v
        return ans

    def nth_window(self, all_windows, num, make_active=True):
        windows = process_overlaid_windows(all_windows)[1]
        w = windows[min(num, len(windows) - 1)]
        if not make_active:
            return w
        active_window_idx = idx_for_id(w.id, all_windows)
        return self.set_active_window(all_windows, active_window_idx)

    def next_window(self, all_windows, active_window_idx, delta=1):
        w = all_windows[active_window_idx]
        windows = process_overlaid_windows(all_windows)[1]
        idx = idx_for_id(w.id, windows)
        if idx is None:
            idx = idx_for_id(w.overlay_window_id, windows)
        active_window_idx = (idx + len(windows) + delta) % len(windows)
        active_window_idx = idx_for_id(windows[active_window_idx].id, all_windows)
        return self.set_active_window(all_windows, active_window_idx)

    def neighbors(self, all_windows, active_window_idx):
        w = all_windows[active_window_idx]
        windows = process_overlaid_windows(all_windows)[1]
        ans = self.neighbors_for_window(w, windows)
        for values in ans.values():
            values[:] = [idx_for_id(w.id, all_windows) for w in values]
        return ans

    def move_window(self, all_windows, active_window_idx, delta=1):
        # delta can be either a number or a string such as 'left', 'top', etc
        # for neighborhood moves
        w = all_windows[active_window_idx]
        windows = process_overlaid_windows(all_windows)[1]
        if len(windows) < 2 or not delta:
            return active_window_idx
        idx = idx_for_id(w.id, windows)
        if idx is None:
            idx = idx_for_id(w.overlay_window_id, windows)
        if isinstance(delta, int):
            nidx = (idx + len(windows) + delta) % len(windows)
        else:
            delta = delta.lower()
            delta = {'up': 'top', 'down': 'bottom'}.get(delta, delta)
            neighbors = self.neighbors_for_window(w, windows)
            if not neighbors.get(delta):
                return active_window_idx
            nidx = idx_for_id(neighbors[delta][0].id, windows)

        nw = windows[nidx]
        nidx = idx_for_id(nw.id, all_windows)
        idx = active_window_idx
        all_windows[nidx], all_windows[idx] = all_windows[idx], all_windows[nidx]
        self.swap_windows_in_os_window(nidx, idx)
        return self.set_active_window(all_windows, nidx)

    def add_window(self, all_windows, window, current_active_window_idx):
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
            active_window_idx = len(all_windows)
            all_windows.append(window)
        self(all_windows, active_window_idx)
        self.set_active_window_in_os_window(active_window_idx)
        return active_window_idx

    def remove_window(self, all_windows, window, current_active_window_idx, swapped=False):
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
        if all_windows:
            self(all_windows, active_window_idx)
        self.set_active_window(all_windows, active_window_idx)
        return active_window_idx

    def update_visibility(self, all_windows, active_window, overlaid_windows=None):
        if overlaid_windows is None:
            overlaid_windows = process_overlaid_windows(all_windows)[0]
        for i, w in enumerate(all_windows):
            w.set_visible_in_layout(i, w is active_window or (not self.only_active_window_visible and w not in overlaid_windows))

    def set_active_window(self, all_windows, active_window_idx):
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

    def _set_dimensions(self):
        global central, cell_width, cell_height
        central, tab_bar, vw, vh, cell_width, cell_height = viewport_for_window(self.os_window_id)

    def __call__(self, all_windows, active_window_idx):
        self._set_dimensions()
        active_window = all_windows[active_window_idx]
        overlaid_windows, windows = process_overlaid_windows(all_windows)
        if overlaid_windows:
            windows = [w for w in all_windows if w not in overlaid_windows]
            active_window_idx = idx_for_id(active_window.id, windows)
            if active_window_idx is None:
                active_window_idx = idx_for_id(active_window.overlay_window_id, windows) or 0
            active_window = windows[active_window_idx]
        else:
            windows = all_windows
        self.update_visibility(all_windows, active_window, overlaid_windows)
        self.blank_rects = []
        self.do_layout(windows, active_window_idx)
        return idx_for_id(active_window.id, all_windows)

    # Utils {{{
    def layout_single_window(self, w):
        mw = self.margin_width if self.single_window_margin_width < 0 else self.single_window_margin_width
        decoration_pairs = ((self.padding_width + mw, self.padding_width + mw),)
        wg = layout_single_window(decoration_pairs, decoration_pairs)
        w.set_geometry(0, wg)
        self.blank_rects = blank_rects_for_window(w)

    def xlayout(self, num, bias=None):
        decoration = self.margin_width + self.border_width + self.padding_width
        decoration_pairs = tuple(repeat((decoration, decoration), num))
        return layout_dimension(central.left, central.width, cell_width, decoration_pairs, bias=bias)

    def ylayout(self, num, left_align=True, bias=None):
        decoration = self.margin_width + self.border_width + self.padding_width
        decoration_pairs = tuple(repeat((decoration, decoration), num))
        return layout_dimension(central.top, central.height, cell_height, decoration_pairs, bias=bias)

    def simple_blank_rects(self, first_window, last_window):
        br = self.blank_rects
        left_blank_rect(first_window, br), top_blank_rect(first_window, br), right_blank_rect(last_window, br)

    def between_blank_rect(self, left_window, right_window):
        self.blank_rects.append(Rect(left_window.geometry.right, central.top, right_window.geometry.left, central.bottom + 1))

    def bottom_blank_rect(self, window):
        self.blank_rects.append(Rect(window.geometry.left, window.geometry.bottom, window.geometry.right, central.bottom + 1))
    # }}}

    def do_layout(self, windows, active_window_idx):
        raise NotImplementedError()

    def neighbors_for_window(self, window, windows):
        return {'left': [], 'right': [], 'top': [], 'bottom': []}

    def resolve_borders(self, windows, active_window):
        if draw_minimal_borders:
            needs_borders_map = {w.id: ((w is active_window and draw_active_borders) or w.needs_attention) for w in windows}
            yield from self.minimal_borders(windows, active_window, needs_borders_map)
        else:
            yield from Layout.minimal_borders(self, windows, active_window, None)

    def minimal_borders(self, windows, active_window, needs_borders_map):
        for w in windows:
            if w is active_window and not draw_active_borders and not w.needs_attention:
                yield no_borders
            else:
                yield all_borders
# }}}


class Stack(Layout):  # {{{

    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def do_layout(self, windows, active_window_idx):
        mw = self.margin_width if self.single_window_margin_width < 0 else self.single_window_margin_width
        decoration_pairs = ((mw + self.padding_width, mw + self.padding_width),)
        wg = layout_single_window(decoration_pairs, decoration_pairs)
        for i, w in enumerate(windows):
            w.set_geometry(i, wg)
            if w.is_visible_in_layout:
                self.blank_rects = blank_rects_for_window(w)
# }}}


class Tall(Layout):  # {{{

    name = 'tall'
    vlayout = Layout.ylayout
    main_is_horizontal = True
    only_between_border = False, False, False, True
    only_main_border = False, False, True, False

    def remove_all_biases(self):
        self.main_bias = list(self.layout_opts['bias'])
        self.biased_map = {}
        return True

    def variable_layout(self, num_windows, biased_map):
        num_windows -= 1
        return self.vlayout(num_windows, bias=variable_bias(num_windows, biased_map) if num_windows > 1 else None)

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        if self.main_is_horizontal == is_horizontal:
            before = self.main_bias
            if idx == 0:
                self.main_bias = [safe_increment_bias(self.main_bias[0], increment), safe_increment_bias(self.main_bias[1], -increment)]
            else:
                self.main_bias = [safe_increment_bias(self.main_bias[0], -increment), safe_increment_bias(self.main_bias[1], increment)]
            self.main_bias = normalize_biases(self.main_bias)
            after = self.main_bias
        else:
            if idx == 0 or num_windows < 3:
                return False
            idx -= 1
            before_layout = list(self.variable_layout(num_windows, self.biased_map))
            candidate = self.biased_map.copy()
            before = candidate.get(idx, 0)
            candidate[idx] = after = before + increment
            if before_layout == list(self.variable_layout(num_windows, candidate)):
                return False
            self.biased_map = candidate

        return before != after

    def parse_layout_opts(self, layout_opts):
        ans = Layout.parse_layout_opts(self, layout_opts)
        try:
            ans['bias'] = int(ans.get('bias', 50)) / 100
        except Exception:
            ans['bias'] = 0.5
        ans['bias'] = max(0.1, min(ans['bias'], 0.9))
        ans['bias'] = ans['bias'], 1.0 - ans['bias']
        return ans

    def do_layout(self, windows, active_window_idx):
        if len(windows) == 1:
            return self.layout_single_window(windows[0])
        xlayout = self.xlayout(2, bias=self.main_bias)
        xstart, xnum = next(xlayout)
        ystart, ynum = next(self.vlayout(1))
        windows[0].set_geometry(0, window_geometry(xstart, xnum, ystart, ynum))
        xstart, xnum = next(xlayout)
        ylayout = self.variable_layout(len(windows), self.biased_map)
        for i, (w, (ystart, ynum)) in enumerate(zip(islice(windows, 1, None), ylayout)):
            w.set_geometry(i + 1, window_geometry(xstart, xnum, ystart, ynum))
            # right bottom blank rect
            self.bottom_blank_rect(windows[i + 1])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])
        # between blank rect
        self.between_blank_rect(windows[0], windows[1])
        # left bottom blank rect
        self.bottom_blank_rect(windows[0])

    def neighbors_for_window(self, window, windows):
        if window is windows[0]:
            return {'left': [], 'right': windows[1:], 'top': [], 'bottom': []}
        idx = windows.index(window)
        return {'left': [windows[0]], 'right': [], 'top': [] if idx <= 1 else [windows[idx-1]],
                'bottom': [] if window is windows[-1] else [windows[idx+1]]}

    def minimal_borders(self, windows, active_window, needs_borders_map):
        last_i = len(windows) - 1
        for i, w in enumerate(windows):
            if needs_borders_map[w.id]:
                yield all_borders
                continue
            if i == 0:
                if last_i == 1 and needs_borders_map[windows[1].id]:
                    yield no_borders
                else:
                    yield self.only_main_border
                continue
            if i == last_i:
                yield no_borders
                break
            if needs_borders_map[windows[i+1].id]:
                yield no_borders
            else:
                yield self.only_between_border
# }}}


class Fat(Tall):  # {{{

    name = 'fat'
    vlayout = Layout.xlayout
    main_is_horizontal = False
    only_between_border = False, False, True, False
    only_main_border = False, False, False, True

    def do_layout(self, windows, active_window_idx):
        if len(windows) == 1:
            return self.layout_single_window(windows[0])
        xstart, xnum = next(self.xlayout(1))
        ylayout = self.ylayout(2, bias=self.main_bias)
        ystart, ynum = next(ylayout)
        windows[0].set_geometry(0, window_geometry(xstart, xnum, ystart, ynum))
        xlayout = self.variable_layout(len(windows), self.biased_map)
        ystart, ynum = next(ylayout)
        for i, (w, (xstart, xnum)) in enumerate(zip(islice(windows, 1, None), xlayout)):
            w.set_geometry(i + 1, window_geometry(xstart, xnum, ystart, ynum))
            if i > 0:
                # bottom between blank rect
                self.between_blank_rect(windows[i - 1], windows[i])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])
        # top bottom blank rect
        self.bottom_blank_rect(windows[0])
        # bottom blank rect
        self.blank_rects.append(Rect(windows[0].geometry.left, windows[0].geometry.bottom, windows[-1].geometry.right, central.bottom + 1))

    def neighbors_for_window(self, window, windows):
        if window is windows[0]:
            return {'left': [], 'bottom': windows[1:], 'top': [], 'right': []}
        idx = windows.index(window)
        return {'top': [windows[0]], 'bottom': [], 'left': [] if idx <= 1 else [windows[idx-1]],
                'right': [] if window is windows[-1] else [windows[idx+1]]}

# }}}


class Grid(Layout):  # {{{

    name = 'grid'

    def remove_all_biases(self):
        self.biased_rows = {}
        self.biased_cols = {}
        return True

    def variable_layout(self, layout_func, num_windows, biased_map):
        return layout_func(num_windows, bias=variable_bias(num_windows, biased_map) if num_windows > 1 else None)

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        b = self.biased_cols if is_horizontal else self.biased_rows
        ncols, nrows, special_rows, special_col = self.calc_grid_size(num_windows)

        def position_for_window_idx(idx):
            row_num = col_num = 0

            def on_col_done(col_windows):
                nonlocal col_num, row_num
                row_num = 0
                col_num += 1

            for window_idx, xstart, xnum, ystart, ynum in self.layout_windows(
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
            layout_func = self.xlayout
            attr = 'biased_cols'
        else:
            b = self.biased_rows
            if max(nrows, special_rows) < 2:
                return False
            bias_idx = row_num
            layout_func = self.ylayout
            attr = 'biased_rows'

        before_layout = list(self.variable_layout(layout_func, num_windows, b))
        candidate = b.copy()
        before = candidate.get(bias_idx, 0)
        candidate[bias_idx] = before + increment
        if before_layout == list(self.variable_layout(layout_func, num_windows, candidate)):
            return False
        setattr(self, attr, candidate)
        return True

    def calc_grid_size(self, n):
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

    def layout_windows(self, num_windows, nrows, ncols, special_rows, special_col, on_col_done=lambda col_windows: None):
        # Distribute windows top-to-bottom, left-to-right (i.e. in columns)
        xlayout = self.variable_layout(self.xlayout, ncols, self.biased_cols)
        yvals_normal = tuple(self.variable_layout(self.ylayout, nrows, self.biased_rows))
        yvals_special = yvals_normal if special_rows == nrows else tuple(self.variable_layout(self.ylayout, special_rows, self.biased_rows))
        pos = 0
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            yl = yvals_special if col == special_col else yvals_normal
            xstart, xnum = next(xlayout)
            col_windows = []
            for i, (ystart, ynum) in enumerate(yl):
                window_idx = pos + i
                yield window_idx, xstart, xnum, ystart, ynum
                col_windows.append(window_idx)
            pos += rows
            on_col_done(col_windows)

    def do_layout(self, windows, active_window_idx):
        n = len(windows)
        if n == 1:
            return self.layout_single_window(windows[0])
        ncols, nrows, special_rows, special_col = self.calc_grid_size(n)
        layout_data = n, ncols, nrows, special_rows, special_col
        for w in windows:
            w.layout_data = layout_data

        win_col_map = []

        def on_col_done(col_windows):
            col_windows = [windows[i] for i in col_windows]
            win_col_map.append(col_windows)
            # bottom blank rect
            self.bottom_blank_rect(col_windows[-1])

        for window_idx, xstart, xnum, ystart, ynum in self.layout_windows(
                len(windows), nrows, ncols, special_rows, special_col, on_col_done):
            w = windows[window_idx]
            w.set_geometry(window_idx, window_geometry(xstart, xnum, ystart, ynum))

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])

        # the in-between columns blank rects
        for i in range(ncols - 1):
            self.between_blank_rect(win_col_map[i][0], win_col_map[i + 1][0])

    def minimal_borders(self, windows, active_window, needs_borders_map):
        try:
            n, ncols, nrows, special_rows, special_col = windows[0].layout_data
        except Exception:
            n = -1
        if n != len(windows):
            # Something bad happened
            yield from Layout.minimal_borders(self, windows, active_window, needs_borders_map)
            return
        blank_row = [None for i in range(ncols)]
        matrix = tuple(blank_row[:] for j in range(max(nrows, special_rows)))
        wi = iter(windows)
        pos_map = {}
        col_counts = []
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            for row in range(rows):
                matrix[row][col] = wid = next(wi).id
                pos_map[wid] = row, col
            col_counts.append(rows)

        for w in windows:
            wid = w.id
            if needs_borders_map[wid]:
                yield all_borders
                continue
            row, col = pos_map[wid]
            if col + 1 < ncols:
                next_col_has_different_count = col_counts[col + 1] != col_counts[col]
                right_neighbor_id = matrix[row][col+1]
            else:
                right_neighbor_id = None
                next_col_has_different_count = False
            try:
                bottom_neighbor_id = matrix[row+1][col]
            except IndexError:
                bottom_neighbor_id = None
            yield (
                False, False,
                (right_neighbor_id is not None and not needs_borders_map[right_neighbor_id]) or next_col_has_different_count,
                bottom_neighbor_id is not None and not needs_borders_map[bottom_neighbor_id]
            )

    def neighbors_for_window(self, window, windows):
        n = len(windows)
        if n < 4:
            return Tall.neighbors_for_window(self, window, windows)
        try:
            n, ncols, nrows, special_rows, special_col = windows[0].layout_data
        except Exception:
            n = -1
        if n != len(windows):
            # Something bad happened
            return Layout.neighbors_for_window(self, window, windows)

        blank_row = [None for i in range(ncols)]
        matrix = tuple(blank_row[:] for j in range(max(nrows, special_rows)))
        wi = iter(windows)
        pos_map = {}
        col_counts = []
        id_map = {}
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            for row in range(rows):
                w = next(wi)
                matrix[row][col] = wid = w.id
                pos_map[wid] = row, col
                id_map[wid] = w
            col_counts.append(rows)
        row, col = pos_map[window.id]

        def neighbors(row, col):
            try:
                ans = matrix[row][col]
            except IndexError:
                ans = None
            return [] if ans is None else [id_map[ans]]

        def side(row, col, delta):
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


# }}}


class Vertical(Layout):  # {{{

    name = 'vertical'
    main_is_horizontal = False
    vlayout = Layout.ylayout
    only_between_border = False, False, False, True

    def variable_layout(self, num_windows, biased_map):
        return self.vlayout(num_windows, bias=variable_bias(num_windows, biased_map) if num_windows else None)

    def remove_all_biases(self):
        self.biased_map = {}
        return True

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        if self.main_is_horizontal != is_horizontal:
            return False
        if num_windows < 2:
            return False
        before_layout = list(self.variable_layout(num_windows, self.biased_map))
        candidate = self.biased_map.copy()
        before = candidate.get(idx, 0)
        candidate[idx] = before + increment
        if before_layout == list(self.variable_layout(num_windows, candidate)):
            return False
        self.biased_map = candidate
        return True

    def do_layout(self, windows, active_window_idx):
        window_count = len(windows)
        if window_count == 1:
            return self.layout_single_window(windows[0])

        xlayout = self.xlayout(1)
        xstart, xnum = next(xlayout)
        ylayout = self.variable_layout(window_count, self.biased_map)
        for i, (w, (ystart, ynum)) in enumerate(zip(windows, ylayout)):
            w.set_geometry(i, window_geometry(xstart, xnum, ystart, ynum))
            # bottom blank rect
            self.bottom_blank_rect(windows[i])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])

    def minimal_borders(self, windows, active_window, needs_borders_map):
        last_i = len(windows) - 1
        for i, w in enumerate(windows):
            if needs_borders_map[w.id]:
                yield all_borders
                continue
            if i == last_i:
                yield no_borders
                break
            if needs_borders_map[windows[i+1].id]:
                yield no_borders
            else:
                yield self.only_between_border

    def neighbors_for_window(self, window, windows):
        idx = windows.index(window)
        before = [] if window is windows[0] else [windows[idx-1]]
        after = [] if window is windows[-1] else [windows[idx+1]]
        if self.main_is_horizontal:
            return {'left': before, 'right': after, 'top': [], 'bottom': []}
        return {'top': before, 'bottom': after, 'left': [], 'right': []}

# }}}


class Horizontal(Vertical):  # {{{

    name = 'horizontal'
    main_is_horizontal = True
    vlayout = Layout.xlayout
    only_between_border = False, False, True, False

    def do_layout(self, windows, active_window_idx):
        window_count = len(windows)
        if window_count == 1:
            return self.layout_single_window(windows[0])

        xlayout = self.variable_layout(window_count, self.biased_map)
        ylayout = self.ylayout(1)
        ystart, ynum = next(ylayout)
        for i, (w, (xstart, xnum)) in enumerate(zip(windows, xlayout)):
            w.set_geometry(i, window_geometry(xstart, xnum, ystart, ynum))
            if i > 0:
                # between blank rect
                self.between_blank_rect(windows[i - 1], windows[i])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])
        # bottom blank rect
        self.blank_rects.append(Rect(windows[0].geometry.left, windows[0].geometry.bottom, windows[-1].geometry.right, central.bottom + 1))

# }}}


# Instantiation {{{

all_layouts = {o.name: o for o in globals().values() if isinstance(o, type) and issubclass(o, Layout) and o is not Layout}


def create_layout_object_for(name, os_window_id, tab_id, margin_width, single_window_margin_width, padding_width, border_width, layout_opts=''):
    key = name, os_window_id, tab_id, margin_width, single_window_margin_width, padding_width, border_width, layout_opts
    ans = create_layout_object_for.cache.get(key)
    if ans is None:
        name, layout_opts = name.partition(':')[::2]
        ans = create_layout_object_for.cache[key] = all_layouts[name](
            os_window_id, tab_id, margin_width, single_window_margin_width, padding_width, border_width, layout_opts)
    return ans


create_layout_object_for.cache = {}


def evict_cached_layouts(tab_id):
    remove = [key for key in create_layout_object_for.cache if key[2] == tab_id]
    for key in remove:
        del create_layout_object_for.cache[key]

# }}}
