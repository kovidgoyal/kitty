#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from functools import partial
from html.entities import html5
from itertools import groupby
from operator import itemgetter
from urllib.request import urlopen

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
name_map = {}
word_search_map = defaultdict(set)
marks = set()
not_assigned = set(range(0, sys.maxunicode))


def parse_ucd():

    def add_word(w, c):
        if c <= 32 or c == 127 or 128 <= c <= 159:
            return
        word_search_map[w.lower()].add(c)

    first = None
    for word, c in html5.items():
        if len(c) == 1:
            add_word(word.rstrip(';'), ord(c))
    word_search_map['nnbsp'].add(0x202f)
    for line in get_data('ucd/UnicodeData.txt'):
        parts = [x.strip() for x in line.split(';')]
        codepoint = int(parts[0], 16)
        name = parts[1]
        if name:
            name_map[codepoint] = name
            for word in name.lower().split():
                add_word(word, codepoint)
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
emoji_presentation_bases = set()


def parse_emoji():
    for line in get_data('emoji-data.txt', 'emoji'):
        chars, rest = split_two(line)
        s = emoji_categories.setdefault(rest, set())
        s.update(chars)
        all_emoji.update(chars)
    for line in get_data('emoji-variation-sequences.txt', 'emoji'):
        base, var, *rest = line.split()
        if base.startswith('#'):
            continue
        base = int(base, 16)
        if var.upper() == 'FE0F':
            emoji_presentation_bases.add(base)


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
def create_header(path, include_data_types=True):
    f = open(path, 'w')
    p = partial(print, file=f)
    p('// unicode data, built from the unicode standard on:', date.today())
    p('// see gen-wcwidth.py')
    if path.endswith('.h'):
        p('#pragma once')
    if include_data_types:
        p('#include "data-types.h"\n')
        p('START_ALLOW_CASE_RANGE')
    p()
    yield p
    p()
    if include_data_types:
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


def category_test(name, p, classes, comment, static=False):
    static = 'static inline ' if static else ''
    chars = set()
    for c in classes:
        chars |= class_maps[c]
    p(f'{static}bool\n{name}(char_type code) {{')
    p(f'\t// {comment} ({len(chars)} codepoints)' + ' {{' '{')
    p('\tswitch(code) {')
    for spec in get_ranges(list(chars)):
        write_case(spec, p)
        p(f'\t\t\treturn true;')
    p('\t} // }}}\n')
    p('\treturn false;\n}\n')


def codepoint_to_mark_map(p, mark_map):
    p('\tswitch(c) { // {{{')
    rmap = {c: m for m, c in enumerate(mark_map)}
    for spec in get_ranges(mark_map):
        if isinstance(spec, tuple):
            s = rmap[spec[0]]
            p(f'\t\tcase {spec[0]} ... {spec[1]}: return {s} + c - {spec[0]};')
        else:
            p(f'\t\tcase {spec}: return {rmap[spec]};')
    p('default: return 0;')
    p('\t} // }}}')
    return rmap


def classes_to_regex(classes):
    chars = set()
    for c in classes:
        chars |= class_maps[c]

    def as_string(codepoint):
        if codepoint < 256:
            return r'\x{:02x}'.format(codepoint)
        if codepoint <= 0xffff:
            return r'\u{:04x}'.format(codepoint)
        return r'\U{:08x}'.format(codepoint)

    for spec in get_ranges(list(chars)):
        if isinstance(spec, tuple):
            yield '{}-{}'.format(*map(as_string, (spec[0], spec[1])))
        else:
            yield as_string(spec)


def gen_ucd():
    cz = {c for c in class_maps if c[0] in 'CZ'}
    with create_header('kitty/unicode-data.c') as p:
        p('#include "unicode-data.h"')
        category_test('is_combining_char', p, {c for c in class_maps if c.startswith('M')}, 'M category (marks)')
        category_test('is_ignored_char', p, 'Cc Cf Cs'.split(), 'Control characters (Cc Cf Cs)')
        category_test('is_word_char', p, {c for c in class_maps if c[0] in 'LN'}, 'L and N categories')
        category_test('is_CZ_category', p, cz, 'C and Z categories')
        category_test('is_P_category', p, {c for c in class_maps if c[0] == 'P'}, 'P category (punctuation)')
        mark_map = [0] + list(sorted(marks))
        p('char_type codepoint_for_mark(combining_type m) {')
        p(f'\tstatic char_type map[{len(mark_map)}] =', '{', ', '.join(map(str, mark_map)), '}; // {{{ mapping }}}')
        p('\tif (m < arraysz(map)) return map[m];')
        p('\treturn 0;')
        p('}\n')
        p('combining_type mark_for_codepoint(char_type c) {')
        rmap = codepoint_to_mark_map(p, mark_map)
        p('}\n')
        if rmap[0xfe0e] != 1275:
            raise ValueError('The mark for 0xfe0e has changed, you have to update VS15 to {} and VS16 to {} in unicode-data.h'.format(
                rmap[0xfe0e], rmap[0xfe0f]
            ))
    with open('kittens/hints/url_regex.py', 'w') as f:
        f.write("url_delimiters = '{}'  # noqa".format(''.join(classes_to_regex(cz))))


def gen_names():
    words = tuple(sorted(word_search_map))

    with create_header('kittens/unicode_input/names.h') as p:
        cp_map = list(sorted(name_map))
        p(f'static const char* name_map[{len(cp_map)}] = {{' ' // {{{')
        for cp in cp_map:
            w = name_map[cp].replace('"', '\\"')
            p(f'\t"{w}",')
        p("}; // }}}\n")

        p(f'static const char* idx_to_word[{len(words)}] = ' '{ // {{{')
        for s in words:
            s = s.replace('"', '\\"')
            p(f'\t"{s}",')
        p("}; // }}}\n")

        first_letters = {ord(w[0]) for w in words if ord(w[0]) < 256}
        wmap = {w: i for i, w in enumerate(words)}
        p(f'static const unsigned short* words_for_first_letter[256] = ' '{ // {{{')
        for fl in range(0, 256):
            if fl in first_letters:
                winds = [str(wmap[w]) for w in words if w.startswith(chr(fl))]
                p(f'\t(const unsigned short[{len(winds) + 1}]){{{len(winds)}, ', ', '.join(winds), '},')
            else:
                p('NULL,')
        p("}; // }}}\n")

        p(f'static const char_type* codepoints_for_word_idx[{len(words)}] = ' '{ // {{{')
        for s in words:
            cps = word_search_map[s]
            a = ', '.join(map(str, cps))
            p(f'\t(const char_type[{len(cps) + 1}]){{{len(cps)}, ', a, '},')
        p("}; // }}}\n")

        p('static char_type mark_for_codepoint(char_type c) {')
        codepoint_to_mark_map(p, cp_map)
        p('}\n')
        p('static inline const char* name_for_codepoint(char_type cp) {')
        p('\tchar_type m = mark_for_codepoint(cp); if (m == 0) return NULL;')
        p('\treturn name_map[m];')
        p('}\n')


def gen_wcwidth():
    seen = set()

    def add(p, comment, chars_, ret):
        chars = chars_ - seen
        seen.update(chars)
        p(f'\t\t// {comment} ({len(chars)} codepoints)' + ' {{' '{')
        for spec in get_ranges(list(chars)):
            write_case(spec, p)
            p(f'\t\t\treturn {ret};')
        p('\t\t// }}}\n')

    with create_header('kitty/wcwidth-std.h') as p:
        p('static int\nwcwidth_std(int32_t code) {')
        p('\tswitch(code) {')

        non_printing = class_maps['Cc'] | class_maps['Cf'] | class_maps['Cs']
        add(p, 'Marks', marks | {0}, 0)
        add(p, 'Non-printing characters', non_printing, -1)
        add(p, 'Private use', class_maps['Co'], -3)
        add(p, 'Text Presentation', emoji_categories['Emoji'] - emoji_categories['Emoji_Presentation'], 1)
        add(p, 'East Asian ambiguous width', ambiguous, -2)
        add(p, 'East Asian double width', doublewidth, 2)
        add(p, 'Emoji Presentation', emoji_categories['Emoji_Presentation'], 2)

        add(p, 'Not assigned in the unicode character database', not_assigned, -1)

        p('\t\tdefault: return 1;')
        p('\t}')
        p('\treturn 1;\n}')

        p('static bool\nis_emoji_presentation_base(uint32_t code) {')
        p('\tswitch(code) {')
        for spec in get_ranges(list(emoji_presentation_bases)):
            write_case(spec, p)
            p('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        p('\treturn 1;\n}')


parse_ucd()
parse_emoji()
parse_eaw()
gen_ucd()
gen_wcwidth()
gen_emoji()
gen_names()
