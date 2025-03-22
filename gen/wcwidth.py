#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Generator, Hashable, Iterable
from contextlib import contextmanager
from functools import lru_cache, partial
from html.entities import html5
from itertools import groupby
from operator import itemgetter
from typing import (
    Callable,
    DefaultDict,
    Literal,
    NamedTuple,
    Optional,
    Protocol,
    Sequence,
    Union,
)
from urllib.request import urlopen

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


@lru_cache(maxsize=2)
def unicode_version() -> tuple[int, int, int]:
    for line in get_data("ReadMe.txt"):
        m = re.search(r'Version\s+(\d+)\.(\d+)\.(\d+)', line)
        if m is not None:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
    raise ValueError('Could not find Unicode Version')


# Map of class names to set of codepoints in class
class_maps: dict[str, set[int]] = {}
all_symbols: set[int] = set()
name_map: dict[int, str] = {}
word_search_map: DefaultDict[str, set[int]] = defaultdict(set)
soft_hyphen = 0xad
flag_codepoints = frozenset(range(0x1F1E6, 0x1F1E6 + 26))
# See https://github.com/harfbuzz/harfbuzz/issues/169
marks = set(emoji_skin_tone_modifiers) | flag_codepoints
not_assigned = set(range(0, sys.maxunicode))
property_maps: dict[str, set[int]] = defaultdict(set)
grapheme_segmentation_maps: dict[str, set[int]] = defaultdict(set)
incb_map: dict[str, set[int]] = defaultdict(set)
extended_pictographic: set[int] = set()


def parse_prop_list() -> None:
    global marks
    for line in get_data('ucd/PropList.txt'):
        if line.startswith('#'):
            continue
        cp_or_range, rest = line.split(';', 1)
        chars = parse_range_spec(cp_or_range.strip())
        name = rest.strip().split()[0]
        property_maps[name] |= chars
    # see https://www.unicode.org/faq/unsup_char.html#3
    marks |= property_maps['Other_Default_Ignorable_Code_Point']


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
        codepoints: Union[tuple[int, ...], Iterable[int]] = (codepoint,)
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
            elif category == 'Cf':
                # we add Cf to marks as it contains things like tags and zero
                # width chars. Not sure if *all* of Cf should be treated as
                # combining chars, might need to add individual exceptions in
                # the future.
                marks.add(codepoint)

    with open('gen/nerd-fonts-glyphs.txt') as f:
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


def parse_range_spec(spec: str) -> set[int]:
    spec = spec.strip()
    if '..' in spec:
        chars_ = tuple(map(lambda x: int(x, 16), filter(None, spec.split('.'))))
        chars = set(range(chars_[0], chars_[1] + 1))
    else:
        chars = {int(spec, 16)}
    return chars


def split_two(line: str) -> tuple[set[int], str]:
    spec, rest = line.split(';', 1)
    spec, rest = spec.strip(), rest.strip().split(' ', 1)[0].strip()
    return parse_range_spec(spec), rest


all_emoji: set[int] = set()
emoji_presentation_bases: set[int] = set()
narrow_emoji: set[int] = set()
wide_emoji: set[int] = set()
flags: dict[int, list[int]] = {}


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


doublewidth: set[int] = set()
ambiguous: set[int] = set()


def parse_eaw() -> None:
    global doublewidth, ambiguous
    seen: set[int] = set()
    for line in get_data('ucd/EastAsianWidth.txt'):
        chars, eaw = split_two(line)
        if eaw == 'A':
            ambiguous |= chars
            seen |= chars
        elif eaw in ('W', 'F'):
            doublewidth |= chars
            seen |= chars
    doublewidth |= set(range(0x3400, 0x4DBF + 1)) - seen
    doublewidth |= set(range(0x4E00, 0x9FFF + 1)) - seen
    doublewidth |= set(range(0xF900, 0xFAFF + 1)) - seen
    doublewidth |= set(range(0x20000, 0x2FFFD + 1)) - seen
    doublewidth |= set(range(0x30000, 0x3FFFD + 1)) - seen


def parse_grapheme_segmentation() -> None:
    global extended_pictographic
    for line in get_data('ucd/auxiliary/GraphemeBreakProperty.txt'):
        chars, category = split_two(line)
        grapheme_segmentation_maps[category] |= chars
    for line in get_data('ucd/DerivedCoreProperties.txt'):
        spec, rest = line.split(';', 1)
        category = rest.strip().split(' ', 1)[0].strip().rstrip(';')
        chars = parse_range_spec(spec.strip())
        if category == 'InCB':
            # Most InCB chars also have a GBP categorization, but not all,
            # there exist some InCB chars that do not have a GBP category
            subcat = rest.strip().split(';')[1].strip().split()[0].strip()
            incb_map[subcat] |= chars
    for line in get_data('ucd/emoji/emoji-data.txt'):
        chars, category = split_two(line)
        if 'Extended_Pictographic#' == category:
            extended_pictographic |= chars


def get_ranges(items: list[int]) -> Generator[Union[int, tuple[int, int]], None, None]:
    items.sort()
    for k, g in groupby(enumerate(items), lambda m: m[0]-m[1]):
        group = tuple(map(itemgetter(1), g))
        a, b = group[0], group[-1]
        if a == b:
            yield a
        else:
            yield a, b


def write_case(spec: Union[tuple[int, ...], int], p: Callable[..., None], for_go: bool = False) -> None:
    if isinstance(spec, tuple):
        if for_go:
            v = ', '.join(f'0x{x:x}' for x in range(spec[0], spec[1] + 1))
            p(f'\t\tcase {v}:')
        else:
            p('\t\tcase 0x{:x} ... 0x{:x}:'.format(*spec))
    else:
        p(f'\t\tcase 0x{spec:x}:')


@contextmanager
def create_header(path: str, include_data_types: bool = True) -> Generator[Callable[..., None], None, None]:
    with open(path, 'w') as f:
        p = partial(print, file=f)
        p('// Unicode data, built from the Unicode Standard', '.'.join(map(str, unicode_version())))
        p(f'// Code generated by {os.path.basename(__file__)}, DO NOT EDIT.', end='\n\n')
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

        p('static inline bool\nis_narrow_emoji(char_type code) {')
        p('\tswitch(code) {')
        for spec in get_ranges(list(narrow_emoji)):
            write_case(spec, p)
            p('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        p('\treturn false;\n}')



def category_test(
    name: str,
    p: Callable[..., None],
    classes: Iterable[str],
    comment: str,
    use_static: bool = False,
    extra_chars: Union[frozenset[int], set[int]] = frozenset(),
    exclude: Union[set[int], frozenset[int]] = frozenset(),
    least_check_return: Optional[str] = None,
    ascii_range: Optional[str] = None
) -> None:
    static = 'static inline ' if use_static else ''
    chars: set[int] = set()
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


def classes_to_regex(classes: Iterable[str], exclude: str = '', for_go: bool = True) -> Iterable[str]:
    chars: set[int] = set()
    for c in classes:
        chars |= class_maps[c]
    for x in map(ord, exclude):
        chars.discard(x)

    if for_go:
        def as_string(codepoint: int) -> str:
            if codepoint < 256:
                return fr'\x{codepoint:02x}'
            return fr'\x{{{codepoint:x}}}'
    else:
        def as_string(codepoint: int) -> str:
            if codepoint < 256:
                return fr'\x{codepoint:02x}'
            if codepoint <= 0xffff:
                return fr'\u{codepoint:04x}'
            return fr'\U{codepoint:08x}'

    for spec in get_ranges(list(chars)):
        if isinstance(spec, tuple):
            yield '{}-{}'.format(*map(as_string, (spec[0], spec[1])))
        else:
            yield as_string(spec)


def gen_ucd() -> None:
    cz = {c for c in class_maps if c[0] in 'CZ'}
    with create_header('kitty/unicode-data.c') as p:
        p('#include "unicode-data.h"')
        p('START_ALLOW_CASE_RANGE')
        category_test(
                'is_combining_char', p,
                (),
                'Combining and default ignored characters',
                extra_chars=marks,
                least_check_return='false'
        )
        category_test(
            'is_ignored_char', p, 'Cc Cs'.split(),
            'Control characters and non-characters',
            extra_chars=non_characters,
            ascii_range='false'
        )
        category_test(
            'is_non_rendered_char', p, 'Cc Cs Cf'.split(),
            'Other_Default_Ignorable_Code_Point and soft hyphen',
            extra_chars=property_maps['Other_Default_Ignorable_Code_Point'] | set(range(0xfe00, 0xfe0f + 1)),
            ascii_range='false'
        )
        category_test('is_word_char', p, {c for c in class_maps if c[0] in 'LN'}, 'L and N categories')
        category_test('is_CZ_category', p, cz, 'C and Z categories')
        category_test('is_P_category', p, {c for c in class_maps if c[0] == 'P'}, 'P category (punctuation)')

def gen_names() -> None:
    aliases_map: dict[int, set[str]] = {}
    for word, codepoints in word_search_map.items():
        for cp in codepoints:
            aliases_map.setdefault(cp, set()).add(word)
    if len(name_map) > 0xffff:
        raise Exception('Too many named codepoints')
    with open('tools/unicode_names/names.txt', 'w') as f:
        print(len(name_map), len(word_search_map), file=f)
        for cp in sorted(name_map):
            name = name_map[cp]
            words = name.lower().split()
            aliases = aliases_map.get(cp, set()) - set(words)
            end = '\n'
            if aliases:
                end = '\t' + ' '.join(sorted(aliases)) + end
            print(cp, *words, end=end, file=f)


def gofmt(*files: str) -> None:
    subprocess.check_call(['gofmt', '-w', '-s'] + list(files))


def gen_wcwidth() -> None:
    seen: set[int] = set()
    non_printing = class_maps['Cc'] | class_maps['Cf'] | class_maps['Cs']

    def add(p: Callable[..., None], comment: str, chars_: Union[set[int], frozenset[int]], ret: int, for_go: bool = False) -> None:
        chars = chars_ - seen
        seen.update(chars)
        p(f'\t\t// {comment} ({len(chars)} codepoints)' + ' {{' '{')
        for spec in get_ranges(list(chars)):
            write_case(spec, p, for_go)
            p(f'\t\t\treturn {ret};')
        p('\t\t// }}}\n')

    def add_all(p: Callable[..., None], for_go: bool = False) -> None:
        seen.clear()
        add(p, 'Flags', flag_codepoints, 2, for_go)
        add(p, 'Marks', marks | {0}, 0, for_go)
        add(p, 'Non-printing characters', non_printing, -1, for_go)
        add(p, 'Private use', class_maps['Co'], -3, for_go)
        add(p, 'Text Presentation', narrow_emoji, 1, for_go)
        add(p, 'East Asian ambiguous width', ambiguous, -2, for_go)
        add(p, 'East Asian double width', doublewidth, 2, for_go)
        add(p, 'Emoji Presentation', wide_emoji, 2, for_go)

        add(p, 'Not assigned in the unicode character database', not_assigned, -4, for_go)

        p('\t\tdefault:\n\t\t\treturn 1;')
        p('\t}')
        if for_go:
            p('\t}')
        else:
            p('\treturn 1;\n}')

    with create_header('kitty/wcwidth-std.h') as p, open('tools/wcswidth/std.go', 'w') as gof:
        gop = partial(print, file=gof)
        gop('package wcswidth\n\n')
        gop('func Runewidth(code rune) int {')
        p('static inline int\nwcwidth_std(int32_t code) {')
        p('\tif (LIKELY(0x20 <= code && code <= 0x7e)) { return 1; }')
        p('\tswitch(code) {')
        gop('\tswitch(code) {')
        add_all(p)
        add_all(gop, True)

        p('static inline bool\nis_emoji_presentation_base(uint32_t code) {')
        gop('func IsEmojiPresentationBase(code rune) bool {')
        p('\tswitch(code) {')
        gop('\tswitch(code) {')
        for spec in get_ranges(list(emoji_presentation_bases)):
            write_case(spec, p)
            write_case(spec, gop, for_go=True)
            p('\t\t\treturn true;')
            gop('\t\t\treturn true;')
        p('\t\tdefault: return false;')
        p('\t}')
        gop('\t\tdefault:\n\t\t\treturn false')
        gop('\t}')
        p('\treturn true;\n}')
        gop('\n}')
        uv = unicode_version()
        p(f'#define UNICODE_MAJOR_VERSION {uv[0]}')
        p(f'#define UNICODE_MINOR_VERSION {uv[1]}')
        p(f'#define UNICODE_PATCH_VERSION {uv[2]}')
        gop('var UnicodeDatabaseVersion [3]int = [3]int{' f'{uv[0]}, {uv[1]}, {uv[2]}' + '}')
    gofmt(gof.name)


def gen_rowcolumn_diacritics() -> None:
    # codes of all row/column diacritics
    codes = []
    with open("gen/rowcolumn-diacritics.txt") as file:
        for line in file.readlines():
            if line.startswith('#'):
                continue
            code = int(line.split(";")[0], 16)
            codes.append(code)

    go_file = 'tools/utils/images/rowcolumn_diacritics.go'
    with create_header('kitty/rowcolumn-diacritics.c') as p, create_header(go_file, include_data_types=False) as g:
        p('int diacritic_to_num(char_type code) {')
        p('\tswitch (code) {')
        g('package images')
        g(f'var NumberToDiacritic = [{len(codes)}]rune''{')
        g(', '.join(f'0x{x:x}' for x in codes) + ',')
        g('}')

        range_start_num = 1
        range_start = 0
        range_end = 0

        def print_range() -> None:
            if range_start >= range_end:
                return
            write_case((range_start, range_end), p)
            p('\t\treturn code - ' + hex(range_start) + ' + ' +
              str(range_start_num) + ';')

        for code in codes:
            if range_end == code:
                range_end += 1
            else:
                print_range()
                range_start_num += range_end - range_start
                range_start = code
                range_end = code + 1
        print_range()

        p('\t}')
        p('\treturn 0;')
        p('}')
    gofmt(go_file)


def gen_test_data() -> None:
    tests = []
    for line in get_data('ucd/auxiliary/GraphemeBreakTest.txt'):
        t, comment = line.split('#')
        t = t.lstrip('÷').strip().rstrip('÷').strip()
        chars: list[list[str]] = [[]]
        for x in re.split(r'([÷×])', t):
            x = x.strip()
            match x:
                case '÷':
                    chars.append([])
                case '×':
                    pass
                case '':
                    pass
                case _:
                    ch = chr(int(x, 16))
                    chars[-1].append(ch)
        c = [''.join(c) for c in chars]
        tests.append({'data': c, 'comment': comment.strip()})
    with open('kitty_tests/GraphemeBreakTest.json', 'wb') as f:
        f.write(json.dumps(tests, indent=2, ensure_ascii=False).encode())


def getsize(data: Iterable[int]) -> Literal[1, 2, 4]:
    # return smallest possible integer size for the given array
    maxdata = max(data)
    if maxdata < 256:
        return 1
    if maxdata < 65536:
        return 2
    return 4


def splitbins[T: Hashable](t: tuple[T, ...], property_size: int, use_fixed_shift: int = 0) -> tuple[list[int], list[T], int, int, int]:
    if use_fixed_shift:
        candidates = range(use_fixed_shift, use_fixed_shift + 1)
    else:
        n = len(t)-1    # last valid index
        maxshift = 0    # the most we can shift n and still have something left
        if n > 0:
            while n >> 1:
                n >>= 1
                maxshift += 1
        candidates = range(maxshift + 1)
    bytesz = sys.maxsize
    for shift in candidates:
        t1: list[int] = []
        t2: list[T] = []
        size = 2**shift
        bincache: dict[tuple[T, ...], int] = {}
        for i in range(0, len(t), size):
            bin = t[i:i+size]
            index = bincache.get(bin)
            if index is None:
                index = len(t2)
                bincache[bin] = index
                t2.extend(bin)
            t1.append(index >> shift)
        # determine memory size
        b = len(t1)*getsize(t1) + len(t2)*property_size
        if b < bytesz:
            best = t1, t2, shift
            bytesz = b
    t1, t2, shift = best
    mask = ~((~0) << shift)
    return t1, t2, shift, mask, bytesz


class Property(Protocol):
    @property
    def as_c(self) -> str:
        return ''

    @property
    def as_go(self) -> str:
        return ''


def gen_multistage_table(
    c: Callable[..., None], g: Callable[..., None], t1: Sequence[int], t2: Sequence[Property], shift: int, mask: int
) -> None:
    sz = getsize(t1)
    name = t2[0].__class__.__name__
    match sz:
        case 1:
            ctype = 'unsigned char'
            gotype = 'uint8'
        case 2:
            ctype = 'unsigned short'
            gotype = 'uint16'
        case 4:
            ctype = 'uint32_t'
            gotype = 'uint32'
    c(f'static const char_type {name}_mask = {mask}u;')
    c(f'static const char_type {name}_shift = {shift}u;')
    c(f'static const {ctype} {name}_t1[{len(t1)}] = ''{')
    c(f'\t{", ".join(map(str, t1))}')
    c('};')
    items = '\n\t'.join(x.as_c + ',' for x in t2)
    c(f'static const {name} {name}_t2[{len(t2)}] = ''{')
    c(f'\t{items}')
    c('};')

    lname = name.lower()
    g(f'const {lname}_mask = {mask}')
    g(f'const {lname}_shift = {shift}')
    g(f'var {lname}_t1 = [{len(t1)}]{gotype}''{')
    g(f'\t{", ".join(map(str, t1))},')
    g('}')
    items = '\n\t'.join(x.as_go + ',' for x in t2)
    g(f'var {lname}_t2 = [{len(t2)}]{name}''{')
    g(f'\t{items}')
    g('}')


width_shift = 4

class CharProps(NamedTuple):

    width: int = 3
    grapheme_break: str = '2'
    indic_conjunct_break: str = '2'
    is_invalid: bool = True
    is_extended_pictographic: bool = True
    is_non_rendered: bool = True

    @property
    def go_fields(self) -> Iterable[str]:
        ans = []
        for f in self._fields:
            bits = int(self._field_defaults[f])
            if f == 'width':
                f = 'shifted_width'
            ans.append(f'{f} {bits}')
        return tuple(ans)

    @property
    def as_go(self) -> str:
        shift = 0
        parts = []
        for f in reversed(self._fields):
            x = getattr(self, f)
            match f:
                case 'width':
                    x += width_shift
                case 'grapheme_break':
                    x = f'CharProps(GBP_{x})'
                case 'indic_conjunct_break':
                    x = f'CharProps(ICB_{x})'
                case _:
                    x = int(x)
            bits = int(self._field_defaults[f])
            mask = '0b' + '1' * bits
            parts.append(f'(({x} & {mask}) << {shift})')
            shift += bits
        return ' | '.join(parts)

    @property
    def as_c(self) -> str:
        return ('{'
            f' .shifted_width={self.width + width_shift}, .grapheme_break=GBP_{self.grapheme_break},'
            f' .indic_conjunct_break=ICB_{self.indic_conjunct_break},'
            f' .is_invalid={int(self.is_invalid)}, .is_extended_pictographic={int(self.is_extended_pictographic)},'
            f' .is_non_rendered={int(self.is_non_rendered)},'
        ' }')


def generate_enum(p: Callable[..., None], gp: Callable[..., None], name: str, *items: str, prefix: str = '') -> None:
    p(f'typedef enum {name} {{')  # }}
    gp(f'type {name} uint8\n')
    gp('const (')  # )
    for i, x in enumerate(items):
        x = prefix + x
        p(f'\t{x},')
        if i == 0:
            gp(f'{x} {name} = iota')
        else:
            gp(x)
    p(f'}} {name};')
    gp(')')
    p('')
    gp('')


def gen_char_props() -> None:
    invalid = class_maps['Cc'] | class_maps['Cs']
    non_printing = invalid | class_maps['Cf']
    width_map: dict[int, int] = {}
    def aw(s: Iterable[int], width: int) -> None:
        nonlocal width_map
        d = dict.fromkeys(s, width)
        d.update(width_map)
        width_map = d

    aw(flag_codepoints, 2)
    aw(doublewidth, 2)
    aw(wide_emoji, 2)
    aw(marks | {0}, 0)
    aw(non_printing, -1)
    aw(ambiguous, -2)
    aw(class_maps['Co'], -3)  # Private use
    aw(not_assigned, -4)

    gs_map: dict[int, str] = {}
    icb_map: dict[int, str] = {}
    for name, cps in grapheme_segmentation_maps.items():
        gs_map.update(dict.fromkeys(cps, name))
    for name, cps in incb_map.items():
        icb_map.update(dict.fromkeys(cps, name))
    prop_array = tuple(
        CharProps(
            width=width_map.get(ch, 1), grapheme_break=gs_map.get(ch, 'None'), indic_conjunct_break=icb_map.get(ch, 'None'),
            is_invalid=ch in invalid, is_non_rendered=ch in non_printing,
            is_extended_pictographic=ch in extended_pictographic
        ) for ch in range(sys.maxunicode + 1))
    t1, t2, shift, mask, bytesz = splitbins(prop_array, 2)
    print(f'Size of character properties table: {bytesz/1024:.1f}KB')
    from .bitfields import make_bitfield
    with create_header('kitty/char-props-data.h', include_data_types=False) as c, open('tools/wcswidth/char-props-data.go', 'w') as gof:
        gp = partial(print, file=gof)
        gp('package wcswidth')
        generate_enum(c, gp, 'GraphemeBreakProperty', 'AtStart', 'None', *grapheme_segmentation_maps, prefix='GBP_')
        generate_enum(c, gp, 'IndicConjunctBreak', 'None', *incb_map, prefix='ICB_')
        bf = make_bitfield('tools/wcswidth', 'CharProps', *CharProps().go_fields, add_package=False)[1]
        gp(bf)
        gp(f'''
func (s CharProps) Width() int {{
	return int(s.Shifted_width()) - {width_shift}
}}''')
        gen_multistage_table(c, gp, t1, t2, shift, mask)
    gofmt(gof.name)


def main(args: list[str]=sys.argv) -> None:
    parse_ucd()
    parse_prop_list()
    parse_emoji()
    parse_eaw()
    parse_grapheme_segmentation()
    gen_ucd()
    gen_wcwidth()
    gen_emoji()
    gen_names()
    gen_rowcolumn_diacritics()
    gen_test_data()
    gen_char_props()


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'wcwidth'])
