#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import re

from typing import TYPE_CHECKING, List, Generator, Any, Type

if TYPE_CHECKING:
    from kitty.cli_stub import HintsCLIOptions
    from kittens.hints.main import Mark as MarkClass
    HintsCLIOptions, MarkClass


def mark(text: str, args: 'HintsCLIOptions', Mark: Type['MarkClass'], extra_cli_args: List[str], *a: Any) -> Generator['MarkClass', None, None]:
    for idx, m in enumerate(re.finditer(args.regex, text)):
        start, end = m.span()
        mark_text = text[start:end].replace('\n', '').replace('\0', '')
        yield Mark(idx, start, end, mark_text, {'index': idx})
