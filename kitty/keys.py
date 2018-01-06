#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import string

from . import fast_data_types as defines
from .key_encoding import KEY_MAP
from .terminfo import key_as_bytes
from .utils import base64_encode


def modify_key_bytes(keybytes, amt):
    ans = bytearray(keybytes)
    amt = str(amt).encode('ascii')
    if ans[-1] == ord('~'):
        return bytes(ans[:-1] + bytearray(b';' + amt + b'~'))
    if ans[1] == ord('O'):
        return bytes(ans[:1] + bytearray(b'[1;' + amt) + ans[-1:])
    raise ValueError('Unknown key type')


def modify_complex_key(name, amt):
    return modify_key_bytes(key_as_bytes(name), amt)


control_codes = {}
smkx_key_map = {}
alt_codes = {
    defines.GLFW_KEY_TAB: b'\033\t',
    defines.GLFW_KEY_ENTER: b'\033\r',
    defines.GLFW_KEY_ESCAPE: b'\033\033',
    # alt+bs matches iTerm and gnome-terminal
    defines.GLFW_KEY_BACKSPACE: b'\x17'
}
shift_alt_codes = alt_codes.copy()
shift_alt_codes[defines.GLFW_KEY_TAB] = key_as_bytes('kcbt')
alt_mods = (defines.GLFW_MOD_ALT, defines.GLFW_MOD_SHIFT | defines.GLFW_MOD_ALT)

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
    smkx_key_map[kf] = key_as_bytes(kn)
    alt_codes[kf] = modify_complex_key(kn, 3)
    shift_alt_codes[kf] = modify_complex_key(kn, 4)
    control_codes[kf] = modify_complex_key(kn, 5)
for f in range(1, 13):
    kf = getattr(defines, 'GLFW_KEY_F{}'.format(f))
    kn = 'kf{}'.format(f)
    smkx_key_map[kf] = key_as_bytes(kn)
    alt_codes[kf] = modify_complex_key(kn, 3)
    shift_alt_codes[kf] = modify_complex_key(kn, 4)
    control_codes[kf] = modify_complex_key(kn, 5)
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

SHIFTED_KEYS = {
    defines.GLFW_KEY_TAB: key_as_bytes('kcbt'),
    defines.GLFW_KEY_HOME: key_as_bytes('kHOM'),
    defines.GLFW_KEY_END: key_as_bytes('kEND'),
    defines.GLFW_KEY_LEFT: key_as_bytes('kLFT'),
    defines.GLFW_KEY_RIGHT: key_as_bytes('kRIT'),
    defines.GLFW_KEY_UP: key_as_bytes('kri'),
    defines.GLFW_KEY_DOWN: key_as_bytes('kind'),
}

control_codes.update({
    k: (1 + i, )
    for i, k in
    enumerate(range(defines.GLFW_KEY_A, defines.GLFW_KEY_RIGHT_BRACKET + 1))
})
control_codes[defines.GLFW_KEY_6] = (30,)
control_codes[defines.GLFW_KEY_SLASH] = (31,)
control_codes[defines.GLFW_KEY_SPACE] = (0,)

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
        mods == defines.GLFW_MOD_SHIFT and 32 <= key <= 126
    ):
        return b''
    if mods == 0 and key in (
        defines.GLFW_KEY_BACKSPACE, defines.GLFW_KEY_ENTER
    ):
        return smkx_key_map[key]
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
    'LEFT_BRACKET BACKSLASH RIGHT_BRACKET GRAVE_ACCENT',
    "[\\]`"
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


def key_to_bytes(key, smkx, extended, mods, action):
    if extended:
        return extended_key_event(key, mods, action)
    data = bytearray()
    if mods == defines.GLFW_MOD_CONTROL and key in control_codes:
        # Map Ctrl-key to ascii control code
        data.extend(control_codes[key])
    elif mods in alt_mods:
        if key in alt_codes:
            data.extend((alt_codes if mods == defines.GLFW_MOD_ALT else shift_alt_codes)[key])
        elif key in UN_SHIFTED_PRINTABLE:
            m = UN_SHIFTED_PRINTABLE if mods == defines.GLFW_MOD_ALT else SHIFTED_PRINTABLE
            data.append(0o33)
            data.extend(m[key])
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
    return keymap.get((mods & 0b1111, key))


def generate_key_table():
    # To run this, use: python3 . -c "from kitty.keys import *; generate_key_table()"
    import os
    from functools import partial
    f = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys.h'), 'w')
    w = partial(print, file=f)
    w('// auto-generated from keys.py, do not edit!')
    w('#pragma once')
    w('#include <stddef.h>')
    w('#include <stdint.h>')
    w('#include <stdbool.h>')
    w('#include <limits.h>')
    w('static bool needs_special_handling[%d] = {0};' % (128 * 16))
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
                ind('}  // end switch(mods)\n')
                i -= 1
            else:
                ind('return NULL;\n')
                i -= 1
            i -= 1
        ind('}}  // end switch(action) in mode {}\n\n'.format(mode))
        i -= 1
    i -= 1
    ind('}')
    ind('return NULL;')
    i -= 1
    w('}')
