#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections.abc import Callable, Generator, Iterable, Sequence
from re import Pattern
from typing import Union

from .fast_data_types import set_uint_at_address
from .utils import resolve_custom_file


MarkerFunc = Callable[[str, int, int, int], Generator[None, None, None]]


def marker_from_regex(expression: Union[str, 'Pattern[str]'], color: int, flags: int = re.UNICODE) -> MarkerFunc:
    color = max(1, min(color, 3))
    if isinstance(expression, str):
        pat = re.compile(expression, flags=flags)
    else:
        pat = expression

    def marker(text: str, left_address: int, right_address: int, color_address: int) -> Generator[None, None, None]:
        set_uint_at_address(color_address, color)
        for match in pat.finditer(text):
            set_uint_at_address(left_address, match.start())
            set_uint_at_address(right_address, match.end() - 1)
            yield

    return marker


def marker_from_multiple_regex(regexes: Iterable[tuple[int, str]], flags: int = re.UNICODE) -> MarkerFunc:
    expr = ''
    color_map = {}
    for i, (color, spec) in enumerate(regexes):
        grp = f'mcg{i}'
        expr += f'|(?P<{grp}>{spec})'
        color_map[grp] = color
    expr = expr[1:]
    pat = re.compile(expr, flags=flags)

    def marker(text: str, left_address: int, right_address: int, color_address: int) -> Generator[None, None, None]:
        for match in pat.finditer(text):
            set_uint_at_address(left_address, match.start())
            set_uint_at_address(right_address, match.end() - 1)
            grp = match.lastgroup
            set_uint_at_address(color_address, color_map[grp] if grp is not None else 0)
            yield

    return marker


def marker_from_text(expression: str, color: int) -> MarkerFunc:
    return marker_from_regex(re.escape(expression), color)


def marker_from_function(func: Callable[[str], Iterable[tuple[int, int, int]]]) -> MarkerFunc:
    def marker(text: str, left_address: int, right_address: int, color_address: int) -> Generator[None, None, None]:
        for (ll, r, c) in func(text):
            set_uint_at_address(left_address, ll)
            set_uint_at_address(right_address, r)
            set_uint_at_address(color_address, c)
            yield

    return marker


def marker_from_spec(ftype: str, spec: str | Sequence[tuple[int, str]], flags: int) -> MarkerFunc:
    if ftype == 'regex':
        assert not isinstance(spec, str)
        if len(spec) == 1:
            return marker_from_regex(spec[0][1], spec[0][0], flags=flags)
        return marker_from_multiple_regex(spec, flags=flags)
    if ftype == 'function':
        import runpy
        assert isinstance(spec, str)
        path = resolve_custom_file(spec)
        return marker_from_function(runpy.run_path(path, run_name='__marker__')["marker"])
    raise ValueError(f'Unknown marker type: {ftype}')
