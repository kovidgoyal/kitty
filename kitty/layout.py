#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from itertools import islice

from .constants import WindowGeometry, viewport_size, cell_size, tab_manager


def available_height():
    return viewport_size.height - tab_manager().current_tab_bar_height


def layout_dimension(length, cell_length, number_of_windows=1, border_length=0):
    number_of_cells = length // cell_length
    space_needed_for_border = number_of_windows * 2 * border_length
    extra = length - number_of_cells * cell_length
    while extra < space_needed_for_border:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    cells_per_window = number_of_cells // number_of_windows
    extra -= space_needed_for_border
    pos = (extra // 2) + border_length
    inner_length = cells_per_window * cell_length
    window_length = 2 * border_length + inner_length
    extra = number_of_cells - (cells_per_window * number_of_windows)
    while number_of_windows > 0:
        number_of_windows -= 1
        yield pos, cells_per_window + (extra if number_of_windows == 0 else 0)
        pos += window_length


class Layout:

    name = None
    needs_window_borders = True

    def __init__(self, opts, border_width, windows):
        self.opts = opts
        self.border_width = border_width

    def next_window(self, windows, active_window_idx):
        active_window_idx = (active_window_idx + 1) % len(windows)
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


def layout_single_window():
    xstart, xnum = next(layout_dimension(viewport_size.width, cell_size.width))
    ystart, ynum = next(layout_dimension(available_height(), cell_size.height))
    return window_geometry(xstart, xnum, ystart, ynum)


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False

    def set_active_window(self, windows, active_window_idx):
        for i, w in enumerate(windows):
            w.is_visible_in_layout = i == active_window_idx

    def __call__(self, windows, active_window_idx):
        wg = layout_single_window()
        for i, w in enumerate(windows):
            w.is_visible_in_layout = i == active_window_idx
            w.set_geometry(wg)


class Tall(Layout):

    name = 'tall'

    def set_active_window(self, windows, active_window_idx):
        pass

    def __call__(self, windows, active_window_idx):
        if len(windows) == 1:
            wg = layout_single_window()
            windows[0].set_geometry(wg)
            return
        xlayout = layout_dimension(viewport_size.width, cell_size.width, 2, self.border_width)
        xstart, xnum = next(xlayout)
        ystart, ynum = next(layout_dimension(available_height(), cell_size.height, 1, self.border_width))
        windows[0].set_geometry(window_geometry(xstart, xnum, ystart, ynum))
        xstart, xnum = next(xlayout)
        ylayout = layout_dimension(available_height(), cell_size.height, len(windows) - 1, self.border_width)
        for w, (ystart, ynum) in zip(islice(windows, 1, None), ylayout):
            w.set_geometry(window_geometry(xstart, xnum, ystart, ynum))


all_layouts = {o.name: o for o in globals().values() if isinstance(o, type) and issubclass(o, Layout) and o is not Layout}
