#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import random
import string

from . import BaseTest


def run(input_data, query, **kw):
    kw['threads'] = kw.get('threads', 1)
    mark = kw.pop('mark', False)
    from kittens.choose.main import match
    mark_before = mark_after = ''
    if mark:
        if mark is True:
            mark_before, mark_after = '\033[32m', '\033[39m'
        else:
            mark_before = mark_after = mark
    kw['mark_before'], kw['mark_after'] = mark_before, mark_after
    return match(input_data, query, **kw)


class TestMatcher(BaseTest):

    def run_matcher(self, *args, **kwargs):
        result = run(*args, **kwargs)
        return result

    def basic_test(self, inp, query, out, **k):
        result = self.run_matcher(inp, query, **k)
        if out is not None:
            if hasattr(out, 'splitlines'):
                out = list(filter(None, out.split(k.get('delimiter', '\n'))))
            self.assertEqual(list(out), result)
        return out

    def test_filtering(self):
        ' Non matching entries must be removed '
        self.basic_test('test\nxyz', 'te', 'test')
        self.basic_test('abc\nxyz', 'ba', '')
        self.basic_test('abc\n123', 'abc', 'abc')

    def test_case_insensitive(self):
        self.basic_test('test\nxyz', 'Te', 'test')
        self.basic_test('test\nxyz', 'XY', 'xyz')
        self.basic_test('test\nXYZ', 'xy', 'XYZ')
        self.basic_test('test\nXYZ', 'mn', '')

    def test_marking(self):
        ' Marking of matched characters '
        self.basic_test(
            'test\nxyz',
            'ts',
            '\x1b[32mt\x1b[39me\x1b[32ms\x1b[39mt',
            mark=True)

    def test_positions(self):
        ' Output of positions '
        self.basic_test('abc\nac', 'ac', '0,1:ac\n0,2:abc', positions=True)

    def test_delimiter(self):
        ' Test using a custom line delimiter '
        self.basic_test('abc\n21ac', 'ac', 'ac1abc\n2', delimiter='1')

    def test_scoring(self):
        ' Scoring algorithm '
        # Match at start
        self.basic_test('archer\nelementary', 'e', 'elementary\narcher')
        # Match at level factor
        self.basic_test('xxxy\nxx/y', 'y', 'xx/y\nxxxy')
        # CamelCase
        self.basic_test('xxxy\nxxxY', 'y', 'xxxY\nxxxy')
        # Total length
        self.basic_test('xxxya\nxxxy', 'y', 'xxxy\nxxxya')
        # Distance
        self.basic_test('abbc\nabc', 'ac', 'abc\nabbc')
        # Extreme chars
        self.basic_test('xxa\naxx', 'a', 'axx\nxxa')
        # Highest score
        self.basic_test('xa/a', 'a', 'xa/|a|', mark='|')

    def test_threading(self):
        ' Test matching on a large data set with different number of threads '
        alphabet = string.ascii_lowercase + string.ascii_uppercase + string.digits

        def random_word():
            sz = random.randint(2, 10)
            return ''.join(random.choice(alphabet) for x in range(sz))
        words = [random_word() for i in range(400)]

        def random_item():
            num = random.randint(2, 7)
            return '/'.join(random.choice(words) for w in range(num))

        data = '\n'.join(random_item() for x in range(25123))

        for threads in range(4):
            self.basic_test(data, 'foo', None, threads=threads)
