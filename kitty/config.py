#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import ast
import json
import os
import re
import shlex
import sys
import tempfile
from collections import namedtuple

from . import fast_data_types as defines
from .constants import config_dir
from .fast_data_types import CURSOR_BEAM, CURSOR_BLOCK, CURSOR_UNDERLINE
from .layout import all_layouts
from .rgb import to_color
from .utils import safe_print

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')
MINIMUM_FONT_SIZE = 6


def to_font_size(x):
    return max(MINIMUM_FONT_SIZE, float(x))


cshapes = {
    'block': CURSOR_BLOCK,
    'beam': CURSOR_BEAM,
    'underline': CURSOR_UNDERLINE
}


def to_cursor_shape(x):
    try:
        return cshapes[x.lower()]
    except KeyError:
        raise ValueError(
            'Invalid cursor shape: {} allowed values are {}'.
            format(x, ', '.join(cshapes))
        )


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
            safe_print(
                'Shortcut: {} has an unknown modifier, ignoring'.
                format(parts.join('+')),
                file=sys.stderr
            )
            return

    return mods


named_keys = {
    "'": 'APOSTROPHE',
    ',': 'COMMA',
    '-': 'MINUS',
    '.': 'PERIOD',
    '/': 'SLASH',
    ';': 'SEMICOLON',
    '=': 'EQUAL',
    '[': 'LEFT_BRACKET',
    ']': 'RIGHT_BRACKET',
    '`': 'GRAVE_ACCENT'
}


def parse_shortcut(sc):
    parts = sc.split('+')
    mods = parse_mods(parts[:-1])
    key = parts[-1].upper()
    key = getattr(defines, 'GLFW_KEY_' + named_keys.get(key, key), None)
    if key is not None:
        return mods, key
    return None, None


def parse_key(val, keymap):
    sc, action = val.partition(' ')[::2]
    sc, action = sc.strip(), action.strip()
    if not sc or not action:
        return
    mods, key = parse_shortcut(sc)
    if key is None:
        safe_print(
            'Shortcut: {} has an unknown key, ignoring'.format(val),
            file=sys.stderr
        )
        return
    keymap[(mods, key)] = action


def parse_symbol_map(val):
    parts = val.split(' ')
    symbol_map = {}

    def abort():
        safe_print(
            'Symbol map: {} is invalid, ignoring'.format(val), file=sys.stderr
        )
        return {}

    if len(parts) < 2:
        return abort()
    family = ' '.join(parts[1:])

    def to_chr(x):
        if not x.startswith('U+'):
            raise ValueError()
        x = int(x[2:], 16)
        return x

    for x in parts[0].split(','):
        a, b = x.partition('-')[::2]
        b = b or a
        try:
            a, b = map(to_chr, (a, b))
        except Exception:
            return abort()
        if b < a or max(a, b) > sys.maxunicode or min(a, b) < 1:
            return abort()
        for y in range(a, b + 1):
            symbol_map[chr(y)] = family
    return symbol_map


def parse_send_text(val):
    parts = val.split(' ')

    def abort(msg):
        safe_print(
            'Send text: {} is invalid ({}), ignoring'.format(val, msg), file=sys.stderr
        )
        return {}

    if len(parts) < 3:
        return abort('Incomplete')

    text = ' '.join(parts[2:])
    mode, sc = parts[:2]
    mods, key = parse_shortcut(sc.strip())
    if key is None:
        return abort('Invalid shortcut')
    text = ast.literal_eval("'''" + text + "'''").encode('utf-8')
    if not text:
        return abort('Empty text')

    if mode in ('all', '*'):
        modes = parse_send_text.all_modes
    else:
        modes = frozenset(mode.split(',')).intersection(parse_send_text.all_modes)
        if not modes:
            return abort('Invalid keyboard modes')
    return {mode: {(mods, key): text} for mode in modes}


parse_send_text.all_modes = frozenset({'normal', 'application', 'kitty'})


def to_open_url_modifiers(val):
    return parse_mods(val.split('+'))


def to_layout_names(raw):
    parts = [x.strip().lower() for x in raw.split(',')]
    if '*' in parts:
        return sorted(all_layouts)
    for p in parts:
        if p not in all_layouts:
            raise ValueError('The window layout {} is unknown'.format(p))


def positive_int(x):
    return max(0, int(x))


def positive_float(x):
    return max(0, float(x))


type_map = {
    'scrollback_lines': positive_int,
    'scrollback_pager': shlex.split,
    'scrollback_in_new_tab': to_bool,
    'font_size': to_font_size,
    'font_size_delta': positive_float,
    'cursor_shape': to_cursor_shape,
    'cursor_opacity': to_opacity,
    'open_url_modifiers': to_open_url_modifiers,
    'repaint_delay': positive_int,
    'window_border_width': positive_float,
    'window_margin_width': positive_float,
    'window_padding_width': positive_float,
    'wheel_scroll_multiplier': float,
    'visual_bell_duration': positive_float,
    'enable_audio_bell': to_bool,
    'click_interval': positive_float,
    'mouse_hide_wait': positive_float,
    'cursor_blink_interval': positive_float,
    'cursor_stop_blinking_after': positive_float,
    'enabled_layouts': to_layout_names,
    'remember_window_size': to_bool,
    'initial_window_width': positive_int,
    'initial_window_height': positive_int,
    'use_system_wcwidth': to_bool,
    'macos_hide_titlebar': to_bool,
}

for name in (
    'foreground background cursor active_border_color inactive_border_color'
    ' selection_foreground selection_background'
).split():
    type_map[name] = lambda x: to_color(x, validate=True)
for i in range(16):
    type_map['color%d' % i] = lambda x: to_color(x, validate=True)
for a in ('active', 'inactive'):
    for b in ('foreground', 'background'):
        type_map['%s_tab_%s' % (a, b)] = lambda x: to_color(x, validate=True)


def parse_config(lines):
    ans = {'keymap': {}, 'symbol_map': {}, 'send_text_map': {'kitty': {}, 'normal': {}, 'application': {}}}
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
            if key == 'symbol_map':
                ans['symbol_map'].update(parse_symbol_map(val))
                continue
            if key == 'send_text':
                stvals = parse_send_text(val)
                for k, v in ans['send_text_map'].items():
                    v.update(stvals.get(k, {}))
                continue
            tm = type_map.get(key)
            if tm is not None:
                val = tm(val)
            ans[key] = val
    return ans


with open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kitty.conf')
) as f:
    defaults = parse_config(f.readlines())
Options = namedtuple('Defaults', ','.join(defaults.keys()))
defaults = Options(**defaults)
actions = frozenset(defaults.keymap.values())


def merge_keymaps(defaults, newvals):
    ans = defaults.copy()
    for k, v in newvals.items():
        if v in {'noop', 'no-op', 'no_op'}:
            ans.pop(k, None)
            continue
        if v in actions:
            ans[k] = v
    return ans


def merge_dicts(defaults, newvals):
    ans = defaults.copy()
    ans.update(newvals)
    return ans


def merge_configs(defaults, vals):
    ans = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            newvals = vals.get(k, {})
            if k == 'keymap':
                ans['keymap'] = merge_keymaps(v, newvals)
            elif k == 'send_text_map':
                ans[k] = {m: merge_dicts(mm, newvals.get(m, {})) for m, mm in v.items()}
            else:
                ans[k] = merge_dicts(v, newvals)
        else:
            ans[k] = vals.get(k, v)
    return ans


def load_config(*paths, overrides=None) -> Options:
    ans = defaults._asdict()
    for path in paths:
        if not path:
            continue
        try:
            f = open(path)
        except FileNotFoundError:
            continue
        with f:
            vals = parse_config(f)
            ans = merge_configs(ans, vals)
    if overrides is not None:
        vals = parse_config(overrides)
        ans = merge_configs(ans, vals)
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
        safe_print(
            'Failed to load cached values with error: {}'.format(err),
            file=sys.stderr
        )


def save_cached_values():
    fd, p = tempfile.mkstemp(
        dir=os.path.dirname(cached_path), suffix='cached.json.tmp'
    )
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(json.dumps(cached_values).encode('utf-8'))
        os.rename(p, cached_path)
    except Exception as err:
        safe_print(
            'Failed to save cached values with error: {}'.format(err),
            file=sys.stderr
        )
    finally:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except Exception as err:
            safe_print(
                'Failed to delete temp file for saved cached values with error: {}'.
                format(err),
                file=sys.stderr
            )
