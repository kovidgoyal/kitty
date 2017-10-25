#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from collections import namedtuple

from kitty.fast_data_types import Face, get_fontconfig_font


def escape_family_name(name):
    return re.sub(r'([-:,\\])', lambda m: '\\' + m.group(1), name)


Font = namedtuple(
    'Font',
    'face hinting hintstyle bold italic scalable outline weight slant index'
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
    if not ans.face or not os.path.exists(ans.face):
        raise FontNotFound(
            'Failed to find font for characters: {!r}'.format(chars)
        )
    return ans


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
    ans['regular'] = n._replace(face=Face(n.face, n.index))

    def do(key):
        b = get_font_information(
            get_family(key),
            bold=key in ('bold', 'bi'),
            italic=key in ('italic', 'bi')
        )
        if b.face != n.face:
            ans[key] = b._replace(face=Face(b.face, b.index))

    do('bold'), do('italic'), do('bi')
    return ans


def font_for_family(family):
    ans = get_font_information(family)
    return ans._replace(face=Face(ans.face, ans.index))
