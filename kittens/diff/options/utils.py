#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


from typing import Any, Dict, Iterable, Sequence, Tuple, Union

from kitty.conf.utils import KittensKeyDefinition, key_func, parse_kittens_key

func_with_args, args_funcs = key_func()
FuncArgsType = Tuple[str, Sequence[Any]]


@func_with_args('scroll_by')
def parse_scroll_by(func: str, rest: str) -> Tuple[str, int]:
    try:
        return func, int(rest)
    except Exception:
        return func, 1


@func_with_args('scroll_to')
def parse_scroll_to(func: str, rest: str) -> Tuple[str, str]:
    rest = rest.lower()
    if rest not in {'start', 'end', 'next-change', 'prev-change', 'next-page', 'prev-page', 'next-match', 'prev-match'}:
        rest = 'start'
    return func, rest


@func_with_args('change_context')
def parse_change_context(func: str, rest: str) -> Tuple[str, Union[int, str]]:
    rest = rest.lower()
    if rest in {'all', 'default'}:
        return func, rest
    try:
        amount = int(rest)
    except Exception:
        amount = 5
    return func, amount


@func_with_args('start_search')
def parse_start_search(func: str, rest: str) -> Tuple[str, Tuple[bool, bool]]:
    rest_ = rest.lower().split()
    is_regex = bool(rest_ and rest_[0] == 'regex')
    is_backward = bool(len(rest_) > 1 and rest_[1] == 'backward')
    return func, (is_regex, is_backward)


def syntax_aliases(raw: str) -> Dict[str, str]:
    ans = {}
    for x in raw.split():
        a, b = x.partition(':')[::2]
        if a and b:
            ans[a.lower()] = b
    return ans


def parse_map(val: str) -> Iterable[KittensKeyDefinition]:
    x = parse_kittens_key(val, args_funcs)
    if x is not None:
        yield x
