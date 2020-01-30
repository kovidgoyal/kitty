#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from functools import lru_cache, partial
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
align_top_left = False


def idx_for_id(win_id, windows):
    for i, w in enumerate(windows):
        if w.id == win_id:
            return i


def set_layout_options(opts):
    global draw_minimal_borders, draw_active_borders, align_top_left
    draw_minimal_borders = opts.draw_minimal_borders and opts.window_margin_width == 0
    draw_active_borders = opts.active_border_color is not None
    align_top_left = opts.placement_strategy == 'top-left'


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


def layout_single_window(xdecoration_pairs, ydecoration_pairs, left_align=False):
    xstart, xnum = next(layout_dimension(central.left, central.width, cell_width, xdecoration_pairs, left_align=align_top_left))
    ystart, ynum = next(layout_dimension(central.top, central.height, cell_height, ydecoration_pairs, left_align=align_top_left))
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
    needs_all_windows = False
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
        if self.needs_all_windows:
            windows = all_windows
        else:
            windows = process_overlaid_windows(all_windows)[1]
        ans = self.neighbors_for_window(w, windows)
        for values in ans.values():
            values[:] = [idx_for_id(getattr(w, 'id', w), all_windows) for w in values]
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
            neighbors = self.neighbors_for_window(w, all_windows if self.needs_all_windows else windows)
            if not neighbors.get(delta):
                return active_window_idx
            w = neighbors[delta][0]
            nidx = idx_for_id(getattr(w, 'id', w), windows)

        nw = windows[nidx]
        nidx = idx_for_id(nw.id, all_windows)
        idx = active_window_idx
        self.swap_windows_in_layout(all_windows, nidx, idx)
        self.swap_windows_in_os_window(nidx, idx)
        return self.set_active_window(all_windows, nidx)

    def swap_windows_in_layout(self, all_windows, a, b):
        all_windows[a], all_windows[b] = all_windows[b], all_windows[a]

    def add_window(self, all_windows, window, current_active_window_idx, location=None):
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

    def do_add_window(self, all_windows, window, current_active_window_idx, location):
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

    def remove_window(self, all_windows, window, current_active_window_idx, swapped=False):
        try:
            active_window = all_windows[current_active_window_idx]
        except Exception:
            active_window = window
        if not swapped and window.overlay_for is not None:
            nidx = idx_for_id(window.overlay_for, all_windows)
            if nidx is not None:
                idx = all_windows.index(window)
                self.swap_windows_in_layout(all_windows, nidx, idx)
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
        if self.needs_all_windows:
            self.do_layout(windows, active_window_idx, all_windows)
        else:
            self.do_layout(windows, active_window_idx)
        return idx_for_id(active_window.id, all_windows)

    # Utils {{{
    def layout_single_window(self, w):
        mw = self.margin_width if self.single_window_margin_width < 0 else self.single_window_margin_width
        decoration_pairs = ((self.padding_width + mw, self.padding_width + mw),)
        wg = layout_single_window(decoration_pairs, decoration_pairs)
        w.set_geometry(0, wg)
        self.blank_rects = blank_rects_for_window(w)

    def xlayout(self, num, bias=None, left=None, width=None):
        decoration = self.margin_width + self.border_width + self.padding_width
        decoration_pairs = tuple(repeat((decoration, decoration), num))
        if left is None:
            left = central.left
        if width is None:
            width = central.width
        return layout_dimension(left, width, cell_width, decoration_pairs, bias=bias, left_align=align_top_left)

    def ylayout(self, num, left_align=True, bias=None, top=None, height=None):
        decoration = self.margin_width + self.border_width + self.padding_width
        decoration_pairs = tuple(repeat((decoration, decoration), num))
        if top is None:
            top = central.top
        if height is None:
            height = central.height
        return layout_dimension(top, height, cell_height, decoration_pairs, bias=bias, left_align=align_top_left)

    def simple_blank_rects(self, first_window, last_window):
        br = self.blank_rects
        left_blank_rect(first_window, br), top_blank_rect(first_window, br), right_blank_rect(last_window, br)

    def between_blank_rect(self, left_window, right_window, vertical=True):
        if vertical:
            self.blank_rects.append(Rect(left_window.geometry.right, central.top, right_window.geometry.left, central.bottom + 1))
        else:
            self.blank_rects.append(Rect(central.left, left_window.geometry.top, central.right + 1, right_window.geometry.bottom))

    def bottom_blank_rect(self, window):
        self.blank_rects.append(Rect(window.geometry.left, window.geometry.bottom, window.geometry.right, central.bottom + 1))
    # }}}

    def do_layout(self, windows, active_window_idx):
        raise NotImplementedError()

    def neighbors_for_window(self, window, windows):
        return {'left': [], 'right': [], 'top': [], 'bottom': []}

    def compute_needs_borders_map(self, windows, active_window):
        return {w.id: ((w is active_window and draw_active_borders) or w.needs_attention) for w in windows}

    def resolve_borders(self, windows, active_window):
        if draw_minimal_borders:
            needs_borders_map = self.compute_needs_borders_map(windows, active_window)
            yield from self.minimal_borders(windows, active_window, needs_borders_map)
        else:
            yield from Layout.minimal_borders(self, windows, active_window, None)

    def window_independent_borders(self, windows, active_windows):
        return
        yield

    def minimal_borders(self, windows, active_window, needs_borders_map):
        for w in windows:
            if (w is active_window and draw_active_borders) or w.needs_attention:
                yield all_borders
            else:
                yield no_borders
# }}}


class Stack(Layout):  # {{{

    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def do_layout(self, windows, active_window_idx):
        mw = self.margin_width if self.single_window_margin_width < 0 else self.single_window_margin_width
        decoration_pairs = ((mw + self.padding_width, mw + self.padding_width),)
        wg = layout_single_window(decoration_pairs, decoration_pairs, left_align=align_top_left)
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

    @property
    def num_full_size_windows(self):
        return self.layout_opts['full_size']

    def remove_all_biases(self):
        self.main_bias = list(self.layout_opts['bias'])
        self.biased_map = {}
        return True

    def variable_layout(self, num_windows, biased_map):
        num_windows -= self.num_full_size_windows
        return self.vlayout(num_windows, bias=variable_bias(num_windows, biased_map) if num_windows > 1 else None)

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        if self.main_is_horizontal == is_horizontal:
            before = self.main_bias
            ncols = self.num_full_size_windows + 1
            biased_col = idx if idx < self.num_full_size_windows else (ncols - 1)
            self.main_bias = [
                safe_increment_bias(self.main_bias[i], increment * (1 if i == biased_col else -1)) for i in range(ncols)
            ]
            self.main_bias = normalize_biases(self.main_bias)
            after = self.main_bias
        else:
            num_of_short_windows = num_windows - self.num_full_size_windows
            if idx < self.num_full_size_windows or num_of_short_windows < 2:
                return False
            idx -= self.num_full_size_windows
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
            ans['full_size'] = int(ans.get('full_size', 1))
        except Exception:
            ans['full_size'] = 1
        ans['full_size'] = fs = max(1, min(ans['full_size'], 100))
        try:
            b = int(ans.get('bias', 50)) / 100
        except Exception:
            b = 0.5
        b = max(0.1, min(b, 0.9))
        ans['bias'] = tuple(repeat(b / fs, fs)) + (1.0 - b,)
        return ans

    def do_layout(self, windows, active_window_idx):
        if len(windows) == 1:
            return self.layout_single_window(windows[0])
        y, ynum = next(self.vlayout(1))
        if len(windows) <= self.num_full_size_windows:
            bias = normalize_biases(self.main_bias[:-1])
            xlayout = self.xlayout(self.num_full_size_windows, bias=bias)
            for i, (w, (x, xnum)) in enumerate(zip(windows, xlayout)):
                w.set_geometry(i, window_geometry(x, xnum, y, ynum))
                if i > 0:
                    self.between_blank_rect(windows[i-1], windows[i])
                # bottom blank rect
                self.bottom_blank_rect(windows[i])

            # left, top and right blank rects
            self.simple_blank_rects(windows[0], windows[-1])
            return

        xlayout = self.xlayout(self.num_full_size_windows + 1, bias=self.main_bias)
        for i in range(self.num_full_size_windows):
            w = windows[i]
            x, xnum = next(xlayout)
            w.set_geometry(i, window_geometry(x, xnum, y, ynum))
            self.between_blank_rect(windows[i], windows[i+1])
            # bottom blank rect
            self.bottom_blank_rect(windows[i])
        x, xnum = next(xlayout)
        ylayout = self.variable_layout(len(windows), self.biased_map)
        for i, (w, (ystart, ynum)) in enumerate(zip(islice(windows, self.num_full_size_windows, None), ylayout)):
            w.set_geometry(i + self.num_full_size_windows, window_geometry(x, xnum, ystart, ynum))
        # right bottom blank rect
        self.bottom_blank_rect(windows[-1])
        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])

    def neighbors_for_window(self, window, windows):
        idx = windows.index(window)
        prev = None if idx == 0 else windows[idx-1]
        nxt = None if idx == len(windows) - 1 else windows[idx+1]
        ans = {'left': [prev] if prev is not None else [], 'right': [], 'top': [], 'bottom': []}
        if idx < self.num_full_size_windows - 1:
            if nxt is not None:
                ans['right'] = [nxt]
        elif idx == self.num_full_size_windows - 1:
            ans['right'] = windows[idx+1:]
        else:
            ans['left'] = [windows[self.num_full_size_windows - 1]]
            if idx > self.num_full_size_windows:
                ans['top'] = [prev]
            if nxt is not None:
                ans['bottom'] = [nxt]
        return ans

    def minimal_borders(self, windows, active_window, needs_borders_map):
        last_i = len(windows) - 1
        for i, w in enumerate(windows):
            if needs_borders_map[w.id]:
                yield all_borders
                continue
            if i < self.num_full_size_windows:
                if (last_i == i+1 or i+1 < self.num_full_size_windows) and needs_borders_map[windows[i+1].id]:
                    yield no_borders
                else:
                    yield no_borders if i == last_i else self.only_main_border
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
        x, xnum = next(self.vlayout(1))
        if len(windows) <= self.num_full_size_windows:
            bias = normalize_biases(self.main_bias[:-1])
            ylayout = self.ylayout(self.num_full_size_windows, bias=bias)
            for i, (w, (y, ynum)) in enumerate(zip(windows, ylayout)):
                w.set_geometry(i, window_geometry(x, xnum, y, ynum))
                if i > 0:
                    self.between_blank_rect(windows[i-1], windows[i], vertical=False)
            # bottom blank rect
            self.bottom_blank_rect(windows[-1])
            # left, top and right blank rects
            self.simple_blank_rects(windows[0], windows[-1])
            return

        ylayout = self.ylayout(self.num_full_size_windows + 1, bias=self.main_bias)
        for i in range(self.num_full_size_windows):
            w = windows[i]
            y, ynum = next(ylayout)
            w.set_geometry(i, window_geometry(x, xnum, y, ynum))
            self.between_blank_rect(windows[i], windows[i+1], vertical=False)
        y, ynum = next(ylayout)
        xlayout = self.variable_layout(len(windows), self.biased_map)
        for i, (w, (x, xnum)) in enumerate(zip(islice(windows, self.num_full_size_windows, None), xlayout)):
            w.set_geometry(i + self.num_full_size_windows, window_geometry(x, xnum, y, ynum))
            # bottom blank rect
            self.bottom_blank_rect(windows[i])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])

    def neighbors_for_window(self, window, windows):
        idx = windows.index(window)
        prev = None if idx == 0 else windows[idx-1]
        nxt = None if idx == len(windows) - 1 else windows[idx+1]
        ans = {'left': [], 'right': [], 'top': [] if prev is None else [prev], 'bottom': []}
        if idx < self.num_full_size_windows - 1:
            if nxt is not None:
                ans['bottom'] = [nxt]
        elif idx == self.num_full_size_windows - 1:
            ans['bottom'] = windows[idx+1:]
        else:
            ans['top'] = [windows[self.num_full_size_windows - 1]]
            if idx > self.num_full_size_windows:
                ans['left'] = [prev]
            if nxt is not None:
                ans['right'] = [nxt]
        return ans

# }}}


# Grid {{{
@lru_cache()
def calc_grid_size(n):
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

    def remove_all_biases(self):
        self.biased_rows = {}
        self.biased_cols = {}
        return True

    def variable_layout(self, layout_func, num_windows, biased_map):
        return layout_func(num_windows, bias=variable_bias(num_windows, biased_map) if num_windows > 1 else None)

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        b = self.biased_cols if is_horizontal else self.biased_rows
        ncols, nrows, special_rows, special_col = calc_grid_size(num_windows)

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
        ncols, nrows, special_rows, special_col = calc_grid_size(n)

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
        n = len(windows)
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
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
        ncols, nrows, special_rows, special_col = calc_grid_size(n)
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


# Splits {{{
class Pair:

    def __init__(self, horizontal=True):
        self.horizontal = horizontal
        self.one = self.two = None
        self.bias = 0.5
        self.between_border = None

    def __repr__(self):
        return 'Pair(horizontal={}, bias={:.2f}, one={}, two={}, between_border={})'.format(
                self.horizontal, self.bias, self.one, self.two, self.between_border)

    def all_window_ids(self):
        if self.one is not None:
            if isinstance(self.one, Pair):
                yield from self.one.all_window_ids()
            yield self.one
        if self.two is not None:
            if isinstance(self.two, Pair):
                yield from self.two.all_window_ids()
            yield self.two

    def self_and_descendants(self):
        yield self
        if isinstance(self.one, Pair):
            yield from self.one.self_and_descendants()
        if isinstance(self.two, Pair):
            yield from self.two.self_and_descendants()

    def pair_for_window(self, window_id):
        if self.one == window_id or self.two == window_id:
            return self
        ans = None
        if isinstance(self.one, Pair):
            ans = self.one.pair_for_window(window_id)
        if ans is None and isinstance(self.two, Pair):
            ans = self.two.pair_for_window(window_id)
        return ans

    def parent(self, root):
        for q in root.self_and_descendants():
            if q.one is self or q.two is self:
                return q

    def remove_windows(self, window_ids):
        if isinstance(self.one, int) and self.one in window_ids:
            self.one = None
        if isinstance(self.two, int) and self.two in window_ids:
            self.two = None
        if self.one is None and self.two is not None:
            self.one, self.two = self.two, None

    @property
    def is_redundant(self):
        return self.one is None or self.two is None

    def collapse_redundant_pairs(self):
        while isinstance(self.one, Pair) and self.one.is_redundant:
            self.one = self.one.one or self.one.two
        while isinstance(self.two, Pair) and self.two.is_redundant:
            self.two = self.two.one or self.two.two
        if isinstance(self.one, Pair):
            self.one.collapse_redundant_pairs()
        if isinstance(self.two, Pair):
            self.two.collapse_redundant_pairs()

    def balanced_add(self, window_id):
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
        pair.balanced_add(window_to_be_split)
        pair.balanced_add(window_id)
        return pair

    def split_and_add(self, existing_window_id, new_window_id, horizontal, after):
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

    def apply_window_geometry(self, window_id, window_geometry, id_window_map, id_idx_map):
        w = id_window_map[window_id]
        w.set_geometry(id_idx_map[window_id], window_geometry)
        if w.overlay_window_id is not None:
            w = id_window_map.get(w.overlay_window_id)
            if w is not None:
                w.set_geometry(id_idx_map[w.id], window_geometry)

    def blank_rects_for_window(self, layout_object: 'Splits', window, left: float, top: float, width: float, height: float):
        right = left + width - 1
        bottom = top + height - 1
        g: WindowGeometry = window.geometry
        rects: list = layout_object.blank_rects
        lt = g.left
        if lt > left:
            rects.append(Rect(left, top, lt, bottom + 1))
        r = g.right
        if r <= right:
            rects.append(Rect(r, top, right + 1, bottom + 1))
        t = g.top
        if t > top:
            rects.append(Rect(left, top, right + 1, t))
        b = g.bottom
        if b <= bottom:
            rects.append(Rect(left, b, right + 1, bottom + 1))

    def layout_pair(self, left, top, width, height, id_window_map, id_idx_map, layout_object):
        self.between_border = None
        if self.one is None or self.two is None:
            q = self.one or self.two
            if isinstance(q, Pair):
                return q.layout_pair(left, top, width, height, id_window_map, id_idx_map, layout_object)
            if q is None:
                return
            xstart, xnum = next(layout_object.xlayout(1, left=left, width=width))
            ystart, ynum = next(layout_object.ylayout(1, top=top, height=height))
            geom = window_geometry(xstart, xnum, ystart, ynum)
            self.apply_window_geometry(q, geom, id_window_map, id_idx_map)
            self.blank_rects_for_window(layout_object, id_window_map[q], left, top, width, height)
            return
        bw = layout_object.border_width if draw_minimal_borders else 0
        b1 = bw // 2
        b2 = bw - b1
        if self.horizontal:
            ystart, ynum = next(layout_object.ylayout(1, top=top, height=height))
            w1 = max(2*cell_width + 1, int(self.bias * width) - b1)
            w2 = max(2*cell_width + 1, width - w1 - b1 - b2)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, w1, height, id_window_map, id_idx_map, layout_object)
            else:
                xstart, xnum = next(layout_object.xlayout(1, left=left, width=w1))
                self.apply_window_geometry(self.one, window_geometry(xstart, xnum, ystart, ynum), id_window_map, id_idx_map)
                self.blank_rects_for_window(layout_object, id_window_map[self.one], left, top, w1, height)
            if b1 + b2:
                self.between_border = (left + w1, top, left + w1 + b1 + b2, top + height)
            left += b1 + b2
            if isinstance(self.two, Pair):
                self.two.layout_pair(left + w1, top, w2, height, id_window_map, id_idx_map, layout_object)
            else:
                xstart, xnum = next(layout_object.xlayout(1, left=left + w1, width=w2))
                self.apply_window_geometry(self.two, window_geometry(xstart, xnum, ystart, ynum), id_window_map, id_idx_map)
                self.blank_rects_for_window(layout_object, id_window_map[self.two], left + w1, top, w2, height)
        else:
            xstart, xnum = next(layout_object.xlayout(1, left=left, width=width))
            h1 = max(2*cell_height + 1, int(self.bias * height) - b1)
            h2 = max(2*cell_height + 1, height - h1 - b1 - b2)
            if isinstance(self.one, Pair):
                self.one.layout_pair(left, top, width, h1, id_window_map, id_idx_map, layout_object)
            else:
                ystart, ynum = next(layout_object.ylayout(1, top=top, height=h1))
                self.apply_window_geometry(self.one, window_geometry(xstart, xnum, ystart, ynum), id_window_map, id_idx_map)
                self.blank_rects_for_window(layout_object, id_window_map[self.one], left, top, width, h1)
            if b1 + b2:
                self.between_border = (left, top + h1, left + width, top + h1 + b1 + b2)
            top += b1 + b2
            if isinstance(self.two, Pair):
                self.two.layout_pair(left, top + h1, width, h2, id_window_map, id_idx_map, layout_object)
            else:
                ystart, ynum = next(layout_object.ylayout(1, top=top + h1, height=h2))
                self.apply_window_geometry(self.two, window_geometry(xstart, xnum, ystart, ynum), id_window_map, id_idx_map)
                self.blank_rects_for_window(layout_object, id_window_map[self.two], left, top + h1, width, h2)

    def modify_size_of_child(self, which: int, increment: float, is_horizontal: bool, layout_object: 'Splits'):
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

    def neighbors_for_window(self, window_id: int, ans: dict, layout_object: 'Splits'):

        def quadrant(is_horizontal, is_first):
            if is_horizontal:
                edge, which = ('left', 'right') if is_first else ('right', 'left')
            else:
                edge, which = ('top', 'bottom') if is_first else ('bottom', 'top')
            return edge, which

        def extend(other, edge, which):
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

    def edge_windows(self, edge):
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


class Splits(Layout):
    name = 'splits'
    needs_all_windows = True

    @property
    def default_axis_is_horizontal(self):
        return self.layout_opts['default_axis_is_horizontal']

    @property
    def pairs_root(self):
        root = getattr(self, '_pairs_root', None)
        if root is None:
            self._pairs_root = root = Pair(horizontal=self.default_axis_is_horizontal)
        return root

    @pairs_root.setter
    def pairs_root(self, root):
        self._pairs_root = root

    def parse_layout_opts(self, layout_opts):
        ans = Layout.parse_layout_opts(self, layout_opts)
        ans['default_axis_is_horizontal'] = ans.get('split_axis', 'horizontal') == 'horizontal'
        return ans

    def do_layout(self, windows, active_window_idx, all_windows):
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
            root.layout_pair(central.left, central.top, central.width, central.height, id_window_map, id_idx_map, self)

    def do_add_window(self, all_windows, window, current_active_window_idx, location):
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
        if 0 <= current_active_window_idx < len(all_windows):
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

    def modify_size_of_window(self, all_windows, window_id, increment, is_horizontal=True):
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

    def remove_all_biases(self):
        for pair in self.pairs_root.self_and_descendants():
            pair.bias = 0.5
        return True

    def window_independent_borders(self, windows, active_windows):
        if not draw_minimal_borders:
            return
        for pair in self.pairs_root.self_and_descendants():
            if pair.between_border is not None:
                yield pair.between_border

    def neighbors_for_window(self, window, windows):
        window_id = window.overlay_for or window.id
        pair = self.pairs_root.pair_for_window(window_id)
        ans = {'left': [], 'right': [], 'top': [], 'bottom': []}
        if pair is not None:
            pair.neighbors_for_window(window_id, ans, self)
        return ans

    def swap_windows_in_layout(self, all_windows, a, b):
        w1, w2 = all_windows[a], all_windows[b]
        super().swap_windows_in_layout(all_windows, a, b)
        w1 = w1.overlay_for or w1.id
        w2 = w2.overlay_for or w2.id
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
