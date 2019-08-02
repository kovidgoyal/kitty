#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import string

from . import fast_data_types as defines
from .key_encoding import KEY_MAP
from .terminfo import key_as_bytes, modify_key_bytes
from .utils import base64_encode


def modify_complex_key(name, amt):
    if not isinstance(name, bytes):
        name = key_as_bytes(name)
    return modify_key_bytes(name, amt)


control_codes = {
    defines.GLFW_KEY_BACKSPACE: b'\x08'
}
smkx_key_map = {}
alt_codes = {
    defines.GLFW_KEY_TAB: b'\033\t',
    defines.GLFW_KEY_ENTER: b'\033\r',
    defines.GLFW_KEY_ESCAPE: b'\033\033',
    defines.GLFW_KEY_BACKSPACE: b'\033\177'
}
shift_alt_codes = alt_codes.copy()
shift_alt_codes[defines.GLFW_KEY_TAB] = key_as_bytes('kcbt')
alt_mods = (defines.GLFW_MOD_ALT, defines.GLFW_MOD_SHIFT | defines.GLFW_MOD_ALT)
ctrl_shift_mod = defines.GLFW_MOD_SHIFT | defines.GLFW_MOD_CONTROL
ctrl_alt_mod = defines.GLFW_MOD_ALT | defines.GLFW_MOD_CONTROL
ctrl_alt_shift_mod = ctrl_alt_mod | defines.GLFW_MOD_SHIFT
SHIFTED_KEYS = {
    defines.GLFW_KEY_TAB: key_as_bytes('kcbt'),
    defines.GLFW_KEY_HOME: key_as_bytes('kHOM'),
    defines.GLFW_KEY_END: key_as_bytes('kEND'),
    defines.GLFW_KEY_LEFT: key_as_bytes('kLFT'),
    defines.GLFW_KEY_RIGHT: key_as_bytes('kRIT'),
    defines.GLFW_KEY_UP: key_as_bytes('kri'),
    defines.GLFW_KEY_DOWN: key_as_bytes('kind'),
    defines.GLFW_KEY_PAGE_UP: modify_complex_key('kpp', 2),
    defines.GLFW_KEY_PAGE_DOWN: modify_complex_key('knp', 2),
}

control_alt_codes = {
    defines.GLFW_KEY_SPACE: b'\x1b\0',
}
control_alt_shift_codes = {}
ASCII_C0_SHIFTED = {
    # ^@
    '2': b'\x00',
    # ^^
    '6': b'\x1e',
    # ^_
    'MINUS': b'\x1f',
    # ^?
    'SLASH': b'\x7f',
}
control_shift_keys = {getattr(defines, 'GLFW_KEY_' + k): v for k, v in ASCII_C0_SHIFTED.items()}


def create_modifier_variants(keycode, terminfo_name_or_bytes, add_shifted_key=True):
    kn = terminfo_name_or_bytes
    smkx_key_map[keycode] = kn if isinstance(kn, bytes) else key_as_bytes(kn)
    if add_shifted_key:
        SHIFTED_KEYS[keycode] = modify_complex_key(kn, 2)
    alt_codes[keycode] = modify_complex_key(kn, 3)
    shift_alt_codes[keycode] = modify_complex_key(kn, 4)
    control_codes[keycode] = modify_complex_key(kn, 5)
    control_shift_keys[keycode] = modify_complex_key(kn, 6)
    control_alt_codes[keycode] = modify_complex_key(kn, 7)
    control_alt_shift_codes[keycode] = modify_complex_key(kn, 8)


for kf, kn in {
    defines.GLFW_KEY_UP: 'kcuu1',
    defines.GLFW_KEY_DOWN: 'kcud1',
    defines.GLFW_KEY_LEFT: 'kcub1',
    defines.GLFW_KEY_RIGHT: 'kcuf1',
    defines.GLFW_KEY_HOME: 'khome',
    defines.GLFW_KEY_END: 'kend',
    defines.GLFW_KEY_INSERT: 'kich1',
    defines.GLFW_KEY_DELETE: 'kdch1',
    defines.GLFW_KEY_PAGE_UP: 'kpp',
    defines.GLFW_KEY_PAGE_DOWN: 'knp',
}.items():
    create_modifier_variants(kf, kn, add_shifted_key=False)
for f in range(1, 13):
    kf = getattr(defines, 'GLFW_KEY_F{}'.format(f))
    kn = 'kf{}'.format(f)
    create_modifier_variants(kf, kn)
for f in range(13, 26):
    kf = getattr(defines, 'GLFW_KEY_F{}'.format(f))
    kn = 'kf{}'.format(f)
    smkx_key_map[kf] = key_as_bytes(kn)
create_modifier_variants(defines.GLFW_KEY_MENU, b'\x1b[29~')
f = {k: k for k in '0123456789'}
f.update({
    'COMMA': ',',
    'PERIOD': '.',
    'SEMICOLON': ';',
    'APOSTROPHE': "'",
    'MINUS': '-',
    'EQUAL': '=',
})
for kf, kn in f.items():
    control_codes[getattr(defines, 'GLFW_KEY_' + kf)] = (ord(kn),)
del f, kf, kn

smkx_key_map[defines.GLFW_KEY_ESCAPE] = b'\033'
smkx_key_map[defines.GLFW_KEY_ENTER] = b'\r'
smkx_key_map[defines.GLFW_KEY_KP_ENTER] = b'\r'
smkx_key_map[defines.GLFW_KEY_BACKSPACE] = key_as_bytes('kbs')
smkx_key_map[defines.GLFW_KEY_TAB] = b'\t'

control_codes.update({
    k: (1 + i, )
    for i, k in
    enumerate(range(defines.GLFW_KEY_A, defines.GLFW_KEY_RIGHT_BRACKET + 1))
})
control_codes[defines.GLFW_KEY_GRAVE_ACCENT] = (0,)
control_codes[defines.GLFW_KEY_UNDERSCORE] = (0,)
control_codes[defines.GLFW_KEY_SPACE] = (0,)
control_codes[defines.GLFW_KEY_2] = (0,)
control_codes[defines.GLFW_KEY_3] = (27,)
control_codes[defines.GLFW_KEY_4] = (28,)
control_codes[defines.GLFW_KEY_5] = (29,)
control_codes[defines.GLFW_KEY_6] = (30,)
control_codes[defines.GLFW_KEY_7] = (31,)
control_codes[defines.GLFW_KEY_SLASH] = (31,)
control_codes[defines.GLFW_KEY_8] = (127,)

rmkx_key_map = smkx_key_map.copy()
rmkx_key_map.update({
    defines.GLFW_KEY_UP: b'\033[A',
    defines.GLFW_KEY_DOWN: b'\033[B',
    defines.GLFW_KEY_LEFT: b'\033[D',
    defines.GLFW_KEY_RIGHT: b'\033[C',
    defines.GLFW_KEY_HOME: b'\033[H',
    defines.GLFW_KEY_END: b'\033[F',
})

cursor_key_mode_map = {True: smkx_key_map, False: rmkx_key_map}


def keyboard_mode_name(screen):
    if screen.extended_keyboard:
        return 'kitty'
    return 'application' if screen.cursor_key_mode else 'normal'


action_map = {
    defines.GLFW_PRESS: 'p',
    defines.GLFW_RELEASE: 'r',
    defines.GLFW_REPEAT: 't'
}


def extended_key_event(key, mods, action):
    if key >= defines.GLFW_KEY_LAST or key == defines.GLFW_KEY_UNKNOWN or (
        # Shifted printable key should be handled by on_text_input()
        mods <= defines.GLFW_MOD_SHIFT and 32 <= key <= 126
    ):
        return b''
    if mods == 0 and key in (
        defines.GLFW_KEY_BACKSPACE, defines.GLFW_KEY_ENTER
    ):
        if action == defines.GLFW_RELEASE:
            return b''
        return smkx_key_map[key]
    if key in (defines.GLFW_KEY_LEFT_SHIFT, defines.GLFW_KEY_RIGHT_SHIFT):
        return b''
    name = KEY_MAP.get(key)
    if name is None:
        return b''
    m = 0
    if mods & defines.GLFW_MOD_SHIFT:
        m |= 0x1
    if mods & defines.GLFW_MOD_ALT:
        m |= 0x2
    if mods & defines.GLFW_MOD_CONTROL:
        m |= 0x4
    if mods & defines.GLFW_MOD_SUPER:
        m |= 0x8
    return 'K{}{}{}'.format(
        action_map[action], base64_encode(m), name
    ).encode('ascii')


def pmap(names, r):
    names = names.split()
    r = [x.encode('ascii') for x in r]
    if len(names) != len(r):
        raise ValueError('Incorrect mapping for {}'.format(names))
    names = [getattr(defines, 'GLFW_KEY_' + n) for n in names]
    return dict(zip(names, r))


UN_SHIFTED_PRINTABLE = {
    getattr(defines, 'GLFW_KEY_' + x): x.lower().encode('ascii')
    for x in string.digits + string.ascii_uppercase
}
UN_SHIFTED_PRINTABLE.update(pmap(
    'SPACE APOSTROPHE COMMA MINUS PERIOD SLASH SEMICOLON EQUAL',
    " ',-./;="
))
UN_SHIFTED_PRINTABLE.update(pmap(
    'LEFT_BRACKET BACKSLASH RIGHT_BRACKET GRAVE_ACCENT UNDERSCORE',
    "[\\]`_"
))
SHIFTED_PRINTABLE = UN_SHIFTED_PRINTABLE.copy()
SHIFTED_PRINTABLE.update({
    getattr(defines, 'GLFW_KEY_' + x): x.encode('ascii') for x in string.ascii_uppercase
})
SHIFTED_PRINTABLE.update(pmap(
    '1 2 3 4 5 6 7 8 9 0',
    '!@#$%^&*()'
))
SHIFTED_PRINTABLE.update(pmap(
    'APOSTROPHE COMMA MINUS PERIOD SLASH SEMICOLON EQUAL',
    '"<_>?:+'
))
SHIFTED_PRINTABLE.update(pmap(
    'LEFT_BRACKET BACKSLASH RIGHT_BRACKET GRAVE_ACCENT',
    "{|}~"
))

CTRL_ALT_KEYS = {getattr(defines, 'GLFW_KEY_' + k) for k in string.ascii_uppercase}
all_control_alt_keys = set(CTRL_ALT_KEYS) | set(control_alt_codes)


def key_to_bytes(key, smkx, extended, mods, action):
    if extended:
        return extended_key_event(key, mods, action)
    data = bytearray()
    if mods == defines.GLFW_MOD_CONTROL and key in control_codes:
        # Map Ctrl-key to ascii control code
        data.extend(control_codes[key])
    elif mods == ctrl_shift_mod and key in control_shift_keys:
        data.extend(control_shift_keys[key])
    elif mods in alt_mods:
        if key in alt_codes:
            data.extend((alt_codes if mods == defines.GLFW_MOD_ALT else shift_alt_codes)[key])
        elif key in UN_SHIFTED_PRINTABLE:
            m = UN_SHIFTED_PRINTABLE if mods == defines.GLFW_MOD_ALT else SHIFTED_PRINTABLE
            data.append(0o33)
            data.extend(m[key])
    elif mods == ctrl_alt_mod and key in all_control_alt_keys:
        if key in CTRL_ALT_KEYS:
            data.append(0x1b), data.extend(control_codes[key])
        else:
            data.extend(control_alt_codes[key])
    elif mods == ctrl_alt_shift_mod and key in control_alt_shift_codes:
        data.extend(control_alt_shift_codes[key])
    else:
        key_map = cursor_key_mode_map[smkx]
        x = key_map.get(key)
        if x is not None:
            if mods == defines.GLFW_MOD_SHIFT:
                x = SHIFTED_KEYS.get(key, x)
            data.extend(x)
    return bytes(data)


def interpret_key_event(key, scancode, mods, window, action):
    screen = window.screen
    if (
            action == defines.GLFW_PRESS or
            (action == defines.GLFW_REPEAT and screen.auto_repeat_enabled) or
            screen.extended_keyboard
    ):
        return defines.key_to_bytes(key, screen.cursor_key_mode, screen.extended_keyboard, mods, action)
    return b''


def get_shortcut(keymap, mods, key, scancode):
    mods &= 0b1111
    ans = keymap.get((mods, False, key))
    if ans is None:
        ans = keymap.get((mods, True, scancode))
    return ans


def shortcut_matches(s, mods, key, scancode):
    mods &= 0b1111
    q = scancode if s[1] else key
    return s[0] & 0b1111 == mods & 0b1111 and s[2] == q


def generate_key_table_impl(w):
    w('// auto-generated from keys.py, do not edit!')
    w('#pragma once')
    w('#include <stddef.h>')
    w('#include <stdint.h>')
    w('#include <stdbool.h>')
    w('#include <limits.h>')
    number_of_keys = defines.GLFW_KEY_LAST + 1
    w('// map glfw key numbers to 7-bit numbers for compact data storage')
    w('static const uint8_t key_map[%d] = {' % number_of_keys)
    key_count = 0

    def key_name(k):
        return k[len('GLFW_KEY_'):]

    keys = {v: k for k, v in vars(defines).items() if k.startswith('GLFW_KEY_') and k not in {'GLFW_KEY_LAST', 'GLFW_KEY_UNKNOWN'}}
    key_rmap = []
    for i in range(number_of_keys):
        k = keys.get(i)
        if k is None:
            w('UINT8_MAX,')
        else:
            w('%d, /* %s */' % (key_count, key_name(k)))
            key_rmap.append(i)
            key_count += 1
            if key_count > 128:
                raise OverflowError('Too many keys')
    w('};\n')
    w('static inline const char* key_name(int key) { switch(key) {')
    for i in range(number_of_keys):
        k = keys.get(i)
        if k is not None:
            w('case %d: return "%s";' % (i, key_name(k)))
    w('default: return NULL; }}\n')
    w('typedef enum { NORMAL, APPLICATION, EXTENDED } KeyboardMode;\n')
    w('static inline const char*\nkey_lookup(uint8_t key, KeyboardMode mode, uint8_t mods, uint8_t action) {')
    i = 1

    def ind(*a):
        w(('  ' * i)[:-1], *a)
    ind('switch(mode) {')
    mmap = [(False, False), (True, False), (False, True)]
    for (smkx, extended), mode in zip(mmap, 'NORMAL APPLICATION EXTENDED'.split()):
        i += 1
        ind('case {}:'.format(mode))
        i += 1
        ind('switch(action & 3) { case 3: return NULL;')
        for action in (defines.GLFW_RELEASE, defines.GLFW_PRESS, defines.GLFW_REPEAT):
            i += 1
            ind('case {}: // {}'.format(action, 'RELEASE PRESS REPEAT'.split()[action]))
            i += 1
            if action != defines.GLFW_RELEASE or mode == 'EXTENDED':
                ind('switch (mods & 0xf) {')
                i += 1
                for mods in range(16):
                    key_bytes = {}
                    for key in range(key_count):
                        glfw_key = key_rmap[key]
                        data = key_to_bytes(glfw_key, smkx, extended, mods, action)
                        if data:
                            key_bytes[key] = data, glfw_key
                    i += 1
                    ind('case 0x{:x}:'.format(mods))
                    i += 1
                    if key_bytes:
                        ind('switch(key & 0x7f) { default: return NULL;')
                        i += 1
                        for key, (data, glfw_key) in key_bytes.items():
                            ind('case {}: // {}'.format(key, key_name(keys[glfw_key])))
                            i += 1
                            items = bytearray(data)
                            items.insert(0, len(items))
                            ind('return "{}";'.format(''.join('\\x{:02x}'.format(x) for x in items)))
                            i -= 1
                        i -= 1
                        ind('} // end switch(key)')
                    else:
                        ind('return NULL;')
                    i -= 2
                i -= 1
                ind('}  // end switch(mods)')
                ind('break;\n')
                i -= 1
            else:
                ind('return NULL;\n')
                i -= 1
            i -= 1
        ind('}}  // end switch(action) in mode {}'.format(mode))
        ind('break;\n\n')
        i -= 1
    i -= 1
    ind('}')
    ind('return NULL;')
    i -= 1
    w('}')


def generate_key_table():
    # To run this, use: python3 . +runpy "from kitty.keys import *; generate_key_table()"
    import os
    from functools import partial
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys.h'), 'w') as f:
        w = partial(print, file=f)
        generate_key_table_impl(w)
