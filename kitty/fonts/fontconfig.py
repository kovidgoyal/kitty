#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache

from kitty.fast_data_types import (
    FC_SLANT_ITALIC, FC_SLANT_ROMAN, FC_WEIGHT_BOLD, FC_WEIGHT_REGULAR,
    fc_list, fc_match,
)

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


def create_font_map(all_fonts):
    ans = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
    for x in all_fonts:
        if 'path' not in x:
            continue
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


def list_fonts():
    for fd in fc_list(False):
        f = fd.get('family')
        if f:
            fn = fd.get('full_name') or (f + ' ' + fd.get('style', '')).strip()
            is_mono = fd.get('spacing') == 'MONO'
            yield {'family': f, 'full_name': fn, 'is_monospace': is_mono}


def family_name_to_key(family):
    return re.sub(r'\s+', ' ', family.lower())


def find_best_match(family, bold=False, italic=False, monospaced=True):
    q = family_name_to_key(family)
    font_map = all_fonts_map(monospaced)

    def score(candidate):
        bold_score = abs((FC_WEIGHT_BOLD if bold else FC_WEIGHT_REGULAR) - candidate.get('weight', 0))
        italic_score = abs((FC_SLANT_ITALIC if italic else FC_SLANT_ROMAN) - candidate.get('slant', 0))
        monospace_match = 0 if candidate.get('spacing') == 'MONO' else 1
        return bold_score + italic_score, monospace_match

    # First look for an exact match
    for selector in ('ps_map', 'full_map', 'family_map'):
        candidates = font_map[selector].get(q)
        if candidates:
            candidates.sort(key=score)
            return candidates[0]

    # Use fc-match to see if we can find a monospaced font that matches family
    possibility = fc_match(family, False, False)
    for key, map_key in (('postscript_name', 'ps_map'), ('full_name', 'full_map'), ('family', 'family_map')):
        val = possibility.get(key)
        if val:
            candidates = font_map[map_key].get(family_name_to_key(val))
            if candidates:
                if len(candidates) == 1:
                    # happens if the family name is an alias, so we search with
                    # the actual family name to see if we can find all the
                    # fonts in the family.
                    family_name_candidates = font_map['family_map'].get(family_name_to_key(candidates[0]['family']))
                    if family_name_candidates and len(family_name_candidates) > 1:
                        candidates = family_name_candidates
                return sorted(candidates, key=score)[0]

    # Use fc-match with a generic family
    family = 'monospace' if monospaced else 'sans-serif'
    return fc_match(family, bold, italic)


def resolve_family(f, main_family, bold, italic):
    if (bold or italic) and f == 'auto':
        f = main_family
    return f


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
    return ans


def font_for_family(family):
    ans = find_best_match(family, monospaced=False)
    return ans, ans.get('weight', 0) >= FC_WEIGHT_BOLD, ans.get('slant', FC_SLANT_ROMAN) != FC_SLANT_ROMAN
