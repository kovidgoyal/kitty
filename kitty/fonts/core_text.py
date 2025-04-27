#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import itertools
import operator
from collections import defaultdict
from collections.abc import Generator, Iterable, Sequence
from functools import lru_cache
from typing import NamedTuple

from kitty.fast_data_types import CTFace, coretext_all_fonts
from kitty.typing_compat import CoreTextFont
from kitty.utils import log_error

from . import Descriptor, DescriptorVar, ListedFont, Score, Scorer, VariableData, family_name_to_key

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


FontMap = dict[str, dict[str, list[CoreTextFont]]]


def create_font_map(all_fonts: Iterable[CoreTextFont]) -> FontMap:
    ans: FontMap = {'family_map': {}, 'ps_map': {}, 'full_map': {}, 'variable_map': {}}
    vmap: dict[str, list[CoreTextFont]] = defaultdict(list)
    for x in all_fonts:
        f = family_name_to_key(x['family'])
        s = family_name_to_key(x['style'])
        ps = family_name_to_key(x['postscript_name'])
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(f'{f} {s}', []).append(x)
        if x['variation'] is not None:
            vmap[f].append(x)
    # CoreText makes a separate descriptor for each named style in each
    # variable font file. Keep only the default style descriptor, which has an
    # empty variation dictionary. If no default exists, pick the one with the
    # smallest variation dictionary size.
    keyfunc = operator.itemgetter('path')
    for k, v in vmap.items():
        v.sort(key=keyfunc)
        uniq_per_path = []
        for _, g in itertools.groupby(v, keyfunc):
            uniq_per_path.append(sorted(g, key=lambda x: len(x['variation'] or ()))[0])
        ans['variable_map'][k] = uniq_per_path
    return ans


@lru_cache(maxsize=2)
def all_fonts_map(monospaced: bool = True) -> FontMap:
    return create_font_map(coretext_all_fonts(monospaced))


def is_monospace(descriptor: CoreTextFont) -> bool:
    return descriptor['monospace']


def is_variable(descriptor: CoreTextFont) -> bool:
    return descriptor['variation'] is not None


def list_fonts() -> Generator[ListedFont, None, None]:
    for fd in coretext_all_fonts(False):
        f = fd['family']
        if f:
            fn = fd['display_name']
            if not fn:
                fn = f'{f} {fd["style"]}'.strip()
            yield {'family': f, 'full_name': fn, 'postscript_name': fd['postscript_name'] or '', 'is_monospace': fd['monospace'],
                   'is_variable': is_variable(fd), 'descriptor': fd, 'style': fd['style']}


class WeightRange(NamedTuple):
    minimum: float = 99999
    maximum: float = -99999
    medium: float = -99999
    bold: float = -99999

    @property
    def is_valid(self) -> bool:
        return self.minimum != wr.minimum and self.maximum != wr.maximum and self.medium != wr.medium and self.bold != wr.bold

wr = WeightRange()


@lru_cache
def weight_range_for_family(family: str) -> WeightRange:
    faces = all_fonts_map(True)['family_map'].get(family_name_to_key(family), ())
    mini, maxi, medium, bold = wr.minimum, wr.maximum, wr.medium, wr.bold
    for face in faces:
        w = face['weight']
        mini, maxi = min(w, mini), max(w, maxi)
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
    return WeightRange(mini, maxi, medium, bold)


class CTScorer(Scorer):
    weight_range: WeightRange | None = None

    def score(self, candidate: Descriptor) -> Score:
        assert candidate['descriptor_type'] == 'core_text'
        variable_score = 0 if self.prefer_variable and candidate['variation'] is not None else 1
        bold_score = candidate['weight']  # -1 to 1 with 0 being normal
        if self.weight_range is None:
            if bold_score < 0:  # thinner than normal, reject
                bold_score = 2.0
            else:
                if self.bold:
                    # prefer semibold=0.3 to full bold = 0.4
                    bold_score = abs(bold_score - 0.3)
        else:
            anchor = self.weight_range.bold if self.bold else self.weight_range.medium
            bold_score = abs(bold_score - anchor)
        italic_score = candidate['slant'] # -1 to 1 with 0 being upright < 0 being backward slant, abs(slant) == 1 implies 30 deg rotation
        if self.italic:
            if italic_score < 0:
                italic_score = 2.0
            else:
                italic_score = abs(1 - italic_score)
        monospace_match = 0 if candidate['monospace'] else 1
        is_regular_width = not candidate['expanded'] and not candidate['condensed']
        return Score(variable_score, bold_score + italic_score, monospace_match, 0 if is_regular_width else 1)

    def sorted_candidates(self, candidates: Sequence[DescriptorVar], dump: bool = False) -> list[DescriptorVar]:
        self.weight_range = None
        families = {x['family'] for x in candidates}
        if len(families) == 1:
            wr = weight_range_for_family(next(iter(families)))
            if wr.is_valid and wr.medium < 0:  # Operator Mono is an example of this craziness
                self.weight_range = wr
        candidates = sorted(candidates, key=self.score)
        if dump:
            print(self)
            if self.weight_range:
                print(self.weight_range)
            for x in candidates:
                assert x['descriptor_type'] == 'core_text'
                print(CTFace(descriptor=x).postscript_name(),
                      f'bold={x["bold"]}', f'italic={x["italic"]}', f'weight={x["weight"]:.2f}', f'slant={x["slant"]:.2f}')
                print(' ', self.score(x))
            print()
        return candidates


def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer:
    return CTScorer(bold, italic, monospaced, prefer_variable)


def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> CoreTextFont:
    font_map = all_fonts_map(monospaced)
    candidates = font_map['family_map']['menlo']
    return create_scorer(bold, italic, monospaced).sorted_candidates(candidates)[0]


def find_best_match(
    family: str, bold: bool = False, italic: bool = False, monospaced: bool = True, ignore_face: CoreTextFont | None = None,
    prefer_variable: bool = False
) -> CoreTextFont:
    q = family_name_to_key(family)
    font_map = all_fonts_map(monospaced)
    scorer = create_scorer(bold, italic, monospaced, prefer_variable=prefer_variable)

    # First look for an exact match
    for selector in ('ps_map', 'full_map'):
        candidates = font_map[selector].get(q)
        if candidates:
            candidates = scorer.sorted_candidates(candidates)
            possible = candidates[0]
            if possible != ignore_face:
                return possible

    # See if we have a variable font
    if not bold and not italic and font_map['variable_map'].get(q):
        candidates = font_map['variable_map'][q]
        candidates = scorer.sorted_candidates(candidates)
        possible = candidates[0]
        if possible != ignore_face:
            from .common import find_medium_variant
            return find_medium_variant(possible)

    # Let CoreText choose the font if the family exists, otherwise
    # fallback to Menlo
    if q not in font_map['family_map']:
        if family.lower() not in ('monospace', 'symbols nerd font mono'):
            log_error(f'The font {family} was not found, falling back to Menlo')
        q = 'menlo'
    candidates = scorer.sorted_candidates(font_map['family_map'][q])
    return candidates[0]


def font_for_family(family: str) -> tuple[CoreTextFont, bool, bool]:
    ans = find_best_match(family, monospaced=False)
    return ans, ans['bold'], ans['italic']


def descriptor(f: ListedFont) -> CoreTextFont:
    d = f['descriptor']
    assert d['descriptor_type'] == 'core_text'
    return d


def prune_family_group(g: list[ListedFont]) -> list[ListedFont]:
    # CoreText returns a separate font for every style in the variable font, so
    # merge them.
    variable_paths = {descriptor(f)['path']: False for f in g if f['is_variable']}
    if not variable_paths:
        return g
    def is_ok(d: CoreTextFont) -> bool:
        if d['path'] not in variable_paths:
            return True
        if not variable_paths[d['path']]:
            variable_paths[d['path']] = True
            return True
        return False
    return [x for x in g if is_ok(descriptor(x))]


def set_axis_values(tag_map: dict[str, float], font: CoreTextFont, vd: VariableData) -> bool:
    known_axes = {ax['tag'] for ax in vd['axes']}
    previous = font.get('axis_map', {})
    new = previous.copy()
    for tag in known_axes:
        val = tag_map.get(tag)
        if val is not None:
            new[tag] = val
    font['axis_map'] = new
    return new != previous


def set_named_style(name: str, font: CoreTextFont, vd: VariableData) -> bool:
    q = name.lower()
    for i, ns in enumerate(vd['named_styles']):
        if ns['psname'].lower() == q:
            return set_axis_values(ns['axis_values'], font, vd)
    for i, ns in enumerate(vd['named_styles']):
        if ns['name'].lower() == q:
            return set_axis_values(ns['axis_values'], font, vd)
    if vd['elided_fallback_name']:
        for i, ns in enumerate(vd['named_styles']):
            eq = ' '.join(ns['name'].replace(vd['elided_fallback_name'], '').strip().split()).lower()
            if q == eq:
                return set_axis_values(ns['axis_values'], font, vd)
    return False


def get_axis_values(font: CoreTextFont, vd: VariableData) -> dict[str, float]:
    return font.get('axis_map', {})
