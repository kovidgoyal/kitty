#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
from collections import defaultdict
from functools import partial
from itertools import groupby
from operator import itemgetter
from urllib.request import urlopen

os.chdir(os.path.dirname(os.path.abspath(__file__)))

raw = urlopen('http://unicode.org/Public/emoji/5.0/emoji-data.txt').read().decode('utf-8')
seen = set()
cmap = defaultdict(set)
for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    spec, rest = line.partition(';')[::2]
    spec, rest = spec.strip(), rest.strip().split(' ', 1)[0].strip()
    if '.' in spec:
        spec = tuple(map(lambda x: int(x, 16), filter(None, spec.split('.'))))
        spec = set(range(spec[0], spec[1] + 1))
    else:
        spec = {int(spec, 16)}
    cmap[rest] |= spec
    seen |= spec
items = list(seen)


def get_ranges(items):
    items.sort()
    for k, g in groupby(enumerate(items), lambda m: m[0]-m[1]):
        group = tuple(map(itemgetter(1), g))
        a, b = group[0], group[-1]
        if a == b:
            yield a
        else:
            yield a, b


def write_case(spec, p):
    if isinstance(spec, tuple):
        p('\t\tcase 0x{:x} ... 0x{:x}:'.format(*spec))
    else:
        p('\t\tcase 0x{:x}:'.format(spec))


with open('kitty/emoji.h', 'w') as f:
    p = partial(print, file=f)
    p('#pragma once')
    p('#include "data-types.h"\n')
    p('START_ALLOW_CASE_RANGE')
    p('static inline bool is_emoji(uint32_t code) {')
    p('\tswitch(code) {')
    for spec in get_ranges(items):
        last = spec[1] if isinstance(spec, tuple) else spec
        if last < 0x231a:
            continue
        write_case(spec, p)
        p('\t\t\treturn true;')
    p('\t\tdefault: return false;')
    p('\t}')
    p('\treturn false; \n}')
    p('static inline bool is_emoji_modifier(uint32_t code) {')
    p('\tswitch(code) {')
    for spec in get_ranges(list(cmap['Emoji_Modifier'])):
        write_case(spec, p)
        p('\t\t\treturn true;')
    p('\t\tdefault: return false;')
    p('\t}')
    p('\treturn false; \n}')
    p('END_ALLOW_CASE_RANGE')
