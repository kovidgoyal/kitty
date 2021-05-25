#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache
from typing import Dict, Generator, List, Optional, Tuple, cast

from kitty.fast_data_types import (
    FC_DUAL, FC_MONO, FC_SLANT_ITALIC, FC_SLANT_ROMAN, FC_WEIGHT_BOLD,
    FC_WEIGHT_REGULAR, FC_WIDTH_NORMAL, fc_list, fc_match as fc_match_impl,
    fc_match_postscript_name, parse_font_feature
)
from kitty.options_stub import Options
from kitty.typing import FontConfigPattern
from kitty.utils import log_error

from . import ListedFont, FontFeature

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


FontMap = Dict[str, Dict[str, List[FontConfigPattern]]]


def create_font_map(all_fonts: Tuple[FontConfigPattern, ...]) -> FontMap:
    ans: FontMap = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
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
def all_fonts_map(monospaced: bool = True) -> FontMap:
    if monospaced:
        ans = fc_list(FC_DUAL) + fc_list(FC_MONO)
    else:
        ans = fc_list()
    return create_font_map(ans)


def list_fonts() -> Generator[ListedFont, None, None]:
    for fd in fc_list():
        f = fd.get('family')
        if f and isinstance(f, str):
            fn_ = fd.get('full_name')
            if fn_:
                fn = str(fn_)
            else:
                fn = (f + ' ' + str(fd.get('style', ''))).strip()
            is_mono = fd.get('spacing') in ('MONO', 'DUAL')
            yield {'family': f, 'full_name': fn, 'postscript_name': str(fd.get('postscript_name', '')), 'is_monospace': is_mono}


def family_name_to_key(family: str) -> str:
    return re.sub(r'\s+', ' ', family.lower())


@lru_cache()
def fc_match(family: str, bold: bool, italic: bool, spacing: int = FC_MONO) -> FontConfigPattern:
    return fc_match_impl(family, bold, italic, spacing)


def find_font_features(postscript_name: str) -> Tuple[FontFeature, ...]:
    pat = fc_match_postscript_name(postscript_name)

    if pat.get('postscript_name') != postscript_name or 'fontfeatures' not in pat:
        return ()

    features = []
    for feat in pat['fontfeatures']:
        try:
            parsed = parse_font_feature(feat)
        except ValueError:
            log_error('Ignoring invalid font feature: {}'.format(feat))
        else:
            features.append(FontFeature(feat, parsed))

    return tuple(features)


def find_best_match(family: str, bold: bool = False, italic: bool = False, monospaced: bool = True) -> FontConfigPattern:
    q = family_name_to_key(family)
    font_map = all_fonts_map(monospaced)

    def score(candidate: FontConfigPattern) -> Tuple[int, int, int]:
        bold_score = abs((FC_WEIGHT_BOLD if bold else FC_WEIGHT_REGULAR) - candidate.get('weight', 0))
        italic_score = abs((FC_SLANT_ITALIC if italic else FC_SLANT_ROMAN) - candidate.get('slant', 0))
        monospace_match = 0 if candidate.get('spacing') == 'MONO' else 1
        width_score = abs(candidate.get('width', FC_WIDTH_NORMAL) - FC_WIDTH_NORMAL)

        return bold_score + italic_score, monospace_match, width_score

    # First look for an exact match
    for selector in ('ps_map', 'full_map', 'family_map'):
        candidates = font_map[selector].get(q)
        if not candidates:
            continue
        if len(candidates) == 1 and (bold or italic) and candidates[0].get('family') == candidates[0].get('full_name'):
            # IBM Plex Mono does this, where the full name of the regular font
            # face is the same as its family name
            continue
        candidates.sort(key=score)
        return candidates[0]

    # Use fc-match to see if we can find a monospaced font that matches family
    for spacing in (FC_MONO, FC_DUAL):
        possibility = fc_match(family, False, False, spacing)
        for key, map_key in (('postscript_name', 'ps_map'), ('full_name', 'full_map'), ('family', 'family_map')):
            val: Optional[str] = cast(Optional[str], possibility.get(key))
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


def resolve_family(f: str, main_family: str, bold: bool, italic: bool) -> str:
    if (bold or italic) and f == 'auto':
        f = main_family
    return f


def get_font_files(opts: Options) -> Dict[str, FontConfigPattern]:
    ans: Dict[str, FontConfigPattern] = {}
    for (bold, italic), attr in attr_map.items():
        rf = resolve_family(getattr(opts, attr), opts.font_family, bold, italic)
        font = find_best_match(rf, bold, italic)
        key = {(False, False): 'medium',
               (True, False): 'bold',
               (False, True): 'italic',
               (True, True): 'bi'}[(bold, italic)]
        ans[key] = font
    return ans


def font_for_family(family: str) -> Tuple[FontConfigPattern, bool, bool]:
    ans = find_best_match(family, monospaced=False)
    return ans, ans.get('weight', 0) >= FC_WEIGHT_BOLD, ans.get('slant', FC_SLANT_ROMAN) != FC_SLANT_ROMAN
