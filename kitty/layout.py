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

central = Region((0, 0, 199, 199, 200, 200))
cell_width = cell_height = 20


def idx_for_id(win_id, windows):
    for i, w in enumerate(windows):
        if w.id == win_id:
            return i


def layout_dimension(start_at, length, cell_length, number_of_windows=1, border_length=0, margin_length=0, padding_length=0, left_align=False, bias=None):
    number_of_cells = length // cell_length
    border_length += padding_length
    space_needed_for_border = number_of_windows * 2 * border_length
    space_needed_for_padding = number_of_windows * 2 * margin_length
    space_needed = space_needed_for_padding + space_needed_for_border
    extra = length - number_of_cells * cell_length
    while extra < space_needed:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    cells_per_window = number_of_cells // number_of_windows
    extra -= space_needed
    pos = start_at
    if not left_align:
        pos += extra // 2
    pos += border_length + margin_length

    def calc_window_length(cells_in_window):
        inner_length = cells_in_window * cell_length
        return 2 * (border_length + margin_length) + inner_length

    if bias is not None and number_of_windows > 1 and len(bias) == number_of_windows and cells_per_window > 5:
        cells_map = [int(b * number_of_cells) for b in bias]
        while min(cells_map) < 5:
            maxi, mini = map(cells_map.index, (max(cells_map), min(cells_map)))
            if maxi == mini:
                break
            cells_map[mini] += 1
            cells_map[maxi] -= 1

        extra = number_of_cells - sum(cells_map)
        if extra:
            cells_map[-1] += extra
        for cells_per_window in cells_map:
            window_length = calc_window_length(cells_per_window)
            yield pos, cells_per_window
            pos += window_length
        return

    window_length = calc_window_length(cells_per_window)
    extra = number_of_cells - (cells_per_window * number_of_windows)
    while number_of_windows > 0:
        number_of_windows -= 1
        yield pos, cells_per_window + (extra if number_of_windows == 0 else 0)
        pos += window_length


Rect = namedtuple('Rect', 'left top right bottom')


def process_overlaid_windows(all_windows):
    id_map = {w.id: w for w in all_windows}
    overlaid_windows = frozenset(w for w in all_windows if w.overlay_window_id is not None and w.overlay_window_id in id_map)
    windows = [w for w in all_windows if w not in overlaid_windows]
    return overlaid_windows, windows


class Layout:

    name = None
    needs_window_borders = True
    only_active_window_visible = False

    def __init__(self, os_window_id, tab_id, margin_width, padding_width, border_width, layout_opts=''):
        self.os_window_id = os_window_id
        self.tab_id = tab_id
        self.set_active_window_in_os_window = partial(set_active_window, os_window_id, tab_id)
        self.swap_windows_in_os_window = partial(swap_windows, os_window_id, tab_id)
        self.border_width = border_width
        self.margin_width = margin_width
        self.padding_width = padding_width
        # A set of rectangles corresponding to the blank spaces at the edges of
        # this layout, i.e. spaces that are not covered by any window
        self.blank_rects = ()
        self.layout_opts = self.parse_layout_opts(layout_opts)
        self.full_name = self.name + ((':' + layout_opts) if layout_opts else '')
        self.initialize_sub_class()

    def initialize_sub_class(self):
        pass

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        return False

    def remove_all_biases(self):
        return False

    def modify_size_of_window(self, all_windows, window_id, increment, is_horizontal=True):
        idx = idx_for_id(window_id, all_windows)
        if idx is None:
            return
        w = all_windows[idx]
        windows = process_overlaid_windows(all_windows)[1]
        idx = idx_for_id(w.id, windows)
        if idx is None:
            idx = idx_for_id(w.overlay_window_id, windows)
        if idx is not None:
            return self.apply_bias(idx, increment, len(windows), is_horizontal)

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

    def move_window(self, all_windows, active_window_idx, delta=1):
        w = all_windows[active_window_idx]
        windows = process_overlaid_windows(all_windows)[1]
        if len(windows) < 2 or abs(delta) == 0:
            return active_window_idx
        idx = idx_for_id(w.id, windows)
        if idx is None:
            idx = idx_for_id(w.overlay_window_id, windows)
        nidx = (idx + len(windows) + delta) % len(windows)
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

    def __call__(self, all_windows, active_window_idx):
        global central, cell_width, cell_height
        central, tab_bar, vw, vh, cell_width, cell_height = viewport_for_window(self.os_window_id)

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
        self.do_layout(windows, active_window_idx)
        return idx_for_id(active_window.id, all_windows)

    # Utils {{{
    def xlayout(self, num, bias=None):
        return layout_dimension(
            central.left, central.width, cell_width, num, self.border_width,
            margin_length=self.margin_width, padding_length=self.padding_width, bias=bias)

    def ylayout(self, num, left_align=True, bias=None):
        return layout_dimension(
            central.top, central.height, cell_height, num, self.border_width, left_align=left_align,
            margin_length=self.margin_width, padding_length=self.padding_width, bias=bias)

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


def window_geometry(xstart, xnum, ystart, ynum):
    return WindowGeometry(left=xstart, top=ystart, xnum=xnum, ynum=ynum, right=xstart + cell_width * xnum, bottom=ystart + cell_height * ynum)


def layout_single_window(margin_length, padding_length):
    xstart, xnum = next(layout_dimension(central.left, central.width, cell_width, margin_length=margin_length, padding_length=padding_length))
    ystart, ynum = next(layout_dimension(central.top, central.height, cell_height, margin_length=margin_length, padding_length=padding_length))
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


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False
    only_active_window_visible = True

    def do_layout(self, windows, active_window_idx):
        self.blank_rects = []
        wg = layout_single_window(self.margin_width, self.padding_width)
        for i, w in enumerate(windows):
            w.set_geometry(i, wg)
            if w.is_visible_in_layout:
                self.blank_rects = blank_rects_for_window(w)


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


class Tall(Layout):

    name = 'tall'

    def initialize_sub_class(self):
        self.remove_all_biases()

    def remove_all_biases(self):
        self.x_bias = list(self.layout_opts['bias'])
        self.biased_rows = {}
        return True

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        if is_horizontal:
            before = self.x_bias
            if idx == 0:
                self.x_bias = [safe_increment_bias(self.x_bias[0], increment), safe_increment_bias(self.x_bias[1], -increment)]
            else:
                self.x_bias = [safe_increment_bias(self.x_bias[0], -increment), safe_increment_bias(self.x_bias[1], increment)]
            self.x_bias = normalize_biases(self.x_bias)
            after = self.x_bias
        else:
            if idx == 0:
                return False
            idx -= 1
            before = self.biased_rows.get(idx, 0)
            self.biased_rows[idx] = after = before + increment
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
        self.blank_rects = []
        if len(windows) == 1:
            wg = layout_single_window(self.margin_width, self.padding_width)
            windows[0].set_geometry(0, wg)
            self.blank_rects = blank_rects_for_window(windows[0])
            return
        xlayout = self.xlayout(2, bias=self.x_bias)
        xstart, xnum = next(xlayout)
        ystart, ynum = next(self.ylayout(1))
        windows[0].set_geometry(0, window_geometry(xstart, xnum, ystart, ynum))
        xstart, xnum = next(xlayout)
        if len(windows) > 2:
            y_bias = distribute_indexed_bias(list(repeat(1/(len(windows) - 1), len(windows) - 1)), self.biased_rows)
        else:
            y_bias = None
        ylayout = self.ylayout(len(windows) - 1, bias=y_bias)
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


class Fat(Tall):

    name = 'fat'

    def remove_all_biases(self):
        self.y_bias = list(self.layout_opts['bias'])
        self.biased_columns = {}
        return True

    def apply_bias(self, idx, increment, num_windows, is_horizontal):
        if not is_horizontal:
            before = self.y_bias
            if idx == 0:
                self.y_bias = [safe_increment_bias(self.y_bias[0], increment), safe_increment_bias(self.y_bias[1], -increment)]
            else:
                self.y_bias = [safe_increment_bias(self.y_bias[0], -increment), safe_increment_bias(self.y_bias[1], increment)]
            self.y_bias = normalize_biases(self.y_bias)
            after = self.y_bias
        else:
            if idx == 0:
                return False
            idx -= 1
            before = self.biased_columns.get(idx, 0)
            self.biased_columns[idx] = after = before + increment
        return before != after

    def do_layout(self, windows, active_window_idx):
        self.blank_rects = []
        if len(windows) == 1:
            wg = layout_single_window(self.margin_width, self.padding_width)
            windows[0].set_geometry(0, wg)
            self.blank_rects = blank_rects_for_window(windows[0])
            return
        xstart, xnum = next(self.xlayout(1))
        ylayout = self.ylayout(2, bias=self.y_bias)
        ystart, ynum = next(ylayout)
        windows[0].set_geometry(0, window_geometry(xstart, xnum, ystart, ynum))
        if len(windows) > 2:
            x_bias = distribute_indexed_bias(list(repeat(1/(len(windows) - 1), len(windows) - 1)), self.biased_columns)
        else:
            x_bias = None
        xlayout = self.xlayout(len(windows) - 1, bias=x_bias)
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


class Grid(Tall):

    name = 'grid'

    def do_layout(self, windows, active_window_idx):
        n = len(windows)
        if n < 4:
            return Tall.do_layout(self, windows, active_window_idx)
        self.blank_rects = []
        if n <= 5:
            ncols = 2
        else:
            for ncols in range(3, (n // 2) + 1):
                if ncols * ncols >= n:
                    break
        nrows = n // ncols
        special_rows = n - (nrows * (ncols - 1))
        special_col = 0 if special_rows < nrows else ncols - 1

        # Distribute windows top-to-bottom, left-to-right (i.e. in columns)
        xlayout = self.xlayout(ncols)
        yvals_normal = tuple(self.ylayout(nrows))
        yvals_special = yvals_normal if special_rows == nrows else tuple(self.ylayout(special_rows))

        winmap = list(enumerate(windows))
        pos = 0
        win_col_map = []
        for col in range(ncols):
            rows = special_rows if col == special_col else nrows
            yl = yvals_special if col == special_col else yvals_normal
            xstart, xnum = next(xlayout)
            col_windows = []
            for (ystart, ynum), (window_idx, w) in zip(yl, winmap[pos:pos + rows]):
                w.set_geometry(window_idx, window_geometry(xstart, xnum, ystart, ynum))
                col_windows.append(w)
            # bottom blank rect
            self.bottom_blank_rect(w)
            pos += rows
            win_col_map.append(col_windows)

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])

        # the in-between columns blank rects
        for i in range(ncols - 1):
            self.between_blank_rect(win_col_map[i][0], win_col_map[i + 1][0])


class Vertical(Layout):

    name = 'vertical'

    def do_layout(self, windows, active_window_idx):
        self.blank_rects = []
        window_count = len(windows)
        if window_count == 1:
            wg = layout_single_window(self.margin_width, self.padding_width)
            windows[0].set_geometry(0, wg)
            self.blank_rects = blank_rects_for_window(windows[0])
            return

        xlayout = self.xlayout(1)
        xstart, xnum = next(xlayout)
        ylayout = self.ylayout(window_count)

        for i in range(window_count):
            ystart, ynum = next(ylayout)
            windows[i].set_geometry(i, window_geometry(xstart, xnum, ystart, ynum))
            # bottom blank rect
            self.bottom_blank_rect(windows[i])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])


class Horizontal(Layout):

    name = 'horizontal'

    def do_layout(self, windows, active_window_idx):
        self.blank_rects = []
        window_count = len(windows)
        if window_count == 1:
            wg = layout_single_window(self.margin_width, self.padding_width)
            windows[0].set_geometry(0, wg)
            self.blank_rects = blank_rects_for_window(windows[0])
            return

        xlayout = self.xlayout(window_count)
        ylayout = self.ylayout(1)
        ystart, ynum = next(ylayout)

        for i in range(window_count):
            xstart, xnum = next(xlayout)
            windows[i].set_geometry(i, window_geometry(xstart, xnum, ystart, ynum))
            if i > 0:
                # between blank rect
                self.between_blank_rect(windows[i - 1], windows[i])

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])
        # bottom blank rect
        self.blank_rects.append(Rect(windows[0].geometry.left, windows[0].geometry.bottom, windows[-1].geometry.right, central.bottom + 1))


all_layouts = {o.name: o for o in globals().values() if isinstance(o, type) and issubclass(o, Layout) and o is not Layout}


def create_layout_object_for(name, os_window_id, tab_id, margin_width, padding_width, border_width, layout_opts=''):
    key = name, os_window_id, tab_id, margin_width, padding_width, border_width, layout_opts
    ans = create_layout_object_for.cache.get(key)
    if ans is None:
        name, layout_opts = name.partition(':')[::2]
        ans = create_layout_object_for.cache[key] = all_layouts[name](os_window_id, tab_id, margin_width, padding_width, border_width, layout_opts)
    return ans


create_layout_object_for.cache = {}


def evict_cached_layouts(tab_id):
    remove = [key for key in create_layout_object_for.cache if key[2] == tab_id]
    for key in remove:
        del create_layout_object_for.cache[key]
