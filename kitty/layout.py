#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from itertools import islice

from .constants import WindowGeometry
from .utils import pt_to_px
from .fast_data_types import viewport_for_window


viewport_width = viewport_height = available_height = 400
cell_width = cell_height = 20


def layout_dimension(length, cell_length, number_of_windows=1, border_length=0, margin_length=0, padding_length=0, left_align=False):
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
    pos = 0 if left_align else (extra // 2)
    pos += border_length + margin_length
    inner_length = cells_per_window * cell_length
    window_length = 2 * (border_length + margin_length) + inner_length
    extra = number_of_cells - (cells_per_window * number_of_windows)
    while number_of_windows > 0:
        number_of_windows -= 1
        yield pos, cells_per_window + (extra if number_of_windows == 0 else 0)
        pos += window_length


Rect = namedtuple('Rect', 'left top right bottom')


class Layout:

    name = None
    needs_window_borders = True

    def __init__(self, os_window_id, opts, border_width, windows):
        self.os_window_id = os_window_id
        self.opts = opts
        self.border_width = border_width
        self.margin_width = pt_to_px(opts.window_margin_width)
        self.padding_width = pt_to_px(opts.window_padding_width)
        # A set of rectangles corresponding to the blank spaces at the edges of
        # this layout, i.e. spaces that are not covered by any window
        self.blank_rects = ()

    def next_window(self, windows, active_window_idx, delta=1):
        active_window_idx = (active_window_idx + len(windows) + delta) % len(windows)
        self.set_active_window(windows, active_window_idx)
        return active_window_idx

    def add_window(self, windows, window, active_window_idx):
        active_window_idx = len(windows)
        windows.append(window)
        self(windows, active_window_idx)
        return active_window_idx

    def remove_window(self, windows, window, active_window_idx):
        windows.remove(window)
        active_window_idx = max(0, min(active_window_idx, len(windows) - 1))
        if windows:
            self(windows, active_window_idx)
        return active_window_idx

    def xlayout(self, num):
        return layout_dimension(
            viewport_width, cell_width, num, self.border_width,
            margin_length=self.margin_width, padding_length=self.padding_width)

    def ylayout(self, num, left_align=True):
        return layout_dimension(
            available_height, cell_height, num, self.border_width, left_align=left_align,
            margin_length=self.margin_width, padding_length=self.padding_width)

    def simple_blank_rects(self, first_window, last_window):
        br, vh = self.blank_rects, available_height
        left_blank_rect(first_window, br, vh), top_blank_rect(first_window, br, vh), right_blank_rect(last_window, br, vh)

    def between_blank_rect(self, left_window, right_window):
        self.blank_rects.append(Rect(left_window.geometry.right, 0, right_window.geometry.left, available_height))

    def bottom_blank_rect(self, window):
        self.blank_rects.append(Rect(window.geometry.left, window.geometry.bottom, window.geometry.right, available_height))

    def set_active_window(self, windows, active_window_idx):
        pass

    def __call__(self, windows, active_window_idx):
        global viewport_width, viewport_height, cell_width, cell_height, available_height
        viewport_width, viewport_height, available_height, cell_width, cell_height = viewport_for_window(self.os_window_id)
        self.do_layout(windows, active_window_idx)

    def do_layout(self, windows, active_window_idx):
        raise NotImplementedError()


def window_geometry(xstart, xnum, ystart, ynum):
    return WindowGeometry(left=xstart, top=ystart, xnum=xnum, ynum=ynum, right=xstart + cell_width * xnum, bottom=ystart + cell_height * ynum)


def layout_single_window(margin_length, padding_length):
    xstart, xnum = next(layout_dimension(viewport_width, cell_width, margin_length=margin_length, padding_length=padding_length))
    ystart, ynum = next(layout_dimension(available_height, cell_height, margin_length=margin_length, padding_length=padding_length))
    return window_geometry(xstart, xnum, ystart, ynum)


def left_blank_rect(w, rects, vh):
    if w.geometry.left > 0:
        rects.append(Rect(0, 0, w.geometry.left, vh))


def right_blank_rect(w, rects, vh):
    if w.geometry.right < viewport_width:
        rects.append(Rect(w.geometry.right, 0, viewport_width, vh))


def top_blank_rect(w, rects, vh):
    if w.geometry.top > 0:
        rects.append(Rect(0, 0, viewport_width, w.geometry.top))


def bottom_blank_rect(w, rects, vh):
    if w.geometry.bottom < available_height:
        rects.append(Rect(0, w.geometry.bottom, viewport_width, vh))


def blank_rects_for_window(w):
    ans = []
    vh = available_height
    left_blank_rect(w, ans, vh), top_blank_rect(w, ans, vh), right_blank_rect(w, ans, vh), bottom_blank_rect(w, ans, vh)
    return ans


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False

    def set_active_window(self, windows, active_window_idx):
        for i, w in enumerate(windows):
            w.set_visible_in_layout(i, i == active_window_idx)

    def do_layout(self, windows, active_window_idx):
        self.blank_rects = []
        wg = layout_single_window(self.margin_width, self.padding_width)
        for i, w in enumerate(windows):
            w.set_visible_in_layout(i, i == active_window_idx)
            w.set_geometry(i, wg)
            if w.is_visible_in_layout:
                self.blank_rects = blank_rects_for_window(w)


class Tall(Layout):

    name = 'tall'

    def do_layout(self, windows, active_window_idx):
        self.blank_rects = []
        if len(windows) == 1:
            wg = layout_single_window(self.margin_width, self.padding_width)
            windows[0].set_geometry(0, wg)
            self.blank_rects = blank_rects_for_window(windows[0])
            return
        xlayout = self.xlayout(2)
        xstart, xnum = next(xlayout)
        ystart, ynum = next(self.ylayout(1))
        windows[0].set_geometry(0, window_geometry(xstart, xnum, ystart, ynum))
        xstart, xnum = next(xlayout)
        ylayout = self.ylayout(len(windows) - 1)
        for i, (w, (ystart, ynum)) in enumerate(zip(islice(windows, 1, None), ylayout)):
            w.set_geometry(i + 1, window_geometry(xstart, xnum, ystart, ynum))

        # left, top and right blank rects
        self.simple_blank_rects(windows[0], windows[-1])
        # between blank rect
        self.between_blank_rect(windows[0], windows[1])
        # left bottom blank rect
        self.bottom_blank_rect(windows[0])
        # right bottom blank rect
        self.bottom_blank_rect(windows[-1])


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


all_layouts = {o.name: o for o in globals().values() if isinstance(o, type) and issubclass(o, Layout) and o is not Layout}
