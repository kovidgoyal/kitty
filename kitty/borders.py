#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Iterable
from enum import IntFlag
from functools import partial
from typing import NamedTuple

from .fast_data_types import current_focused_os_window_id, get_options, pt_to_px, set_borders_rects
from .typing_compat import LayoutType
from .utils import color_as_int
from .window_list import WindowGroup, WindowList


class BorderColor(IntFlag):
    # These are indices into the array of colors in the border vertex shader
    default_bg, active, inactive, window_bg, bell, tab_bar_bg, tab_bar_margin_color, tab_bar_left_edge_color, tab_bar_right_edge_color = range(9)


class Border(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int
    color: BorderColor
    border_type: int = 0
    horizontal: bool = False
    render: bool = True
    radius: int = 0
    thickness: int = 0


def vertical_edge(rects: list[Border], color: BorderColor, width: int, top: int, bottom: int, left: int, border_type: int, render: bool = True) -> None:
    if width > 0:
        rects.append(Border(left, top, left + width, bottom, color, border_type, False, render))


def horizontal_edge(rects: list[Border], color: BorderColor, height: int, left: int, right: int, top: int, border_type: int, render: bool = True) -> None:
    if height > 0:
        rects.append(Border(left, top, right, top + height, color, border_type, True, render))


def add_borders(rects: list[Border], color: BorderColor, wg: WindowGroup, radius: int = 0) -> None:
    geometry = wg.geometry
    if geometry is None:
        return
    pl, pt = wg.effective_padding('left'), wg.effective_padding('top')
    pr, pb = wg.effective_padding('right'), wg.effective_padding('bottom')
    left = geometry.left - pl
    top = geometry.top - pt
    lr = geometry.right
    right = lr + pr
    bt = geometry.bottom
    bottom = bt + pb
    h = partial(horizontal_edge, rects, color)
    v = partial(vertical_edge, rects, color)
    width = wg.effective_border()
    bt = bottom
    lr = right
    left -= width
    top -= width
    right += width
    bottom += width
    pl = pr = pb = pt = width
    wid = wg.active_window_id
    render_edges = radius < 1
    h(pt, left, right, top, -wid, render_edges)
    h(pb, left, right, bt, wid, render_edges)
    v(pl, top, bottom, left, -wid, render_edges)
    v(pr, top, bottom, lr, wid, render_edges)
    if radius > 0:
        rects.append(Border(left, top, right, bottom, color, render=False, radius=radius, thickness=width))


class Borders:
    def __init__(self, os_window_id: int, tab_id: int):
        self.os_window_id = os_window_id
        self.tab_id = tab_id

    def __call__(
        self,
        all_windows: WindowList,
        current_layout: LayoutType,
        tab_bar_rects: Iterable[Border],
        draw_window_borders: bool = True,
    ) -> None:
        opts = get_options()
        draw_active_borders = opts.active_border_color is not None
        rects: list[Border] = []
        for br in current_layout.blank_rects:
            rects.append(Border(*br, BorderColor.default_bg))
        rects.extend(tab_bar_rects)
        bw = 0
        groups = tuple(all_windows.iter_all_layoutable_groups(only_visible=True))
        if groups:
            bw = groups[0].effective_border()
        draw_borders = bw > 0 and draw_window_borders
        active_group = all_windows.active_group

        # Count visible windows
        num_visible_groups = len(groups)

        # When draw_window_borders_for_single_window is set and there's only 1 window,
        # behave like draw_minimal_borders is False (draw full borders around the window)
        if opts.draw_window_borders_for_single_window and num_visible_groups == 1:
            draw_minimal_borders = False
        else:
            draw_minimal_borders = opts.draw_minimal_borders and max(opts.window_margin_width) < 1

        # For single window with the option enabled, check OS window focus state
        # When unfocused, the border should appear inactive
        os_window_focused = True
        if opts.draw_window_borders_for_single_window and num_visible_groups == 1:
            os_window_focused = current_focused_os_window_id() == self.os_window_id

        radius, radius_unit = opts.window_border_radius
        if radius_unit == 'pt':
            radius = pt_to_px(radius, self.os_window_id)
        else:
            radius = round(radius)

        if draw_borders and not draw_minimal_borders:
            for i, wg in enumerate(groups):
                window_bg = color_as_int(wg.default_bg)
                window_bg = (window_bg << 8) | BorderColor.window_bg
                # Draw the border rectangles
                if wg is active_group and draw_active_borders and os_window_focused:
                    color = BorderColor.active
                else:
                    color = BorderColor.bell if wg.needs_attention else BorderColor.inactive
                add_borders(rects, color, wg, int(radius))

        if draw_minimal_borders:
            for border_line in current_layout.get_minimal_borders(all_windows):
                rects.append(Border(*border_line.edges, border_line.color, border_line.window_id, border_line.horizontal))
        set_borders_rects(self.os_window_id, self.tab_id, rects)
