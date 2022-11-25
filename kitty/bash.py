#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import string
from typing import Dict, List, Tuple

ansi_c_escapes = {
    'a': '\a',
    'b': '\b',
    'e': '\x1b',
    'E': '\x1b',
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t',
    'v': '\v',
    '\\': '\\',
    "'": "'",
    '"': '"',
    '?': '?',
}


def ctrl_mask_char(ch: str) -> str:
    try:
        o = ord(ch)
    except Exception:
        return ch
    return chr(o & 0b0011111)


def read_digit(text: str, pos: int, max_len: int, valid_digits: str, base: int) -> Tuple[str, int]:
    epos = pos
    while (epos - pos) <= max_len and epos < len(text) and text[epos] in valid_digits:
        epos += 1
    raw = text[pos:epos]
    try:
        return chr(int(raw, base)), epos
    except Exception:
        return raw, epos


def read_hex_digit(text: str, pos: int, max_len: int) -> Tuple[str, int]:
    return read_digit(text, pos, max_len, string.digits + 'abcdefABCDEF', 16)


def read_octal_digit(text: str, pos: int) -> Tuple[str, int]:
    return read_digit(text, pos, 3, '01234567', 8)


def decode_ansi_c_quoted_string(text: str, pos: int) -> Tuple[str, int]:
    buf: List[str] = []
    a = buf.append
    while pos < len(text):
        ch = text[pos]
        pos += 1
        if ch == '\\':
            ec = text[pos]
            pos += 1
            ev = ansi_c_escapes.get(ec)
            if ev is None:
                if ec == 'c' and pos + 1 < len(text):
                    a(ctrl_mask_char(text[pos]))
                    pos += 1
                elif ec in 'xuU' and pos + 1 < len(text):
                    hd, pos = read_hex_digit(text, pos, {'x': 2, 'u': 4, 'U': 8}[ec])
                    a(hd)
                elif ec.isdigit():
                    hd, pos = read_octal_digit(text, pos-1)
                    a(hd)
                else:
                    a(ec)
            else:
                a(ev)
        elif ch == "'":
            break
        else:
            a(ch)
    return ''.join(buf), pos


def decode_double_quoted_string(text: str, pos: int) -> Tuple[str, int]:
    escapes = r'"\$`'
    buf: List[str] = []
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


def parse_modern_bash_env(text: str) -> Dict[str, str]:
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
            val = decode_ansi_c_quoted_string(val, 2)[0]
        ans[key] = val
    return ans


def parse_bash_env(text: str, bash_version: str) -> Dict[str, str]:
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
