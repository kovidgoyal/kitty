#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Sequence, TypedDict, Union

from kitty.constants import is_macos
from kitty.options.types import Options

from . import Descriptor, FontSpec, Scorer, VariableData, family_name_to_key

if TYPE_CHECKING:
    from kitty.fast_data_types import CTFace
    from kitty.fast_data_types import Face as FT_Face

    FontCollectionMapType = Literal['family_map', 'ps_map', 'full_map']
    FontMap = Dict[FontCollectionMapType, Dict[str, List[Descriptor]]]
    Face = Union[FT_Face, CTFace]
    def all_fonts_map(monospaced: bool) -> FontMap: ...
    def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer: ...
    def find_best_match(
        family: str, bold: bool = False, italic: bool = False, monospaced: bool = True, ignore_face: Optional[Descriptor] = None
        ) -> Descriptor: ...
    def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> Descriptor: ...
    def face_from_descriptor(descriptor: Descriptor) -> Face: ...
else:
    FontCollectionMapType = FontMap = None
    if is_macos:
        from kitty.fast_data_types import CTFace as Face

        from .core_text import all_fonts_map, create_scorer, find_best_match, find_last_resort_text_font
    else:
        from kitty.fast_data_types import Face

        from .fontconfig import all_fonts_map, create_scorer, find_best_match, find_last_resort_text_font
    def face_from_descriptor(descriptor: Descriptor) -> Face: return Face(descriptor=descriptor)


cache_for_variable_data_by_path: Dict[str, VariableData] = {}
attr_map = {(False, False): 'font_family', (True, False): 'bold_font', (False, True): 'italic_font', (True, True): 'bold_italic_font'}


def get_variable_data_for_descriptor(d: Descriptor) -> VariableData:
    if not d['path']:
        return face_from_descriptor(d).get_variable_data()
    ans = cache_for_variable_data_by_path.get(d['path'])
    if ans is None:
        ans = cache_for_variable_data_by_path[d['path']] = face_from_descriptor(d).get_variable_data()
    return ans


def find_best_match_in_candidates(
    candidates: Sequence[Descriptor], scorer: Scorer, is_medium_face: bool, ignore_face: Optional[Descriptor] = None
) -> Optional[Descriptor]:
    if len(candidates) == 1 and not is_medium_face and candidates[0].get('family') == candidates[0].get('full_name'):
        # IBM Plex Mono does this, where the full name of the regular font
        # face is the same as its family name
        return None
    candidates = sorted(candidates, key=scorer)
    for x in candidates:
        if ignore_face is None or x != ignore_face:
            return x
    return None


def get_fine_grained_font(
    spec: FontSpec, bold: bool = False, italic: bool = False, medium_font_spec: FontSpec = FontSpec(),
    resolved_medium_font: Optional[Descriptor] = None, monospaced: bool = True
) -> Descriptor:
    font_map = all_fonts_map(monospaced)
    is_medium_face = resolved_medium_font is None
    prefer_variable = bool(spec.axes) or bool(spec.style)
    scorer = create_scorer(bold, italic, monospaced, prefer_variable=prefer_variable)
    if spec.postscript_name:
        q = find_best_match_in_candidates(font_map['ps_map'].get(family_name_to_key(spec.postscript_name), []), scorer, is_medium_face)
        if q:
            return q
    if spec.full_name:
        q = find_best_match_in_candidates(font_map['full_map'].get(family_name_to_key(spec.full_name), []), scorer, is_medium_face)
        if q:
            return q
    if spec.family:
        candidates = font_map['family_map'].get(family_name_to_key(spec.family), [])
        if spec.style:
            qs = spec.style.lower()
            candidates = [x for x in candidates if x['style'].lower() == qs]
        q = find_best_match_in_candidates(candidates, scorer, is_medium_face)
        if q:
            return q
    return find_last_resort_text_font(bold, italic, monospaced)


def apply_variation_to_pattern(pat: Descriptor, spec: FontSpec) -> Descriptor:
    if not pat['variable']:
        return pat

    vd = face_from_descriptor(pat).get_variable_data()
    if spec.style:
        q = spec.style.lower()
        for i, ns in enumerate(vd['named_styles']):
            if ns.get('psname') and ns['psname'].lower() == q:
                pat['named_style'] = i
                break
        else:
            for i, ns in enumerate(vd['named_styles']):
                if ns['name'].lower() == q:
                    pat['named_style'] = i
                    break
    tag_map, name_map = {}, {}
    axes = [ax['default'] for ax in vd['axes']]
    for i, ax in enumerate(vd['axes']):
        tag_map[ax['tag']] = i
        if ax['strid']:
            name_map[ax['strid'].lower()] = i
    changed = False
    for axspec in spec.axes:
        qname = axspec[0]
        axis = tag_map.get(qname)
        if axis is None:
            axis = name_map.get(qname.lower())
        if axis is not None:
            axes[axis] = axspec[1]
            changed = True
    if changed:
        pat['axes'] = axes
    return pat


def find_bold_italic_variant(medium: Descriptor, bold: bool, italic: bool) -> Optional[Descriptor]:
    raise NotImplementedError('TODO: Implement me')


def get_font_from_spec(
    spec: FontSpec, bold: bool = False, italic: bool = False, medium_font_spec: FontSpec = FontSpec(),
    resolved_medium_font: Optional[Descriptor] = None
) -> Descriptor:
    if not spec.is_system:
        return apply_variation_to_pattern(get_fine_grained_font(spec, bold, italic, medium_font_spec, resolved_medium_font), spec)
    family = spec.system
    if family == 'auto':
        if bold or italic:
            assert resolved_medium_font is not None
            family = resolved_medium_font['family']
            if resolved_medium_font['variable']:
                v = find_bold_italic_variant(resolved_medium_font, bold, italic)
                if v is not None:
                    return v
        else:
            family = 'monospace'
    return find_best_match(family, bold, italic, ignore_face=resolved_medium_font)


class FontFiles(TypedDict):
    medium: Descriptor
    bold: Descriptor
    italic: Descriptor
    bi: Descriptor


def get_font_files(opts: Options) -> FontFiles:
    ans: Dict[str, Descriptor] = {}
    medium_font = get_font_from_spec(opts.font_family)
    kd = {(False, False): 'medium', (True, False): 'bold', (False, True): 'italic', (True, True): 'bi'}
    for (bold, italic), attr in attr_map.items():
        if bold or italic:
            font = get_font_from_spec(getattr(opts, attr), bold, italic, medium_font_spec=opts.font_family, resolved_medium_font=medium_font)
        else:
            font = medium_font
        key = kd[(bold, italic)]
        ans[key] = font
    return {'medium': ans['medium'], 'bold': ans['bold'], 'italic': ans['italic'], 'bi': ans['bi']}
