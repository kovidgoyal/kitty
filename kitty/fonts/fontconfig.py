#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
from collections import namedtuple

from kitty.fast_data_types import Face, get_fontconfig_font


def face_from_font(font, pt_sz, xdpi, ydpi):
    return Face(font.path, font.index, font.hinting, font.hintstyle, pt_sz, xdpi, ydpi)


Font = namedtuple(
    'Font',
    'path hinting hintstyle bold italic scalable outline weight slant index'
)


class FontNotFound(ValueError):
    pass


def to_bool(x):
    return x.lower() == 'true'


def font_not_found(err, chars):
    msg = 'Failed to find font'
    if chars:
        chars = ', '.join('U+{:X}'.format(ord(c)) for c in chars)
        msg = 'Failed to find font for characters U+{:X}, error from fontconfig: {}'.  format(chars, err)
    return FontNotFound(msg)


def get_font(
    family='monospace',
    bold=False,
    italic=False,
    allow_bitmaped_fonts=False,
    size_in_pts=None,
    characters='',
    dpi=None
):
    try:
        path, index, hintstyle, hinting, scalable, outline, weight, slant = get_fontconfig_font(
            family, bold, italic, allow_bitmaped_fonts, size_in_pts or 0,
            characters or '', dpi or 0
        )
    except KeyError as err:
        raise font_not_found(err, characters)

    return Font(
        path, hinting, hintstyle, bold, italic, scalable, outline, weight,
        slant, index
    )


def find_font_for_characters(
    family,
    chars,
    bold=False,
    italic=False,
    allow_bitmaped_fonts=False,
    size_in_pts=None,
    dpi=None
):
    ans = get_font(
        family,
        bold,
        italic,
        characters=chars,
        allow_bitmaped_fonts=allow_bitmaped_fonts,
        size_in_pts=size_in_pts,
        dpi=dpi
    )
    if not ans.path or not os.path.exists(ans.path):
        raise FontNotFound(
            'Failed to find font for characters: {!r}'.format(chars)
        )
    return ans


def font_for_text(text, current_font_family, pt_sz, xdpi, ydpi, bold=False, italic=False):
    dpi = (xdpi + ydpi) / 2
    try:
        return find_font_for_characters(current_font_family, text, bold=bold, italic=italic, size_in_pts=pt_sz, dpi=dpi)
    except FontNotFound:
        return find_font_for_characters(current_font_family, text, bold=bold, italic=italic, size_in_pts=pt_sz, dpi=dpi, allow_bitmaped_fonts=True)


def get_font_information(family, bold=False, italic=False):
    return get_font(family, bold, italic)


def get_font_files(opts):
    ans = {}
    attr_map = {
        'bold': 'bold_font',
        'italic': 'italic_font',
        'bi': 'bold_italic_font'
    }

    def get_family(key=None):
        ans = getattr(opts, attr_map.get(key, 'font_family'))
        if ans == 'auto' and key:
            ans = get_family()
        return ans

    n = get_font_information(get_family())
    ans['medium'] = n

    def do(key):
        b = get_font_information(
            get_family(key),
            bold=key in ('bold', 'bi'),
            italic=key in ('italic', 'bi')
        )
        if b.path != n.path:
            ans[key] = b

    do('bold'), do('italic'), do('bi')
    return ans


def font_for_family(family):
    ans = get_font_information(family)
    return ans
