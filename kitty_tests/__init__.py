#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from unittest import TestCase


class BaseTest(TestCase):

    ae = TestCase.assertEqual


def set_text_in_line(line, text, offset=0):
    pos = offset
    for ch in text:
        line.set_char(pos, ch)
        pos += 1
        if pos >= len(line):
            break
