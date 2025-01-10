#!/usr/bin/env python
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from collections.abc import Callable
from contextlib import suppress
from typing import Optional

from .constants import is_macos

functional_key_name_aliases: dict[str, str] = {
    'ESC': 'ESCAPE',
    'PGUP': 'PAGE_UP',
    'PAGEUP': 'PAGE_UP',
    'PGDN': 'PAGE_DOWN',
    'PAGEDOWN': 'PAGE_DOWN',
    'RETURN': 'ENTER',
    'ARROWUP': 'UP',
    'ARROWDOWN': 'DOWN',
    'ARROWRIGHT': 'RIGHT',
    'ARROWLEFT': 'LEFT',
    'DEL': 'DELETE',
    'KP_PLUS': 'KP_ADD',
    'KP_MINUS': 'KP_SUBTRACT',
}


character_key_name_aliases: dict[str, str] = {
    'SPC': ' ',
    'SPACE': ' ',
    'STAR': '*',
    'MULTIPLY': '*',
    'PLUS': '+',
    'MINUS': '-',
    'BAR': '|',
    'PIPE': '|',
    'HYPHEN': '-',
    'EQUAL': '=',
    'UNDERSCORE': '_',
    'COMMA': ',',
    'PERIOD': '.',
    'DOT': '.',
    'SLASH': '/',
    'BACKSLASH': '\\',
    'TILDE': '~',
    'GRAVE': '`',
    'GRAVE_ACCENT': '`',
    'APOSTROPHE': "'",
    'SEMICOLON': ';',
    'COLON': ':',
    'LEFT_BRACKET': '[',
    'RIGHT_BRACKET': ']',
}
LookupFunc = Callable[[str, bool], Optional[int]]


def null_lookup(name: str, case_sensitive: bool = False) -> int | None:
    return None


if is_macos:
    def get_key_name_lookup() -> LookupFunc:
        return null_lookup
else:
    def load_libxkb_lookup() -> LookupFunc:
        import ctypes
        for suffix in ('.0', ''):
            with suppress(Exception):
                lib = ctypes.CDLL(f'libxkbcommon.so{suffix}')
                break
        else:
            from ctypes.util import find_library
            lname = find_library('xkbcommon')
            if lname is None:
                raise RuntimeError('Failed to find libxkbcommon')
            lib = ctypes.CDLL(lname)

        f = lib.xkb_keysym_from_name
        f.argtypes = [ctypes.c_char_p, ctypes.c_int]
        f.restype = ctypes.c_int

        def xkb_lookup(name: str, case_sensitive: bool = False) -> int | None:
            q = name.encode('utf-8')
            return f(q, int(case_sensitive)) or None

        return xkb_lookup

    def get_key_name_lookup() -> LookupFunc:
        ans: LookupFunc | None = getattr(get_key_name_lookup, 'ans', None)
        if ans is None:
            try:
                ans = load_libxkb_lookup()
            except Exception as e:
                print('Failed to load libxkbcommon.xkb_keysym_from_name with error:', e, file=sys.stderr)
                ans = null_lookup
            setattr(get_key_name_lookup, 'ans', ans)
        return ans
