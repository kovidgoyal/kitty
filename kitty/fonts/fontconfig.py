#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Generator
from functools import lru_cache
from typing import Literal

from kitty.fast_data_types import (
    FC_DUAL,
    FC_MONO,
    clear_fallback_font_cache,
    fc_list,
)
from kitty.fast_data_types import fc_match as fc_match_impl
from kitty.typing_compat import FontConfigPattern

from . import ListedFont, family_name_to_key

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


def clear_caches() -> None:
    all_fonts_map.cache_clear()
    fc_match.cache_clear()
    clear_fallback_font_cache()


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
                'family': f,
                'full_name': fn,
                'postscript_name': str(fd.get('postscript_name', '')),
                'is_monospace': is_monospace(fd),
                'descriptor': fd,
                'is_variable': is_variable(fd),
                'style': fd['style'],
            }


@lru_cache
def fc_match(family: str, bold: bool, italic: bool, spacing: int = FC_MONO) -> FontConfigPattern:
    return fc_match_impl(family, bold, italic, spacing)


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
