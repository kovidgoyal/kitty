#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


from .utils import shlex_split


def decode_ansi_c_quoted_string(text: str) -> str:
    return next(shlex_split(text, True))


def decode_double_quoted_string(text: str, pos: int) -> tuple[str, int]:
    escapes = r'"\$`'
    buf: list[str] = []
    a = buf.append
    while pos < len(text):
        ch = text[pos]
        pos += 1
        if ch == '\\':
            if text[pos] in escapes:
                a(text[pos])
                pos += 1
                continue
            a(ch)
        elif ch == '"':
            break
        else:
            a(ch)
    return ''.join(buf), pos


def parse_modern_bash_env(text: str) -> dict[str, str]:
    ans = {}
    for line in text.splitlines():
        idx = line.find('=')
        if idx < 0:
            break
        key = line[:idx].rpartition(' ')[2]
        val = line[idx+1:]
        if val.startswith('"'):
            val = decode_double_quoted_string(val, 1)[0]
        else:
            val = decode_ansi_c_quoted_string(val)
        ans[key] = val
    return ans


def parse_bash_env(text: str, bash_version: str) -> dict[str, str]:
    # See https://www.gnu.org/software/bash/manual/html_node/Double-Quotes.html
    parts = bash_version.split('.')
    bv = tuple(map(int, parts[:2]))
    if bv >= (5, 2):
        return parse_modern_bash_env(text)
    ans = {}
    pos = 0
    while pos < len(text):
        idx = text.find('="', pos)
        if idx < 0:
            break
        i = text.rfind(' ', 0, idx)
        if i < 0:
            break
        key = text[i+1:idx]
        pos = idx + 2
        ans[key], pos = decode_double_quoted_string(text, pos)
    return ans
