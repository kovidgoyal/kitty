#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import string
from collections import namedtuple

from . import fast_data_types as defines
from .key_names import key_name_aliases

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
    'PLUS': 'Bi',
    'UNDERSCORE': 'Bj',
    'MENU': 'Bk',
    'EXCLAM': 'Bl',
    'DOUBLE QUOTE': 'Bm',
    'NUMBER SIGN': 'Bn',
    'DOLLAR': 'Bo',
    'AMPERSAND': 'Bp',
    'PARENTHESIS LEFT': 'Bq',
    'PARENTHESIS RIGHT': 'Br',
    'COLON': 'Bs',
    'LESS': 'Bt',
    'GREATER': 'Bu',
    'AT': 'Bv',
    'PARAGRAPH': 'Bw',
    'MASCULINE': 'Bx',
    'A GRAVE': 'By',
    'A DIAERESIS': 'Bz',
    'A RING': 'B0',
    'AE': 'B1',
    'C CEDILLA': 'B2',
    'E GRAVE': 'B3',
    'E ACUTE': 'B4',
    'I GRAVE': 'B5',
    'N TILDE': 'B6',
    'O GRAVE': 'B7',
    'O DIAERESIS': 'B8',
    'O SLASH': 'B9',
    'U GRAVE': 'B.',
    'U DIAERESIS': 'B-',
    'S SHARP': 'B:',
    'CYRILLIC A': 'B+',
    'CYRILLIC BE': 'B=',
    'CYRILLIC VE': 'B^',
    'CYRILLIC GHE': 'B!',
    'CYRILLIC DE': 'B/',
    'CYRILLIC IE': 'B*',
    'CYRILLIC ZHE': 'B?',
    'CYRILLIC ZE': 'B&',
    'CYRILLIC I': 'B<',
    'CYRILLIC SHORT I': 'B>',
    'CYRILLIC KA': 'B(',
    'CYRILLIC EL': 'B)',
    'CYRILLIC EM': 'B[',
    'CYRILLIC EN': 'B]',
    'CYRILLIC O': 'B{',
    'CYRILLIC PE': 'B}',
    'CYRILLIC ER': 'B@',
    'CYRILLIC ES': 'B%',
    'CYRILLIC TE': 'B$',
    'CYRILLIC U': 'B#',
    'CYRILLIC EF': 'CA',
    'CYRILLIC HA': 'CB',
    'CYRILLIC TSE': 'CC',
    'CYRILLIC CHE': 'CD',
    'CYRILLIC SHA': 'CE',
    'CYRILLIC SHCHA': 'CF',
    'CYRILLIC HARD SIGN': 'CG',
    'CYRILLIC YERU': 'CH',
    'CYRILLIC SOFT SIGN': 'CI',
    'CYRILLIC E': 'CJ',
    'CYRILLIC YU': 'CK',
    'CYRILLIC YA': 'CL',
    'CYRILLIC IO': 'CM'
}
KEY_MAP = {
    32: 'A',
    33: 'Bl',
    34: 'Bm',
    35: 'Bn',
    36: 'Bo',
    38: 'Bp',
    39: 'B',
    40: 'Bq',
    41: 'Br',
    43: 'Bi',
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
    58: 'Bs',
    59: 'Q',
    60: 'Bt',
    61: 'R',
    62: 'Bu',
    64: 'Bv',
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
    95: 'Bj',
    96: 'v',
    161: 'w',
    162: 'x',
    167: 'Bw',
    186: 'Bx',
    192: 'By',
    196: 'Bz',
    197: 'B0',
    198: 'B1',
    199: 'B2',
    200: 'B3',
    201: 'B4',
    204: 'B5',
    209: 'B6',
    210: 'B7',
    214: 'B8',
    216: 'B9',
    217: 'B.',
    220: 'B-',
    222: 'B:',
    223: 'B+',
    224: 'B=',
    225: 'B^',
    226: 'B!',
    227: 'B/',
    228: 'B*',
    229: 'B?',
    230: 'B&',
    231: 'B<',
    232: 'B>',
    233: 'B(',
    234: 'B)',
    235: 'B[',
    236: 'B]',
    237: 'B{',
    238: 'B}',
    239: 'B@',
    240: 'B%',
    241: 'B$',
    242: 'B#',
    243: 'CA',
    244: 'CB',
    245: 'CC',
    246: 'CD',
    247: 'CE',
    248: 'CF',
    249: 'CG',
    250: 'CH',
    251: 'CI',
    252: 'CJ',
    253: 'CK',
    254: 'CL',
    255: 'CM',
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
    347: 'Bh',
    348: 'Bk'
}
# END_ENCODING }}}

text_keys = (
    string.ascii_uppercase + string.ascii_lowercase + string.digits +
    '`~!@#$%^&*()_-+=[{]}\\|<,>./?;:\'" '
    'ÄäÖöÜüß§ºàåæçèéìñòøùабвгдежзийклмнопрстуфхцчшщъыьэюяё'
)


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
        if k in ('GLFW_KEY_LAST', 'GLFW_KEY_LAST_PRINTABLE'):
            continue
        val = getattr(defines, k)
        name = symbolic_name(k)
        if val <= defines.GLFW_KEY_LAST and val != defines.GLFW_KEY_UNKNOWN:
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
rtype_map = {v: k for k, v in type_map.items()}
mod_map = {c: i for i, c in enumerate('ABCDEFGHIJKLMNOP')}
rmod_map = {v: k for k, v in mod_map.items()}
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
config_key_map.update({k: g[v] for k, v in key_name_aliases.items() if v in g})

enter_key = KeyEvent(PRESS, 0, g['ENTER'])
backspace_key = KeyEvent(PRESS, 0, g['BACKSPACE'])
del key_name, enc, g


def decode_key_event(text):
    typ = type_map[text[1]]
    mods = mod_map[text[2]]
    key = key_rmap[text[3:5]]
    return KeyEvent(typ, mods, key)


def encode_key_event(key_event):
    typ = rtype_map[key_event.type]
    mods = rmod_map[key_event.mods]
    key = ENCODING[key_event.key.replace('_', ' ')]
    return typ + mods + key
