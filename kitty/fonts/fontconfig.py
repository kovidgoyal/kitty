#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import subprocess
from collections import namedtuple
from functools import lru_cache
from kitty.fast_data_types import Face


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
        q += ':weight=200'
    if italic:
        q += ':slant=100'
    return get_font(q, bold, italic)


@lru_cache(maxsize=64)
def get_font_information(q, bold=False, italic=False):
    q = escape_family_name(q)
    if bold:
        q += ':weight=200'
    if italic:
        q += ':slant=100'
    return get_font(q, bold, italic)


def get_font_files(opts):
    ans = {}
    attr_map = {'bold': 'bold_font', 'italic': 'italic_font', 'bi': 'bold_italic_font'}

    def get_family(key=None):
        ans = getattr(opts, attr_map.get(key, 'font_family'))
        if ans == 'auto' and key:
            ans = get_family()
        return ans

    n = get_font_information(get_family())
    ans['regular'] = Font(Face(n.face), n.hinting, n.hintstyle, n.bold, n.italic)

    def do(key):
        b = get_font_information(get_family(key), bold=key in ('bold', 'bi'), italic=key in ('italic', 'bi'))
        if b.face != n.face:
            ans[key] = Font(Face(b.face), b.hinting, b.hintstyle, b.bold, b.italic)
    do('bold'), do('italic'), do('bi')
    return ans
