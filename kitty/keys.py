#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from . import fast_data_types as defines
from .terminfo import key_as_bytes
from .utils import base64_encode
from .key_encoding import KEY_MAP


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
alt_codes = {defines.GLFW_KEY_TAB: b'\033\t'}
shift_alt_codes = {defines.GLFW_KEY_TAB: key_as_bytes('kcbt')}
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


def get_key_map(screen):
    return cursor_key_mode_map[screen.cursor_key_mode]


def keyboard_mode_name(screen):
    if screen.extended_keyboard:
        return 'kitty'
    return 'application' if screen.cursor_key_mode else 'normal'


valid_localized_key_names = {
    k: getattr(defines, 'GLFW_KEY_' + k)
    for k in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
}

for name, ch in {
    'APOSTROPHE': "'",
    'COMMA': ',',
    'PERIOD': '.',
    'SLASH': '/',
    'MINUS': '-',
    'SEMICOLON': ';',
    'EQUAL': '=',
    'LEFT_BRACKET': '[',
    'RIGHT_BRACKET': ']',
    'GRAVE_ACCENT': '`',
    'BACKSLASH': '\\'
}.items():
    valid_localized_key_names[ch] = getattr(defines, 'GLFW_KEY_' + name)


def get_localized_key(key, scancode):
    name = defines.glfw_get_key_name(key, scancode)
    return valid_localized_key_names.get((name or '').upper(), key)


action_map = {
    defines.GLFW_PRESS: 'p',
    defines.GLFW_RELEASE: 'r',
    defines.GLFW_REPEAT: 't'
}


def extended_key_event(key, mods, action):
    if key >= defines.GLFW_KEY_LAST or key == defines.GLFW_KEY_UNKNOWN or (
        # Shifted printable key should be handled by interpret_text_event()
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
    return '\033_K{}{}{}\033\\'.format(
        action_map[action], base64_encode(mods), name
    ).encode('ascii')


def key_to_bytes(key, smkx, extended, mods, action):
    if extended:
        return extended_key_event(key, mods, action)
    data = bytearray()
    if mods == defines.GLFW_MOD_CONTROL and key in control_codes:
        # Map Ctrl-key to ascii control code
        data.extend(control_codes[key])
    elif mods in alt_mods and key in alt_codes:
        # Printable keys handled by interpret_text_event()
        data.extend((alt_codes if mods == defines.GLFW_MOD_ALT else shift_alt_codes)[key])
    else:
        key_map = cursor_key_mode_map[smkx]
        x = key_map.get(key)
        if x is not None:
            if mods == defines.GLFW_MOD_SHIFT:
                x = SHIFTED_KEYS.get(key, x)
            data.extend(x)
    return bytes(data)


def interpret_key_event(key, scancode, mods, window, action, get_localized_key=get_localized_key):
    screen = window.screen
    if (
            action == defines.GLFW_PRESS or
            (action == defines.GLFW_REPEAT and screen.auto_repeat_enabled) or
            screen.extended_keyboard
    ):
        key = get_localized_key(key, scancode)
        return key_to_bytes(key, screen.cursor_key_mode, screen.extended_keyboard, mods, action)
    return b''


def interpret_text_event(codepoint, mods, window):
    screen = window.screen
    if mods > defines.GLFW_MOD_SHIFT:
        if mods in alt_mods and not screen.extended_keyboard:
            data = chr(codepoint).encode('utf-8')
            return b'\x1b' + data
        return b''  # Handled by interpret_key_event above
    data = chr(codepoint).encode('utf-8')
    return data


def get_shortcut(keymap, mods, key, scancode):
    key = get_localized_key(key, scancode)
    return keymap.get((mods & 0b1111, key))


def get_sent_data(send_text_map, key, scancode, mods, window, action):
    if action in (defines.GLFW_PRESS, defines.GLFW_REPEAT):
        key = get_localized_key(key, scancode)
        m = keyboard_mode_name(window.screen)
        keymap = send_text_map[m]
        return keymap.get((mods & 0b1111, key))
