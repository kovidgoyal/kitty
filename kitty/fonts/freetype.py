#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ctypes
import sys
from collections import namedtuple
from functools import lru_cache
from itertools import chain

from kitty.fast_data_types import FT_PIXEL_MODE_GRAY, Face, FreeTypeError
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


def load_char(font, face, text):
    face.load_char(text, font.hinting, font.hintstyle)


def calc_cell_width(font, face):
    ans = 0
    for i in range(32, 128):
        ch = chr(i)
        load_char(font, face, ch)
        m = face.glyph_metrics()
        ans = max(ans, ceil_int(m.horiAdvance / 64))
    return ans


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
    cell_width = calc_cell_width(current_font_family['regular'], face)
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


CharBitmap = namedtuple(
    'CharBitmap', 'data bearingX bearingY advance rows columns'
)


def render_to_bitmap(font, face, text):
    load_char(font, face, text)
    bitmap = face.bitmap()
    if bitmap.pixel_mode != FT_PIXEL_MODE_GRAY:
        raise ValueError(
            'FreeType rendered the glyph for {!r} with an unsupported pixel mode: {}'.
            format(text, bitmap.pixel_mode)
        )
    return bitmap


def render_using_face(font, face, text, width, italic, bold):
    bitmap = render_to_bitmap(font, face, text)
    if width == 1 and bitmap.width > cell_width:
        extra = bitmap.width - cell_width
        if italic and extra < cell_width // 2:
            bitmap = face.trim_to_width(bitmap, cell_width)
        elif extra > max(2, 0.3 * cell_width) and face.is_scalable:
            # rescale the font size so that the glyph is visible in a single
            # cell and hope somebody updates libc's wcwidth
            sz = cff_size.copy()
            sz['width'] = int(sz['width'] * cell_width / bitmap.width)
            # Preserve aspect ratio
            sz['height'] = int(sz['height'] * cell_width / bitmap.width)
            try:
                set_char_size(face, **sz)
                bitmap = render_to_bitmap(font, face, text)
            finally:
                set_char_size(face, **cff_size)
    m = face.glyph_metrics()
    return CharBitmap(
        bitmap.buffer,
        ceil_int(abs(m.horiBearingX) / 64),
        ceil_int(abs(m.horiBearingY) / 64),
        ceil_int(m.horiAdvance / 64), bitmap.rows, bitmap.width
    )


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
                face = alt_face_cache[font] = Face(font.face, font.index)
                if face.is_scalable:
                    set_char_size(face, **cff_size)
    else:
        face = font.face
    return font, face


def render_char(text, bold=False, italic=False, width=1):
    font, face = face_for_text(text[0], bold, italic)
    return render_using_face(font, face, text, width, italic, bold)


def render_complex_char(text, bold=False, italic=False, width=1):
    font, face = face_for_text(text, bold, italic)
    import pprint
    pprint.pprint(face.shape(text, font.hinting, font.hintstyle))


def place_char_in_cell(bitmap_char):
    # We want the glyph to be positioned inside the cell based on the bearingX
    # and bearingY values, making sure that it does not overflow the cell.

    # Calculate column bounds
    if bitmap_char.columns > cell_width:
        src_start_column, dest_start_column = 0, 0
    else:
        src_start_column, dest_start_column = 0, bitmap_char.bearingX
        extra = dest_start_column + bitmap_char.columns - cell_width
        if extra > 0:
            dest_start_column -= extra
    column_count = min(
        bitmap_char.columns - src_start_column, cell_width - dest_start_column
    )

    # Calculate row bounds, making sure the baseline is aligned with the cell
    # baseline
    if bitmap_char.bearingY > baseline:
        src_start_row, dest_start_row = bitmap_char.bearingY - baseline, 0
    else:
        src_start_row, dest_start_row = 0, baseline - bitmap_char.bearingY
    row_count = min(
        bitmap_char.rows - src_start_row, cell_height - dest_start_row
    )
    return create_cell_buffer(
        bitmap_char, src_start_row, dest_start_row, row_count,
        src_start_column, dest_start_column, column_count
    )


def split_char_bitmap(bitmap_char):
    stride = bitmap_char.columns
    extra = stride - cell_width
    rows = bitmap_char.rows
    first_buf = (ctypes.c_ubyte * (cell_width * rows))()
    second_buf = (ctypes.c_ubyte * (extra * rows))()
    src = bitmap_char.data
    for r in range(rows):
        soff, off = r * stride, r * cell_width
        first_buf[off:off + cell_width] = src[soff:soff + cell_width]
        off = r * extra
        soff += cell_width
        second_buf[off:off + extra] = src[soff:soff + extra]
    first = bitmap_char._replace(data=first_buf, columns=cell_width)
    second = bitmap_char._replace(data=second_buf, bearingX=0, columns=extra)
    return first, second


def current_cell():
    return CharTexture, cell_width, cell_height, baseline, underline_thickness, underline_position


@lru_cache(maxsize=8)
def missing_glyph(width):
    w = cell_width * width
    ans = bytearray(w * cell_height)
    render_missing_glyph(ans, w, cell_height)
    first, second = CharBitmap(ans, 0, 0, 0, cell_height, w), None
    if width == 2:
        first, second = split_char_bitmap(first)
        second = create_cell_buffer(
            second, 0, 0, second.rows, 0, 0, second.columns
        )
    first = create_cell_buffer(first, 0, 0, first.rows, 0, 0, first.columns)
    return first, second


def render_cell(text=' ', bold=False, italic=False):
    width = wcwidth(text[0])

    try:
        if len(text) > 1:
            bitmap_char = render_complex_char(text, bold, italic, width)
        else:
            bitmap_char = render_char(text, bold, italic, width)
    except FontNotFound as err:
        safe_print('ERROR:', err, file=sys.stderr)
        return missing_glyph(width)
    except FreeTypeError as err:
        safe_print('Failed to render text:', repr(text), 'with error:', err, file=sys.stderr)
        return missing_glyph(width)
    second = None
    if width == 2:
        if bitmap_char.columns > cell_width:
            bitmap_char, second = split_char_bitmap(bitmap_char)
            second = place_char_in_cell(second)
        else:
            second = render_cell()[0]

    first = place_char_in_cell(bitmap_char)

    return first, second


def create_cell_buffer(
    bitmap_char, src_start_row, dest_start_row, row_count, src_start_column,
    dest_start_column, column_count
):
    src = bitmap_char.data
    src_stride = bitmap_char.columns
    dest = CharTexture()
    for r in range(row_count):
        sr, dr = src_start_column + (
            src_start_row + r
        ) * src_stride, dest_start_column + (dest_start_row + r) * cell_width
        dest[dr:dr + column_count] = src[sr:sr + column_count]
    return dest
