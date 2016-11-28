#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from .constants import WindowGeometry, viewport_size, cell_size, tab_manager


def available_height():
    return viewport_size.height - tab_manager().current_tab_bar_height


def layout_dimension(length, cell_length, number_of_windows=1, border_length=0):
    number_of_cells = length // cell_length
    space_needed_for_border = number_of_windows * border_length
    extra = length - number_of_cells * cell_length
    while extra < space_needed_for_border:
        number_of_cells -= 1
        extra = length - number_of_cells * cell_length
    extra -= space_needed_for_border
    pos = (extra // 2) + border_length
    inner_length = number_of_cells * cell_length
    window_length = 2 * border_length + inner_length
    while number_of_windows > 0:
        number_of_windows -= 1
        yield pos, number_of_cells
        pos += window_length


class Layout:

    name = None
    needs_window_borders = True

    def __init__(self, opts, border_width):
        self.opts = opts
        self.border_width = border_width

    def add_window(self, windows, window):
        raise NotImplementedError()

    def remove_window(self, windows, window):
        raise NotImplementedError()

    def __call__(self, windows):
        raise NotImplementedError()


class Stack(Layout):

    name = 'stack'
    needs_window_borders = False

    def add_window(self, windows, window):
        windows.appendleft(window)
        self(windows)

    def remove_window(self, windows, window):
        windows.remove(window)
        self(windows)

    def __call__(self, windows):
        xstart, xnum = next(layout_dimension(viewport_size.width, cell_size.width))
        ystart, ynum = next(layout_dimension(available_height(), cell_size.height))
        wg = WindowGeometry(left=xstart, top=ystart, xnum=xnum, ynum=ynum, right=xstart + cell_size.width * xnum, bottom=ystart + cell_size.height * ynum)
        for i, w in enumerate(windows):
            w.is_visible_in_layout = i == 0
            w.set_geometry(wg)
