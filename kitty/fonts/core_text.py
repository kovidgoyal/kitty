#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import itertools
import operator
from collections import defaultdict
from collections.abc import Generator, Iterable
from functools import lru_cache

from kitty.fast_data_types import coretext_all_fonts
from kitty.typing_compat import CoreTextFont

from . import ListedFont, family_name_to_key

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


def clear_caches() -> None:
    all_fonts_map.cache_clear()


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
            yield {
                'family': f,
                'full_name': fn,
                'postscript_name': fd['postscript_name'] or '',
                'is_monospace': fd['monospace'],
                'is_variable': is_variable(fd),
                'descriptor': fd,
                'style': fd['style'],
            }


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
