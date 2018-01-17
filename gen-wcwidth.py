#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import contextmanager
from datetime import date
from functools import partial
from itertools import groupby
from operator import itemgetter
from urllib.request import urlopen

# We ignore the first few emojis as they are widely assumed to be single width
# in legacy applications
FIRST_EMOJI = 0x2194
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def get_data(fname, folder='UCD'):
    url = f'https://www.unicode.org/Public/{folder}/latest/{fname}'
    bn = os.path.basename(url)
    local = os.path.join('/tmp', bn)
    if os.path.exists(local):
        data = open(local, 'rb').read()
    else:
        data = urlopen(url).read()
        open(local, 'wb').write(data)
    for line in data.decode('utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            yield line


# Map of class names to set of codepoints in class
class_maps = {}
marks = set()
not_assigned = set(range(0, sys.maxunicode))


def parse_ucd():
    first = None
    for line in get_data('ucd/UnicodeData.txt'):
        parts = [x.strip() for x in line.split(';')]
        codepoint = int(parts[0], 16)
        category = parts[2]
        s = class_maps.setdefault(category, set())
        desc = parts[1]
        codepoints = (codepoint,)
        if first is None:
            if desc.endswith(', First>'):
                first = codepoint
                continue
        else:
            codepoints = range(first, codepoint + 1)
            first = None
        for codepoint in codepoints:
            s.add(codepoint)
            not_assigned.discard(codepoint)
            if category.startswith('M'):
                marks.add(codepoint)


def split_two(line):
    spec, rest = line.split(';', 1)
    spec, rest = spec.strip(), rest.strip().split(' ', 1)[0].strip()
    if '..' in spec:
        chars = tuple(map(lambda x: int(x, 16), filter(None, spec.split('.'))))
        chars = set(range(chars[0], chars[1] + 1))
    else:
        chars = {int(spec, 16)}
    return chars, rest


all_emoji = set()
emoji_categories = {}


def parse_emoji():
    for line in get_data('emoji-data.txt', 'emoji'):
        chars, rest = split_two(line)
        if max(chars) >= FIRST_EMOJI:
            s = emoji_categories.setdefault(rest, set())
            s |= chars
            all_emoji.update(chars)


doublewidth, ambiguous = set(), set()


def parse_eaw():
    global doublewidth, ambiguous
    seen = set()
    for line in get_data('ucd/EastAsianWidth.txt'):
        chars, eaw = split_two(line)
        if eaw == 'A':
            ambiguous |= chars
            seen |= chars
        elif eaw == 'W' or eaw == 'F':
            doublewidth |= chars
            seen |= chars
    doublewidth |= set(range(0x3400, 0x4DBF + 1)) - seen
    doublewidth |= set(range(0x4E00, 0x9FFF + 1)) - seen
    doublewidth |= set(range(0xF900, 0xFAFF + 1)) - seen
    doublewidth |= set(range(0x20000, 0x2FFFD + 1)) - seen
    doublewidth |= set(range(0x30000, 0x3FFFD + 1)) - seen


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


@contextmanager
def create_header(path):
    f = open(path, 'w')
    p = partial(print, file=f)
    p('// unicode data, built from the unicode standard on:', date.today())
    p('// see gen-wcwidth.py')
    p('#pragma once')
    p('#include "data-types.h"\n')
    p('START_ALLOW_CASE_RANGE')
    p()
    yield p
    p()
    p('END_ALLOW_CASE_RANGE')
    f.close()


def gen_emoji():
    with create_header('kitty/emoji.h') as p:
        p('static inline bool\nis_emoji(char_type code) {')
        p('\tswitch(code) {')
        for spec in get_ranges(list(all_emoji)):
            write_case(spec, p)
            p('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        p('\treturn false;\n}')
        p('static inline bool\nis_emoji_modifier(char_type code) {')
        p('\tswitch(code) {')
        for spec in get_ranges(list(emoji_categories['Emoji_Modifier'])):
            write_case(spec, p)
            p('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        p('\treturn false;\n}')


def gen_wcwidth():
    seen = set()

    def add(p, comment, chars_, ret):
        chars = chars_ - seen
        seen.update(chars)
        p(f'\t\t// {comment} ({len(chars)} codepoints)' + ' {{{')
        for spec in get_ranges(list(chars)):
            write_case(spec, p)
            p(f'\t\t\treturn {ret};')
        p('\t\t// }}}\n')

    with create_header('kitty/wcwidth-std.h') as p:
        p('static int\nwcwidth_std(int32_t code) {')
        p('\tswitch(code) {')

        non_printing = class_maps['Cc'] | class_maps['Cf'] | class_maps['Cs']
        add(p, 'Non-printing characters', non_printing, -1)
        add(p, 'Marks', marks, -1)
        add(p, 'Private use', class_maps['Co'], -3)
        add(p, 'East Asian ambiguous width', ambiguous, -2)
        add(p, 'East Asian double width', doublewidth, 2)
        add(p, 'Emoji', all_emoji, 2)

        add(p, 'Not assigned in the unicode character database', not_assigned, -1)

        p('\t\tdefault: return 1;')
        p('\t}')
        p('\treturn 1;\n}')


parse_ucd()
parse_emoji()
parse_eaw()
gen_wcwidth()
gen_emoji()
