#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import glfw_constants as defines

key_map = {
    defines.GLFW_KEY_UP: b'OA',
    defines.GLFW_KEY_DOWN: b'OB',
    defines.GLFW_KEY_LEFT: b'OD',
    defines.GLFW_KEY_RIGHT: b'OC',
    defines.GLFW_KEY_HOME: b'OH',
    defines.GLFW_KEY_END: b'OF',
    defines.GLFW_KEY_ESCAPE: b'',
    defines.GLFW_KEY_INSERT: b'[2~',
    defines.GLFW_KEY_DELETE: b'[3~',
    defines.GLFW_KEY_PAGE_UP: b'[5~',
    defines.GLFW_KEY_PAGE_DOWN: b'[6~',
    defines.GLFW_KEY_F1: b'OP',
    defines.GLFW_KEY_F2: b'OQ',
    defines.GLFW_KEY_F3: b'OR',
    defines.GLFW_KEY_F4: b'OS',
    defines.GLFW_KEY_F5: b'[15~',
    defines.GLFW_KEY_F6: b'[17~',
    defines.GLFW_KEY_F7: b'[18~',
    defines.GLFW_KEY_F8: b'[19~',
    defines.GLFW_KEY_F9: b'[20~',
    defines.GLFW_KEY_F10: b'[21~',
    defines.GLFW_KEY_F11: b'[23~',
    defines.GLFW_KEY_F12: b'[24~',
}
key_map = {k: b'\x1b' + v for k, v in key_map.items()}
key_map[defines.GLFW_KEY_ENTER] = b'\r'
key_map[defines.GLFW_KEY_BACKSPACE] = b'\x08'
key_map[defines.GLFW_KEY_TAB] = b'\t'

control_codes = {k: 1 + i for i, k in enumerate(range(defines.GLFW_KEY_A, defines.GLFW_KEY_RIGHT_BRACKET))}
alt_codes = {k: (0x1b, k) for i, k in enumerate(range(defines.GLFW_KEY_A, defines.GLFW_KEY_RIGHT_BRACKET))}


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
                if key == defines.GLFW_KEY_TAB:
                    x = b'\x1b[Z'
            data.extend(x)
    return bytes(data)


def interpret_text_event(codepoint, mods):
    if mods > defines.GLFW_MOD_SHIFT:
        return b''  # Handled by interpret_key_event above
    data = chr(codepoint).encode('utf-8')
    return data


def get_shortcut(keymap, mods, key):
    return keymap.get((mods & 0b1111, key))
