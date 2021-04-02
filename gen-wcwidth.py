#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from functools import partial
from html.entities import html5
from itertools import groupby
from operator import itemgetter
from typing import (
    Callable, DefaultDict, Dict, FrozenSet, Generator, Iterable, List,
    Optional, Set, Tuple, Union
)
from urllib.request import urlopen

os.chdir(os.path.dirname(os.path.abspath(__file__)))

non_characters = frozenset(range(0xfffe, 0x10ffff, 0x10000))
non_characters |= frozenset(range(0xffff, 0x10ffff + 1, 0x10000))
non_characters |= frozenset(range(0xfdd0, 0xfdf0))
if len(non_characters) != 66:
    raise SystemExit('non_characters table incorrect')
emoji_skin_tone_modifiers = frozenset(range(0x1f3fb, 0x1F3FF + 1))


def get_data(fname: str, folder: str = 'UCD') -> Iterable[str]:
    url = f'https://www.unicode.org/Public/{folder}/latest/{fname}'
    bn = os.path.basename(url)
    local = os.path.join('/tmp', bn)
    if os.path.exists(local):
        with open(local, 'rb') as f:
            data = f.read()
    else:
        data = urlopen(url).read()
        with open(local, 'wb') as f:
            f.write(data)
    for line in data.decode('utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            yield line


# Map of class names to set of codepoints in class
class_maps: Dict[str, Set[int]] = {}
all_symbols: Set[int] = set()
name_map: Dict[int, str] = {}
word_search_map: DefaultDict[str, Set[int]] = defaultdict(set)
zwj = 0x200d
flag_codepoints = frozenset(range(0x1F1E6, 0x1F1E6 + 26))
marks = set(emoji_skin_tone_modifiers) | {zwj} | flag_codepoints
not_assigned = set(range(0, sys.maxunicode))


def parse_ucd() -> None:

    def add_word(w: str, c: int) -> None:
        if c <= 32 or c == 127 or 128 <= c <= 159:
            return
        if len(w) > 1:
            word_search_map[w.lower()].add(c)

    first: Optional[int] = None
    for word, c in html5.items():
        if len(c) == 1:
            add_word(word.rstrip(';'), ord(c))
    word_search_map['nnbsp'].add(0x202f)
    for line in get_data('ucd/UnicodeData.txt'):
        parts = [x.strip() for x in line.split(';')]
        codepoint = int(parts[0], 16)
        name = parts[1] or parts[10]
        if name == '<control>':
            name = parts[10]
        if name:
            name_map[codepoint] = name
            for word in name.lower().split():
                add_word(word, codepoint)
        category = parts[2]
        s = class_maps.setdefault(category, set())
        desc = parts[1]
        codepoints: Union[Tuple[int, ...], Iterable[int]] = (codepoint,)
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
            elif category.startswith('S'):
                all_symbols.add(codepoint)

    with open('nerd-fonts-glyphs.txt') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            code, category, name = line.split(' ', 2)
            codepoint = int(code, 16)
            if name and codepoint not in name_map:
                name_map[codepoint] = name.upper()
                for word in name.lower().split():
                    add_word(word, codepoint)

    # Some common synonyms
    word_search_map['bee'] |= word_search_map['honeybee']
    word_search_map['lambda'] |= word_search_map['lamda']
    word_search_map['lamda'] |= word_search_map['lambda']
    word_search_map['diamond'] |= word_search_map['gem']


def parse_range_spec(spec: str) -> Set[int]:
    spec = spec.strip()
    if '..' in spec:
        chars_ = tuple(map(lambda x: int(x, 16), filter(None, spec.split('.'))))
        chars = set(range(chars_[0], chars_[1] + 1))
    else:
        chars = {int(spec, 16)}
    return chars


def split_two(line: str) -> Tuple[Set[int], str]:
    spec, rest = line.split(';', 1)
    spec, rest = spec.strip(), rest.strip().split(' ', 1)[0].strip()
    return parse_range_spec(spec), rest


all_emoji: Set[int] = set()
emoji_presentation_bases: Set[int] = set()
narrow_emoji: Set[int] = set()
wide_emoji: Set[int] = set()
flags: Dict[int, List[int]] = {}


def parse_basic_emoji(spec: str) -> None:
    parts = list(filter(None, spec.split()))
    has_emoji_presentation = len(parts) < 2
    chars = parse_range_spec(parts[0])
    all_emoji.update(chars)
    emoji_presentation_bases.update(chars)
    (wide_emoji if has_emoji_presentation else narrow_emoji).update(chars)


def parse_keycap_sequence(spec: str) -> None:
    base, fe0f, cc = list(filter(None, spec.split()))
    chars = parse_range_spec(base)
    all_emoji.update(chars)
    emoji_presentation_bases.update(chars)
    narrow_emoji.update(chars)


def parse_flag_emoji_sequence(spec: str) -> None:
    a, b = list(filter(None, spec.split()))
    left, right = int(a, 16), int(b, 16)
    chars = {left, right}
    all_emoji.update(chars)
    wide_emoji.update(chars)
    emoji_presentation_bases.update(chars)
    flags.setdefault(left, []).append(right)


def parse_emoji_tag_sequence(spec: str) -> None:
    a = int(spec.split()[0], 16)
    all_emoji.add(a)
    wide_emoji.add(a)
    emoji_presentation_bases.add(a)


def parse_emoji_modifier_sequence(spec: str) -> None:
    a, b = list(filter(None, spec.split()))
    char, mod = int(a, 16), int(b, 16)
    mod
    all_emoji.add(char)
    wide_emoji.add(char)
    emoji_presentation_bases.add(char)


def parse_emoji() -> None:
    for line in get_data('emoji-sequences.txt', 'emoji'):
        parts = [x.strip() for x in line.split(';')]
        if len(parts) < 2:
            continue
        data, etype = parts[:2]
        if etype == 'Basic_Emoji':
            parse_basic_emoji(data)
        elif etype == 'Emoji_Keycap_Sequence':
            parse_keycap_sequence(data)
        elif etype == 'RGI_Emoji_Flag_Sequence':
            parse_flag_emoji_sequence(data)
        elif etype == 'RGI_Emoji_Tag_Sequence':
            parse_emoji_tag_sequence(data)
        elif etype == 'RGI_Emoji_Modifier_Sequence':
            parse_emoji_modifier_sequence(data)


doublewidth: Set[int] = set()
ambiguous: Set[int] = set()


def parse_eaw() -> None:
    global doublewidth, ambiguous
    seen: Set[int] = set()
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


def get_ranges(items: List[int]) -> Generator[Union[int, Tuple[int, int]], None, None]:
    items.sort()
    for k, g in groupby(enumerate(items), lambda m: m[0]-m[1]):
        group = tuple(map(itemgetter(1), g))
        a, b = group[0], group[-1]
        if a == b:
            yield a
        else:
            yield a, b


def write_case(spec: Union[Tuple, int], p: Callable) -> None:
    if isinstance(spec, tuple):
        p('\t\tcase 0x{:x} ... 0x{:x}:'.format(*spec))
    else:
        p('\t\tcase 0x{:x}:'.format(spec))


@contextmanager
def create_header(path: str, include_data_types: bool = True) -> Generator[Callable, None, None]:
    with open(path, 'w') as f:
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


def gen_emoji() -> None:
    with create_header('kitty/emoji.h') as p:
        p('static inline bool\nis_emoji(char_type code) {')
        p('\tswitch(code) {')
        for spec in get_ranges(list(all_emoji)):
            write_case(spec, p)
            p('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        p('\treturn false;\n}')

        p('static inline bool\nis_symbol(char_type code) {')
        p('\tswitch(code) {')
        for spec in get_ranges(list(all_symbols)):
            write_case(spec, p)
            p('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        p('\treturn false;\n}')


def category_test(
    name: str,
    p: Callable,
    classes: Iterable[str],
    comment: str,
    use_static: bool = False,
    extra_chars: Union[FrozenSet[int], Set[int]] = frozenset(),
    exclude: Union[Set[int], FrozenSet[int]] = frozenset(),
    least_check_return: Optional[str] = None,
    ascii_range: Optional[str] = None
) -> None:
    static = 'static inline ' if use_static else ''
    chars: Set[int] = set()
    for c in classes:
        chars |= class_maps[c]
    chars |= extra_chars
    chars -= exclude
    p(f'{static}bool\n{name}(char_type code) {{')
    p(f'\t// {comment} ({len(chars)} codepoints)' + ' {{' '{')
    if least_check_return is not None:
        least = min(chars)
        p(f'\tif (LIKELY(code < {least})) return {least_check_return};')
    if ascii_range is not None:
        p(f'\tif (LIKELY(0x20 <= code && code <= 0x7e)) return {ascii_range};')
    p('\tswitch(code) {')
    for spec in get_ranges(list(chars)):
        write_case(spec, p)
        p('\t\t\treturn true;')
    p('\t} // }}}\n')
    p('\treturn false;\n}\n')


def codepoint_to_mark_map(p: Callable, mark_map: List[int]) -> Dict[int, int]:
    p('\tswitch(c) { // {{{')
    rmap = {c: m for m, c in enumerate(mark_map)}
    for spec in get_ranges(mark_map):
        if isinstance(spec, tuple):
            s = rmap[spec[0]]
            cases = ' '.join(f'case {i}:' for i in range(spec[0], spec[1]+1))
            p(f'\t\t{cases} return {s} + c - {spec[0]};')
        else:
            p(f'\t\tcase {spec}: return {rmap[spec]};')
    p('default: return 0;')
    p('\t} // }}}')
    return rmap


def classes_to_regex(classes: Iterable[str], exclude: str = '') -> Iterable[str]:
    chars: Set[int] = set()
    for c in classes:
        chars |= class_maps[c]
    for x in map(ord, exclude):
        chars.discard(x)

    def as_string(codepoint: int) -> str:
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


def gen_ucd() -> None:
    cz = {c for c in class_maps if c[0] in 'CZ'}
    with create_header('kitty/unicode-data.c') as p:
        p('#include "unicode-data.h"')
        category_test(
                'is_combining_char', p,
                {c for c in class_maps if c.startswith('M')},
                'M category (marks)',
                # See https://github.com/harfbuzz/harfbuzz/issues/169
                extra_chars=emoji_skin_tone_modifiers | {zwj},
                least_check_return='false'
        )
        category_test(
            'is_ignored_char', p, 'Cc Cf Cs'.split(),
            'Control characters and non-characters',
            extra_chars=non_characters, exclude={zwj},
            ascii_range='false'
        )
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
        with open('kitty/unicode-data.h') as f:
            unicode_data = f.read()
        m = re.search(r'^#define VS15 (\d+)', unicode_data, re.M)
        if m is not None:
            expected = int(m.group(1))
        if rmap[0xfe0e] != expected:
            raise ValueError('The mark for 0xfe0e has changed, you have to update VS15 to {} and VS16 to {} in unicode-data.h'.format(
                rmap[0xfe0e], rmap[0xfe0f]
            ))
    with open('kittens/hints/url_regex.py', 'w') as f:
        f.write("url_delimiters = '{}'  # noqa".format(''.join(classes_to_regex(cz, exclude='\n'))))


def gen_names() -> None:
    with create_header('kittens/unicode_input/names.h') as p:
        mark_to_cp = list(sorted(name_map))
        cp_to_mark = {cp: m for m, cp in enumerate(mark_to_cp)}
        # Mapping of mark to codepoint name
        p(f'static const char* name_map[{len(mark_to_cp)}] = {{' ' // {{{')
        for cp in mark_to_cp:
            w = name_map[cp].replace('"', '\\"')
            p(f'\t"{w}",')
        p("}; // }}}\n")

        # Mapping of mark to codepoint
        p(f'static const char_type mark_to_cp[{len(mark_to_cp)}] = {{' ' // {{{')
        p(', '.join(map(str, mark_to_cp)))
        p('}; // }}}\n')

        # Function to get mark number for codepoint
        p('static char_type mark_for_codepoint(char_type c) {')
        codepoint_to_mark_map(p, mark_to_cp)
        p('}\n')
        p('static inline const char* name_for_codepoint(char_type cp) {')
        p('\tchar_type m = mark_for_codepoint(cp); if (m == 0) return NULL;')
        p('\treturn name_map[m];')
        p('}\n')

        # Array of all words
        word_map = tuple(sorted(word_search_map))
        word_rmap = {w: i for i, w in enumerate(word_map)}
        p(f'static const char* all_words_map[{len(word_map)}] = {{' ' // {{{')
        cwords = (w.replace('"', '\\"') for w in word_map)
        p(', '.join(f'"{w}"' for w in cwords))
        p('}; // }}}\n')

        # Array of sets of marks for each word
        word_to_marks = {word_rmap[w]: frozenset(map(cp_to_mark.__getitem__, cps)) for w, cps in word_search_map.items()}
        all_mark_groups = frozenset(word_to_marks.values())
        array = [0]
        mg_to_offset = {}
        for mg in all_mark_groups:
            mg_to_offset[mg] = len(array)
            array.append(len(mg))
            array.extend(sorted(mg))
        p(f'static const char_type mark_groups[{len(array)}] = {{' ' // {{{')
        p(', '.join(map(str, array)))
        p('}; // }}}\n')
        offsets_array = []
        for wi, w in enumerate(word_map):
            mg = word_to_marks[wi]
            offsets_array.append(mg_to_offset[mg])
        p(f'static const char_type mark_to_offset[{len(offsets_array)}] = {{' ' // {{{')
        p(', '.join(map(str, offsets_array)))
        p('}; // }}}\n')

        # The trie
        p('typedef struct { uint32_t children_offset; uint32_t match_offset; } word_trie;\n')
        all_trie_nodes: List['TrieNode'] = []  # noqa

        class TrieNode:

            def __init__(self) -> None:
                self.match_offset = 0
                self.children_offset = 0
                self.children: Dict[int, int] = {}

            def add_letter(self, letter: int) -> int:
                if letter not in self.children:
                    self.children[letter] = len(all_trie_nodes)
                    all_trie_nodes.append(TrieNode())
                return self.children[letter]

            def __str__(self) -> str:
                return f'{{ .children_offset={self.children_offset}, .match_offset={self.match_offset} }}'

        root = TrieNode()
        all_trie_nodes.append(root)

        def add_word(word_idx: int, word: str) -> None:
            parent = root
            for letter in map(ord, word):
                idx = parent.add_letter(letter)
                parent = all_trie_nodes[idx]
            parent.match_offset = offsets_array[word_idx]

        for i, word in enumerate(word_map):
            add_word(i, word)
        children_array = [0]
        for node in all_trie_nodes:
            if node.children:
                node.children_offset = len(children_array)
                children_array.append(len(node.children))
                for letter, child_offset in node.children.items():
                    children_array.append((child_offset << 8) | (letter & 0xff))

        p(f'static const word_trie all_trie_nodes[{len(all_trie_nodes)}] = {{' ' // {{{')
        p(',\n'.join(map(str, all_trie_nodes)))
        p('\n}; // }}}\n')
        p(f'static const uint32_t children_array[{len(children_array)}] = {{' ' // {{{')
        p(', '.join(map(str, children_array)))
        p('}; // }}}\n')


def gen_wcwidth() -> None:
    seen: Set[int] = set()

    def add(p: Callable, comment: str, chars_: Union[Set[int], FrozenSet[int]], ret: int) -> None:
        chars = chars_ - seen
        seen.update(chars)
        p(f'\t\t// {comment} ({len(chars)} codepoints)' + ' {{' '{')
        for spec in get_ranges(list(chars)):
            write_case(spec, p)
            p(f'\t\t\treturn {ret};')
        p('\t\t// }}}\n')

    with create_header('kitty/wcwidth-std.h') as p:
        p('static inline int\nwcwidth_std(int32_t code) {')
        p('\tif (LIKELY(0x20 <= code && code <= 0x7e)) return 1;')
        p('\tswitch(code) {')

        non_printing = class_maps['Cc'] | class_maps['Cf'] | class_maps['Cs']
        add(p, 'Flags', flag_codepoints, 2)
        add(p, 'Marks', marks | {0}, 0)
        add(p, 'Non-printing characters', non_printing, -1)
        add(p, 'Private use', class_maps['Co'], -3)
        add(p, 'Text Presentation', narrow_emoji, 1)
        add(p, 'East Asian ambiguous width', ambiguous, -2)
        add(p, 'East Asian double width', doublewidth, 2)
        add(p, 'Emoji Presentation', wide_emoji, 2)

        add(p, 'Not assigned in the unicode character database', not_assigned, -4)

        p('\t\tdefault: return 1;')
        p('\t}')
        p('\treturn 1;\n}')

        p('static inline bool\nis_emoji_presentation_base(uint32_t code) {')
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
