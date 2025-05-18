#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Callable, Iterable, Iterator
from gettext import gettext as _
from typing import TYPE_CHECKING, Any, Optional

from .constants import is_macos
from .fast_data_types import (
    GLFW_MOD_ALT,
    GLFW_MOD_CONTROL,
    GLFW_MOD_HYPER,
    GLFW_MOD_META,
    GLFW_MOD_SHIFT,
    GLFW_MOD_SUPER,
    KeyEvent,
    SingleKey,
    get_boss,
    get_options,
    grab_keyboard,
    is_modifier_key,
    ring_bell,
    set_ignore_os_keyboard_processing,
)
from .options.types import Options
from .options.utils import KeyboardMode, KeyDefinition, KeyMap
from .typing_compat import ScreenType

if TYPE_CHECKING:
    from .window import Window

mod_mask = GLFW_MOD_ALT | GLFW_MOD_CONTROL | GLFW_MOD_SHIFT | GLFW_MOD_SUPER | GLFW_MOD_META | GLFW_MOD_HYPER


def keyboard_mode_name(screen: ScreenType) -> str:
    flags = screen.current_key_encoding_flags()
    if flags:
        return 'kitty'
    return 'application' if screen.cursor_key_mode else 'normal'


def get_shortcut(keymap: KeyMap, ev: KeyEvent) -> list[KeyDefinition] | None:
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


class Mappings:

    ' Manage all keyboard mappings '

    def __init__(self, global_shortcuts:dict[str, SingleKey] | None = None, callback_on_mode_change: Callable[[], Any] = lambda: None) -> None:
        self.keyboard_mode_stack: list[KeyboardMode] = []
        self.update_keymap(global_shortcuts)
        self.callback_on_mode_change = callback_on_mode_change

    @property
    def current_keyboard_mode_name(self) -> str:
        return self.keyboard_mode_stack[-1].name if self.keyboard_mode_stack else ''

    def update_keymap(self, global_shortcuts: dict[str, SingleKey] | None = None) -> None:
        if global_shortcuts is None:
            global_shortcuts = self.set_cocoa_global_shortcuts(self.get_options()) if is_macos else {}
        self.global_shortcuts_map: KeyMap = {v: [KeyDefinition(definition=k)] for k, v in global_shortcuts.items()}
        self.global_shortcuts = global_shortcuts
        self.keyboard_modes = self.get_options().keyboard_modes.copy()
        km = self.keyboard_modes[''].keymap
        self.keyboard_modes[''].keymap = km = km.copy()
        for sc in self.global_shortcuts.values():
            km.pop(sc, None)

    def clear_keyboard_modes(self) -> None:
        had_mode = bool(self.keyboard_mode_stack)
        self.keyboard_mode_stack = []
        self.set_ignore_os_keyboard_processing(False)
        if had_mode:
            self.callback_on_mode_change()

    def pop_keyboard_mode(self) -> bool:
        passthrough = True
        if self.keyboard_mode_stack:
            self.keyboard_mode_stack.pop()
            if not self.keyboard_mode_stack:
                self.set_ignore_os_keyboard_processing(False)
            passthrough = False
            self.callback_on_mode_change()
        return passthrough

    def pop_keyboard_mode_if_is(self, name: str) -> bool:
        if self.keyboard_mode_stack and self.keyboard_mode_stack[-1].name == name:
            return self.pop_keyboard_mode()
        return False

    def _push_keyboard_mode(self, mode: KeyboardMode) -> None:
        self.keyboard_mode_stack.append(mode)
        self.set_ignore_os_keyboard_processing(True)
        self.callback_on_mode_change()

    def push_keyboard_mode(self, new_mode: str) -> None:
        mode = self.keyboard_modes[new_mode]
        self._push_keyboard_mode(mode)

    def matching_key_actions(self, candidates: Iterable[KeyDefinition]) -> list[KeyDefinition]:
        w = self.get_active_window()
        matches = []
        has_sequence_match = False
        for x in candidates:
            is_applicable = False
            if x.options.when_focus_on:
                try:
                    if w and w in self.match_windows(x.options.when_focus_on):
                        is_applicable = True
                except Exception:
                    self.clear_keyboard_modes()
                    self.show_error(_('Invalid key mapping'), _(
                        'The match expression {0} is not valid for {1}').format(x.options.when_focus_on, '--when-focus-on'))
                    return []
            else:
                is_applicable = True
            if is_applicable:
                matches.append(x)
                if x.is_sequence:
                    has_sequence_match = True
        if has_sequence_match:
            last_terminal_idx = -1
            for i, x in enumerate(matches):
                if not x.rest:
                    last_terminal_idx = i
            if last_terminal_idx > -1:
                if last_terminal_idx == len(matches) -1:
                    matches = matches[last_terminal_idx:]
                else:
                    matches = matches[last_terminal_idx+1:]
            q = matches[-1].options.when_focus_on
            matches = [x for x in matches if x.options.when_focus_on == q]
        elif matches:
            matches = [matches[-1]]
        return matches

    def dispatch_possible_special_key(self, ev: KeyEvent) -> bool:
        # Handles shortcuts, return True if the key was consumed
        is_root_mode = not self.keyboard_mode_stack
        mode = self.keyboard_modes[''] if is_root_mode else self.keyboard_mode_stack[-1]
        key_action = get_shortcut(mode.keymap, ev)
        if key_action is None and self.global_shortcuts_map and (global_key_action := get_shortcut(self.global_shortcuts_map, ev)) is not None:
            if grab_keyboard(None):
                # the shortcuts in the global menubar will have been bypassed so trigger them here
                key_action = global_key_action
            else:
                return True
        if key_action is None:
            if is_modifier_key(ev.key):
                return False
            if not is_root_mode:
                if mode.sequence_keys is not None:
                    self.pop_keyboard_mode()
                    w = self.get_active_window()
                    if w is not None:
                        w.send_key_sequence(*mode.sequence_keys)
                    return False
                if mode.on_unknown in ('beep', 'ignore'):
                    if mode.on_unknown == 'beep':
                        self.ring_bell()
                    return True
                if mode.on_unknown == 'passthrough':
                    return False
            if not self.pop_keyboard_mode():
                self.ring_bell()
                return True
        else:
            final_actions = self.matching_key_actions(key_action)
            if final_actions:
                mode_pos = len(self.keyboard_mode_stack) - 1
                if final_actions[0].is_sequence:
                    if mode.sequence_keys is None:
                        sm = KeyboardMode('__sequence__')
                        sm.on_action = 'end'
                        sm.sequence_keys = [ev]
                        for fa in final_actions:
                            sm.keymap[fa.rest[0]].append(fa.shift_sequence_and_copy())
                        self._push_keyboard_mode(sm)
                        self.debug_print('\n\x1b[35mKeyPress\x1b[m matched sequence prefix, ', end='')
                    else:
                        if len(final_actions) == 1 and not final_actions[0].rest:
                            self.pop_keyboard_mode()
                            consumed = self.combine(final_actions[0].definition)
                            if not consumed:
                                w = self.get_active_window()
                                if w is not None:
                                    w.send_key_sequence(*mode.sequence_keys)
                            return consumed
                        mode.sequence_keys.append(ev)
                        self.debug_print('\n\x1b[35mKeyPress\x1b[m matched sequence prefix, ', end='')
                        mode.keymap.clear()
                        for fa in final_actions:
                            mode.keymap[fa.rest[0]].append(fa.shift_sequence_and_copy())
                    return True
                final_action = final_actions[0]
                consumed = self.combine(final_action.definition)
                if consumed and not is_root_mode and mode.on_action == 'end':
                    if mode_pos < len(self.keyboard_mode_stack) and self.keyboard_mode_stack[mode_pos] is mode:
                        del self.keyboard_mode_stack[mode_pos]
                        self.callback_on_mode_change()
                        if not self.keyboard_mode_stack:
                            self.set_ignore_os_keyboard_processing(False)
                return consumed
        return False

    # System integration {{{
    def get_active_window(self) -> Optional['Window']:
        return get_boss().active_window

    def match_windows(self, expr: str) -> Iterator['Window']:
        return get_boss().match_windows(expr)

    def show_error(self, title: str, msg: str) -> None:
        return get_boss().show_error(title, msg)

    def ring_bell(self) -> None:
        if self.get_options().enable_audio_bell:
            ring_bell()

    def combine(self, action_definition: str) -> bool:
        return get_boss().combine(action_definition)

    def set_ignore_os_keyboard_processing(self, on: bool) -> None:
        set_ignore_os_keyboard_processing(on)

    def get_options(self) -> Options:
        return get_options()

    def debug_print(self, *args: Any, end: str = '\n') -> None:
        b = get_boss()
        if b.args.debug_keyboard:
            print(*args, end=end, flush=True)

    def set_cocoa_global_shortcuts(self, opts: Options) -> dict[str, SingleKey]:
        from .main import set_cocoa_global_shortcuts
        return set_cocoa_global_shortcuts(opts)
    # }}}
