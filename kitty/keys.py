#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Optional, Union

from .constants import SingleKey
from .config import KeyAction, KeyMap, SequenceMap, SubSequenceMap
from .typing import ScreenType


def keyboard_mode_name(screen: ScreenType) -> str:
    flags = screen.current_key_encoding_flags()
    if flags:
        return 'kitty'
    return 'application' if screen.cursor_key_mode else 'normal'


def get_shortcut(keymap: Union[KeyMap, SequenceMap], mods: int, key: int, native_key: int) -> Optional[Union[KeyAction, SubSequenceMap]]:
    mods &= 0b1111
    ans = keymap.get(SingleKey(mods, False, key))
    if ans is None:
        ans = keymap.get(SingleKey(mods, True, native_key))
    return ans


def shortcut_matches(s: SingleKey, mods: int, key: int, native_key: int) -> bool:
    mods &= 0b1111
    q = native_key if s[1] else key
    return bool(s[0] & 0b1111 == mods & 0b1111 and s[2] == q)
