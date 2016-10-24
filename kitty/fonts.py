#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess
import re
from collections import namedtuple
from functools import lru_cache

from freetype import Face


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
    raw = subprocess.check_output(['fc-match', q, '-f', '%{file}\x31%{hinting}\x31%{hintstyle}']).decode('utf-8')
    parts = raw.split('\x31')
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


@lru_cache()
def load_font_family(r):
    return get_font_files(r)
