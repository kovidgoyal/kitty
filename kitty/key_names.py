#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import suppress

from .constants import is_macos


key_name_aliases = {
    '!': 'EXCLAM',
    '"': 'DOUBLE_QUOTE',
    '#': 'NUMBER_SIGN',
    '$': 'DOLLAR',
    '&': 'AMPERSAND',
    "'": 'APOSTROPHE',
    '(': 'PARENTHESIS_LEFT',
    ')': 'PARENTHESIS_RIGHT',
    ',': 'COMMA',
    '-': 'MINUS',
    '.': 'PERIOD',
    '/': 'SLASH',
    ':': 'COLON',
    ';': 'SEMICOLON',
    '<': 'LESS',
    '=': 'EQUAL',
    '>': 'GREATER',
    '@': 'AT',
    '[': 'LEFT_BRACKET',
    '\\': 'BACKSLASH',
    ']': 'RIGHT_BRACKET',
    '_': 'UNDERSCORE',
    '`': 'GRAVE_ACCENT',
    '§': 'PARAGRAPH',
    'º': 'MASCULINE',
    'À': 'A_GRAVE',
    'Ä': 'A_DIAERESIS',
    'Å': 'A_RING',
    'Æ': 'AE',
    'Ç': 'C_CEDILLA',
    'È': 'E_GRAVE',
    'É': 'E_ACUTE',
    'Ì': 'I_GRAVE',
    'Ñ': 'N_TILDE',
    'Ò': 'O_GRAVE',
    'Ö': 'O_DIAERESIS',
    'Ø': 'O_SLASH',
    'Ù': 'U_GRAVE',
    'Ü': 'U_DIAERESIS',
    'SS': 'S_SHARP',  # 'ß'.upper() == 'SS'
    'А': 'CYRILLIC_A',
    'Б': 'CYRILLIC_BE',
    'В': 'CYRILLIC_VE',
    'Г': 'CYRILLIC_GHE',
    'Д': 'CYRILLIC_DE',
    'Е': 'CYRILLIC_IE',
    'Ж': 'CYRILLIC_ZHE',
    'З': 'CYRILLIC_ZE',
    'И': 'CYRILLIC_I',
    'Й': 'CYRILLIC_SHORT_I',
    'К': 'CYRILLIC_KA',
    'Л': 'CYRILLIC_EL',
    'М': 'CYRILLIC_EM',
    'Н': 'CYRILLIC_EN',
    'О': 'CYRILLIC_O',
    'П': 'CYRILLIC_PE',
    'Р': 'CYRILLIC_ER',
    'С': 'CYRILLIC_ES',
    'Т': 'CYRILLIC_TE',
    'У': 'CYRILLIC_U',
    'Ф': 'CYRILLIC_EF',
    'Х': 'CYRILLIC_HA',
    'Ц': 'CYRILLIC_TSE',
    'Ч': 'CYRILLIC_CHE',
    'Ш': 'CYRILLIC_SHA',
    'Щ': 'CYRILLIC_SHCHA',
    'Ъ': 'CYRILLIC_HARD_SIGN',
    'Ы': 'CYRILLIC_YERU',
    'Ь': 'CYRILLIC_SOFT_SIGN',
    'Э': 'CYRILLIC_E',
    'Ю': 'CYRILLIC_YU',
    'Я': 'CYRILLIC_YA',
    'Ё': 'CYRILLIC_IO',

    'ESC': 'ESCAPE',
    'PGUP': 'PAGE_UP',
    'PAGEUP': 'PAGE_UP',
    'PGDN': 'PAGE_DOWN',
    'PAGEDOWN': 'PAGE_DOWN',
    'RETURN': 'ENTER',
    'ARROWUP': 'UP',
    'ARROWDOWN': 'DOWN',
    'ARROWRIGHT': 'RIGHT',
    'ARROWLEFT': 'LEFT'
}


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
