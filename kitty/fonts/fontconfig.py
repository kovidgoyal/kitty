#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import subprocess
from collections import namedtuple

from kitty.fast_data_types import Face


def escape_family_name(name):
    return re.sub(r'([-:,\\])', lambda m: '\\' + m.group(1), name)


Font = namedtuple(
    'Font', 'face hinting hintstyle bold italic scalable outline weight slant'
)


class FontNotFound(ValueError):
    pass


def to_bool(x):
    return x.lower() == 'true'


def get_font(
    family,
    bold,
    italic,
    allow_bitmaped_fonts=False,
    size_in_pts=None,
    character=None,
    dpi=None
):
    query = escape_family_name(family)
    if character is not None:
        query += ':charset={:x}'.format(ord(character[0]))
    if not allow_bitmaped_fonts:
        query += ':scalable=true:outline=true'
    if size_in_pts is not None:
        query += ':size={:.1f}'.format(size_in_pts)
    if dpi is not None:
        query += ':dpi={:.1f}'.format(dpi)
    if bold:
        query += ':weight=200'
    if italic:
        query += ':slant=100'
    raw = subprocess.check_output([
        'fc-match', query, '-f',
        '%{file}\x1e%{hinting}\x1e%{hintstyle}\x1e%{scalable}\x1e%{outline}\x1e%{weight}\x1e%{slant}'
    ]).decode('utf-8')
    parts = raw.split('\x1e')
    try:
        path, hinting, hintstyle, scalable, outline, weight, slant = parts
    except ValueError:
        path = parts[0]
        hintstyle, hinting, scalable, outline, weight, slant = 1, 'True', 'True', 'True', 100, 0
    return Font(
        path,
        to_bool(hinting),
        int(hintstyle), bold, italic,
        to_bool(scalable), to_bool(outline), int(weight), int(slant)
    )


def find_font_for_character(
    family,
    char,
    bold=False,
    italic=False,
    allow_bitmaped_fonts=False,
    size_in_pts=None,
    dpi=None
):
    try:
        ans = get_font(
            family,
            bold,
            italic,
            character=char,
            allow_bitmaped_fonts=allow_bitmaped_fonts,
            size_in_pts=size_in_pts,
            dpi=dpi
        )
    except subprocess.CalledProcessError as err:
        raise FontNotFound(
            'Failed to find font for character U+{:X}, error from fontconfig: {}'.
            format(ord(char[0]), err)
        )
    if not ans.face or not os.path.exists(ans.face):
        raise FontNotFound(
            'Failed to find font for character U+{:X}'.format(ord(char[0]))
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
    ans['regular'] = n._replace(face=Face(n.face))

    def do(key):
        b = get_font_information(
            get_family(key),
            bold=key in ('bold', 'bi'),
            italic=key in ('italic', 'bi')
        )
        if b.face != n.face:
            ans[key] = b._replace(face=Face(b.face))

    do('bold'), do('italic'), do('bi')
    return ans
