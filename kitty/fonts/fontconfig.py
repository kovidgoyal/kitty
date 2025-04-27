#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from collections.abc import Generator, Sequence
from functools import lru_cache
from typing import Literal, NamedTuple, Optional, cast

from kitty.fast_data_types import (
    FC_DUAL,
    FC_MONO,
    FC_SLANT_ITALIC,
    FC_SLANT_ROMAN,
    FC_WEIGHT_REGULAR,
    FC_WIDTH_NORMAL,
    Face,
    fc_list,
)
from kitty.fast_data_types import (
    FC_WEIGHT_SEMIBOLD as FC_WEIGHT_BOLD,
)
from kitty.fast_data_types import fc_match as fc_match_impl
from kitty.typing_compat import FontConfigPattern

from . import Descriptor, DescriptorVar, ListedFont, Score, Scorer, VariableData, family_name_to_key

FontCollectionMapType = Literal['family_map', 'ps_map', 'full_map', 'variable_map']
FontMap = dict[FontCollectionMapType, dict[str, list[FontConfigPattern]]]


def create_font_map(all_fonts: tuple[FontConfigPattern, ...]) -> FontMap:
    ans: FontMap = {'family_map': {}, 'ps_map': {}, 'full_map': {}, 'variable_map': {}}
    for x in all_fonts:
        if not x.get('path'):
            continue
        f = family_name_to_key(x['family'])
        full = family_name_to_key(x['full_name'])
        ps = family_name_to_key(x['postscript_name'])
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(full, []).append(x)
        if x['variable']:
            ans['variable_map'].setdefault(f, []).append(x)
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


def is_monospace(descriptor: FontConfigPattern) -> bool:
    return descriptor['spacing'] in ('MONO', 'DUAL')


def is_variable(descriptor: FontConfigPattern) -> bool:
    return descriptor['variable']


def list_fonts(only_variable: bool = False) -> Generator[ListedFont, None, None]:
    for fd in fc_list(only_variable=only_variable):
        f = fd.get('family')
        if f and isinstance(f, str):
            fn_ = fd.get('full_name')
            if fn_:
                fn = str(fn_)
            else:
                fn = f'{f} {fd.get("style", "")}'.strip()
            yield {
                'family': f, 'full_name': fn, 'postscript_name': str(fd.get('postscript_name', '')),
                'is_monospace': is_monospace(fd), 'descriptor': fd, 'is_variable': is_variable(fd),
                'style': fd['style'],
            }


@lru_cache
def fc_match(family: str, bold: bool, italic: bool, spacing: int = FC_MONO) -> FontConfigPattern:
    return fc_match_impl(family, bold, italic, spacing)


class WeightRange(NamedTuple):
    minimum: int = sys.maxsize
    maximum: int = -1
    medium: int = -1
    bold: int = -1

    @property
    def is_valid(self) -> bool:
        return self.minimum != wr.minimum and self.maximum != wr.maximum and self.medium != wr.medium and self.bold != wr.bold

wr = WeightRange()


@lru_cache
def weight_range_for_family(family: str) -> WeightRange:
    faces = all_fonts_map(True)['family_map'].get(family_name_to_key(family), ())
    mini, maxi, medium, bold = wr.minimum, wr.maximum, wr.medium, wr.bold
    seen_weights = set()
    for face in faces:
        w = face['weight']
        mini, maxi = min(w, mini), max(w, maxi)
        seen_weights.add(w)
        s = face['style'].lower()
        if not s:
            continue
        s = s.split()[0]
        if s == 'semibold':
            bold = w
        elif s == 'bold' and bold == wr.bold:
            bold = w
        elif s == 'regular':
            medium = w
        elif s == 'medium' and medium == wr.medium:
            medium = w
    if len(seen_weights) < 2:
        return wr
    return WeightRange(mini, maxi, medium, bold)



class FCScorer(Scorer):

    weight_range: WeightRange | None = None

    def score(self, candidate: Descriptor) -> Score:
        assert candidate['descriptor_type'] == 'fontconfig'
        variable_score = 0 if self.prefer_variable and candidate['variable'] else 1
        if self.weight_range is None:
            bold_score = abs((FC_WEIGHT_BOLD if self.bold else FC_WEIGHT_REGULAR) - candidate['weight'])
        else:
            bold_score = abs((self.weight_range.bold if self.bold else self.weight_range.medium) - candidate['weight'])
        italic_score = abs((FC_SLANT_ITALIC if self.italic else FC_SLANT_ROMAN) - candidate['slant'])
        monospace_match = 0
        if self.monospaced:
            monospace_match = 0 if candidate.get('spacing') == 'MONO' else 1
        width_score = abs(candidate['width'] - FC_WIDTH_NORMAL)
        return Score(variable_score, bold_score / 1000 + italic_score / 110, monospace_match, width_score)

    def sorted_candidates(self, candidates: Sequence[DescriptorVar], dump: bool = False) -> list[DescriptorVar]:
        self.weight_range = None
        families = {x['family'] for x in candidates}
        if len(families) == 1:
            wr = weight_range_for_family(next(iter(families)))
            if wr.is_valid and wr.medium < 100:  # Operator Mono and Cascadia Code are examples
                self.weight_range = wr
        candidates = sorted(candidates, key=self.score)
        if dump:
            print(self)
            if self.weight_range:
                print(self.weight_range)
            for x in candidates:
                assert x['descriptor_type'] == 'fontconfig'
                print(Face(descriptor=x).postscript_name(), f'weight={x["weight"]}', f'slant={x["slant"]}')
                print(' ', self.score(x))
            print()
        return candidates


def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer:
    return FCScorer(bold, italic, monospaced, prefer_variable)


def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> FontConfigPattern:
    # Use fc-match with a generic family
    family = 'monospace' if monospaced else 'sans-serif'
    return fc_match(family, bold, italic)


def find_best_match(
        family: str, bold: bool = False, italic: bool = False, monospaced: bool = True,
        ignore_face: FontConfigPattern | None = None, prefer_variable: bool = False,
) -> FontConfigPattern:
    from .common import find_best_match_in_candidates
    q = family_name_to_key(family)
    font_map = all_fonts_map(monospaced)
    scorer = create_scorer(bold, italic, monospaced, prefer_variable=prefer_variable)
    is_medium_face = not bold and not italic
    # First look for an exact match
    groups: tuple[FontCollectionMapType, ...] = ('ps_map', 'full_map', 'family_map')
    for which in groups:
        m = font_map[which]
        cq = m.get(q, [])
        if cq:
            if which == 'full_map' and cq[0]['family'] == cq[0]['full_name']:
                continue  # IBM Plex Mono has fullname of regular face == family_name under fontconfig
            exact_match = find_best_match_in_candidates(cq, scorer, is_medium_face, ignore_face=ignore_face)
            if exact_match:
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
            val: str | None = cast(Optional[str], possibility.get(key))
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
                    return scorer.sorted_candidates(candidates)[0]
    return find_last_resort_text_font(bold, italic, monospaced)


def font_for_family(family: str) -> tuple[FontConfigPattern, bool, bool]:
    ans = find_best_match(family, monospaced=False)
    return ans, ans.get('weight', 0) >= FC_WEIGHT_BOLD, ans.get('slant', FC_SLANT_ROMAN) != FC_SLANT_ROMAN


def descriptor(f: ListedFont) -> FontConfigPattern:
    d = f['descriptor']
    assert d['descriptor_type'] == 'fontconfig'
    return d


def prune_family_group(g: list[ListedFont]) -> list[ListedFont]:
    # fontconfig creates dummy entries for named styles in variable fonts, prune them
    variable_paths = {descriptor(f)['path'] for f in g if f['is_variable']}
    if not variable_paths:
        return g
    def is_ok(d: FontConfigPattern) -> bool:
        return d['variable'] or d['path'] not in variable_paths

    return [x for x in g if is_ok(descriptor(x))]


def set_named_style(name: str, font: FontConfigPattern, vd: VariableData) -> bool:
    q = name.lower()
    for i, ns in enumerate(vd['named_styles']):
        if ns['psname'].lower() == q:
            font['named_style'] = i
            return True
    for i, ns in enumerate(vd['named_styles']):
        if ns['name'].lower() == q:
            font['named_style'] = i
            return True
    if vd['elided_fallback_name']:
        for i, ns in enumerate(vd['named_styles']):
            eq = ' '.join(ns['name'].replace(vd['elided_fallback_name'], '').strip().split()).lower()
            if q == eq:
                font['named_style'] = i
                return True
    return False


def lift_axes_to_named_style_if_possible(font: FontConfigPattern, vd: VariableData) -> bool:
    axes = font.get('axes', tuple(ax['default'] for ax in vd['axes']))
    q = {vd['axes'][i]['tag']: val for i, val in enumerate(axes)}
    for i, ns in enumerate(vd['named_styles']):
        if ns['axis_values'] == q:
            font.pop('axes', None)
            font['named_style'] = i
            return True
    return False


def set_axis_values(tag_map: dict[str, float], font: FontConfigPattern, vd: VariableData) -> bool:
    axes = list(font.get('axes', ())) or [ax['default'] for ax in vd['axes']]
    changed = False
    for i, ax in enumerate(vd['axes']):
        val = tag_map.get(ax['tag'])
        if val is not None:
            changed = True
            axes[i] = val
    if changed:
        font['axes'] = tuple(axes)
        lift_axes_to_named_style_if_possible(font, vd)
    return changed


def get_axis_values(font: FontConfigPattern, vd: VariableData) -> dict[str, float]:
    ans: dict[str, float] = {}
    ns = font.get('named_style')
    if ns is not None:
        if ns > -1 and ns < len(vd['named_styles']):
            ans = vd['named_styles'][ns]['axis_values']

    axis_values = font.get('axes', ())
    for i, ax in enumerate(vd['axes']):
        tag = ax['tag']
        if i < len(axis_values):
            ans[tag] = axis_values[i]
        else:
            if tag not in ans:
                ans[tag] = ax['default']
    return ans
