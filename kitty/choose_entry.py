#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import re


def mark(text, args, Mark, extra_cli_args, *a):
    for idx, m in enumerate(re.finditer(args.regex, text)):
        start, end = m.span()
        mark_text = text[start:end].replace('\n', '').replace('\0', '')
        yield Mark(idx, start, end, mark_text, {'index': idx})
