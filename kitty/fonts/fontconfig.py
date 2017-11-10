#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache

from kitty.fast_data_types import (
    FC_SLANT_ITALIC, FC_SLANT_ROMAN, FC_WEIGHT_BOLD, FC_WEIGHT_REGULAR, Face,
    fc_list, fc_match, fc_font
)

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


def create_font_map(all_fonts):
    ans = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
    for x in all_fonts:
        f = (x.get('family') or '').lower()
        full = (x.get('full_name') or '').lower()
        ps = (x.get('postscript_name') or '').lower()
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(full, []).append(x)
    return ans


@lru_cache()
def all_fonts_map(monospaced=True):
    return create_font_map(fc_list(monospaced))


def find_best_match(family, bold=False, italic=False, monospaced=True):
    q = re.sub(r'\s+', ' ', family.lower())
    font_map = all_fonts_map(monospaced)

    def score(candidate):
        bold_score = abs((FC_WEIGHT_BOLD if bold else FC_WEIGHT_REGULAR) - candidate['weight'])
        italic_score = abs((FC_SLANT_ITALIC if italic else FC_SLANT_ROMAN) - candidate['slant'])
        monospace_match = 0 if candidate['spacing'] == 'MONO' else 1
        return bold_score + italic_score, monospace_match

    # First look for an exact match
    for selector in ('ps_map', 'full_map', 'family_map'):
        candidates = font_map[selector].get(q)
        if candidates:
            candidates.sort(key=score)
            return candidates[0]

    # Use fc-match with a generic family
    family = 'monospace' if monospaced else 'sans-serif'
    return fc_match(family, bold, italic)


def face_from_font(font, pt_sz=11.0, xdpi=96.0, ydpi=96.0):
    font = fc_font(pt_sz, (xdpi + ydpi) / 2.0, font['path'], font['index'])
    return Face(font['path'], font['index'], font['hinting'], font['hint_style'], pt_sz, xdpi, ydpi)


def resolve_family(f, main_family, bold, italic):
    if (bold or italic) and f == 'auto':
        f = main_family
    return f


def save_medium_face(face):
    pass


def get_font_files(opts):
    ans = {}
    for (bold, italic), attr in attr_map.items():
        rf = resolve_family(getattr(opts, attr), opts.font_family, bold, italic)
        font = find_best_match(rf, bold, italic)
        key = {(False, False): 'medium',
               (True, False): 'bold',
               (False, True): 'italic',
               (True, True): 'bi'}[(bold, italic)]
        ans[key] = font
        if key == 'medium':
            save_medium_face.medium_font = font
    return ans


def font_for_family(family):
    ans = find_best_match(family)
    return ans, ans['weight'] >= FC_WEIGHT_BOLD, ans['slant'] != FC_SLANT_ROMAN


def font_for_text(text, current_font_family='monospace', pt_sz=11.0, xdpi=96.0, ydpi=96.0, bold=False, italic=False):
    return fc_match('monospace', bold, italic, False, pt_sz, str(text), (xdpi + ydpi) / 2.0)
