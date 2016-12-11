#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import kitty.fast_data_types as defines
from .terminfo import key_as_bytes

key_map = {
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
key_map = {k: key_as_bytes(v) for k, v in key_map.items()}
for f in range(1, 13):
    key_map[getattr(defines, 'GLFW_KEY_F{}'.format(f))] = key_as_bytes('kf{}'.format(f))
del f

key_map[defines.GLFW_KEY_ESCAPE] = b'\033'
key_map[defines.GLFW_KEY_ENTER] = b'\r'
key_map[defines.GLFW_KEY_BACKSPACE] = key_as_bytes('kbs')
key_map[defines.GLFW_KEY_TAB] = b'\t'

SHIFTED_KEYS = {
    defines.GLFW_KEY_TAB: key_as_bytes('kcbt'),
    defines.GLFW_KEY_HOME: key_as_bytes('kHOM'),
    defines.GLFW_KEY_END: key_as_bytes('kEND'),
    defines.GLFW_KEY_LEFT: key_as_bytes('kLFT'),
    defines.GLFW_KEY_RIGHT: key_as_bytes('kRIT'),
}

control_codes = {k: 1 + i for i, k in enumerate(range(defines.GLFW_KEY_A, defines.GLFW_KEY_RIGHT_BRACKET + 1))}
alt_codes = {k: (0x1b, k) for i, k in enumerate(range(defines.GLFW_KEY_SPACE, defines.GLFW_KEY_RIGHT_BRACKET + 1))}


def interpret_key_event(key, scancode, mods):
    data = bytearray()
    if mods == defines.GLFW_MOD_CONTROL and key in control_codes:
        # Map Ctrl-key to ascii control code
        data.append(control_codes[key])
    elif mods == defines.GLFW_MOD_ALT and key in alt_codes:
        # Map Alt+key to Esc-key
        data.extend(alt_codes[key])
    else:
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


def get_shortcut(keymap, mods, key):
    return keymap.get((mods & 0b1111, key))
