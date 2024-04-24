#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import re
from typing import Dict, Generator, Iterable, List, Optional, Tuple

from kitty.fast_data_types import CTFace, coretext_all_fonts
from kitty.fonts import FontFeature, FontSpec, VariableData
from kitty.options.types import Options
from kitty.typing import CoreTextFont
from kitty.utils import log_error

from . import ListedFont

attr_map = {(False, False): 'font_family',
            (True, False): 'bold_font',
            (False, True): 'italic_font',
            (True, True): 'bold_italic_font'}


FontMap = Dict[str, Dict[str, List[CoreTextFont]]]


def create_font_map(all_fonts: Iterable[CoreTextFont]) -> FontMap:
    ans: FontMap = {'family_map': {}, 'ps_map': {}, 'full_map': {}}
    for x in all_fonts:
        f = (x['family'] or '').lower()
        s = (x['style'] or '').lower()
        ps = (x['postscript_name'] or '').lower()
        ans['family_map'].setdefault(f, []).append(x)
        ans['ps_map'].setdefault(ps, []).append(x)
        ans['full_map'].setdefault(f'{f} {s}', []).append(x)
    return ans


def all_fonts_map() -> FontMap:
    ans: Optional[FontMap] = getattr(all_fonts_map, 'ans', None)
    if ans is None:
        ans = create_font_map(coretext_all_fonts())
        setattr(all_fonts_map, 'ans', ans)
    return ans


def list_fonts() -> Generator[ListedFont, None, None]:
    for fd in coretext_all_fonts():
        f = fd['family']
        if f:
            fn = fd['display_name']
            if not fn:
                fn = f'{f} {fd["style"]}'.strip()
            yield {'family': f, 'full_name': fn, 'postscript_name': fd['postscript_name'] or '', 'is_monospace': fd['monospace'],
                   'is_variable': fd['variable'], 'descriptor': fd}


def find_font_features(postscript_name: str) -> Tuple[FontFeature, ...]:
    """Not Implemented"""
    return ()


def find_best_match(family: str, bold: bool = False, italic: bool = False, ignore_face: Optional[CoreTextFont] = None) -> CoreTextFont:
    q = re.sub(r'\s+', ' ', family.lower())
    font_map = all_fonts_map()

    def score(candidate: CoreTextFont) -> Tuple[int, int, int, float]:
        style_match = 1 if candidate['bold'] == bold and candidate[
            'italic'
        ] == italic else 0
        monospace_match = 1 if candidate['monospace'] else 0
        is_regular_width = not candidate['expanded'] and not candidate['condensed']
        # prefer semi-bold to bold to heavy, less bold means less chance of
        # overflow
        weight_distance_from_medium = abs(candidate['weight'])
        return style_match, monospace_match, 1 if is_regular_width else 0, 1 - weight_distance_from_medium

    # First look for an exact match
    for selector in ('ps_map', 'full_map'):
        candidates = font_map[selector].get(q)
        if candidates:
            possible = sorted(candidates, key=score)[-1]
            if possible != ignore_face:
                return possible

    # Let CoreText choose the font if the family exists, otherwise
    # fallback to Menlo
    if q not in font_map['family_map']:
        log_error(f'The font {family} was not found, falling back to Menlo')
        q = 'menlo'
    candidates = font_map['family_map'][q]
    return sorted(candidates, key=score)[-1]


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
    ans = find_best_match(family)
    return ans, ans['bold'], ans['italic']


def get_variable_data_for_descriptor(f: ListedFont) -> VariableData:
    return CTFace(descriptor=descriptor(f)).get_variable_data()


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
