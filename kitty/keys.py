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
    if ans is None:
        ans = keymap.get(SingleKey(mods, True, ev.native_key))
    return ans


def shortcut_matches(s: SingleKey, ev: KeyEvent) -> bool:
    mods = ev.mods & 0b1111
    q = ev.native_key if s.is_native else ev.key
    return bool(s.mods & 0b1111 == mods & 0b1111 and s.key == q)
