#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import suppress

from .constants import is_macos


def null_lookup(name, case_sensitive=False):
    pass


if is_macos:
    def get_key_name_lookup():
        return null_lookup
else:
    def load_libxkb_lookup():
        import ctypes
        for suffix in ('.0', ''):
            with suppress(Exception):
                lib = ctypes.CDLL('libxkbcommon.so' + suffix)
                break
        else:
            from ctypes.util import find_library
            lib = ctypes.CDLL(find_library('xkbcommon'))

        f = lib.xkb_keysym_from_name
        f.argtypes = [ctypes.c_char_p, ctypes.c_int]
        f.restype = ctypes.c_int

        def xkb_lookup(name, case_sensitive=False):
            name = name.encode('utf-8')
            return f(name, int(case_sensitive)) or None

        return xkb_lookup

    def get_key_name_lookup():
        ans = getattr(get_key_name_lookup, 'ans', None)
        if ans is None:
            try:
                ans = load_libxkb_lookup()
            except Exception as e:
                print('Failed to load libxkbcommon.xkb_keysym_from_name with error:', e, file=sys.stderr)
                ans = null_lookup
            get_key_name_lookup.ans = ans
        return ans
