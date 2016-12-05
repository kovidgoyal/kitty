#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import unicodedata
import itertools
import sys

IGNORED_CATEGORIES = ('Cc', 'Cf', 'Cs')


def ranges(i):
    for a, b in itertools.groupby(enumerate(i), lambda r: r[1] - r[0]):
        b = list(b)
        yield b[0][1], b[-1][1]


def generate_data(chars):
    points, cranges = [], []
    for l, r in ranges(chars):
        if l == r:
            points.append(l)
        else:
            cranges.append((l, r))
    return points, cranges


def generate_predicate(name, chars):
    points, cranges = generate_data(chars)
    cranges = ['(0x%x %s ch && ch <= 0x%x)' % (l, '<' if l == 0 else '<=', r) for l, r in cranges]
    points = ['(ch == 0x%x)' % p for p in points]
    return '''
static inline bool %s(uint32_t ch) {
    return %s || %s;
}
    ''' % (name, '||'.join(cranges), '||'.join(points))


def main():
    combining_chars = []
    igchars = []
    for c in map(chr, range(sys.maxunicode + 1)):
        if unicodedata.category(c) in IGNORED_CATEGORIES:
            igchars.append(ord(c))
        if unicodedata.combining(c):
            combining_chars.append(ord(c))

    cc = generate_predicate('is_combining_char', combining_chars)
    ig = generate_predicate('is_ignored_char', igchars)
    with open('kitty/unicode-data.h', 'w') as f:
        print('#pragma once', file=f)
        print(cc, file=f)
        print(ig, file=f)


if __name__ == '__main__':
    main()
