#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess
import re

from freetype import Face


def escape_family_name(name):
    return re.sub(r'([-:,\\])', lambda m: '\\' + m.group(1), name)


def fc_match(q, bold=False, italic=False):
    q = escape_family_name(q)
    if bold:
        q += ':bold=200'
    if italic:
        q += ':slant=100'
    return subprocess.check_output(['fc-match', q, '-f', '%{file}']).decode('utf-8')


def validate_monospace_font(raw_name):
    raw = fc_match(raw_name)
    if not raw:
        raise ValueError('Failed to find a font matching the name: {}'.format(raw_name))
    f = Face(raw)
    if not f.is_fixed_width:
        raise ValueError('The font {} is not a monospace font'.format(raw_name))
    return f, raw_name


def get_font_files(family):
    ans = {}

    b = fc_match(family, bold=True)
    if b:
        ans['bold'] = Face(b)
    i = fc_match(family, italic=True)
    if i:
        ans['italic'] = Face(i)
    bi = fc_match(family, True, True)
    if bi:
        ans['bi'] = Face(bi)
    return ans


def load_font_family(r):
    face, raw_name = r
    ans = get_font_files(raw_name)
    ans['regular'] = face
    return ans
