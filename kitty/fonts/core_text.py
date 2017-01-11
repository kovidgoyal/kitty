#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
from kitty.fast_data_types import CTFace as Face
from kitty.utils import get_logical_dpi, wcwidth, ceil_int

main_font = {}
cell_width = cell_height = baseline = CellTexture = WideCellTexture = underline_thickness = underline_position = None


def set_font_family(family, size_in_pts):
    global cell_width, cell_height, baseline, CellTexture, WideCellTexture, underline_thickness, underline_position
    dpi = get_logical_dpi()
    dpi = sum(dpi) / 2.0
    if family.lower() == 'monospace':
        family = 'Menlo'
    for bold in (False, True):
        for italic in (False, True):
            main_font[(bold, italic)] = Face(family, bold, italic, True, size_in_pts, dpi)
    mf = main_font[(False, False)]
    cell_width = mf.cell_size()
    cell_height = ceil_int(mf.ascent + mf.descent)
    cell_height += 1 * int(round(dpi / 72.0))  # some line spacing
    CellTexture = ctypes.c_ubyte * (cell_width * cell_height)
    WideCellTexture = ctypes.c_ubyte * (2 * cell_width * cell_height)
    baseline = int(round(mf.ascent))
    underline_position = int(round(mf.underline_position))
    underline_thickness = ceil_int(mf.underline_thickness)
    return cell_width, cell_height


def current_cell():
    return CellTexture, cell_width, cell_height, baseline, underline_thickness, underline_position


def render_cell(text=' ', bold=False, italic=False):
    width = wcwidth(text[0])
    face = main_font[(bold, italic)]
    if width == 2:
        buf, width = WideCellTexture(), cell_width * 2
    else:
        buf, width = CellTexture(), cell_width
    face.render_char(text, width, cell_height, ctypes.addressof(buf))


def develop():
    from kitty.fast_data_types import glfw_init
    glfw_init()
    set_font_family('monospace', 12.0)
    for (bold, italic), face in main_font.items():
        print('bold: {} italic: {} family:{} full name: {}'.format(bold, italic, face.family_name, face.full_name))
    f = main_font[(False, False)]
    for attr in 'units_per_em ascent descent leading underline_position underline_thickness scaled_point_sz'.split():
        print(attr, getattr(f, attr))
    print('cell_width: {}, cell_height: {}, baseline: {}'.format(cell_width, cell_height, baseline))
