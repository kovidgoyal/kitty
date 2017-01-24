#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
import os
import shlex
import json
import tempfile
from collections import namedtuple

from .fast_data_types import (
    CURSOR_BLOCK, CURSOR_BEAM, CURSOR_UNDERLINE
)
import kitty.fast_data_types as defines
from .utils import to_color, safe_print
from .layout import all_layouts
from .constants import config_dir

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')


def to_font_size(x):
    return max(6, float(x))


cshapes = {'block': CURSOR_BLOCK, 'beam': CURSOR_BEAM, 'underline': CURSOR_UNDERLINE}


def to_cursor_shape(x):
    try:
        return cshapes[x.lower()]
    except KeyError:
        raise ValueError('Invalid cursor shape: {} allowed values are {}'.format(x, ', '.join(cshapes)))


def to_bool(x):
    return x.lower() in 'y yes true'.split()


def to_opacity(x):
    return max(0.3, min(float(x), 1))


def parse_mods(parts):

    def map_mod(m):
        return {'CTRL': 'CONTROL', 'CMD': 'CONTROL'}.get(m, m)

    mods = 0
    for m in parts:
        try:
            mods |= getattr(defines, 'GLFW_MOD_' + map_mod(m.upper()))
        except AttributeError:
            safe_print('Shortcut: {} has an unknown modifier, ignoring'.format(parts.join('+')), file=sys.stderr)
            return

    return mods


named_keys = {"'": 'APOSTROPHE', ',': 'COMMA', '-': 'MINUS', '.': 'PERIOD',
              '/': 'SLASH', ';': 'SEMICOLON', '=': 'EQUAL', '[': 'LEFT_BRACKET',
              ']': 'RIGHT_BRACKET', '`': 'GRAVE_ACCENT'}


def parse_key(val, keymap):
    sc, action = val.partition(' ')[::2]
    action = action.strip()
    sc = sc.strip()
    if not sc or not action:
        return
    parts = sc.split('+')
    mods = parse_mods(parts[:-1])
    key = parts[-1].upper()
    key = getattr(defines, 'GLFW_KEY_' + named_keys.get(key, key), None)
    if key is None:
        safe_print('Shortcut: {} has an unknown key, ignoring'.format(val), file=sys.stderr)
        return
    keymap[(mods, key)] = action


def to_open_url_modifiers(val):
    return parse_mods(val.split('+'))


def to_layout_names(raw):
    parts = [x.strip().lower() for x in raw.split(',')]
    if '*' in parts:
        return sorted(all_layouts)
    for p in parts:
        if p not in all_layouts:
            raise ValueError('The window layout {} is unknown'.format(p))


type_map = {
    'scrollback_lines': int,
    'scrollback_pager': shlex.split,
    'scrollback_in_new_tab': to_bool,
    'font_size': to_font_size,
    'cursor_shape': to_cursor_shape,
    'cursor_opacity': to_opacity,
    'open_url_modifiers': to_open_url_modifiers,
    'repaint_delay': int,
    'window_border_width': float,
    'wheel_scroll_multiplier': float,
    'click_interval': float,
    'mouse_hide_wait': float,
    'cursor_blink_interval': float,
    'cursor_stop_blinking_after': float,
    'enabled_layouts': to_layout_names,
    'remember_window_size': to_bool,
    'initial_window_width': int,
    'initial_window_height': int,
    'use_system_wcwidth': to_bool,
}

for name in 'foreground background cursor active_border_color inactive_border_color selection_foreground selection_background'.split():
    type_map[name] = lambda x: to_color(x, validate=True)
for i in range(16):
    type_map['color%d' % i] = lambda x: to_color(x, validate=True)
for a in ('active', 'inactive'):
    for b in ('foreground', 'background'):
        type_map['%s_tab_%s' % (a, b)] = lambda x: to_color(x, validate=True)


def parse_config(lines):
    ans = {'keymap': {}}
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = key_pat.match(line)
        if m is not None:
            key, val = m.groups()
            if key == 'map':
                parse_key(val, ans['keymap'])
                continue
            tm = type_map.get(key)
            if tm is not None:
                val = tm(val)
            ans[key] = val
    return ans


with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kitty.conf')) as f:
    defaults = parse_config(f.readlines())
Options = namedtuple('Defaults', ','.join(defaults.keys()))
defaults = Options(**defaults)


def update_dict(a, b):
    a.update(b)
    return a


def merge_dicts(vals, defaults):
    return {k: update_dict(v, vals.get(k, {})) if isinstance(v, dict) else vals.get(k, v) for k, v in defaults.items()}


def load_config(path: str) -> Options:
    if not path:
        return defaults
    try:
        f = open(path)
    except FileNotFoundError:
        return defaults
    ans = defaults._asdict()
    actions = frozenset(defaults.keymap.values())
    with f:
        vals = parse_config(f)
    remove_keys = {k for k, v in vals.get('keymap', {}).items() if v in ('noop', 'no-op', 'no_op')}
    vals['keymap'] = {k: v for k, v in vals.get('keymap', {}).items() if v in actions}
    ans = merge_dicts(vals, ans)
    for k in remove_keys:
        ans['keymap'].pop(k, None)
    return Options(**ans)


def build_ansi_color_table(opts: Options=defaults):
    def as_int(x):
        return (x[0] << 16) | (x[1] << 8) | x[2]

    def col(i):
        return as_int(getattr(opts, 'color{}'.format(i)))
    return list(map(col, range(16)))


cached_values = {}
cached_path = os.path.join(config_dir, 'cached.json')


def load_cached_values():
    cached_values.clear()
    try:
        with open(cached_path, 'rb') as f:
            cached_values.update(json.loads(f.read().decode('utf-8')))
    except FileNotFoundError:
        pass
    except Exception as err:
        safe_print('Failed to load cached values with error: {}'.format(err), file=sys.stderr)


def save_cached_values():
    fd, p = tempfile.mkstemp(dir=os.path.dirname(cached_path), suffix='cached.json.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(json.dumps(cached_values).encode('utf-8'))
        os.rename(p, cached_path)
    except Exception as err:
        safe_print('Failed to save cached values with error: {}'.format(err), file=sys.stderr)
    finally:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except Exception as err:
            safe_print('Failed to delete temp file for saved cached values with error: {}'.format(err), file=sys.stderr)
