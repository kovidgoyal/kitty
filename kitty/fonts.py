#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess
import unicodedata
import re
import ctypes
from collections import namedtuple
from functools import lru_cache

from freetype import (
    Face, FT_LOAD_RENDER, FT_LOAD_TARGET_NORMAL, FT_LOAD_TARGET_LIGHT,
    FT_LOAD_NO_HINTING, FT_PIXEL_MODE_GRAY
)

from .utils import get_logical_dpi


def escape_family_name(name):
    return re.sub(r'([-:,\\])', lambda m: '\\' + m.group(1), name)

Font = namedtuple('Font', 'face hinting hintstyle bold italic')


@lru_cache()
def get_font_information(q, bold=False, italic=False):
    q = escape_family_name(q)
    if bold:
        q += ':bold=200'
    if italic:
        q += ':slant=100'
    raw = subprocess.check_output(['fc-match', q, '-f', '%{file}\x1e%{hinting}\x1e%{hintstyle}']).decode('utf-8')
    parts = raw.split('\x1e')
    hintstyle, hinting = 1, 'True'
    if len(parts) == 3:
        path, hinting, hintstyle = parts
    else:
        path = parts[0]
    hinting = hinting.lower() == 'true'
    hintstyle = int(hintstyle)
    return Font(path, hinting, hintstyle, bold, italic)


def get_font_files(family):
    ans = {}
    n = get_font_information(family)
    ans['regular'] = Font(Face(n.face), n.hinting, n.hintstyle, n.bold, n.italic)

    def do(key):
        b = get_font_information(family, bold=key in ('bold', 'bi'), italic=key in ('italic', 'bi'))
        if b.face != n.face:
            ans[key] = Font(Face(b.face), b.hinting, b.hintstyle, b.bold, b.italic)
    do('bold'), do('italic'), do('bi')
    return ans


current_font_family = current_font_family_name = cff_size = cell_width = cell_height = baseline = None
CharTexture = underline_position = underline_thickness = None


def set_font_family(family, size_in_pts):
    global current_font_family, current_font_family_name, cff_size, cell_width, cell_height, CharTexture, baseline, underline_position, underline_thickness
    if current_font_family_name != family or cff_size != size_in_pts:
        current_font_family = get_font_files(family)
        current_font_family_name = family
        cff_size = size_in_pts
        dpi = get_logical_dpi()
        face = current_font_family['regular'].face
        cell_width = font_units_to_pixels(face.max_advance_width, face.units_per_EM, size_in_pts, dpi[0])
        cell_height = font_units_to_pixels(face.height, face.units_per_EM, size_in_pts, dpi[1])
        baseline = font_units_to_pixels(face.ascender, face.units_per_EM, size_in_pts, dpi[1])
        underline_position = baseline - font_units_to_pixels(face.underline_position, face.units_per_EM, size_in_pts, dpi[1])
        underline_thickness = font_units_to_pixels(face.underline_thickness, face.units_per_EM, size_in_pts, dpi[1])
        CharTexture = ctypes.c_ubyte * (cell_width * cell_height)
    return cell_width, cell_height

CharBitmap = namedtuple('CharBitmap', 'data bearingX bearingY advance rows columns')


def font_units_to_pixels(x, units_per_em, size_in_pts, dpi):
    return int(x * ((size_in_pts * dpi) / (72 * units_per_em)))


def render_char(text, bold=False, italic=False, size_in_pts=None):
    # TODO: Handle non-normalizable combining chars. Probably need to use
    # harfbuzz for that
    size_in_pts = size_in_pts or cff_size
    text = unicodedata.normalize('NFC', text)[0]
    key = 'regular'
    if bold:
        key = 'bi' if italic else 'bold'
    elif italic:
        key = 'italic'
    font = current_font_family.get(key) or current_font_family['regular']
    dpi = get_logical_dpi()
    sz = int(64 * size_in_pts)
    face = font.face
    face.set_char_size(width=sz, height=sz, hres=dpi[0], vres=dpi[1])
    flags = FT_LOAD_RENDER
    if font.hinting:
        if font.hintstyle >= 3:
            flags |= FT_LOAD_TARGET_NORMAL
        elif 0 < font.hintstyle < 3:
            flags |= FT_LOAD_TARGET_LIGHT
    else:
        flags |= FT_LOAD_NO_HINTING
    face.load_char(text, flags)
    bitmap = face.glyph.bitmap
    if bitmap.pixel_mode != FT_PIXEL_MODE_GRAY:
        raise ValueError(
            'FreeType rendered the glyph for {!r} with an unsupported pixel mode: {}'.format(text, bitmap.pixel_mode))
    m = face.glyph.metrics
    return CharBitmap(bitmap.buffer, min(int(abs(m.horiBearingX) / 64), bitmap.width),
                      min(int(abs(m.horiBearingY) / 64), bitmap.rows), int(m.horiAdvance / 64), bitmap.rows, bitmap.width)


def is_wide_char(bitmap_char):
    return bitmap_char.advance > 1.1 * cell_width


def render_cell(text, bold=False, italic=False, size_in_pts=None):
    bitmap_char = render_char(text, bold, italic, size_in_pts)
    if is_wide_char(bitmap_char):
        raise NotImplementedError('TODO: Implement this')

    # We want the glyph to be positioned inside the cell based on the bearingX
    # and bearingY values, making sure that it does not overflow the cell.

    # Calculate column bounds
    if bitmap_char.columns > cell_width:
        src_start_column, dest_start_column = cell_width - bitmap_char.columns, 0
    else:
        src_start_column, dest_start_column = 0, bitmap_char.bearingX
        extra = dest_start_column + bitmap_char.columns - cell_width
        if extra > 0:
            dest_start_column -= extra
    column_count = min(bitmap_char.columns - src_start_column, cell_width - dest_start_column)

    # Calculate row bounds, making sure the baseline is aligned with the cell
    # baseline
    if bitmap_char.bearingY > baseline:
        src_start_row, dest_start_row = bitmap_char.bearingY - baseline, 0
    else:
        src_start_row, dest_start_row = 0, baseline - bitmap_char.bearingY
    row_count = min(bitmap_char.rows - src_start_row, cell_height - dest_start_row)
    return create_cell_buffer(bitmap_char, src_start_row, dest_start_row, row_count,
                              src_start_column, dest_start_column, column_count)


def create_cell_buffer(bitmap_char, src_start_row, dest_start_row, row_count, src_start_column, dest_start_column, column_count):
    src = bitmap_char.data
    src_stride = bitmap_char.columns
    dest = CharTexture()
    for r in range(row_count):
        sr, dr = (src_start_row + r) * src_stride, (dest_start_row + r) * cell_width
        for c in range(column_count):
            dest[dr + dest_start_column + c] = src[sr + src_start_column + c]
    return dest


def join_cells(*cells):
    dstride = len(cells) * cell_width
    ans = (ctypes.c_ubyte * (cell_height * dstride))()
    for r in range(cell_height):
        soff = r * cell_width
        doff = r * dstride
        for cnum, cell in enumerate(cells):
            doff2 = doff + (cnum * cell_width)
            for c in range(cell_width):
                ans[doff2 + c] = cell[soff + c]
    return ans


def test_rendering(text='Testing', sz=144, family='monospace'):
    set_font_family(family, sz)
    cells = tuple(map(render_cell, text))
    char_data = join_cells(*cells)
    from PIL import Image
    img = Image.new('L', (cell_width * len(cells), cell_height))
    img.putdata(char_data)
    img.show()
