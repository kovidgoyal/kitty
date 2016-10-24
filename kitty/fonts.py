#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess
import unicodedata
import re
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


current_font_family = current_font_family_name = None


def set_font_family(family):
    global current_font_family, current_font_family_name
    if current_font_family_name != family:
        current_font_family = get_font_files(family)
        current_font_family_name = family
    return current_font_family['regular'].face

CharData = namedtuple('CharData', 'left width ascender descender')


def render_char(text, size_in_pts, bold=False, italic=False):
    # TODO: Handle non-normalizable combining chars. Probably need to use
    # harfbuzz for that
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
        raise ValueError('FreeType rendered the glyph with an unsupported pixel mode: {}'.format(bitmap.pixel_mode))
    width = bitmap.width
    ascender = face.glyph.bitmap_top
    descender = bitmap.rows - ascender
    left = face.glyph.bitmap_left

    return bitmap.buffer, CharData(left, width, ascender, descender)


def test_rendering(text='M', sz=144, family='monospace'):
    set_font_family(family)
    buf, char_data = render_char(text, sz)
    print(char_data)
    from PIL import Image
    img = Image.new('L', (char_data.width, char_data.ascender + char_data.descender))
    img.putdata(buf)
    img.show()
