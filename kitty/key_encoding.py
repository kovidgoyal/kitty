#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import string

from . import fast_data_types as defines

# ENCODING {{{
ENCODING = {
    '0': 'G',
    '1': 'H',
    '2': 'I',
    '3': 'J',
    '4': 'K',
    '5': 'L',
    '6': 'M',
    '7': 'N',
    '8': 'O',
    '9': 'P',
    'A': 'S',
    'APOSTROPHE': 'B',
    'B': 'T',
    'BACKSLASH': 't',
    'BACKSPACE': '1',
    'C': 'U',
    'CAPS LOCK': ':',
    'COMMA': 'C',
    'D': 'V',
    'DELETE': '3',
    'DOWN': '6',
    'E': 'W',
    'END': '-',
    'ENTER': 'z',
    'EQUAL': 'R',
    'ESCAPE': 'y',
    'F': 'X',
    'F1': '/',
    'F10': ']',
    'F11': '{',
    'F12': '}',
    'F13': '@',
    'F14': '%',
    'F15': '$',
    'F16': '#',
    'F17': 'BA',
    'F18': 'BB',
    'F19': 'BC',
    'F2': '*',
    'F20': 'BD',
    'F21': 'BE',
    'F22': 'BF',
    'F23': 'BG',
    'F24': 'BH',
    'F25': 'BI',
    'F3': '?',
    'F4': '&',
    'F5': '<',
    'F6': '>',
    'F7': '(',
    'F8': ')',
    'F9': '[',
    'G': 'Y',
    'GRAVE ACCENT': 'v',
    'H': 'Z',
    'HOME': '.',
    'I': 'a',
    'INSERT': '2',
    'J': 'b',
    'K': 'c',
    'KP 0': 'BJ',
    'KP 1': 'BK',
    'KP 2': 'BL',
    'KP 3': 'BM',
    'KP 4': 'BN',
    'KP 5': 'BO',
    'KP 6': 'BP',
    'KP 7': 'BQ',
    'KP 8': 'BR',
    'KP 9': 'BS',
    'KP ADD': 'BX',
    'KP DECIMAL': 'BT',
    'KP DIVIDE': 'BU',
    'KP ENTER': 'BY',
    'KP EQUAL': 'BZ',
    'KP MULTIPLY': 'BV',
    'KP SUBTRACT': 'BW',
    'L': 'd',
    'LEFT': '5',
    'LEFT ALT': 'Bc',
    'LEFT BRACKET': 's',
    'LEFT CONTROL': 'Bb',
    'LEFT SHIFT': 'Ba',
    'LEFT SUPER': 'Bd',
    'M': 'e',
    'MINUS': 'D',
    'N': 'f',
    'NUM LOCK': '=',
    'O': 'g',
    'P': 'h',
    'PAGE DOWN': '9',
    'PAGE UP': '8',
    'PAUSE': '!',
    'PERIOD': 'E',
    'PRINT SCREEN': '^',
    'Q': 'i',
    'R': 'j',
    'RIGHT': '4',
    'RIGHT ALT': 'Bg',
    'RIGHT BRACKET': 'u',
    'RIGHT CONTROL': 'Bf',
    'RIGHT SHIFT': 'Be',
    'RIGHT SUPER': 'Bh',
    'S': 'k',
    'SCROLL LOCK': '+',
    'SEMICOLON': 'Q',
    'SLASH': 'F',
    'SPACE': 'A',
    'T': 'l',
    'TAB': '0',
    'U': 'm',
    'UP': '7',
    'V': 'n',
    'W': 'o',
    'WORLD 1': 'w',
    'WORLD 2': 'x',
    'X': 'p',
    'Y': 'q',
    'Z': 'r'
}

# END_ENCODING }}}


def encode(
    integer,
    chars=string.ascii_uppercase + string.ascii_lowercase + string.digits +
    '.-:+=^!/*?&<>()[]{}@%$#'
):
    ans = ''
    d = len(chars)
    while True:
        integer, remainder = divmod(integer, d)
        ans = chars[remainder] + ans
        if integer == 0:
            break
    return ans


def symbolic_name(glfw_name):
    return glfw_name[9:].replace('_', ' ')


def generate_extended_key_map(symbolic=False):
    keys = (a for a in dir(defines) if a.startswith('GLFW_KEY_'))
    ans = {}
    for k in keys:
        name = symbolic_name(k)
        enc = ENCODING.get(name)
        if name is not None:
            ans[getattr(defines, k)] = enc
    return ans


def update_encoding():
    import re
    import subprocess
    from pprint import pformat
    keys = {a for a in dir(defines) if a.startswith('GLFW_KEY_')}
    ans = ENCODING
    i = len(ans)
    for k in sorted(keys, key=lambda k: getattr(defines, k)):
        val = getattr(defines, k)
        name = symbolic_name(k)
        if val < defines.GLFW_KEY_LAST and val != defines.GLFW_KEY_UNKNOWN and name not in ans:
            ans[name] = encode(i)
            i += 1
    with open(__file__, 'r+') as f:
        raw = f.read()
        nraw = re.sub(
            r'^ENCODING = {.+^# END_ENCODING',
            'ENCODING = {}\n# END_ENCODING'.format(pformat(ans, indent=4)),
            raw,
            flags=re.MULTILINE | re.DOTALL
        )
        if raw == nraw:
            raise SystemExit('Failed to replace ENCODING dict')
        f.seek(0), f.truncate()
        f.write(nraw)
    subprocess.check_call(['yapf', '-i', __file__])
