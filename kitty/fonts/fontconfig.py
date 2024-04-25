#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache
from typing import Dict, Generator, List, Literal, Optional, Tuple, cast

from kitty.fast_data_types import (
    FC_DUAL,
    FC_MONO,
    FC_SLANT_ITALIC,
    FC_SLANT_ROMAN,
    FC_WEIGHT_BOLD,
    FC_WEIGHT_REGULAR,
    FC_WIDTH_NORMAL,
    fc_list,
)
from kitty.fast_data_types import fc_match as fc_match_impl
from kitty.typing import FontConfigPattern

from . import Descriptor, ListedFont, Score, Scorer, family_name_to_key

FontCollectionMapType = Literal['family_map', 'ps_map', 'full_map']
FontMap = Dict[FontCollectionMapType, Dict[str, List[FontConfigPattern]]]


def create_font_map(all_fonts: Tuple[FontConfigPattern, ...]) -> FontMap:
    ans: FontMap = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
    for x in all_fonts:
        if not x.get('path'):
            continue
        f = (x.get('family') or '').lower()
        full = (x.get('full_name') or '').lower()
        ps = (x.get('postscript_name') or '').lower()
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(full, []).append(x)
    return ans


@lru_cache(maxsize=2)
def all_fonts_map(monospaced: bool = True) -> FontMap:
    if monospaced:
        ans = fc_list(spacing=FC_DUAL) + fc_list(spacing=FC_MONO)
    else:
        # allow non-monospaced and bitmapped fonts as these are used for
        # symbol_map
        ans = fc_list(allow_bitmapped_fonts=True)
    return create_font_map(ans)


def list_fonts(only_variable: bool = False) -> Generator[ListedFont, None, None]:
    for fd in fc_list(only_variable=only_variable):
        f = fd.get('family')
        if f and isinstance(f, str):
            fn_ = fd.get('full_name')
            if fn_:
                fn = str(fn_)
            else:
                fn = f'{f} {fd.get("style", "")}'.strip()
            is_mono = fd.get('spacing') in ('MONO', 'DUAL')
            yield {
                'family': f, 'full_name': fn, 'postscript_name': str(fd.get('postscript_name', '')),
                'is_monospace': is_mono, 'descriptor': fd, 'is_variable': fd.get('variable', False),
            }


@lru_cache()
def fc_match(family: str, bold: bool, italic: bool, spacing: int = FC_MONO) -> FontConfigPattern:
    return fc_match_impl(family, bold, italic, spacing)


def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer:

    def score(candidate: Descriptor) -> Score:
        assert candidate['descriptor_type'] == 'fontconfig'
        variable_score = 0 if prefer_variable and candidate['variable'] else 1
        bold_score = abs((FC_WEIGHT_BOLD if bold else FC_WEIGHT_REGULAR) - candidate['weight'])
        italic_score = abs((FC_SLANT_ITALIC if italic else FC_SLANT_ROMAN) - candidate['slant'])
        monospace_match = 0
        if monospaced:
            monospace_match = 0 if candidate.get('spacing') == 'MONO' else 1
        width_score = abs(candidate['width'] - FC_WIDTH_NORMAL)
        return Score(variable_score, bold_score + italic_score, monospace_match, width_score)

    return score


def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> FontConfigPattern:
    # Use fc-match with a generic family
    family = 'monospace' if monospaced else 'sans-serif'
    return fc_match(family, bold, italic)


def find_best_match(
        family: str, bold: bool = False, italic: bool = False, monospaced: bool = True,
        ignore_face: Optional[FontConfigPattern] = None
) -> FontConfigPattern:
    from .common import find_best_match_in_candidates
    q = family_name_to_key(family)
    font_map = all_fonts_map(monospaced)
    scorer = create_scorer(bold, italic, monospaced)
    is_medium_face = not bold and not italic
    # First look for an exact match
    exact_match = (
        find_best_match_in_candidates(font_map['ps_map'].get(q, []), scorer, is_medium_face, ignore_face=ignore_face) or
        find_best_match_in_candidates(font_map['full_map'].get(q, []), scorer, is_medium_face, ignore_face=ignore_face) or
        find_best_match_in_candidates(font_map['family_map'].get(q, []), scorer, is_medium_face, ignore_face=ignore_face)
    )
    if exact_match:
        assert exact_match['descriptor_type'] == 'fontconfig'
        return exact_match

    # Use fc-match to see if we can find a monospaced font that matches family
    # When aliases are defined, spacing can cause the incorrect font to be
    # returned, so check with and without spacing and use the one that matches.
    mono_possibility = fc_match(family, False, False, FC_MONO)
    dual_possibility = fc_match(family, False, False, FC_DUAL)
    any_possibility = fc_match(family, False, False, 0)
    tries = (dual_possibility, mono_possibility) if any_possibility == dual_possibility else (mono_possibility, dual_possibility)
    for possibility in tries:
        for key, map_key in (('postscript_name', 'ps_map'), ('full_name', 'full_map'), ('family', 'family_map')):
            map_key = cast(FontCollectionMapType, map_key)
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
                    return sorted(candidates, key=scorer)[0]
    return find_last_resort_text_font(bold, italic, monospaced)


def font_for_family(family: str) -> Tuple[FontConfigPattern, bool, bool]:
    ans = find_best_match(family, monospaced=False)
    return ans, ans.get('weight', 0) >= FC_WEIGHT_BOLD, ans.get('slant', FC_SLANT_ROMAN) != FC_SLANT_ROMAN


def descriptor(f: ListedFont) -> FontConfigPattern:
    d = f['descriptor']
    assert d['descriptor_type'] == 'fontconfig'
    return d


def prune_family_group(g: List[ListedFont]) -> List[ListedFont]:
    # fontconfig creates dummy entries for named styles in variable fonts, prune them
    variable_paths = {descriptor(f)['path'] for f in g if f['is_variable']}
    if not variable_paths:
        return g
    def is_ok(d: FontConfigPattern) -> bool:
        return d['variable'] or d['path'] not in variable_paths

    return [x for x in g if is_ok(descriptor(x))]
