#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import sys
from functools import lru_cache, partial
from itertools import chain

from kitty.fast_data_types import Face, FreeTypeError
from kitty.fonts.box_drawing import render_missing_glyph
from kitty.utils import ceil_int, get_logical_dpi, safe_print, wcwidth, adjust_line_height

from .fontconfig import (
    FontNotFound, find_font_for_characters, font_for_family, get_font_files
)

current_font_family = current_font_family_name = cff_size = cell_width = cell_height = baseline = None
CharTexture = underline_position = underline_thickness = None
alt_face_cache = {}
symbol_map = {}


def set_char_size(face, width=0, height=0, hres=0, vres=0):
    face.set_char_size(width, height, hres, vres)


@lru_cache(maxsize=2**10)
def font_for_text(char, bold=False, italic=False, allow_bitmaped_fonts=False):
    if allow_bitmaped_fonts:
        return find_font_for_characters(
            current_font_family_name,
            char,
            bold,
            italic,
            allow_bitmaped_fonts=True,
            size_in_pts=cff_size['width'] / 64,
            dpi=(cff_size['hres'] + cff_size['vres']) / 2
        )
    return find_font_for_characters(
        current_font_family_name, char, bold, italic
    )


def install_symbol_map(val):
    global symbol_map
    symbol_map = {}
    family_map = {f: font_for_family(f) for f in set(val.values())}
    for ch, family in val.items():
        symbol_map[ch] = family_map[family]


def font_units_to_pixels(x, units_per_em, size_in_pts, dpi):
    return ceil_int(x * ((size_in_pts * dpi) / (72 * units_per_em)))


def set_font_family(opts, override_font_size=None):
    global current_font_family, current_font_family_name, cff_size, cell_width, cell_height, CharTexture, baseline
    global underline_position, underline_thickness
    size_in_pts = override_font_size or opts.font_size
    current_font_family = get_font_files(opts)
    current_font_family_name = opts.font_family
    dpi = get_logical_dpi()
    cff_size = ceil_int(64 * size_in_pts)
    cff_size = {
        'width': cff_size,
        'height': cff_size,
        'hres': int(dpi[0]),
        'vres': int(dpi[1])
    }
    install_symbol_map(opts.symbol_map)
    for fobj in chain(current_font_family.values(), symbol_map.values()):
        set_char_size(fobj.face, **cff_size)
    face = current_font_family['regular'].face
    cell_width = face.calc_cell_width()
    cell_height = font_units_to_pixels(
        face.height, face.units_per_EM, size_in_pts, dpi[1]
    )
    cell_height = adjust_line_height(cell_height, opts.adjust_line_height)
    baseline = font_units_to_pixels(
        face.ascender, face.units_per_EM, size_in_pts, dpi[1]
    )
    underline_position = min(
        baseline - font_units_to_pixels(
            face.underline_position, face.units_per_EM, size_in_pts, dpi[1]
        ), cell_height - 1
    )
    underline_thickness = font_units_to_pixels(
        face.underline_thickness, face.units_per_EM, size_in_pts, dpi[1]
    )
    CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    font_for_text.cache_clear()
    alt_face_cache.clear()
    return cell_width, cell_height


def font_has_text(font, text):
    for c in text:
        if not font.face.get_char_index(c):
            return False
    return True


def face_for_text(text, bold=False, italic=False):
    key = 'regular'
    if bold:
        key = 'bi' if italic else 'bold'
    elif italic:
        key = 'italic'
    font = symbol_map.get(text[0])
    if font is None or not font_has_text(font, text):
        font = current_font_family.get(key) or current_font_family['regular']
        face = font.face
        if not font_has_text(font, text):
            try:
                font = font_for_text(text, bold, italic)
            except FontNotFound:
                font = font_for_text(
                    text, bold, italic, allow_bitmaped_fonts=True
                )
            face = alt_face_cache.get(font)
            if face is None:
                face = alt_face_cache[font] = Face(font.face, font.index, font.hinting, font.hintstyle)
                if face.is_scalable:
                    set_char_size(face, **cff_size)
    else:
        face = font.face
    return font, face


def render_text(text, bold=False, italic=False, num_cells=1):
    font, face = face_for_text(text, bold, italic)
    func = partial(face.draw_single_glyph, ord(text[0])) if len(text) == 1 else partial(face.draw_complex_glyph, text)
    if num_cells == 1:
        buf = CharTexture()
        ans = (buf,)
    else:
        buf = (ctypes.c_ubyte * (cell_width * num_cells * cell_height))()
        ans = tuple(CharTexture() for i in range(num_cells))
    func(cell_width, cell_height, ctypes.addressof(buf), num_cells, bold, italic, baseline)
    if num_cells > 1:
        face.split_cells(cell_width, cell_height, ctypes.addressof(buf), *(ctypes.addressof(x) for x in ans))
    return ans


def current_cell():
    return CharTexture, cell_width, cell_height, baseline, underline_thickness, underline_position


@lru_cache(maxsize=8)
def missing_glyph(num_cells, cell_width, cell_height):
    w = cell_width * num_cells
    ans = bytearray(w * cell_height)
    render_missing_glyph(ans, w, cell_height)
    buf = (ctypes.c_ubyte * w * cell_height).from_buffer(ans)
    face = current_font_family['regular'].face
    bufs = tuple(CharTexture() for i in range(num_cells))
    face.split_cells(cell_width, cell_height, ctypes.addressof(buf), *(ctypes.addressof(x) for x in bufs))
    if num_cells == 2:
        first, second = bufs
    else:
        first, second = bufs[0], None
    return first, second


def render_cell(text=' ', bold=False, italic=False):
    num_cells = wcwidth(text[0])

    def safe_freetype(func):
        try:
            return func(text, bold, italic, num_cells)
        except FontNotFound as err:
            safe_print('ERROR:', err, file=sys.stderr)
        except FreeTypeError as err:
            safe_print('Failed to render text:', repr(text), 'with error:', err, file=sys.stderr)

    ret = safe_freetype(render_text)
    if ret is None:
        return missing_glyph(num_cells, cell_width, cell_height)
    if num_cells == 1:
        first, second = ret[0], None
    else:
        first, second = ret

    return first, second
