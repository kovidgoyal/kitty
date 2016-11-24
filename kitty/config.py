#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
import os
from collections import namedtuple

import glfw_constants as glfw

from .fast_data_types import CURSOR_BLOCK, CURSOR_BEAM, CURSOR_UNDERLINE
from .utils import to_color

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


type_map = {
    'scrollback_lines': int,
    'font_size': to_font_size,
    'cursor_shape': to_cursor_shape,
    'cursor_blink': to_bool,
    'cursor_opacity': to_opacity,
    'repaint_delay': int,
}

for name in 'foreground background cursor'.split():
    type_map[name] = lambda x: to_color(x, validate=True)
for i in range(16):
    type_map['color%d' % i] = lambda x: to_color(x, validate=True)


def parse_key(val, keymap):
    sc, action = val.partition(' ')[::2]
    if not sc or not action:
        return
    parts = sc.split('+')

    def map_mod(m):
        return {'CTRL': 'CONTROL', 'CMD': 'CONTROL'}.get(m, m)

    mods = 0
    for m in parts[:-1]:
        try:
            mods |= getattr(glfw, 'GLFW_MOD_' + map_mod(m.upper()))
        except AttributeError:
            print('Shortcut: {} has an unknown modifier, ignoring'.format(val), file=sys.stderr)
            return

    key = getattr(glfw, 'GLFW_KEY_' + parts[-1].upper(), None)
    if key is None:
        print('Shortcut: {} has an unknown key, ignoring'.format(val), file=sys.stderr)
        return
    keymap[(mods, key)] = action


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
    vals['keymap'] = {k: v for k, v in vals.get('keymap', {}).items() if v in actions}
    ans = merge_dicts(vals, ans)
    return Options(**ans)


def build_ansi_color_table(opts: Options=defaults):
    def as_int(x):
        return (x[0] << 16) | (x[1] << 8) | x[2]

    def col(i):
        return as_int(getattr(opts, 'color{}'.format(i)))
    return list(map(col, range(16)))
