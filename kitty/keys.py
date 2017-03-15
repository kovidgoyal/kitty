#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from . import fast_data_types as defines
from .terminfo import key_as_bytes
from .utils import base64_encode
from .key_encoding import KEY_MAP

smkx_key_map = {
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
}
smkx_key_map = {k: key_as_bytes(v) for k, v in smkx_key_map.items()}
for f in range(1, 13):
    kf = getattr(defines, 'GLFW_KEY_F{}'.format(f))
    smkx_key_map[kf] = key_as_bytes('kf{}'.format(f))
del f, kf

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

control_codes = {
    k: (1 + i, )
    for i, k in
    enumerate(range(defines.GLFW_KEY_A, defines.GLFW_KEY_RIGHT_BRACKET + 1))
}


def rkey(name, a, b):
    return bytearray(key_as_bytes(name).replace(a, b))


control_codes[defines.GLFW_KEY_UP] = rkey('cuu1', b'[', b'[1;5')
control_codes[defines.GLFW_KEY_DOWN] = rkey('cud', b'[%p1%d', b'[1;5')
control_codes[defines.GLFW_KEY_LEFT] = rkey('cub', b'[%p1%d', b'[1;5')
control_codes[defines.GLFW_KEY_RIGHT] = rkey('cuf1', b'[', b'[1;5')
control_codes[defines.GLFW_KEY_HOME] = rkey('khome', b'O', b'[1;5')
control_codes[defines.GLFW_KEY_END] = rkey('kend', b'O', b'[1;5')
control_codes[defines.GLFW_KEY_PAGE_UP] = rkey('kpp', b'~', b';5~')
control_codes[defines.GLFW_KEY_PAGE_DOWN] = rkey('knp', b'~', b';5~')
control_codes[defines.GLFW_KEY_DELETE] = rkey('kdch1', b'~', b';5~')
alt_codes = {
    k: (0x1b, k)
    for i, k in enumerate(
        range(defines.GLFW_KEY_SPACE, defines.GLFW_KEY_RIGHT_BRACKET + 1)
    )
}

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
    defines.GLFW_PRESS: b'p',
    defines.GLFW_RELEASE: b'r',
    defines.GLFW_REPEAT: b't'
}


def extended_key_event(key, scancode, mods, action):
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


def interpret_key_event(key, scancode, mods, window, action):
    screen = window.screen
    key = get_localized_key(key, scancode)
    if screen.extended_keyboard:
        return extended_key_event(key, scancode, mods, action)
    data = bytearray()
    if action == defines.GLFW_PRESS or (
        action == defines.GLFW_REPEAT and screen.auto_repeat_enabled
    ):
        if mods == defines.GLFW_MOD_CONTROL and key in control_codes:
            # Map Ctrl-key to ascii control code
            data.extend(control_codes[key])
        elif mods == defines.GLFW_MOD_ALT and key in alt_codes:
            # Map Alt+key to Esc-key
            data.extend(alt_codes[key])
        else:
            key_map = get_key_map(screen)
            x = key_map.get(key)
            if x is not None:
                if mods == defines.GLFW_MOD_SHIFT:
                    x = SHIFTED_KEYS.get(key, x)
                data.extend(x)
    return bytes(data)


def interpret_text_event(codepoint, mods):
    if mods > defines.GLFW_MOD_SHIFT:
        return b''  # Handled by interpret_key_event above
    data = chr(codepoint).encode('utf-8')
    return data


def get_shortcut(keymap, mods, key, scancode):
    key = get_localized_key(key, scancode)
    return keymap.get((mods & 0b1111, key))
