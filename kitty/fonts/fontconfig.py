#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache

from kitty.fast_data_types import (
    FC_SLANT_ITALIC, FC_SLANT_ROMAN, FC_WEIGHT_BOLD, FC_WEIGHT_REGULAR,
    fc_list, fc_match,
)

# TODO: how to log info (for font_family=auto)?
# TODO: Only with args.debug_font_fallback or a new option?
from ..utils import log_error

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


def find_best_match(family, bold=False, italic=False, monospaced=True):
    q = re.sub(r'\s+', ' ', family.lower())
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

    # Use fc-match with a generic family
    family = 'monospace' if monospaced else 'sans-serif'
    return fc_match(family, bold, italic)


def resolve_family(f, main_family, bold, italic):
    return main_family if (bold or italic) and f == 'auto' else f


def get_font_files(opts):
    ans = {}
    for (bold, italic), attr in attr_map.items():
        f = getattr(opts, attr)
        rf = resolve_family(f, opts.font_family, bold, italic)
        font = find_best_match(rf, bold, italic)
        if rf != font['family']:
            if f != 'auto':
                # Unexpected substitution.
                log_error('Using %s for %s=%s.' % (font['family'], attr, f))
            elif attr == 'font_family':
                # Info about auto-selection for font_family=auto.
                log_error('Using %s for %s=%s.' % (font['family'], attr, f))
        key = {(False, False): 'medium',
               (True, False): 'bold',
               (False, True): 'italic',
               (True, True): 'bi'}[(bold, italic)]
        ans[key] = font
    return ans


def font_for_family(family):
    ans = find_best_match(family, monospaced=False)
    return ans, ans.get('weight', 0) >= FC_WEIGHT_BOLD, ans.get('slant', FC_SLANT_ROMAN) != FC_SLANT_ROMAN
