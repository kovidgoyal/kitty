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
MINIMUM_FONT_SIZE = 4


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
            'Invalid cursor shape: {} allowed values are {}'.format(
                x, ', '.join(cshapes)
            )
        )


def to_bool(x):
    return x.lower() in 'y yes true'.split()


def parse_mods(parts):

    def map_mod(m):
        return {'CTRL': 'CONTROL', 'CMD': 'SUPER', 'OPTION': 'ALT'}.get(m, m)

    mods = 0
    for m in parts:
        try:
            mods |= getattr(defines, 'GLFW_MOD_' + map_mod(m.upper()))
        except AttributeError:
            safe_print(
                'Shortcut: {} has an unknown modifier, ignoring'.format(
                    parts.join('+')
                ),
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


KeyAction = namedtuple('KeyAction', 'func args')
shlex_actions = {'pass_selection_to_program', 'new_window', 'new_tab', 'new_os_window', 'new_window_with_cwd', 'new_tab_with_cwd', 'new_os_window_with_cwd'}


def parse_key_action(action):
    parts = action.split(' ', 1)
    func = parts[0]
    if len(parts) == 1:
        return KeyAction(func, ())
    rest = parts[1]
    if func == 'combine':
        sep, rest = rest.split(' ', 1)
        parts = re.split(r'\s*' + re.escape(sep) + r'\s*', rest)
        args = tuple(map(parse_key_action, filter(None, parts)))
    elif func == 'send_text':
        args = rest.split(' ', 1)
    elif func == 'goto_tab':
        args = (max(0, int(rest)),)
    elif func in shlex_actions:
        args = shlex.split(rest)
    return KeyAction(func, args)


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
    try:
        paction = parse_key_action(action)
    except Exception:
        safe_print(
            'Invalid shortcut action: {}. Ignoring.'.format(action),
            file=sys.stderr
        )
    else:
        if paction is not None:
            keymap[(mods, key)] = paction


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
        symbol_map[(a, b)] = family
    return symbol_map


def parse_send_text_bytes(text):
    return ast.literal_eval("'''" + text + "'''").encode('utf-8')


def parse_send_text(val, keymap):
    parts = val.split(' ')

    def abort(msg):
        safe_print(
            'Send text: {} is invalid ({}), ignoring'.format(val, msg),
            file=sys.stderr
        )
        return {}

    if len(parts) < 3:
        return abort('Incomplete')
    mode, sc = parts[:2]
    text = ' '.join(parts[2:])
    key_str = '{} send_text {} {}'.format(sc, mode, text)
    return parse_key(key_str, keymap)


def to_modifiers(val):
    return parse_mods(val.split('+'))


def to_layout_names(raw):
    parts = [x.strip().lower() for x in raw.split(',')]
    if '*' in parts:
        return sorted(all_layouts)
    for p in parts:
        if p not in all_layouts:
            raise ValueError('The window layout {} is unknown'.format(p))
    return parts


def positive_int(x):
    return max(0, int(x))


def positive_float(x):
    return max(0, float(x))


def unit_float(x):
    return max(0, min(float(x), 1))


def adjust_line_height(x):
    if x.endswith('%'):
        return float(x[:-1].strip()) / 100.0
    return int(x)


def box_drawing_scale(x):
    ans = tuple(float(x.strip()) for x in x.split(','))
    if len(ans) != 4:
        raise ValueError('Invalid box_drawing scale, must have four entries')
    return ans


def tab_separator(x):
    for q in '\'"':
        if x.startswith(q) and x.endswith(q):
            x = x[1:-1]
            break
    if not x.strip():
        x = ('\xa0' * len(x)) if x else defaults.tab_separator
    return x


def tab_font_style(x):
    return {'bold-italic': (True, True), 'bold': (True, False), 'italic': (False, True)}.get(x.lower().replace('_', '-'), (False, False))


def url_style(x):
    return url_style.map.get(x, url_style.map['curly'])


url_style.map = dict(((v, i) for i, v in enumerate('none single double curly'.split())))


type_map = {
    'allow_remote_control': to_bool,
    'adjust_line_height': adjust_line_height,
    'scrollback_lines': positive_int,
    'scrollback_pager': shlex.split,
    'scrollback_in_new_tab': to_bool,
    'font_size': to_font_size,
    'font_size_delta': positive_float,
    'focus_follows_mouse': to_bool,
    'cursor_shape': to_cursor_shape,
    'open_url_modifiers': to_modifiers,
    'rectangle_select_modifiers': to_modifiers,
    'repaint_delay': positive_int,
    'input_delay': positive_int,
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
    'macos_option_as_alt': to_bool,
    'box_drawing_scale': box_drawing_scale,
    'x11_bell_volume': int,
    'background_opacity': unit_float,
    'tab_separator': tab_separator,
    'active_tab_font_style': tab_font_style,
    'inactive_tab_font_style': tab_font_style,
    'inactive_text_alpha': unit_float,
    'url_style': url_style,
    'prefer_color_emoji': to_bool,
}

for name in (
    'foreground background cursor active_border_color inactive_border_color'
    ' selection_foreground selection_background url_color'
).split():
    type_map[name] = lambda x: to_color(x, validate=True)
for i in range(16):
    type_map['color%d' % i] = lambda x: to_color(x, validate=True)
for a in ('active', 'inactive'):
    for b in ('foreground', 'background'):
        type_map['%s_tab_%s' % (a, b)] = lambda x: to_color(x, validate=True)


def parse_config(lines, check_keys=True):
    ans = {
        'keymap': {},
        'symbol_map': {},
    }
    if check_keys:
        all_keys = defaults._asdict()
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
                # For legacy compatibility
                parse_send_text(val, ans['keymap'])
                continue
            if check_keys:
                if key not in all_keys:
                    safe_print(
                        'Ignoring unknown config key: {}'.format(key),
                        file=sys.stderr
                    )
                    continue
            tm = type_map.get(key)
            if tm is not None:
                val = tm(val)
            ans[key] = val
    return ans


with open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kitty.conf'), 'rb'
) as f:
    defaults = parse_config(f.read().decode('utf-8').splitlines(), check_keys=False)
Options = namedtuple('Defaults', ','.join(defaults.keys()))
defaults = Options(**defaults)
actions = frozenset(a.func for a in defaults.keymap.values()) | frozenset(
    'combine send_text goto_tab new_tab_with_cwd new_window_with_cwd new_os_window_with_cwd'.split()
)
no_op_actions = frozenset({'noop', 'no-op', 'no_op'})


def merge_keymaps(defaults, newvals):
    ans = defaults.copy()
    for k, v in newvals.items():
        f = v.func
        if f in no_op_actions:
            ans.pop(k, None)
            continue
        if f in actions:
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


def build_ansi_color_table(opts: Options = defaults):

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


def initial_window_size(opts):
    w, h = opts.initial_window_width, opts.initial_window_height
    if 'window-size' in cached_values and opts.remember_window_size:
        ws = cached_values['window-size']
        try:
            w, h = map(int, ws)
        except Exception:
            safe_print('Invalid cached window size, ignoring', file=sys.stderr)
    return w, h
