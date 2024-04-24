#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache
from typing import Dict, Generator, List, Optional, Tuple, cast

from kitty.fast_data_types import (
    FC_DUAL,
    FC_MONO,
    FC_SLANT_ITALIC,
    FC_SLANT_ROMAN,
    FC_WEIGHT_BOLD,
    FC_WEIGHT_REGULAR,
    FC_WIDTH_NORMAL,
    Face,
    fc_list,
    fc_match_postscript_name,
    parse_font_feature,
)
from kitty.fast_data_types import fc_match as fc_match_impl
from kitty.options.types import Options
from kitty.typing import FontConfigPattern
from kitty.utils import log_error

from . import FontFeature, FontSpec, ListedFont, VariableData

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


FontMap = Dict[str, Dict[str, List[FontConfigPattern]]]


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


@lru_cache()
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
            log_error(f'Ignoring invalid font feature: {feat}')
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
    # When aliases are defined, spacing can cause the incorrect font to be
    # returned, so check with and without spacing and use the one that matches.
    mono_possibility = fc_match(family, False, False, FC_MONO)
    dual_possibility = fc_match(family, False, False, FC_DUAL)
    any_possibility = fc_match(family, False, False, 0)
    tries = (dual_possibility, mono_possibility) if any_possibility == dual_possibility else (mono_possibility, dual_possibility)
    for possibility in tries:
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


def get_font_from_spec(
    spec: FontSpec, bold: bool = False, italic: bool = False, medium_font_spec: FontSpec = FontSpec(),
    resolved_medium_font: Optional[FontConfigPattern] = None
) -> FontConfigPattern:
    if not spec.is_system:
        raise NotImplementedError('TODO: Implement me')
    family = spec.system
    if family == 'auto' and (bold or italic):
        assert resolved_medium_font is not None
        family = resolved_medium_font['family']
    return find_best_match(family, bold, italic)


def get_font_files(opts: Options) -> Dict[str, FontConfigPattern]:
    ans: Dict[str, FontConfigPattern] = {}
    medium_font = get_font_from_spec(opts.font_family)
    kd = {(False, False): 'medium', (True, False): 'bold', (False, True): 'italic', (True, True): 'bi'}
    for (bold, italic), attr in attr_map.items():
        if bold or italic:
            font = get_font_from_spec(getattr(opts, attr), bold, italic, medium_font_spec=opts.font_family, resolved_medium_font=medium_font)
        else:
            font = medium_font
        key = kd[(bold, italic)]
        ans[key] = font
    return ans


def font_for_family(family: str) -> Tuple[FontConfigPattern, bool, bool]:
    ans = find_best_match(family, monospaced=False)
    return ans, ans.get('weight', 0) >= FC_WEIGHT_BOLD, ans.get('slant', FC_SLANT_ROMAN) != FC_SLANT_ROMAN


def descriptor(f: ListedFont) -> FontConfigPattern:
    d = f['descriptor']
    assert d['descriptor_type'] == 'fontconfig'
    return d


def get_variable_data_for_descriptor(f: ListedFont) -> VariableData:
    return Face(descriptor=descriptor(f)).get_variable_data()


def prune_family_group(g: List[ListedFont]) -> List[ListedFont]:
    # fontconfig creates dummy entries for named styles in variable fonts, prune them
    variable_paths = {descriptor(f)['path'] for f in g if f['is_variable']}
    if not variable_paths:
        return g
    def is_ok(d: FontConfigPattern) -> bool:
        return d['variable'] or d['path'] not in variable_paths

    return [x for x in g if is_ok(descriptor(x))]
