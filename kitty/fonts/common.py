#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Literal, TypedDict, Union, cast

from kitty.constants import is_macos
from kitty.fast_data_types import ParsedFontFeature, finish_font_selection, start_font_selection
from kitty.fonts import Descriptor, FontSpec, NamedStyle, VariableData
from kitty.options.types import Options

if TYPE_CHECKING:
    from kitty.fast_data_types import CTFace, FontSelectionSpec
    from kitty.fast_data_types import Face as FT_Face

    FontCollectionMapType = Literal['family_map', 'ps_map', 'full_map', 'variable_map']
    FontMap = dict[FontCollectionMapType, dict[str, list[Descriptor]]]
    Face = Union[FT_Face, CTFace]

    def all_fonts_map(monospaced: bool) -> FontMap: ...
    def face_from_descriptor(descriptor: Descriptor, font_sz_in_pts: float | None = None, dpi_x: float | None = None, dpi_y: float | None = None) -> Face: ...
    def is_monospace(descriptor: Descriptor) -> bool: ...
    def is_variable(descriptor: Descriptor) -> bool: ...
else:
    FontCollectionMapType = FontMap = None
    from kitty.fast_data_types import specialize_font_descriptor

    if is_macos:
        from kitty.fast_data_types import CTFace as Face
        from kitty.fonts.core_text import all_fonts_map
    else:
        from kitty.fast_data_types import Face
        from kitty.fonts.fontconfig import all_fonts_map

    def face_from_descriptor(descriptor: Descriptor, font_sz_in_pts: float | None = None, dpi_x: float | None = None, dpi_y: float | None = None) -> Face:
        if font_sz_in_pts is not None:
            descriptor = specialize_font_descriptor(descriptor, font_sz_in_pts, dpi_x, dpi_y)
        return Face(descriptor=descriptor)


cache_for_variable_data_by_path: dict[str, VariableData] = {}


def clear_caches() -> None:
    cache_for_variable_data_by_path.clear()


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


class FontFiles(TypedDict):
    medium: Descriptor
    bold: Descriptor
    italic: Descriptor
    bi: Descriptor


SelectedSymbolFont = tuple[Descriptor, bool, bool]
attr_map = {(False, False): 'font_family', (True, False): 'bold_font', (False, True): 'italic_font', (True, True): 'bold_italic_font'}


def spec_for_selection(spec: FontSpec) -> 'FontSelectionSpec':
    return spec.family, spec.style, spec.postscript_name, spec.full_name, spec.system, spec.variable_name, tuple(spec.axes), bool(spec.features)


def start_font_files_selection(opts: Options, symbol_map_families: tuple[str, ...] = (), threaded: bool = False) -> None:
    """
    Start selecting the fonts specified in opts. The selection is done by C
    code, in a thread if threaded is True. Call finish_font_files_selection()
    to get the results.
    """
    specs = cast(
        'tuple[FontSelectionSpec, FontSelectionSpec, FontSelectionSpec, FontSelectionSpec]',
        tuple(spec_for_selection(getattr(opts, attr)) for attr in attr_map.values()),
    )
    start_font_selection(specs, symbol_map_families, threaded)


def finish_font_files_selection(opts: Options) -> tuple[FontFiles, tuple[SelectedSymbolFont, ...]]:
    r = finish_font_selection()

    def with_features(font: Descriptor, spec: FontSpec) -> Descriptor:
        if not spec.is_system and spec.features:
            font = font.copy()
            font['features'] = spec.features
        return font

    medium_font = with_features(r['medium'], opts.font_family)
    ans: dict[str, Descriptor] = {'medium': medium_font}
    for (bold, italic), attr in attr_map.items():
        if bold or italic:
            key = 'bi' if bold and italic else ('bold' if bold else 'italic')
            spec: FontSpec = getattr(opts, attr)
            font = with_features(r[key], spec)
            if spec.is_auto and not font.get('features') and medium_font.get('features'):
                # Set font features based on medium face features
                font = font.copy()
                font['features'] = medium_font['features']
            ans[key] = font
    ff: FontFiles = {'medium': ans['medium'], 'bold': ans['bold'], 'italic': ans['italic'], 'bi': ans['bi']}
    return ff, r['symbols']


def get_font_files(opts: Options) -> FontFiles:
    start_font_files_selection(opts)
    return finish_font_files_selection(opts)[0]


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
        d = cast(Descriptor, face_or_descriptor)
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
        face = cast(Face, face_or_descriptor)
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
        d = cast(Descriptor, face_or_descriptor)
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
        face = cast(Face, face_or_descriptor)
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
