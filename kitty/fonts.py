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

from .utils import get_logical_dpi, set_current_font_metrics


def escape_family_name(name):
    return re.sub(r'([-:,\\])', lambda m: '\\' + m.group(1), name)

Font = namedtuple('Font', 'face hinting hintstyle bold italic')


def get_font(query, bold, italic):
    query += ':scalable=true:outline=true'
    raw = subprocess.check_output(['fc-match', query, '-f', '%{file}\x1e%{hinting}\x1e%{hintstyle}']).decode('utf-8')
    parts = raw.split('\x1e')
    hintstyle, hinting = 1, 'True'
    if len(parts) == 3:
        path, hinting, hintstyle = parts
    else:
        path = parts[0]
    hinting = hinting.lower() == 'true'
    hintstyle = int(hintstyle)
    return Font(path, hinting, hintstyle, bold, italic)


@lru_cache(maxsize=4096)
def find_font_for_character(family, char, bold=False, italic=False):
    q = escape_family_name(family) + ':charset={}'.format(hex(ord(char[0]))[2:])
    if bold:
        q += ':bold=200'
    if italic:
        q += ':slant=100'
    return get_font(q, bold, italic)


@lru_cache(maxsize=64)
def get_font_information(q, bold=False, italic=False):
    q = escape_family_name(q)
    if bold:
        q += ':bold=200'
    if italic:
        q += ':slant=100'
    return get_font(q, bold, italic)


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
CharTexture = underline_position = underline_thickness = glyph_cache = None
fallback_font_face_cache = {}


def set_font_family(family, size_in_pts):
    global current_font_family, current_font_family_name, cff_size, cell_width, cell_height, CharTexture, baseline
    global underline_position, underline_thickness, glyph_cache
    if current_font_family_name != family or cff_size != size_in_pts:
        find_font_for_character.cache_clear()
        fallback_font_face_cache.clear()
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
        glyph_cache = GlyphCache()
        set_current_font_metrics(glyph_cache.width)
    return cell_width, cell_height

CharBitmap = namedtuple('CharBitmap', 'data bearingX bearingY advance rows columns')


def face_for_char(char, bold=False, italic=False):
    ans = find_font_for_character(current_font_family_name, char, bold, italic)
    face = fallback_font_face_cache.get(ans.face)
    if face is None:
        face = fallback_font_face_cache[ans.face] = Face(ans.face)
    return face


def font_units_to_pixels(x, units_per_em, size_in_pts, dpi):
    return int(x * ((size_in_pts * dpi) / (72 * units_per_em)))


def render_char(text, bold=False, italic=False, size_in_pts=None):
    # TODO: Handle non-normalizable combining chars. Probably need to use
    # harfbuzz for that
    size_in_pts = size_in_pts or cff_size
    text = unicodedata.normalize('NFC', text)[0]
    dpi = get_logical_dpi()
    sz = int(64 * size_in_pts)
    key = 'regular'
    if bold:
        key = 'bi' if italic else 'bold'
    elif italic:
        key = 'italic'
    font = current_font_family.get(key) or current_font_family['regular']
    face = font.face
    if not face.get_char_index(ord(text[0])):
        face = face_for_char(text[0], bold, italic)
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
    return min(bitmap_char.advance, bitmap_char.columns) > cell_width * 1.1


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


def render_cell(text, bold=False, italic=False, size_in_pts=None):
    bitmap_char = render_char(text, bold, italic, size_in_pts)
    second = None
    if is_wide_char(bitmap_char):
        bitmap_char, second = split_char_bitmap(bitmap_char)
        second = place_char_in_cell(second)

    return place_char_in_cell(bitmap_char), second


def create_cell_buffer(bitmap_char, src_start_row, dest_start_row, row_count, src_start_column, dest_start_column, column_count):
    src = bitmap_char.data
    src_stride = bitmap_char.columns
    dest = CharTexture()
    for r in range(row_count):
        sr, dr = src_start_column + (src_start_row + r) * src_stride, dest_start_column + (dest_start_row + r) * cell_width
        dest[dr:dr + column_count] = src[sr:sr + column_count]
    return dest


class GlyphCache:

    def __init__(self):
        self.char_map = {}
        self.second_char_map = {}
        self.data = ()
        self.width_map = {}

    def render(self, text, bold=False, italic=False):
        first, second = render_cell(text, bold, italic)
        self.width_map[text] = 1 if second is None else 2
        self.char_map[text] = self.add_cell(first)
        if second is not None:
            self.second_char_map[text] = self.add_cell(second)

    def add_cell(self, data):
        i = len(self.data)
        ndata = ctypes.c_ubyte * (i + len(data))
        if self.data:
            ndata[:i] = self.data
        ndata[i:] = data
        return i

    def width(self, text):
        try:
            return self.width_map[text]
        except KeyError:
            self.render(text)
        return self.width_map[text]


def join_cells(*cells):
    dstride = len(cells) * cell_width
    ans = (ctypes.c_ubyte * (cell_height * dstride))()
    for r in range(cell_height):
        soff = r * cell_width
        doff = r * dstride
        for cnum, cell in enumerate(cells):
            doff2 = doff + (cnum * cell_width)
            ans[doff2:doff2 + cell_width] = cell[soff:soff + cell_width]
    return ans


def display_bitmap(data, w, h):
    from PIL import Image
    img = Image.new('L', (w, h))
    img.putdata(data)
    img.show()


def cell_size():
    return cell_width, cell_height


def test_rendering(text='Ping👁a⧽', sz=144, family='monospace'):
    set_font_family(family, sz)
    cells = []
    for c in text:
        f, s = render_cell(c)
        cells.append(f)
        if s is not None:
            cells.append(s)
    char_data = join_cells(*cells)
    display_bitmap(char_data, cell_width * len(cells), cell_height)
