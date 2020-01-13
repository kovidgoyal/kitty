#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import re
from ctypes import c_void_p, cast, c_uint, POINTER


pointer_to_uint = POINTER(c_uint)


def null_marker(*a):
    return iter(())


def get_output_variables(left_address, right_address, color_address):
    return (
        cast(c_void_p(left_address), pointer_to_uint).contents,
        cast(c_void_p(right_address), pointer_to_uint).contents,
        cast(c_void_p(color_address), pointer_to_uint).contents,
    )


def marker_from_regex(expression, color, flags=re.UNICODE):
    color = max(1, min(color, 3))
    if isinstance(expression, str):
        pat = re.compile(expression, flags=flags)
    else:
        pat = expression

    def marker(text, left_address, right_address, color_address):
        left, right, colorv = get_output_variables(left_address, right_address, color_address)
        colorv.value = color
        for match in pat.finditer(text):
            left.value = match.start()
            right.value = match.end() - 1
            yield

    return marker


def marker_from_multiple_regex(regexes, flags=re.UNICODE):
    expr = ''
    color_map = {}
    for i, (color, spec) in enumerate(regexes):
        grp = 'mcg{}'.format(i)
        expr += '|(?P<{}>{})'.format(grp, spec)
        color_map[grp] = color
    expr = expr[1:]
    pat = re.compile(expr, flags=flags)

    def marker(text, left_address, right_address, color_address):
        left, right, color = get_output_variables(left_address, right_address, color_address)
        for match in pat.finditer(text):
            left.value = match.start()
            right.value = match.end() - 1
            grp = next(k for k, v in match.groupdict().items() if v is not None)
            color.value = color_map[grp]
            yield

    return marker


def marker_from_text(expression, color):
    return marker_from_regex(re.escape(expression), color)


def marker_from_function(func):
    def marker(text, left_address, right_address, color_address):
        left, right, colorv = get_output_variables(left_address, right_address, color_address)
        for (l, r, c) in func(text):
            left.value = l
            right.value = r
            colorv.value = c
            yield

    return marker
