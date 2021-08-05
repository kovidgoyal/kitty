#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Iterable, List, Union

from . import subseq_matcher


def match(
    input_data: Union[str, bytes, Iterable[Union[str, bytes]]],
    query: str,
    threads: int = 0,
    positions: bool = False,
    level1: str = '/',
    level2: str = '-_0123456789',
    level3: str = '.',
    limit: int = 0,
    mark_before: str = '',
    mark_after: str = '',
    delimiter: str = '\n'
) -> List[str]:
    if isinstance(input_data, str):
        idata = [x.encode('utf-8') for x in input_data.split(delimiter)]
    elif isinstance(input_data, bytes):
        idata = input_data.split(delimiter.encode('utf-8'))
    else:
        idata = [x.encode('utf-8') if isinstance(x, str) else x for x in input_data]
    query = query.lower()
    level1 = level1.lower()
    level2 = level2.lower()
    level3 = level3.lower()
    data = subseq_matcher.match(
        idata, (level1, level2, level3), query,
        positions, limit, threads,
        mark_before, mark_after, delimiter)
    if data is None:
        return []
    return list(filter(None, data.split(delimiter or '\n')))
