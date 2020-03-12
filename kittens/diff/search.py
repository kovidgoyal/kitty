#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import re
from typing import TYPE_CHECKING, Callable, Dict, Iterable, List, Tuple

from kitty.fast_data_types import wcswidth
from kitty.options_stub import DiffOptions

from ..tui.operations import styled

if TYPE_CHECKING:
    from .render import Line
    Line


class BadRegex(ValueError):
    pass


class Search:

    def __init__(self, opts: DiffOptions, query: str, is_regex: bool, is_backward: bool):
        self.matches: Dict[int, List[Tuple[int, str]]] = {}
        self.count = 0
        self.style = styled('|', fg=opts.search_fg, bg=opts.search_bg).split('|', 1)[0]
        if not is_regex:
            query = re.escape(query)
        try:
            self.pat = re.compile(query, flags=re.UNICODE | re.IGNORECASE)
        except Exception:
            raise BadRegex('Not a valid regex: {}'.format(query))

    def __call__(self, diff_lines: Iterable['Line'], margin_size: int, cols: int) -> bool:
        self.matches = {}
        self.count = 0
        half_width = cols // 2
        strip_pat = re.compile('\033[[].*?m')
        right_offset = half_width + 1 + margin_size
        find = self.pat.finditer
        for i, line in enumerate(diff_lines):
            text = strip_pat.sub('', line.text)
            left, right = text[margin_size:half_width + 1], text[right_offset:]
            matches = []

            def add(which: str, offset: int) -> None:
                for m in find(which):
                    before = which[:m.start()]
                    matches.append((wcswidth(before) + offset, m.group()))
                    self.count += 1

            add(left, margin_size)
            add(right, right_offset)
            if matches:
                self.matches[i] = matches
        return bool(self.matches)

    def __contains__(self, i: int) -> bool:
        return i in self.matches

    def __len__(self) -> int:
        return self.count

    def highlight_line(self, write: Callable[[str], None], line_num: int) -> bool:
        highlights = self.matches.get(line_num)
        if not highlights:
            return False
        write(self.style)
        for start, text in highlights:
            write('\r\x1b[{}C{}'.format(start, text))
        write('\x1b[m')
        return True
