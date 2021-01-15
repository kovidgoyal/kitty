#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Optional, Union

from .config import KeyAction, KeyMap, SequenceMap, SubSequenceMap
from .fast_data_types import KeyEvent
from .types import SingleKey
from .typing import ScreenType


def keyboard_mode_name(screen: ScreenType) -> str:
    flags = screen.current_key_encoding_flags()
    if flags:
        return 'kitty'
    return 'application' if screen.cursor_key_mode else 'normal'


def get_shortcut(keymap: Union[KeyMap, SequenceMap], ev: KeyEvent) -> Optional[Union[KeyAction, SubSequenceMap]]:
    mods = ev.mods & 0b1111
    ans = keymap.get(SingleKey(mods, False, ev.key))
    if ans is None and ev.shifted_key and mods & 0b1:
        ans = keymap.get(SingleKey(mods & 0b1110, False, ev.shifted_key))
    if ans is None:
        ans = keymap.get(SingleKey(mods, True, ev.native_key))
    return ans


def shortcut_matches(s: SingleKey, ev: KeyEvent) -> bool:
    mods = ev.mods & 0b1111
    smods = s.mods & 0b1111
    if s.is_native:
        return s.key == ev.native_key and smods == mods
    if s.key == ev.key and mods == smods:
        return True
    if ev.shifted_key and mods & 0b1 and (mods & 0b1110) == smods and ev.shifted_key == s.key:
        return True
    return False
