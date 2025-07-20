#!/usr/bin/env python
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

# Imports {{{
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
from io import StringIO
from math import ceil, log
from typing import Callable, DefaultDict, Iterator, Literal, NamedTuple, Optional, Protocol, Sequence, TypedDict, TypeVar, Union
from urllib.request import urlopen

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# }}}

# Fetching data {{{
non_characters = frozenset(range(0xfffe, 0x10ffff, 0x10000))
non_characters |= frozenset(range(0xffff, 0x10ffff + 1, 0x10000))
non_characters |= frozenset(range(0xfdd0, 0xfdf0))
if len(non_characters) != 66:
    raise SystemExit('non_characters table incorrect')
emoji_skin_tone_modifiers = frozenset(range(0x1f3fb, 0x1F3FF + 1))


def fetch_url(url: str) -> str:
    bn = os.path.basename(url)
    local = os.path.join('/tmp', bn)
    if os.path.exists(local):
        with open(local, 'rb') as f:
            data = f.read()
    else:
        data = urlopen(url).read()
        with open(local, 'wb') as f:
            f.write(data)
    return data.decode()


def get_data(fname: str, folder: str = 'UCD') -> Iterable[str]:
    url = f'https://www.unicode.org/Public/{folder}/latest/{fname}'
    for line in fetch_url(url).splitlines():
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
# }}}

# Parsing Unicode databases {{{
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
grapheme_break_as_int: dict[str, int] = {}
int_as_grapheme_break: tuple[str, ...] = ()
incb_as_int: dict[str, int] = {}
int_as_incb: tuple[str, ...] = ()
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

    gndata = fetch_url('https://raw.githubusercontent.com/ryanoasis/nerd-fonts/refs/heads/master/glyphnames.json')
    for name, val in json.loads(gndata).items():
        if name != 'METADATA':
            codepoint = int(val['code'], 16)
            category, sep, name = name.rpartition('-')
            name = name or category
            name = name.replace('_', ' ')
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
    global extended_pictographic, grapheme_break_as_int, incb_as_int, int_as_grapheme_break, int_as_incb
    global seg_props_from_int, seg_props_as_int
    grapheme_segmentation_maps['AtStart']  # this is used by the segmentation algorithm, no character has it
    grapheme_segmentation_maps['None']  # this is used by the segmentation algorithm, no character has it
    for line in get_data('ucd/auxiliary/GraphemeBreakProperty.txt'):
        chars, category = split_two(line)
        grapheme_segmentation_maps[category] |= chars
    grapheme_segmentation_maps['Private_Expecting_RI']  # this is used by the segmentation algorithm, no character has it
    grapheme_break_as_int = {x: i for i, x in enumerate(grapheme_segmentation_maps)}
    int_as_grapheme_break = tuple(grapheme_break_as_int)
    incb_map['None']   # used by segmentation algorithm no character has it
    for line in get_data('ucd/DerivedCoreProperties.txt'):
        spec, rest = line.split(';', 1)
        category = rest.strip().split(' ', 1)[0].strip().rstrip(';')
        chars = parse_range_spec(spec.strip())
        if category == 'InCB':
            # Most InCB chars also have a GBP categorization, but not all,
            # there exist some InCB chars that do not have a GBP category
            subcat = rest.strip().split(';')[1].strip().split()[0].strip()
            incb_map[subcat] |= chars
    incb_as_int = {x: i for i, x in enumerate(incb_map)}
    int_as_incb = tuple(incb_as_int)
    for line in get_data('ucd/emoji/emoji-data.txt'):
        chars, category = split_two(line)
        if 'Extended_Pictographic#' == category:
            extended_pictographic |= chars
    seg_props_from_int = {'grapheme_break': int_as_grapheme_break, 'indic_conjunct_break': int_as_incb}
    seg_props_as_int = {'grapheme_break': grapheme_break_as_int, 'indic_conjunct_break': incb_as_int}


class GraphemeSegmentationTest(TypedDict):
    data: tuple[str, ...]
    comment: str


grapheme_segmentation_tests: list[GraphemeSegmentationTest] = []


def parse_test_data() -> None:
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
        c = tuple(''.join(c) for c in chars)
        grapheme_segmentation_tests.append({'data': c, 'comment': comment.strip()})
    grapheme_segmentation_tests.append({
        'data': (' ', '\xad', ' '),
        'comment': '÷ [0.2] SPACE (Other) ÷ [0.4] SOFT HYPHEN ÷ [999.0] SPACE (Other) ÷ [0.3]'
    })
    grapheme_segmentation_tests.append({
        'data': ('\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466',),
        'comment': '÷ [0.2] MAN × [9.0] ZERO WIDTH JOINER × [11.0] WOMAN × [9.0] ZERO WIDTH JOINER × [11.0] GIRL × [9.0] ZERO WIDTH JOINER × [11.0] BOY ÷ [0.3]'
    })
# }}}


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
    with open('kitty_tests/GraphemeBreakTest.json', 'wb') as f:
        f.write(json.dumps(grapheme_segmentation_tests, indent=2, ensure_ascii=False).encode())


def getsize(data: Iterable[int]) -> Literal[1, 2, 4]:
    # return smallest possible integer size for the given array
    maxdata = max(data)
    if maxdata < 256:
        return 1
    if maxdata < 65536:
        return 2
    return 4


def mask_for(bits: int) -> int:
    return ~((~0) << bits)


HashableType = TypeVar('HashableType', bound=Hashable)

def splitbins(t: tuple[HashableType, ...], property_size: int, use_fixed_shift: int = 0) -> tuple[list[int], list[int], list[HashableType], int]:
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
    t3: list[HashableType] = []
    tmap: dict[HashableType, int] = {}
    seen = set()
    for x in t:
        if x not in seen:
            seen.add(x)
            tmap[x] = len(t3)
            t3.append(x)
    t_int = tuple(tmap[x] for x in t)
    bytesz = sys.maxsize

    def memsize() -> int:
        ans = len(t1)*getsize(t1)
        sz3 = len(t3)*property_size + len(t2)*getsize(t2)
        sz2 = len(t2) * property_size
        return ans + min(sz2, sz3)
    for shift in candidates:
        t1: list[int] = []
        t2: list[int] = []
        size = 2**shift
        bincache: dict[tuple[int, ...], int] = {}
        for i in range(0, len(t_int), size):
            bin = t_int[i:i+size]
            index = bincache.get(bin)
            if index is None:
                index = len(t2)
                bincache[bin] = index
                t2.extend(bin)
            t1.append(index >> shift)
        # determine memory size
        b = memsize()
        if b < bytesz:
            best = t1, t2, shift
            bytesz = b
    t1, t2, shift = best
    return t1, t2, t3, shift


class Property(Protocol):
    @property
    def as_c(self) -> str:
        return ''

    @property
    def as_go(self) -> str:
        return ''

    @classmethod
    def bitsize(cls) -> int:
        return 0


def get_types(sz: int) -> tuple[str, str]:
    sz *= 8
    return f'uint{sz}_t', f'uint{sz}'


def gen_multistage_table(
    c: Callable[..., None], g: Callable[..., None], t1: Sequence[int], t2: Sequence[int], t3: Sequence[Property], shift: int, input_max_val: int
) -> None:
    t1_type_sz = getsize(t1)
    ctype_t1, gotype_t1 = get_types(t1_type_sz)
    mask = mask_for(shift)
    name = t3[0].__class__.__name__
    t2_type_sz = getsize(tuple(range(len(t3))))
    ctype_t2, gotype_t2 = get_types(t2_type_sz)
    t3_type_sz = t3[0].bitsize() // 8
    lname = name.lower()
    input_type = get_types(getsize((input_max_val,)))[1]

    # Output t1
    c(f'static const char_type {name}_mask = {mask}u;')
    c(f'static const char_type {name}_shift = {shift}u;')
    c(f'static const {ctype_t1} {name}_t1[{len(t1)}] = ''{')
    c(f'\t{", ".join(map(str, t1))}')
    c('};')
    g(f'const {lname}_mask = {mask}')
    g(f'const {lname}_shift = {shift}')
    g(f'var {lname}_t1 = [{len(t1)}]{gotype_t1}''{')
    g(f'\t{", ".join(map(str, t1))},')
    g('}')
    bytesz = len(t1) * t1_type_sz

    if t3_type_sz > t2_type_sz:  # needs 3 levels
        bytesz += len(t2) * t2_type_sz + len(t3) * t3_type_sz
        c(f'static const {ctype_t2} {name}_t2[{len(t2)}] = ''{')
        c(f'\t{", ".join(map(str, t2))}')
        c('};')
        items = '\n\t'.join(x.as_c + f', // {i}' for i, x in enumerate(t3))
        c(f'static const {name} {name}_t3[{len(t3)}] = ''{')
        c(f'\t{items}')
        c('};')

        g(f'var {lname}_t2 = [{len(t2)}]{gotype_t2}''{')
        g(f'\t{", ".join(map(str, t2))},')
        g('}')
        items = '\n\t'.join(x.as_go + f', // {i}' for i, x in enumerate(t3))
        g(f'var {lname}_t3 = [{len(t3)}]{name}''{')
        g(f'\t{items}')
        g('}')

        g(f'''
        // Array accessor function that avoids bounds checking
        func {lname}_for(x {input_type}) {name} {{
            t1 := uintptr(*(*{gotype_t1})(unsafe.Pointer(uintptr(unsafe.Pointer(&{lname}_t1[0])) + uintptr(x>>{lname}_shift)*{t1_type_sz})))
            t1_shifted := (t1 << {lname}_shift) + (uintptr(x) & {lname}_mask)
            t2 := uintptr(*(*{gotype_t2})(unsafe.Pointer(uintptr(unsafe.Pointer(&{lname}_t2[0])) + t1_shifted*{t2_type_sz})))
            return *(*{name})(unsafe.Pointer(uintptr(unsafe.Pointer(&{lname}_t3[0])) + t2*{t3_type_sz}))
        }}
        ''')
    else:
        t3 = tuple(t3[i] for i in t2)
        bytesz += len(t3) * t3_type_sz
        items = '\n\t'.join(x.as_c + ',' for x in t3)
        c(f'static const {name} {name}_t2[{len(t3)}] = ''{')
        c(f'\t{items}')
        c('};')
        items = '\n\t'.join(x.as_go + ',' for x in t3)
        g(f'var {lname}_t2 = [{len(t3)}]{name}''{')
        g(f'\t{items}')
        g('}')
        g(f'''
        // Array accessor function that avoids bounds checking
        func {lname}_for(x {input_type}) {name} {{
            t1 := uintptr(*(*{gotype_t1})(unsafe.Pointer(uintptr(unsafe.Pointer(&{lname}_t1[0])) + uintptr(x>>{lname}_shift)*{t1_type_sz})))
            t1_shifted := (t1 << {lname}_shift) + (uintptr(x) & {lname}_mask)
            return *(*{name})(unsafe.Pointer(uintptr(unsafe.Pointer(&{lname}_t2[0])) + t1_shifted*{t3_type_sz}))
        }}
        ''')
    print(f'Size of {name} table: {ceil(bytesz/1024)}KB with {shift} bit shift')


width_shift = 4


def bitsize(maxval: int) -> int:  # number of bits needed to store maxval
    return ceil(log(maxval, 2))


def clamped_bitsize(val: int) -> int:
    if val <= 8:
        return 8
    if val <= 16:
        return 16
    if val <= 32:
        return 32
    if val <= 64:
        return 64
    raise ValueError('Too many fields')


def bitfield_from_int(
    fields: dict[str, int], x: int, int_to_str: dict[str, tuple[str, ...]]
) -> dict[str, str | bool]:
    # first field is least significant, last field is most significant
    args: dict[str, str | bool] = {}
    for f, shift in fields.items():
        mask = mask_for(shift)
        val = x & mask
        if shift == 1:
            args[f] = bool(val)
        else:
            args[f] = int_to_str[f][val]
        x >>= shift
    return args


def bitfield_as_int(
    fields: dict[str, int], vals: Sequence[bool | str], str_maps: dict[str, dict[str, int]]
) -> int:
    # first field is least significant, last field is most significant
    ans = shift = 0
    for i, (f, width) in enumerate(fields.items()):
        qval = vals[i]
        if isinstance(qval, str):
            val = str_maps[f][qval]
        else:
            val = int(qval)
        ans |= val << shift
        shift += width
    return ans


seg_props_from_int: dict[str, tuple[str, ...]] = {}
seg_props_as_int: dict[str, dict[str, int]] = {}


class GraphemeSegmentationProps(NamedTuple):

    grapheme_break: str = ''  # set at runtime
    indic_conjunct_break: str = ''  # set at runtime
    is_extended_pictographic: bool = True

    @classmethod
    def used_bits(cls) -> int:
        return sum(int(cls._field_defaults[f]) for f in cls._fields)

    @classmethod
    def bitsize(cls) -> int:
        return clamped_bitsize(cls.used_bits())

    @classmethod
    def fields(cls) -> dict[str, int]:
        return {f: int(cls._field_defaults[f]) for f in cls._fields}

    @classmethod
    def from_int(cls, x: int) -> 'GraphemeSegmentationProps':
        args = bitfield_from_int(cls.fields(), x, seg_props_from_int)
        return cls(**args)  # type: ignore

    def __int__(self) -> int:
        return bitfield_as_int(self.fields(), self, seg_props_as_int)


control_grapheme_breaks = 'CR', 'LF', 'Control'
linker_or_extend = 'Linker', 'Extend'


def bitfield_declaration_as_c(name: str, fields: dict[str, int], *alternate_fields: dict[str, int]) -> str:
    base_size = clamped_bitsize(sum(fields.values()))
    base_type = f'uint{base_size}_t'
    ans = [f'// {name}Declaration: uses {sum(fields.values())} bits {{''{{', f'typedef union {name} {{']
    def struct(fields: dict[str, int]) -> Iterator[str]:
        if not fields:
            return
        empty = base_size - sum(fields.values())
        yield '    struct __attribute__((packed)) {'
        yield '#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__'
        for f, width in reversed(fields.items()):
            yield f'        uint{clamped_bitsize(width)}_t {f} : {width};'
        if empty:
            yield f'        uint{clamped_bitsize(empty)}_t : {empty};'
        yield '#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__'
        if empty:
            yield f'        uint{clamped_bitsize(empty)}_t : {empty};'
        for f, width in fields.items():
            yield f'        uint{clamped_bitsize(width)}_t {f} : {width};'
        yield '#else'
        yield '#error "Unsupported endianness"'
        yield '#endif'
        yield '    };'
    ans.extend(struct(fields))
    for fields in alternate_fields:
        ans.extend(struct(fields))
    ans.append(f'    {base_type} val;')
    ans.append(f'}} {name};')
    ans.append(f'static_assert(sizeof({name}) == sizeof({base_type}), "Fix the ordering of {name}");')
    ans.append(f'// End{name}Declaration }}''}}')
    return '\n'.join(ans)


class GraphemeSegmentationState(NamedTuple):
    grapheme_break: str = ''  # set at runtime
    # True if the last character ends a sequence of Indic_Conjunct_Break values:  consonant {extend|linker}*
    incb_consonant_extended: bool = True
    # True if the last character ends a sequence of Indic_Conjunct_Break values:  consonant {extend|linker}* linker
    incb_consonant_extended_linker: bool = True
    # True if the last character ends a sequence of Indic_Conjunct_Break values:  consonant {extend|linker}* linker {extend|linker}*
    incb_consonant_extended_linker_extended: bool = True
    # True if the last character ends an emoji modifier sequence \p{Extended_Pictographic} Extend*
    emoji_modifier_sequence: bool = True
    # True if the last character was immediately preceded by an emoji modifier sequence   \p{Extended_Pictographic} Extend*
    emoji_modifier_sequence_before_last_char: bool = True

    @classmethod
    def make(cls) -> 'GraphemeSegmentationState':
        return GraphemeSegmentationState('AtStart', False, False, False, False, False)

    @classmethod
    def fields(cls) -> dict[str, int]:
        return {f: int(cls._field_defaults[f]) for f in cls._fields}

    @classmethod
    def from_int(cls, x: int) -> 'GraphemeSegmentationState':
        args = bitfield_from_int(cls.fields(), x, {'grapheme_break': int_as_grapheme_break})
        return cls(**args)  # type: ignore

    def __int__(self) -> int:
        return bitfield_as_int(self.fields(), self, seg_props_as_int)

    @classmethod
    def c_declaration(cls) -> str:
        return bitfield_declaration_as_c(cls.__name__, cls.fields())

    @classmethod
    def used_bits(cls) -> int:
        return sum(int(cls._field_defaults[f]) for f in cls._fields)

    @classmethod
    def bitsize(cls) -> int:
        return clamped_bitsize(cls.used_bits())

    def add_to_current_cell(self, p: GraphemeSegmentationProps) -> 'GraphemeSegmentationResult':
        prev = self.grapheme_break
        prop = p.grapheme_break
        incb = p.indic_conjunct_break
        add_to_cell = False
        if self.grapheme_break == 'AtStart':
            add_to_cell = True
            if prop == 'Regional_Indicator':
                prop = 'Private_Expecting_RI'
        else:
            # No break between CR and LF (GB3).
            if prev == 'CR' and prop == 'LF':
                add_to_cell = True
            # Break before and after controls (GB4, GB5).
            elif prev in control_grapheme_breaks or prop in control_grapheme_breaks:
                pass
            # No break between Hangul syllable sequences (GB6, GB7, GB8).
            elif (
                (prev == 'L' and prop in ('L', 'V', 'LV', 'LVT')) or
                (prev in ('LV', 'V') and prop in ('V', 'T')) or
                (prev in ('LVT', 'T') and prop == 'T')
            ):
                add_to_cell = True
            # No break before: extending characters or ZWJ (GB9), SpacingMarks (GB9a), Prepend characters (GB9b).
            elif prop in ('Extend', 'ZWJ', 'SpacingMark') or prev == 'Prepend':
                add_to_cell = True
            # No break within certain combinations of Indic_Conjunct_Break values
            # Between consonant {extend|linker}* linker {extend|linker}* and consonant (GB9c).
            elif self.incb_consonant_extended_linker_extended and incb == 'Consonant':
                add_to_cell = True
            # No break within emoji modifier sequences or emoji zwj sequences (GB11).
            elif prev == 'ZWJ' and self.emoji_modifier_sequence_before_last_char and p.is_extended_pictographic:
                add_to_cell = True
            # No break between RI if there is an odd number of RI characters before (GB12, GB13).
            elif prop == 'Regional_Indicator':
                if prev == 'Private_Expecting_RI':
                    add_to_cell = True
                else:
                    prop = 'Private_Expecting_RI'
            # Break everywhere else GB999

        incb_consonant_extended_linker = self.incb_consonant_extended and incb == 'Linker'
        incb_consonant_extended_linker_extended = incb_consonant_extended_linker or (
                self.incb_consonant_extended_linker_extended and incb in linker_or_extend)
        incb_consonant_extended = incb == 'Consonant' or (
            self.incb_consonant_extended and incb in linker_or_extend)
        emoji_modifier_sequence_before_last_char = self.emoji_modifier_sequence
        emoji_modifier_sequence = (self.emoji_modifier_sequence and prop == 'Extend') or p.is_extended_pictographic

        return GraphemeSegmentationResult(GraphemeSegmentationState(
            grapheme_break=prop, incb_consonant_extended=incb_consonant_extended,
            incb_consonant_extended_linker=incb_consonant_extended_linker,
            incb_consonant_extended_linker_extended=incb_consonant_extended_linker_extended,
            emoji_modifier_sequence=emoji_modifier_sequence, emoji_modifier_sequence_before_last_char=emoji_modifier_sequence_before_last_char
        ), add_to_cell)


def split_into_graphemes(props: Sequence[GraphemeSegmentationProps], text: str) -> Iterator[str]:
    s = GraphemeSegmentationState.make()
    pos = 0
    for i, ch in enumerate(text):
        p = props[ord(ch)]
        s, add_to_cell = s.add_to_current_cell(p)
        if not add_to_cell:
            yield text[pos:i]
            pos = i
    if pos < len(text):
        yield text[pos:]


def split_into_graphemes_with_table(
    props: Sequence['GraphemeSegmentationProps'], table: Sequence['GraphemeSegmentationResult'], text: str,
) -> Iterator[str]:
    s = GraphemeSegmentationResult.make()
    pos = 0
    for i, ch in enumerate(text):
        k = int(GraphemeSegmentationKey(s.new_state, props[ord(ch)]))
        s = table[k]
        if not s.add_to_current_cell:
            yield text[pos:i]
            pos = i
    if pos < len(text):
        yield text[pos:]


def test_grapheme_segmentation(split_into_graphemes: Callable[[str], Iterator[str]]) -> None:
    for test in grapheme_segmentation_tests:
        expected = test['data']
        actual = tuple(split_into_graphemes(''.join(test['data'])))
        if expected != actual:
            def as_codepoints(text: str) -> str:
                return ' '.join(hex(ord(x))[2:] for x in text)
            qe = tuple(map(as_codepoints, expected))
            qa = tuple(map(as_codepoints, actual))
            raise SystemExit(f'Failed to split graphemes for: {test["comment"]}\n{expected!r} {qe} != {actual!r} {qa}')


class GraphemeSegmentationKey(NamedTuple):
    state: GraphemeSegmentationState
    char: GraphemeSegmentationProps

    @classmethod
    def from_int(cls, x: int) -> 'GraphemeSegmentationKey':
        shift = GraphemeSegmentationProps.used_bits()
        mask = mask_for(shift)
        state = GraphemeSegmentationState.from_int(x >> shift)
        char = GraphemeSegmentationProps.from_int(x & mask)
        return GraphemeSegmentationKey(state, char)

    def __int__(self) -> int:
        shift = GraphemeSegmentationProps.used_bits()
        return int(self.state) << shift | int(self.char)

    def result(self) -> 'GraphemeSegmentationResult':
        return self.state.add_to_current_cell(self.char)

    @classmethod
    def code_to_convert_to_int(cls, for_go: bool = False) -> str:
        lines: list[str] = []
        a = lines.append
        shift = GraphemeSegmentationProps.used_bits()
        if for_go:
            base_type = f'uint{GraphemeSegmentationState.bitsize()}'
            a(f'func grapheme_segmentation_key(r GraphemeSegmentationResult, ch CharProps) ({base_type}) ''{')
            a(f'\treturn (r.State() << {shift}) | ch.GraphemeSegmentationProperty()')
            a('}')
        else:
            base_type = f'uint{GraphemeSegmentationState.bitsize()}_t'
            a(f'static inline {base_type} {cls.__name__}(GraphemeSegmentationResult r, CharProps ch)' '{')
            a(f'\treturn (r.state << {shift}) | ch.grapheme_segmentation_property;')
            a('}')
        return '\n'.join(lines)


class GraphemeSegmentationResult(NamedTuple):
    new_state: GraphemeSegmentationState = GraphemeSegmentationState()
    add_to_current_cell: bool = True

    @classmethod
    def used_bits(cls) -> int:
        return sum(int(GraphemeSegmentationState._field_defaults[f]) for f in GraphemeSegmentationState._fields) + 1

    @classmethod
    def bitsize(cls) -> int:
        return clamped_bitsize(cls.used_bits())

    @classmethod
    def make(cls) -> 'GraphemeSegmentationResult':
        return GraphemeSegmentationResult(GraphemeSegmentationState.make(), False)

    @classmethod
    def go_fields(cls) -> Sequence[str]:
        ans = []
        ans.append('add_to_current_cell 1')
        for f, width in reversed(GraphemeSegmentationState.fields().items()):
            ans.append(f'{f} {width}')
        return tuple(ans)

    @property
    def as_go(self) -> str:
        shift = 0
        parts = []
        for f in reversed(GraphemeSegmentationResult.go_fields()):
            f, _, w = f.partition(' ')
            bits = int(w)
            if f != 'add_to_current_cell':
                x = getattr(self.new_state, f)
                if f == 'grapheme_break':
                    x = f'GraphemeSegmentationResult(GBP_{x})'
                else:
                    x = int(x)
            else:
                x = int(self.add_to_current_cell)
            mask = '0b' + '1' * bits
            parts.append(f'(({x} & {mask}) << {shift})')
            shift += bits
        return ' | '.join(parts)

    @classmethod
    def go_extra(cls) -> str:
        bits = GraphemeSegmentationState.used_bits()
        base_type = f'uint{GraphemeSegmentationState.bitsize()}'
        return f'''
func (r GraphemeSegmentationResult) State() (ans {base_type}) {{
    return {base_type}(r) & {mask_for(bits)}
}}
    '''

    @property
    def as_c(self) -> str:
        parts = []
        for f in GraphemeSegmentationState._fields:
            x = getattr(self.new_state, f)
            match f:
                case 'grapheme_break':
                    x = f'GBP_{x}'
                case _:
                    x = int(x)
            parts.append(f'.{f}={x}')
        parts.append(f'.add_to_current_cell={int(self.add_to_current_cell)}')
        return '{' + ', '.join(parts) + '}'

    @classmethod
    def c_declaration(cls) -> str:
        fields = {'add_to_current_cell': 1}
        sfields = GraphemeSegmentationState.fields()
        fields.update(sfields)
        bits = sum(sfields.values())
        # dont know if the alternate state access works in big endian
        return bitfield_declaration_as_c('GraphemeSegmentationResult', fields, {'state': bits})


class CharProps(NamedTuple):

    width: int = 3
    is_emoji: bool = True
    category: str = ''  # set at runtime
    is_emoji_presentation_base: bool = True

    # derived properties for fast lookup
    is_invalid: bool = True
    is_non_rendered: bool = True
    is_symbol: bool = True
    is_combining_char: bool = True
    is_word_char: bool = True
    is_punctuation: bool = True

    # needed for grapheme segmentation set as LSB bits for easy conversion to GraphemeSegmentationProps
    grapheme_break: str = ''  # set at runtime
    indic_conjunct_break: str = ''  # set at runtime
    is_extended_pictographic: bool = True

    @classmethod
    def bitsize(cls) -> int:
        ans = sum(int(cls._field_defaults[f]) for f in cls._fields)
        return clamped_bitsize(ans)

    @classmethod
    def go_fields(cls) -> Sequence[str]:
        ans = []
        for f in cls._fields:
            bits = int(cls._field_defaults[f])
            if f == 'width':
                f = 'shifted_width'
            ans.append(f'{f} {bits}')
        return tuple(ans)

    @property
    def as_go(self) -> str:
        shift = 0
        parts = []
        for f in reversed(self.go_fields()):
            f, _, w = f.partition(' ')
            if f == 'shifted_width':
                f = 'width'
            x = getattr(self, f)
            match f:
                case 'width':
                    x += width_shift
                case 'grapheme_break':
                    x = f'CharProps(GBP_{x})'
                case 'indic_conjunct_break':
                    x = f'CharProps(ICB_{x})'
                case 'category':
                    x = f'CharProps(UC_{x})'
                case _:
                    x = int(x)
            bits = int(w)
            mask = '0b' + '1' * bits
            parts.append(f'(({x} & {mask}) << {shift})')
            shift += bits
        return ' | '.join(parts)

    @classmethod
    def go_extra(cls) -> str:
        base_type = f'uint{GraphemeSegmentationState.bitsize()}'
        f = GraphemeSegmentationProps.fields()
        s = f['grapheme_break'] + f['indic_conjunct_break']
        return f'''
func (s CharProps) Width() int {{
	return int(s.Shifted_width()) - {width_shift}
}}

func (s CharProps) GraphemeSegmentationProperty() {base_type} {{
    return {base_type}(s.Grapheme_break() | (s.Indic_conjunct_break() << {f["grapheme_break"]}) | (s.Is_extended_pictographic() << {s}))
}}
    '''

    @property
    def as_c(self) -> str:
        parts = []
        for f in self._fields:
            x = getattr(self, f)
            match f:
                case 'width':
                    x += width_shift
                    f = 'shifted_width'
                case 'grapheme_break':
                    x = f'GBP_{x}'
                case 'indic_conjunct_break':
                    x = f'ICB_{x}'
                case 'category':
                    x = f'UC_{x}'
                case _:
                    x = int(x)
            parts.append(f'.{f}={x}')
        return '{' + ', '.join(parts) + '}'

    @classmethod
    def fields(cls) -> dict[str, int]:
        return {'shifted_width' if f == 'width' else f: int(cls._field_defaults[f]) for f in cls._fields}

    @classmethod
    def c_declaration(cls) -> str:
        # Dont know if grapheme_segmentation_property in alternate works on big endian
        alternate = {
            'grapheme_segmentation_property': sum(int(cls._field_defaults[f]) for f in GraphemeSegmentationProps._fields)
        }
        return bitfield_declaration_as_c(cls.__name__, cls.fields(), alternate)


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


def category_set(predicate: Callable[[str], bool]) -> set[int]:
    ans = set()
    for c, chs in class_maps.items():
        if predicate(c):
            ans |= chs
    return ans


def top_level_category(q: str) -> set[int]:
    return category_set(lambda x: x[0] in q)


def patch_declaration(name: str, decl: str, raw: str) -> str:
    begin = f'// {name}Declaration'
    end = f'// End{name}Declaration }}''}}'
    return re.sub(rf'{begin}.+?{end}', decl.rstrip(), raw, flags=re.DOTALL)


def gen_char_props() -> None:
    CharProps._field_defaults['grapheme_break'] = str(bitsize(len(grapheme_segmentation_maps)))
    CharProps._field_defaults['indic_conjunct_break'] = str(bitsize(len(incb_map)))
    CharProps._field_defaults['category'] = str(bitsize(len(class_maps) + 1))
    GraphemeSegmentationProps._field_defaults['grapheme_break'] = CharProps._field_defaults['grapheme_break']
    GraphemeSegmentationProps._field_defaults['indic_conjunct_break'] = CharProps._field_defaults['indic_conjunct_break']
    GraphemeSegmentationState._field_defaults['grapheme_break'] = GraphemeSegmentationProps._field_defaults['grapheme_break']
    invalid = class_maps['Cc'] | class_maps['Cs'] | non_characters
    non_printing = invalid | class_maps['Cf']
    non_rendered = non_printing | property_maps['Other_Default_Ignorable_Code_Point'] | set(range(0xfe00, 0xfe0f + 1))
    is_word_char = top_level_category('LN')
    is_punctuation = top_level_category('P')
    width_map: dict[int, int] = {}
    cat_map: dict[int, str] = {}
    for cat, chs in class_maps.items():
        for ch in chs:
            cat_map[ch] = cat
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
            is_invalid=ch in invalid, is_non_rendered=ch in non_rendered, is_emoji=ch in all_emoji, is_symbol=ch in all_symbols,
            is_extended_pictographic=ch in extended_pictographic, is_emoji_presentation_base=ch in emoji_presentation_bases,
            is_combining_char=ch in marks, category=cat_map.get(ch, 'Cn'), is_word_char=ch in is_word_char,
            is_punctuation=ch in is_punctuation,
        ) for ch in range(sys.maxunicode + 1))
    gsprops = tuple(GraphemeSegmentationProps(
        grapheme_break=x.grapheme_break, indic_conjunct_break=x.indic_conjunct_break,
        is_extended_pictographic=x.is_extended_pictographic) for x in prop_array)
    test_grapheme_segmentation(partial(split_into_graphemes, gsprops))
    gseg_results = tuple(GraphemeSegmentationKey.from_int(i).result() for i in range(1 << 16))

    test_grapheme_segmentation(partial(split_into_graphemes_with_table, gsprops, gseg_results))
    t1, t2, t3, t_shift = splitbins(prop_array, CharProps.bitsize() // 8)
    g1, g2, g3, g_shift = splitbins(gseg_results, GraphemeSegmentationResult.bitsize() // 8)

    from .bitfields import make_bitfield
    buf = StringIO()
    cen = partial(print, file=buf)
    with create_header('kitty/char-props-data.h', include_data_types=False) as c, open('tools/wcswidth/char-props-data.go', 'w') as gof:
        gp = partial(print, file=gof)
        gp('package wcswidth')
        gp('import "unsafe"')
        gp(f'const MAX_UNICODE = {sys.maxunicode}')
        gp(f'const UNICODE_LIMIT = {sys.maxunicode + 1}')
        cen('// UCBDeclaration {{''{')
        cen(f'#define MAX_UNICODE ({sys.maxunicode}u)')
        generate_enum(cen, gp, 'GraphemeBreakProperty', *grapheme_segmentation_maps, prefix='GBP_')
        generate_enum(c, gp, 'IndicConjunctBreak', *incb_map, prefix='ICB_')
        generate_enum(cen, gp, 'UnicodeCategory', 'Cn', *class_maps, prefix='UC_')
        cen('// EndUCBDeclaration }}''}')
        gp(make_bitfield('tools/wcswidth', 'CharProps', *CharProps.go_fields(), add_package=False)[1])
        gp(make_bitfield('tools/wcswidth', 'GraphemeSegmentationResult', *GraphemeSegmentationResult.go_fields(), add_package=False)[1])
        gp(CharProps.go_extra())
        gp(GraphemeSegmentationResult.go_extra())
        gen_multistage_table(c, gp, t1, t2, t3, t_shift, len(prop_array)-1)
        gen_multistage_table(c, gp, g1, g2, g3, g_shift, len(gseg_results)-1)
        c(GraphemeSegmentationKey.code_to_convert_to_int())
        c(GraphemeSegmentationState.c_declaration())
        gp(GraphemeSegmentationKey.code_to_convert_to_int(for_go=True))
    gofmt(gof.name)
    with open('kitty/char-props.h', 'r+') as f:
        raw = f.read()
        nraw = re.sub(r'\d+/\*=width_shift\*/', f'{width_shift}/*=width_shift*/', raw)
        nraw = patch_declaration('CharProps', CharProps.c_declaration(), nraw)
        nraw = patch_declaration('GraphemeSegmentationResult', GraphemeSegmentationResult.c_declaration(), nraw)
        nraw = patch_declaration('UCB', buf.getvalue(), nraw)
        if nraw != raw:
            f.seek(0)
            f.truncate()
            f.write(nraw)


def main(args: list[str]=sys.argv) -> None:
    parse_ucd()
    parse_prop_list()
    parse_emoji()
    parse_eaw()
    parse_grapheme_segmentation()
    parse_test_data()
    gen_names()
    gen_rowcolumn_diacritics()
    gen_test_data()
    gen_char_props()


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'wcwidth'])
