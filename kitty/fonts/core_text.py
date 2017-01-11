#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from kitty.fast_data_types import CTFace as Face
from kitty.utils import get_dpi


main_font = {}


def set_font_family(family, size_in_pts):
    dpi = get_dpi()['logical']
    dpi = sum(dpi) / 2.0
    if family.lower() == 'monospace':
        family = 'Menlo'
    for bold in (False, True):
        for italic in (False, True):
            main_font[(bold, italic)] = Face(family, bold, italic, True, size_in_pts, dpi)


def render_cell(text=' ', bold=False, italic=False, underline=0, strikethrough=False):
    pass


def develop():
    from kitty.fast_data_types import glfw_init
    glfw_init()
    set_font_family('monospace', 12.0)
    for (bold, italic), face in main_font.items():
        print('bold: {} italic: {} family:{} full name: {}'.format(bold, italic, face.family_name, face.full_name))
    f = main_font[(False, False)]
    for attr in 'units_per_em ascent descent leading underline_position underline_thickness scaled_point_sz'.split():
        print(attr, getattr(f, attr))
