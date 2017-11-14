#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections import namedtuple
from itertools import islice

from .constants import WindowGeometry, get_boss
from .utils import pt_to_px


def available_height():
    return viewport_size.height - get_boss().current_tab_bar_height


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

    def __init__(self, opts, border_width, windows):
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

    def set_active_window(self, windows, active_window_idx):
        pass

    def __call__(self, windows, active_window_idx):
        raise NotImplementedError()


def window_geometry(xstart, xnum, ystart, ynum):
    return WindowGeometry(left=xstart, top=ystart, xnum=xnum, ynum=ynum, right=xstart + cell_size.width * xnum, bottom=ystart + cell_size.height * ynum)


def layout_single_window(margin_length, padding_length):
    xstart, xnum = next(layout_dimension(viewport_size.width, cell_size.width, margin_length=margin_length, padding_length=padding_length))
    ystart, ynum = next(layout_dimension(available_height(), cell_size.height, margin_length=margin_length, padding_length=padding_length))
    return window_geometry(xstart, xnum, ystart, ynum)


def left_blank_rect(w, rects, vh):
    if w.geometry.left > 0:
        rects.append(Rect(0, 0, w.geometry.left, vh))


def right_blank_rect(w, rects, vh):
    if w.geometry.right < viewport_size.width:
        rects.append(Rect(w.geometry.right, 0, viewport_size.width, vh))


def top_blank_rect(w, rects, vh):
    if w.geometry.top > 0:
        rects.append(Rect(0, 0, viewport_size.width, w.geometry.top))


def bottom_blank_rect(w, rects, vh):
    if w.geometry.bottom < available_height():
        rects.append(Rect(0, w.geometry.bottom, viewport_size.width, vh))


def blank_rects_for_window(w):
    ans = []
    vh = available_height()
    left_blank_rect(w, ans, vh), top_blank_rect(w, ans, vh), right_blank_rect(w, ans, vh), bottom_blank_rect(w, ans, vh)
    return ans


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False

    def set_active_window(self, windows, active_window_idx):
        for i, w in enumerate(windows):
            w.set_visible_in_layout(i, i == active_window_idx)

    def __call__(self, windows, active_window_idx):
        self.blank_rects = []
        wg = layout_single_window(self.margin_width, self.padding_width)
        for i, w in enumerate(windows):
            w.set_visible_in_layout(i, i == active_window_idx)
            w.set_geometry(i, wg)
            if w.is_visible_in_layout:
                self.blank_rects = blank_rects_for_window(w)


class Tall(Layout):

    name = 'tall'

    def __call__(self, windows, active_window_idx):
        self.blank_rects = br = []
        if len(windows) == 1:
            wg = layout_single_window(self.margin_width, self.padding_width)
            windows[0].set_geometry(0, wg)
            self.blank_rects = blank_rects_for_window(windows[0])
            return
        xlayout = layout_dimension(
            viewport_size.width, cell_size.width, 2, self.border_width,
            margin_length=self.margin_width, padding_length=self.padding_width)
        xstart, xnum = next(xlayout)
        ystart, ynum = next(layout_dimension(
            available_height(), cell_size.height, 1, self.border_width, left_align=True,
            margin_length=self.margin_width, padding_length=self.padding_width))
        windows[0].set_geometry(0, window_geometry(xstart, xnum, ystart, ynum))
        vh = available_height()
        xstart, xnum = next(xlayout)
        ylayout = layout_dimension(
            available_height(), cell_size.height, len(windows) - 1, self.border_width, left_align=True,
            margin_length=self.margin_width, padding_length=self.padding_width)
        for i, (w, (ystart, ynum)) in enumerate(zip(islice(windows, 1, None), ylayout)):
            w.set_geometry(i + 1, window_geometry(xstart, xnum, ystart, ynum))
        left_blank_rect(windows[0], br, vh), top_blank_rect(windows[0], br, vh), right_blank_rect(windows[-1], br, vh)
        br.append(Rect(windows[0].geometry.right, 0, windows[1].geometry.left, vh))
        br.append(Rect(0, windows[0].geometry.bottom, windows[0].geometry.right, vh))
        br.append(Rect(windows[-1].geometry.left, windows[-1].geometry.bottom, viewport_size.width, vh))


all_layouts = {o.name: o for o in globals().values() if isinstance(o, type) and issubclass(o, Layout) and o is not Layout}
