#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
from functools import partial
from pprint import pformat
from typing import Callable, Dict, Generator, Iterable, Set, Tuple

from .cli import version
from .conf.utils import KeyAction
from .constants import is_macos, is_wayland
from kittens.tui.operations import colored
from .options.types import Options as KittyOpts, defaults
from .options.utils import MouseMap
from .types import MouseEvent, SingleKey
from .typing import SequenceMap

ShortcutMap = Dict[Tuple[SingleKey, ...], KeyAction]


def green(x: str) -> str:
    return colored(x, 'green')


def title(x: str) -> str:
    return colored(x, 'blue', intense=True)


def mod_to_names(mods: int) -> Generator[str, None, None]:
    from .fast_data_types import (
        GLFW_MOD_ALT, GLFW_MOD_CAPS_LOCK, GLFW_MOD_CONTROL, GLFW_MOD_HYPER,
        GLFW_MOD_META, GLFW_MOD_NUM_LOCK, GLFW_MOD_SHIFT, GLFW_MOD_SUPER
    )
    modmap = {'shift': GLFW_MOD_SHIFT, 'alt': GLFW_MOD_ALT, 'ctrl': GLFW_MOD_CONTROL, ('cmd' if is_macos else 'super'): GLFW_MOD_SUPER,
              'hyper': GLFW_MOD_HYPER, 'meta': GLFW_MOD_META, 'num_lock': GLFW_MOD_NUM_LOCK, 'caps_lock': GLFW_MOD_CAPS_LOCK}
    for name, val in modmap.items():
        if mods & val:
            yield name


def print_shortcut(key_sequence: Iterable[SingleKey], action: KeyAction, print: Callable) -> None:
    from .fast_data_types import glfw_get_key_name
    keys = []
    for key_spec in key_sequence:
        names = []
        mods, is_native, key = key_spec
        names = list(mod_to_names(mods))
        if key:
            kname = glfw_get_key_name(0, key) if is_native else glfw_get_key_name(key, 0)
            names.append(kname or f'{key}')
        keys.append('+'.join(names))

    print('\t' + ' > '.join(keys), action)


def print_shortcut_changes(defns: ShortcutMap, text: str, changes: Set[Tuple[SingleKey, ...]], print: Callable) -> None:
    if changes:
        print(title(text))

        for k in sorted(changes):
            print_shortcut(k, defns[k], print)


def compare_keymaps(final: ShortcutMap, initial: ShortcutMap, print: Callable) -> None:
    added = set(final) - set(initial)
    removed = set(initial) - set(final)
    changed = {k for k in set(final) & set(initial) if final[k] != initial[k]}
    print_shortcut_changes(final, 'Added shortcuts:', added, print)
    print_shortcut_changes(initial, 'Removed shortcuts:', removed, print)
    print_shortcut_changes(final, 'Changed shortcuts:', changed, print)


def flatten_sequence_map(m: SequenceMap) -> ShortcutMap:
    ans: Dict[Tuple[SingleKey, ...], KeyAction] = {}
    for key_spec, rest_map in m.items():
        for r, action in rest_map.items():
            ans[(key_spec,) + (r)] = action
    return ans


def compare_mousemaps(final: MouseMap, initial: MouseMap, print: Callable) -> None:
    added = set(final) - set(initial)
    removed = set(initial) - set(final)
    changed = {k for k in set(final) & set(initial) if final[k] != initial[k]}

    def print_mouse_action(trigger: MouseEvent, action: KeyAction) -> None:
        names = list(mod_to_names(trigger.mods)) + [f'b{trigger.button+1}']
        when = {-1: 'repeat', 1: 'press', 2: 'doublepress', 3: 'triplepress'}.get(trigger.repeat_count, trigger.repeat_count)
        grabbed = 'grabbed' if trigger.grabbed else 'ungrabbed'
        print('\t', '+'.join(names), when, grabbed, action)

    def print_changes(defns: MouseMap, changes: Set[MouseEvent], text: str) -> None:
        if changes:
            print(title(text))
            for k in sorted(changes):
                print_mouse_action(k, defns[k])

    print_changes(final, added, 'Added mouse actions:')
    print_changes(initial, removed, 'Removed mouse actions:')
    print_changes(final, changed, 'Changed mouse actions:')


def compare_opts(opts: KittyOpts, print: Callable) -> None:
    from .config import load_config
    print()
    print('Config options different from defaults:')
    default_opts = load_config()
    ignored = ('keymap', 'sequence_map', 'mousemap', 'map', 'mouse_map')
    changed_opts = [
        f for f in sorted(defaults._fields)
        if f not in ignored and getattr(opts, f) != getattr(defaults, f)
    ]
    field_len = max(map(len, changed_opts)) if changed_opts else 20
    fmt = '{{:{:d}s}}'.format(field_len)
    for f in changed_opts:
        val = getattr(opts, f)
        if isinstance(val, dict):
            print(f'{title(f)}:')
            if f == 'symbol_map':
                for k in sorted(val):
                    print(f'\tU+{k[0]:04x} - U+{k[1]:04x} → {val[k]}')
            else:
                print(pformat(val))
        else:
            print(title(fmt.format(f)), str(getattr(opts, f)))

    compare_mousemaps(opts.mousemap, default_opts.mousemap, print)
    final_, initial_ = opts.keymap, default_opts.keymap
    final: ShortcutMap = {(k,): v for k, v in final_.items()}
    initial: ShortcutMap = {(k,): v for k, v in initial_.items()}
    final_s, initial_s = map(flatten_sequence_map, (opts.sequence_map, default_opts.sequence_map))
    final.update(final_s)
    initial.update(initial_s)
    compare_keymaps(final, initial, print)


def debug_config(opts: KittyOpts) -> str:
    from io import StringIO
    out = StringIO()
    p = partial(print, file=out)
    p(version(add_rev=True))
    p(' '.join(os.uname()))
    if is_macos:
        import subprocess
        p(' '.join(subprocess.check_output(['sw_vers']).decode('utf-8').splitlines()).strip())
    if os.path.exists('/etc/issue'):
        with open('/etc/issue', encoding='utf-8', errors='replace') as f:
            p(f.read().strip())
    if os.path.exists('/etc/lsb-release'):
        with open('/etc/lsb-release', encoding='utf-8', errors='replace') as f:
            p(f.read().strip())
    if not is_macos:
        p('Running under:' + green('Wayland' if is_wayland() else 'X11'))
    if opts.config_paths:
        p(green('Loaded config files:'))
        p(' ', '\n  '.join(opts.config_paths))
    if opts.config_overrides:
        p(green('Loaded config overrides:'))
        p(' ', '\n  '.join(opts.config_overrides))
    compare_opts(opts, p)
    return out.getvalue()
