#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Optional, Union

from .config import KeyAction, KeyMap, SequenceMap, SubSequenceMap
from .fast_data_types import (
    GLFW_MOD_ALT, GLFW_MOD_CAPS_LOCK, GLFW_MOD_CONTROL, GLFW_MOD_HYPER,
    GLFW_MOD_META, GLFW_MOD_NUM_LOCK, GLFW_MOD_SHIFT, GLFW_MOD_SUPER, KeyEvent
)
from .types import SingleKey
from .typing import ScreenType


mod_mask = GLFW_MOD_ALT | GLFW_MOD_CONTROL | GLFW_MOD_SHIFT | GLFW_MOD_SUPER | GLFW_MOD_META | GLFW_MOD_HYPER
lock_mask = GLFW_MOD_NUM_LOCK | GLFW_MOD_CAPS_LOCK


def keyboard_mode_name(screen: ScreenType) -> str:
    flags = screen.current_key_encoding_flags()
    if flags:
        return 'kitty'
    return 'application' if screen.cursor_key_mode else 'normal'


def get_shortcut(keymap: Union[KeyMap, SequenceMap], ev: KeyEvent) -> Optional[Union[KeyAction, SubSequenceMap]]:
    mods = ev.mods & mod_mask
    ans = keymap.get(SingleKey(mods, False, ev.key))
    if ans is None and ev.shifted_key and mods & GLFW_MOD_SHIFT:
        ans = keymap.get(SingleKey(mods & (~GLFW_MOD_SHIFT), False, ev.shifted_key))
    if ans is None:
        ans = keymap.get(SingleKey(mods, True, ev.native_key))
    return ans


def shortcut_matches(s: SingleKey, ev: KeyEvent) -> bool:
    mods = ev.mods & mod_mask
    smods = s.mods & mod_mask
    if s.is_native:
        return s.key == ev.native_key and smods == mods
    if s.key == ev.key and mods == smods:
        return True
    if ev.shifted_key and mods & GLFW_MOD_SHIFT and (mods & ~GLFW_MOD_SHIFT) == smods and ev.shifted_key == s.key:
        return True
    return False
