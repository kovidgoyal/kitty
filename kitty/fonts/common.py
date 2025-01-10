#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Any, Literal, TypedDict, Union

from kitty.constants import is_macos
from kitty.fast_data_types import ParsedFontFeature
from kitty.fonts import Descriptor, DescriptorVar, DesignAxis, FontSpec, NamedStyle, Scorer, VariableAxis, VariableData, family_name_to_key
from kitty.options.types import Options

if TYPE_CHECKING:
    from kitty.fast_data_types import CTFace
    from kitty.fast_data_types import Face as FT_Face

    FontCollectionMapType = Literal['family_map', 'ps_map', 'full_map', 'variable_map']
    FontMap = dict[FontCollectionMapType, dict[str, list[Descriptor]]]
    Face = Union[FT_Face, CTFace]
    def all_fonts_map(monospaced: bool) -> FontMap: ...
    def create_scorer(bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> Scorer: ...
    def find_best_match(
        family: str, bold: bool = False, italic: bool = False, monospaced: bool = True, ignore_face: Descriptor | None = None,
        prefer_variable: bool = False,
        ) -> Descriptor: ...
    def find_last_resort_text_font(bold: bool = False, italic: bool = False, monospaced: bool = True) -> Descriptor: ...
    def face_from_descriptor(descriptor: Descriptor, font_sz_in_pts: float | None = None, dpi_x: float | None = None, dpi_y: float | None = None
                             ) -> Face: ...
    def is_monospace(descriptor: Descriptor) -> bool: ...
    def is_variable(descriptor: Descriptor) -> bool: ...
    def set_named_style(name: str, font: Descriptor, vd: VariableData) -> bool: ...
    def set_axis_values(tag_map: dict[str, float], font: Descriptor, vd: VariableData) -> bool: ...
    def get_axis_values(font: Descriptor, vd: VariableData) -> dict[str, float]: ...
else:
    FontCollectionMapType = FontMap = None
    from kitty.fast_data_types import specialize_font_descriptor
    if is_macos:
        from kitty.fast_data_types import CTFace as Face
        from kitty.fonts.core_text import (
            all_fonts_map,
            create_scorer,
            find_best_match,
            find_last_resort_text_font,
            get_axis_values,
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
            get_axis_values,
            is_monospace,
            is_variable,
            set_axis_values,
            set_named_style,
        )
    def face_from_descriptor(descriptor, font_sz_in_pts = None, dpi_x = None, dpi_y = None):
        if font_sz_in_pts is not None:
            descriptor = specialize_font_descriptor(descriptor, font_sz_in_pts, dpi_x, dpi_y)
        return Face(descriptor=descriptor)


cache_for_variable_data_by_path: dict[str, VariableData] = {}
attr_map = {(False, False): 'font_family', (True, False): 'bold_font', (False, True): 'italic_font', (True, True): 'bold_italic_font'}


class Event:
    is_set: bool = False


class FamilyAxisValues:
    regular_weight: float | None = None
    regular_slant: float | None = None
    regular_ital: float | None = None
    regular_width: float | None = None

    bold_weight: float | None = None

    italic_slant: float | None = None
    italic_ital: float | None = None

    def get_wght(self, bold: bool, italic: bool) -> float | None:
        return self.bold_weight if bold else self.regular_weight

    def get_ital(self, bold: bool, italic: bool) -> float | None:
        return self.italic_ital if italic else self.regular_ital

    def get_slnt(self, bold: bool, italic: bool) -> float | None:
        return self.italic_slant if italic else self.regular_slant

    def get_wdth(self, bold: bool, italic: bool) -> float | None:
        return self.regular_width

    def get(self, tag: str, bold: bool, italic: bool) -> float | None:
        f = getattr(self, f'get_{tag}', None)
        return None if f is None else f(bold, italic)

    def set_regular_values(self, axis_values: dict[str, float]) -> None:
        self.regular_weight = axis_values.get('wght')
        self.regular_width = axis_values.get('wdth')
        self.regular_ital = axis_values.get('ital')
        self.regular_slant = axis_values.get('slnt')

    def set_bold_values(self, axis_values: dict[str, float]) -> None:
        self.bold_weight = axis_values.get('wght')

    def set_italic_values(self, axis_values: dict[str, float]) -> None:
        self.italic_ital = axis_values.get('ital')
        self.italic_slant = axis_values.get('slnt')


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
    candidates: list[DescriptorVar], scorer: Scorer, is_medium_face: bool, ignore_face: DescriptorVar | None = None
) -> DescriptorVar | None:
    if candidates:
        for x in scorer.sorted_candidates(candidates):
            if ignore_face is None or x != ignore_face:
                return x
    return None


def pprint(*a: Any, **kw: Any) -> None:
    from pprint import pprint
    pprint(*a, **kw)


def find_medium_variant(font: DescriptorVar) -> DescriptorVar:
    font = font.copy()
    vd = get_variable_data_for_descriptor(font)
    for i, ns in enumerate(vd['named_styles']):
        if ns['name'] == 'Regular':
            set_named_style(ns['psname'] or ns['name'], font, vd)
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


def get_bold_design_weight(dax: DesignAxis, ax: VariableAxis, regular_weight: float) -> float:
    ans = regular_weight
    candidates = []
    for x in dax['values']:
        if x['format'] in (1, 2):
            if x['value'] > regular_weight:
                candidates.append(x['value'])
    if candidates:
        ans = min(candidates)
    return ans


def get_design_value_for(dax: DesignAxis, ax: VariableAxis, bold: bool, italic: bool, family_axis_values: FamilyAxisValues) -> float:
    family_val = family_axis_values.get(ax['tag'], bold, italic)
    if family_val is not None and ax['minimum'] <= family_val <= ax['maximum']:
        return family_val
    default = ax['default']
    if dax['tag'] == 'wght':
        keys = ('semibold', 'bold', 'heavy', 'black') if bold else ('regular', 'medium')
    elif dax['tag'] in ('ital', 'slnt'):
        keys = ('italic', 'oblique', 'slanted', 'slant') if italic else ('regular', 'normal', 'medium', 'upright')
    else:
        return default
    priorities = {}
    for x in dax['values']:
        if x['format'] in (1, 2):
            q = x['name'].lower()
            try:
                idx = keys.index(q)
            except ValueError:
                continue
            priorities[x['value']] = idx
    ans = default
    if priorities:
        ans = sorted(priorities, key=priorities.__getitem__)[0]
    if bold and ax['tag'] == 'wght' and family_axis_values.regular_weight is not None and ans <= family_axis_values.regular_weight:
        ans = get_bold_design_weight(dax, ax, family_axis_values.regular_weight)
    return ans


def find_bold_italic_variant(medium: Descriptor, bold: bool, italic: bool, family_axis_values: FamilyAxisValues) -> Descriptor:
    # we first pick the best font file for bold/italic if there are more than
    # one. For example SourceCodeVF has Italic and Upright faces with variable
    # weights in each, so we rely on the OS font matcher to give us the best
    # font file.
    monospaced = is_monospace(medium)
    unsorted = all_fonts_map(monospaced)['variable_map'][family_name_to_key(medium['family'])]
    fonts = create_scorer(bold, italic, monospaced).sorted_candidates(unsorted)
    vd = get_variable_data_for_descriptor(fonts[0])
    ans = fonts[0].copy()
    # now we need to specialise all axes in ans
    axis_values = {}
    dax_map = {dax['tag']: dax for dax in vd['design_axes']}
    for ax in vd['axes']:
        tag = ax['tag']
        dax = dax_map.get(tag)
        if dax is not None:
            axis_values[tag] = get_design_value_for(dax, ax, bold, italic, family_axis_values)
    if axis_values:
        set_axis_values(axis_values, ans, vd)
    return ans


def find_best_variable_face(spec: FontSpec, bold: bool, italic: bool, monospaced: bool, candidates: list[Descriptor]) -> Descriptor:
    if spec.variable_name is not None:
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
    return create_scorer(bold, italic, monospaced).sorted_candidates(candidates)[0]


def get_fine_grained_font(
    spec: FontSpec, bold: bool = False, italic: bool = False, family_axis_values: FamilyAxisValues = FamilyAxisValues(),
    resolved_medium_font: Descriptor | None = None, monospaced: bool = True, match_is_more_specific_than_family: Event = Event()
) -> Descriptor:
    font_map = all_fonts_map(monospaced)
    is_medium_face = resolved_medium_font is None
    scorer = create_scorer(bold, italic, monospaced)
    if spec.postscript_name:
        q = find_best_match_in_candidates(font_map['ps_map'].get(family_name_to_key(spec.postscript_name), []), scorer, is_medium_face)
        if q:
            match_is_more_specific_than_family.is_set = True
            return q
    if spec.full_name:
        q = find_best_match_in_candidates(font_map['full_map'].get(family_name_to_key(spec.full_name), []), scorer, is_medium_face)
        if q:
            match_is_more_specific_than_family.is_set = True
            return q
    if spec.family:
        key = family_name_to_key(spec.family)
        # First look for a variable font
        candidates = font_map['variable_map'].get(key, [])
        if candidates:
            q = candidates[0] if len(candidates) == 1 else find_best_variable_face(spec, bold, italic, monospaced, candidates)
            q, applied = apply_variation_to_pattern(q, spec)
            if applied:
                match_is_more_specific_than_family.is_set = True
                return q
            return find_medium_variant(q) if resolved_medium_font is None else find_bold_italic_variant(resolved_medium_font, bold, italic, family_axis_values)
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


def apply_variation_to_pattern(pat: Descriptor, spec: FontSpec) -> tuple[Descriptor, bool]:
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
    spec: FontSpec, bold: bool = False, italic: bool = False, family_axis_values: FamilyAxisValues = FamilyAxisValues(),
    resolved_medium_font: Descriptor | None = None, match_is_more_specific_than_family: Event = Event()
) -> Descriptor:
    if not spec.is_system:
        ans = get_fine_grained_font(spec, bold, italic, resolved_medium_font=resolved_medium_font, family_axis_values=family_axis_values,
                                     match_is_more_specific_than_family=match_is_more_specific_than_family)
        if spec.features:
            ans = ans.copy()
            ans['features'] = spec.features
        return ans
    family = spec.system or ''
    if family == 'auto':
        if bold or italic:
            assert resolved_medium_font is not None
            family = resolved_medium_font['family']
            if is_variable(resolved_medium_font) or is_actually_variable_despite_fontconfigs_lies(resolved_medium_font):
                v = find_bold_italic_variant(resolved_medium_font, bold, italic, family_axis_values=family_axis_values)
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


actually_variable_cache: dict[str, bool] = {}


def is_actually_variable_despite_fontconfigs_lies(d: Descriptor) -> bool:
    if d['descriptor_type'] != 'fontconfig':
        return False
    path = d['path']
    ans = actually_variable_cache.get(path)
    if ans is not None:
        return ans
    m = all_fonts_map(is_monospace(d))['variable_map']
    for x in m.get(family_name_to_key(d['family']), ()):
        if x['path'] == path:
            actually_variable_cache[path] = True
            return True
    actually_variable_cache[path] = False
    return False


def get_font_files(opts: Options) -> FontFiles:
    ans: dict[str, Descriptor] = {}
    match_is_more_specific_than_family = Event()
    medium_font = get_font_from_spec(opts.font_family, match_is_more_specific_than_family=match_is_more_specific_than_family)
    medium_font_is_variable = is_variable(medium_font) or is_actually_variable_despite_fontconfigs_lies(medium_font)
    if not match_is_more_specific_than_family.is_set and medium_font_is_variable:
        medium_font = find_medium_variant(medium_font)
    family_axis_values = FamilyAxisValues()
    if medium_font_is_variable:
        family_axis_values.set_regular_values(get_axis_values(medium_font, get_variable_data_for_descriptor(medium_font)))
    kd = {(False, False): 'medium', (True, False): 'bold', (False, True): 'italic', (True, True): 'bi'}
    for (bold, italic), attr in attr_map.items():
        if bold or italic:
            spec: FontSpec = getattr(opts, attr)
            font = get_font_from_spec(spec, bold, italic, resolved_medium_font=medium_font, family_axis_values=family_axis_values)
            # Set family axis values based on the values in font
            if not (bold and italic) and (is_variable(medium_font) or is_actually_variable_despite_fontconfigs_lies(medium_font)):
                av = get_axis_values(font, get_variable_data_for_descriptor(font))
                (family_axis_values.set_italic_values if italic else family_axis_values.set_bold_values)(av)
            if spec.is_auto and not font.get('features') and medium_font.get('features'):
                # Set font features based on medium face features
                font = font.copy()
                font['features'] = medium_font['features']
        else:
            font = medium_font
        key = kd[(bold, italic)]
        ans[key] = font
    return {'medium': ans['medium'], 'bold': ans['bold'], 'italic': ans['italic'], 'bi': ans['bi']}


def axis_values_are_equal(defaults: dict[str, float], a: dict[str, float], b: dict[str, float]) -> bool:
    ad, bd = defaults.copy(), defaults.copy()
    ad.update(a)
    bd.update(b)
    return ad == bd


def _get_named_style(axis_map: dict[str, float], vd: VariableData) -> NamedStyle | None:
    defaults = {ax['tag']: ax['default'] for ax in vd['axes']}
    for ns in vd['named_styles']:
        if axis_values_are_equal(defaults, ns['axis_values'], axis_map):
            return ns
    return None


def get_named_style(face_or_descriptor: Face | Descriptor) -> NamedStyle | None:
    if isinstance(face_or_descriptor, dict):
        d: Descriptor = face_or_descriptor
        vd = get_variable_data_for_descriptor(d)
        if d['descriptor_type'] == 'fontconfig':
            ns = d.get('named_style', -1)
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
        vd = get_variable_data_for_face(face)
        q = face.get_variation()
        if q is None:
            return None
        axis_map = q
    return _get_named_style(axis_map, vd)


def get_axis_map(face_or_descriptor: Face | Descriptor) -> dict[str, float]:
    base_axis_map = {}
    axis_map: dict[str, float] = {}
    if isinstance(face_or_descriptor, dict):
        d: Descriptor = face_or_descriptor
        vd = get_variable_data_for_descriptor(d)
        if d['descriptor_type'] == 'fontconfig':
            ns = d.get('named_style', -1)
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


def spec_for_face(family: str, face: Face) -> FontSpec:
    v = face.get_variation()
    features = tuple(map(ParsedFontFeature, face.applied_features().values()))
    if v is None:
        return FontSpec(family=family, postscript_name=face.postscript_name(), features=features)
    vd = face.get_variable_data()
    varname = vd['variations_postscript_name_prefix']
    ns = get_named_style(face)
    if ns is None:
        axes = []
        for key, val in get_axis_map(face).items():
            axes.append((key, val))
        return FontSpec(family=family, variable_name=varname, axes=tuple(axes), features=features)
    return FontSpec(family=family, variable_name=varname, style=ns['psname'] or ns['name'], features=features)


def develop(family: str = '') -> None:
    import sys
    family = family or sys.argv[-1]
    from kitty.options.utils import parse_font_spec
    opts = Options()
    opts.font_family = parse_font_spec(family)
    ff = get_font_files(opts)
    def s(name: str, d: Descriptor) -> None:
        f = face_from_descriptor(d)
        print(name, str(f))
        features = f.get_features()
        print('  Features :', features)

    s('Medium     :', ff['medium'])
    print()
    s('Bold       :', ff['bold'])
    print()
    s('Italic     :', ff['italic'])
    print()
    s('Bold-Italic:', ff['bi'])


def list_fonts(monospaced: bool = True) -> dict[str, list[dict[str, str]]]:
    ans: dict[str, list[dict[str, str]]] = {}
    for key, descriptors in all_fonts_map(monospaced)['family_map'].items():
        entries = ans.setdefault(key, [])
        for d in descriptors:
            entries.append({'family': d['family'], 'psname': d['postscript_name'], 'path': d['path'], 'style': d['style']})
    return ans


if __name__ == '__main__':
    develop()
