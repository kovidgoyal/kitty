#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
from kitty.fast_data_types import CTFace as Face
from kitty.utils import get_logical_dpi, wcwidth, ceil_int

main_font = {}
cell_width = cell_height = baseline = CellTexture = WideCellTexture = underline_thickness = underline_position = None


def set_font_family(family, size_in_pts, ignore_dpi_failure=False):
    global cell_width, cell_height, baseline, CellTexture, WideCellTexture, underline_thickness, underline_position
    try:
        dpi = get_logical_dpi()
    except Exception:
        if not ignore_dpi_failure:
            raise
        dpi = (72, 72)  # Happens when running via develop() in an ssh session
    dpi = sum(dpi) / 2.0
    if family.lower() == 'monospace':
        family = 'Menlo'
    for bold in (False, True):
        for italic in (False, True):
            main_font[(bold, italic)] = Face(family, bold, italic, True, size_in_pts, dpi)
    mf = main_font[(False, False)]
    cell_width, cell_height = mf.cell_size()
    CellTexture = ctypes.c_ubyte * (cell_width * cell_height)
    WideCellTexture = ctypes.c_ubyte * (2 * cell_width * cell_height)
    baseline = int(round(mf.ascent))
    underline_position = int(round(baseline - mf.underline_position))
    underline_thickness = ceil_int(mf.underline_thickness)
    return cell_width, cell_height


def current_cell():
    return CellTexture, cell_width, cell_height, baseline, underline_thickness, underline_position


def split(buf, cell_width, cell_height):
    first, second = CellTexture(), CellTexture()
    for y in range(cell_height):
        offset, woffset = y * cell_width, y * cell_width * 2
        for x in range(cell_width):
            first[offset + x] = buf[woffset + x]
            second[offset + x] = buf[woffset + cell_width + x]
    return first, second


def render_cell(text=' ', bold=False, italic=False):
    width = wcwidth(text[0])
    face = main_font[(bold, italic)]
    if width == 2:
        buf, width = WideCellTexture(), cell_width * 2
    else:
        buf, width = CellTexture(), cell_width
    face.render_char(text, width, cell_height, ctypes.addressof(buf))
    if width == 2:
        first, second = split(buf, cell_width, cell_height)
    else:
        first, second = buf, None
    return first, second


def develop(family='monospace', sz=288):
    import pickle
    from .render import render_string
    from kitty.fast_data_types import glfw_init
    import os
    glfw_init()
    try:
        os.remove('/tmp/cell.data')
    except EnvironmentError:
        pass
    set_font_family(family, sz, ignore_dpi_failure=True)
    for (bold, italic), face in main_font.items():
        print('bold: {} italic: {} {}'.format(bold, italic, face))
    print('cell_width: {}, cell_height: {}, baseline: {}'.format(cell_width, cell_height, baseline))
    buf, w, h = render_string()
    open('/tmp/cell.data', 'wb').write(pickle.dumps((bytearray(buf), w, h)))
