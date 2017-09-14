#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from .fast_data_types import (
    GLFW_MOUSE_BUTTON_2, GLFW_MOUSE_BUTTON_3, GLFW_MOD_ALT, GLFW_MOD_CONTROL,
    GLFW_MOD_SHIFT, GLFW_MOUSE_BUTTON_4, GLFW_MOUSE_BUTTON_5,
    GLFW_MOUSE_BUTTON_1,
)

PRESS, RELEASE, DRAG, MOVE = range(4)
SHIFT_INDICATOR = 1 << 2
ALT_INDICATOR = 1 << 3
CONTROL_INDICATOR = 1 << 4
MOTION_INDICATOR = 1 << 5
EXTRA_BUTTON_INDICATOR = 1 << 6

cb_map = {
    GLFW_MOUSE_BUTTON_1: 0,
    GLFW_MOUSE_BUTTON_2: 0b1,
    GLFW_MOUSE_BUTTON_3: 0b10,
    GLFW_MOUSE_BUTTON_4: EXTRA_BUTTON_INDICATOR,
    GLFW_MOUSE_BUTTON_5: EXTRA_BUTTON_INDICATOR | 0b1
}


def encode_mouse_event(tracking_mode, tracking_protocol, button, action, mods, x, y):
    x, y = x + 1, y + 1  # One based indexing
    cb = 0
    if action is MOVE:
        if tracking_protocol != SGR_PROTOCOL:
            cb = 0b11
    else:
        cb = cb_map.get(button)
        if cb is None:
            return
    if action in (DRAG, MOVE):
        cb |= MOTION_INDICATOR
    elif action is RELEASE:
        if tracking_protocol != SGR_PROTOCOL:
            cb = 0b11
    if mods & GLFW_MOD_SHIFT:
        cb |= SHIFT_INDICATOR
    if mods & GLFW_MOD_ALT:
        cb |= ALT_INDICATOR
    if mods & GLFW_MOD_CONTROL:
        cb |= CONTROL_INDICATOR
    ans = None
    if tracking_protocol == SGR_PROTOCOL:
        ans = '\033[<%d;%d;%d%s' % (cb, x, y, 'm' if action is RELEASE else 'M')
        ans = ans.encode('ascii')
    elif tracking_protocol == URXVT_PROTOCOL:
        ans = '\033[%d;%d;%dM' % (cb + 32, x, y)
        ans = ans.encode('ascii')
    elif tracking_protocol == UTF8_PROTOCOL:
        ans = bytearray([0o33, ord('['), cb + 32])
        ans.extend(chr(x + 32).encode('utf-8') + chr(y + 32).encode('utf-8'))
        ans = bytes(ans)
    else:
        if x <= 223 and y <= 223:
            ans = bytearray([0o33, ord('['), ord('M'), cb + 32, x + 32, y + 32])
    return ans
