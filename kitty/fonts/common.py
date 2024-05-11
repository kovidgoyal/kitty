#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence, Tuple, TypedDict, Union

from kitty.constants import is_macos
from kitty.fonts import Descriptor, DesignAxis, FontSpec, NamedStyle, Scorer, VariableData, family_name_to_key
from kitty.options.types import Options

if TYPE_CHECKING:
    from kitty.fast_data_types import CTFace
    from kitty.fast_data_types import Face as FT_Face

    FontCollectionMapType = Literal['family_map', 'ps_map', 'full_map', 'variable_map']
    FontMap = Dict[FontCollectionMapType, Dict[str, List[Descriptor]]]
    Face = Union[FT_Face, CTFace]
    def all_fonts_map(monospaced: bool) -> FontMap: ...
    def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer: ...
    def find_best_match(
        family: str, bold: bool = False, italic: bool = False, monospaced: bool = True, ignore_face: Optional[Descriptor] = None,
        prefer_variable: bool = False,
        ) -> Descriptor: ...
    def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> Descriptor: ...
    def face_from_descriptor(descriptor: Descriptor) -> Face: ...
    def is_monospace(descriptor: Descriptor) -> bool: ...
    def is_variable(descriptor: Descriptor) -> bool: ...
    def set_named_style(name: str, font: Descriptor, vd: VariableData) -> bool: ...
    def set_axis_values(tag_map: Dict[str, float], font: Descriptor, vd: VariableData) -> bool: ...
else:
    FontCollectionMapType = FontMap = None
    if is_macos:
        from kitty.fast_data_types import CTFace as Face
        from kitty.fonts.core_text import (
            all_fonts_map,
            create_scorer,
            find_best_match,
            find_last_resort_text_font,
            is_monospace,
            is_variable,
            set_axis_values,
            set_named_style,
        )
    else:
        from kitty.fast_data_types import Face
        from kitty.fonts.fontconfig import (
            all_fonts_map,
            create_scorer,
            find_best_match,
            find_last_resort_text_font,
            is_monospace,
            is_variable,
            set_axis_values,
            set_named_style,
        )
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


def get_variable_data_for_face(d: Face) -> VariableData:
    path = d.path
    if not path:
        return d.get_variable_data()
    ans = cache_for_variable_data_by_path.get(path)
    if ans is None:
        ans = cache_for_variable_data_by_path[path] = d.get_variable_data()
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

def pprint(*a: Any) -> None:
    from pprint import pprint
    pprint(*a)


def find_medium_variant(font: Descriptor) -> Descriptor:
    font = font.copy()
    vd = get_variable_data_for_descriptor(font)
    for i, ns in enumerate(vd['named_styles']):
        if ns['name'] == 'Regular':
            set_named_style(ns['psname'], font, vd)
            return font
    axis_values = {}
    for i, ax in enumerate(vd['axes']):
        tag = ax['tag']
        for dax in vd['design_axes']:
            if dax['tag'] == tag:
                for x in dax['values']:
                    if x['format'] in (1, 2):
                        if x['name'] == 'Regular':
                            axis_values[tag] = x['value']
                            break
    if axis_values:
        set_axis_values(axis_values, font, vd)
    return font


def get_design_value_for(dax: DesignAxis, default: float, bold: bool, italic: bool) -> float:
    if dax['tag'] == 'wght':
        keys = ('semibold', 'bold', 'heavy', 'black') if bold else ('regular', 'medium')
    elif dax['tag'] in ('ital', 'slnt'):
        keys = ('italic', 'oblique', 'slanted', 'slant') if italic else ('regular', 'normal', 'medium', 'upright')
    else:
        return default
    for x in dax['values']:
        if x['format'] in (1, 2):
            if x['name'].lower() in keys:
                return x['value']
    return default


def find_bold_italic_variant(medium: Descriptor, bold: bool, italic: bool) -> Descriptor:
    # we first pick the best font file for bold/italic if there are more than
    # one. For example SourceCodeVF has Italic and Upright faces with variable
    # weights in each, so we rely on the OS font matcher to give us the best
    # font file.
    monospaced = is_monospace(medium)
    fonts = all_fonts_map(monospaced)['variable_map'][family_name_to_key(medium['family'])]
    scorer = create_scorer(bold, italic, monospaced)
    fonts.sort(key=scorer)
    vd = get_variable_data_for_descriptor(fonts[0])
    ans = fonts[0].copy()
    # now we need to specialise all axes in ans
    axis_values = {}
    for i, ax in enumerate(vd['axes']):
        tag = ax['tag']
        for dax in vd['design_axes']:
            if dax['tag'] == tag:
                axis_values[tag] = get_design_value_for(dax, ax['default'], bold, italic)
                break
    if axis_values:
        set_axis_values(axis_values, ans, vd)
    return ans


def find_best_variable_face(spec: FontSpec, bold: bool, italic: bool, monospaced: bool, candidates: List[Descriptor]) -> Descriptor:
    if spec.variable_name:
        q = spec.variable_name.lower()
        for font in candidates:
            vd = get_variable_data_for_descriptor(font)
            if vd['variations_postscript_name_prefix'].lower() == q:
                return font
    if spec.style:
        q = spec.style.lower()
        for font in candidates:
            vd = get_variable_data_for_descriptor(font)
            for x in vd['named_styles']:
                if x['psname'].lower() == q:
                    return font
            for x in vd['named_styles']:
                if x['name'].lower() == q:
                    return font
    scorer = create_scorer(bold, italic, monospaced)
    candidates.sort(key=scorer)
    return candidates[0]


def get_fine_grained_font(
    spec: FontSpec, bold: bool = False, italic: bool = False, medium_font_spec: FontSpec = FontSpec(),
    resolved_medium_font: Optional[Descriptor] = None, monospaced: bool = True
) -> Descriptor:
    font_map = all_fonts_map(monospaced)
    is_medium_face = resolved_medium_font is None
    scorer = create_scorer(bold, italic, monospaced)
    if spec.postscript_name:
        q = find_best_match_in_candidates(font_map['ps_map'].get(family_name_to_key(spec.postscript_name), []), scorer, is_medium_face)
        if q:
            return q
    if spec.full_name:
        q = find_best_match_in_candidates(font_map['full_map'].get(family_name_to_key(spec.full_name), []), scorer, is_medium_face)
        if q:
            return q
    if spec.family:
        key = family_name_to_key(spec.family)
        # First look for a variable font
        candidates = font_map['variable_map'].get(key, [])
        if candidates:
            q = candidates[0] if len(candidates) == 1 else find_best_variable_face(spec, bold, italic, monospaced, candidates)
            q, applied = apply_variation_to_pattern(q, spec)
            if applied:
                return q
            return find_medium_variant(q) if resolved_medium_font is None else find_bold_italic_variant(resolved_medium_font, bold, italic)
        # Now look for any font
        candidates = font_map['family_map'].get(key, [])
        if candidates:
            if spec.style:
                qs = spec.style.lower()
                candidates = [x for x in candidates if x['style'].lower() == qs]
            q = find_best_match_in_candidates(candidates, scorer, is_medium_face)
            if q:
                return q

    return find_last_resort_text_font(bold, italic, monospaced)


def apply_variation_to_pattern(pat: Descriptor, spec: FontSpec) -> Tuple[Descriptor, bool]:
    vd = face_from_descriptor(pat).get_variable_data()
    pat = pat.copy()
    if spec.style:
        if set_named_style(spec.style, pat, vd):
            return pat, True
    tag_map, name_map = {}, {}
    for i, ax in enumerate(vd['axes']):
        tag_map[ax['tag']] = i
        if ax['strid']:
            name_map[ax['strid'].lower()] = ax['tag']
    axis_values = {}
    for axspec in spec.axes:
        qname = axspec[0]
        if qname in tag_map:
            axis_values[qname] = axspec[1]
            continue
        tag = name_map.get(qname.lower())
        if tag:
            axis_values[tag] = axspec[1]
    return pat, set_axis_values(axis_values, pat, vd)


def get_font_from_spec(
    spec: FontSpec, bold: bool = False, italic: bool = False, medium_font_spec: FontSpec = FontSpec(),
    resolved_medium_font: Optional[Descriptor] = None
) -> Descriptor:
    if not spec.is_system:
        return get_fine_grained_font(spec, bold, italic, medium_font_spec, resolved_medium_font)
    family = spec.system
    if family == 'auto':
        if bold or italic:
            assert resolved_medium_font is not None
            family = resolved_medium_font['family']
            if is_variable(resolved_medium_font):
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


def develop(family: str = '') -> None:
    import sys
    family = family or sys.argv[-1]
    from kitty.options.utils import parse_font_spec
    opts = Options()
    opts.font_family = parse_font_spec(family)
    ff = get_font_files(opts)
    def s(d: Descriptor) -> str:
        return str(face_from_descriptor(d))

    print('Medium     :', s(ff['medium']))
    print()
    print('Bold       :', s(ff['bold']))
    print()
    print('Italic     :', s(ff['italic']))
    print()
    print('Bold-Italic:', s(ff['bi']))


def axis_values_are_equal(defaults: Dict[str, float], a: Dict[str, float], b: Dict[str, float]) -> bool:
    ad, bd = defaults.copy(), defaults.copy()
    ad.update(a)
    bd.update(b)
    return ad == bd


def _get_named_style(axis_map: Dict[str, float], vd: VariableData) -> Optional[NamedStyle]:
    defaults = {ax['tag']: ax['default'] for ax in vd['axes']}
    for ns in vd['named_styles']:
        if axis_values_are_equal(defaults, ns['axis_values'], axis_map):
            return ns
    return None


def get_named_style(face_or_descriptor: Union[Face, Descriptor]) -> Optional[NamedStyle]:
    if isinstance(face_or_descriptor, dict):
        d: Descriptor = face_or_descriptor
        vd = get_variable_data_for_descriptor(d)
        if d['descriptor_type'] == 'fontconfig':
            ns = d.get('named_instance', -1)
            if ns > -1 and ns < len(vd['named_styles']):
                return vd['named_styles'][ns]
            axis_map = {}
            axes = vd['axes']
            for i, val in enumerate(d.get('axes', ())):
                if i < len(axes):
                    axis_map[axes[i]['tag']] = val
        else:
            axis_map = d.get('axis_map', {}).copy()
    else:
        face: Face = face_or_descriptor
        q = face.get_variation()
        if q is None:
            return None
        axis_map = q
    return _get_named_style(axis_map, vd)


def get_axis_map(face_or_descriptor: Union[Face, Descriptor]) -> Dict[str, float]:
    base_axis_map = {}
    axis_map: Dict[str, float] = {}
    if isinstance(face_or_descriptor, dict):
        d: Descriptor = face_or_descriptor
        vd = get_variable_data_for_descriptor(d)
        if d['descriptor_type'] == 'fontconfig':
            ns = d.get('named_instance', -1)
            if ns > -1 and ns < len(vd['named_styles']):
                base_axis_map = vd['named_styles'][ns]['axis_values'].copy()
            axis_map = {}
            axes = vd['axes']
            for i, val in enumerate(d.get('axes', ())):
                if i < len(axes):
                    axis_map[axes[i]['tag']] = val

        else:
            axis_map = d.get('axis_map', {}).copy()
    else:
        face: Face = face_or_descriptor
        q = face.get_variation()
        if q is not None:
            axis_map = q
    base_axis_map.update(axis_map)
    return base_axis_map


def spec_for_descriptor(descriptor: Descriptor) -> str:
    from shlex import quote as q
    if is_variable(descriptor):
        vd = get_variable_data_for_descriptor(descriptor)
        spec = f'family={q(descriptor["family"])}'
        if vd['variations_postscript_name_prefix']:
            spec += f' variable_name={q(vd["variations_postscript_name_prefix"])}'
        ns = get_named_style(descriptor)
        if ns is None:
            for key, val in get_axis_map(descriptor).items():
                spec += f' {key}={val:g}'
        else:
            spec = f'{spec} style={q(ns["psname"])}'
        return spec
    return descriptor['postscript_name']


if __name__ == '__main__':
    develop()
