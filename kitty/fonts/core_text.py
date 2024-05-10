#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import itertools
import operator
import re
from collections import defaultdict
from functools import lru_cache
from typing import Dict, Generator, Iterable, List, Optional, Tuple

from kitty.fast_data_types import coretext_all_fonts
from kitty.fonts import FontSpec
from kitty.options.types import Options
from kitty.typing import CoreTextFont
from kitty.utils import log_error

from . import Descriptor, ListedFont, Score, Scorer, VariableData

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


FontMap = Dict[str, Dict[str, List[CoreTextFont]]]


def create_font_map(all_fonts: Iterable[CoreTextFont]) -> FontMap:
    ans: FontMap = {'family_map': {}, 'ps_map': {}, 'full_map': {}, 'variable_map': {}}
    vmap: Dict[str, List[CoreTextFont]] = defaultdict(list)
    for x in all_fonts:
        f = (x['family'] or '').lower()
        s = (x['style'] or '').lower()
        ps = (x['postscript_name'] or '').lower()
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


def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer:

    def score(candidate: Descriptor) -> Score:
        assert candidate['descriptor_type'] == 'core_text'
        variable_score = 0 if prefer_variable and candidate['variation'] is not None else 1
        style_match = 1 if candidate['bold'] == bold and candidate[
            'italic'
        ] == italic else 0
        monospace_match = 1 if candidate['monospace'] else 0
        is_regular_width = not candidate['expanded'] and not candidate['condensed']
        # prefer semi-bold to bold to heavy, less bold means less chance of
        # overflow
        weight_distance_from_medium = abs(candidate['weight'])
        return Score(variable_score, 1 - style_match, 1 - monospace_match, 1 - is_regular_width, weight_distance_from_medium)

    return score


def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> CoreTextFont:
    font_map = all_fonts_map(monospaced)
    candidates = font_map['family_map']['menlo']
    scorer = create_scorer(bold, italic, monospaced)
    return sorted(candidates, key=scorer)[0]


def find_best_match(
    family: str, bold: bool = False, italic: bool = False, monospaced: bool = True, ignore_face: Optional[CoreTextFont] = None,
    prefer_variable: bool = False
) -> CoreTextFont:
    q = re.sub(r'\s+', ' ', family.lower())
    font_map = all_fonts_map(monospaced)
    scorer = create_scorer(bold, italic, monospaced, prefer_variable=prefer_variable)

    # First look for an exact match
    for selector in ('ps_map', 'full_map'):
        candidates = font_map[selector].get(q)
        if candidates:
            possible = sorted(candidates, key=scorer)[0]
            if possible != ignore_face:
                return possible

    # Let CoreText choose the font if the family exists, otherwise
    # fallback to Menlo
    if q not in font_map['family_map']:
        log_error(f'The font {family} was not found, falling back to Menlo')
        q = 'menlo'
    candidates = font_map['family_map'][q]
    return sorted(candidates, key=scorer)[0]


def get_font_from_spec(
    spec: FontSpec, bold: bool = False, italic: bool = False, medium_font_spec: FontSpec = FontSpec(),
    resolved_medium_font: Optional[CoreTextFont] = None
) -> CoreTextFont:
    if not spec.is_system:
        raise NotImplementedError('TODO: Implement me')
    family = spec.system
    if family == 'auto' and (bold or italic):
        assert resolved_medium_font is not None
        family = resolved_medium_font['family']
    return find_best_match(family, bold, italic, ignore_face=resolved_medium_font)


def get_font_files(opts: Options) -> Dict[str, CoreTextFont]:
    medium_font = get_font_from_spec(opts.font_family)
    ans: Dict[str, CoreTextFont] = {}
    kd = {(False, False): 'medium', (True, False): 'bold', (False, True): 'italic', (True, True): 'bi'}
    for (bold, italic) in sorted(attr_map):
        attr = attr_map[(bold, italic)]
        key = kd[(bold, italic)]
        if bold or italic:
            font = get_font_from_spec(getattr(opts, attr), bold, italic, medium_font_spec=opts.font_family, resolved_medium_font=medium_font)
        else:
            font = medium_font
        ans[key] = font
        if key == 'medium':
            setattr(get_font_files, 'medium_family', font['family'])
    return ans


def font_for_family(family: str) -> Tuple[CoreTextFont, bool, bool]:
    ans = find_best_match(family, monospaced=False)
    return ans, ans['bold'], ans['italic']


def descriptor(f: ListedFont) -> CoreTextFont:
    d = f['descriptor']
    assert d['descriptor_type'] == 'core_text'
    return d


def prune_family_group(g: List[ListedFont]) -> List[ListedFont]:
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


def set_axis_values(tag_map: Dict[str, float], font: CoreTextFont, vd: VariableData) -> bool:
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
    return False
