#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import string
from collections import namedtuple

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
    'Z': 'r',
    'PLUS': 'Bi'
}
KEY_MAP = {
    32: 'A',
    39: 'B',
    44: 'C',
    45: 'D',
    46: 'E',
    47: 'F',
    48: 'G',
    49: 'H',
    50: 'I',
    51: 'J',
    52: 'K',
    53: 'L',
    54: 'M',
    55: 'N',
    56: 'O',
    57: 'P',
    59: 'Q',
    61: 'R',
    65: 'S',
    66: 'T',
    67: 'U',
    68: 'V',
    69: 'W',
    70: 'X',
    71: 'Y',
    72: 'Z',
    73: 'a',
    74: 'b',
    75: 'c',
    76: 'd',
    77: 'e',
    78: 'f',
    79: 'g',
    80: 'h',
    81: 'i',
    82: 'j',
    83: 'k',
    84: 'l',
    85: 'm',
    86: 'n',
    87: 'o',
    88: 'p',
    89: 'q',
    90: 'r',
    91: 's',
    92: 't',
    93: 'u',
    96: 'v',
    161: 'w',
    162: 'x',
    163: 'Bi',
    256: 'y',
    257: 'z',
    258: '0',
    259: '1',
    260: '2',
    261: '3',
    262: '4',
    263: '5',
    264: '6',
    265: '7',
    266: '8',
    267: '9',
    268: '.',
    269: '-',
    280: ':',
    281: '+',
    282: '=',
    283: '^',
    284: '!',
    290: '/',
    291: '*',
    292: '?',
    293: '&',
    294: '<',
    295: '>',
    296: '(',
    297: ')',
    298: '[',
    299: ']',
    300: '{',
    301: '}',
    302: '@',
    303: '%',
    304: '$',
    305: '#',
    306: 'BA',
    307: 'BB',
    308: 'BC',
    309: 'BD',
    310: 'BE',
    311: 'BF',
    312: 'BG',
    313: 'BH',
    314: 'BI',
    320: 'BJ',
    321: 'BK',
    322: 'BL',
    323: 'BM',
    324: 'BN',
    325: 'BO',
    326: 'BP',
    327: 'BQ',
    328: 'BR',
    329: 'BS',
    330: 'BT',
    331: 'BU',
    332: 'BV',
    333: 'BW',
    334: 'BX',
    335: 'BY',
    336: 'BZ',
    340: 'Ba',
    341: 'Bb',
    342: 'Bc',
    343: 'Bd',
    344: 'Be',
    345: 'Bf',
    346: 'Bg',
    347: 'Bh'
}
# END_ENCODING }}}

text_keys = string.ascii_uppercase + string.ascii_lowercase + string.digits + '`~!@#$%^&*()_-+=[{]}\\|<,>./?;:\'" '


def text_match(key):
    if key.upper() == 'SPACE':
        return ' '
    if key not in text_keys:
        return
    return key


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


def update_encoding():
    import re
    import subprocess
    keys = {a for a in dir(defines) if a.startswith('GLFW_KEY_')}
    ans = ENCODING
    key_map = {}
    i = len(ans)
    for k in sorted(keys, key=lambda k: getattr(defines, k)):
        val = getattr(defines, k)
        name = symbolic_name(k)
        if val < defines.GLFW_KEY_LAST and val != defines.GLFW_KEY_UNKNOWN:
            if name not in ans:
                ans[name] = encode(i)
                i += 1
            key_map[val] = ans[name]
    with open(__file__, 'r+') as f:
        raw = f.read()
        nraw = re.sub(
            r'^ENCODING = {.+^# END_ENCODING',
            'ENCODING = {!r}\nKEY_MAP={!r}\n# END_ENCODING'.format(
                ans, key_map
            ),
            raw,
            flags=re.MULTILINE | re.DOTALL
        )
        if raw == nraw:
            raise SystemExit('Failed to replace ENCODING dict')
        f.seek(0), f.truncate()
        f.write(nraw)
    subprocess.check_call(['yapf', '-i', __file__])


PRESS, REPEAT, RELEASE = 1, 2, 4
SHIFT, ALT, CTRL, SUPER = 1, 2, 4, 8
KeyEvent = namedtuple('KeyEvent', 'type mods key')
type_map = {'p': PRESS, 't': REPEAT, 'r': RELEASE}
mod_map = {c: i for i, c in enumerate('ABCDEFGHIJKLMNOP')}
key_rmap = {}
g = globals()
config_key_map = {}
config_mod_map = {
    'SHIFT': SHIFT,
    'ALT': ALT,
    'OPTION': ALT,
    '⌥': ALT,
    '⌘': SUPER,
    'CMD': SUPER,
    'SUPER': SUPER,
    'CTRL': CTRL,
    'CONTROL': CTRL
}
for key_name, enc in ENCODING.items():
    key_name = key_name.replace(' ', '_')
    g[key_name] = config_key_map[key_name] = key_name
    key_rmap[enc] = key_name
config_key_map.update({
    '`': g['GRAVE_ACCENT'],
    '-': g['MINUS'],
    '=': g['EQUAL'],
    '[': g['LEFT_BRACKET'],
    ']': g['RIGHT_BRACKET'],
    '\\': g['BACKSLASH'],
    ';': g['SEMICOLON'],
    "'": g['APOSTROPHE'],
    ',': g['COMMA'],
    '.': g['PERIOD'],
    '/': g['SLASH'],
    'ESC': g['ESCAPE'],
    '+': g['PLUS'],
})

enter_key = KeyEvent(PRESS, 0, g['ENTER'])
backspace_key = KeyEvent(PRESS, 0, g['BACKSPACE'])
del key_name, enc, g


def decode_key_event(text):
    typ = type_map[text[1]]
    mods = mod_map[text[2]]
    key = key_rmap[text[3:5]]
    return KeyEvent(typ, mods, key)
