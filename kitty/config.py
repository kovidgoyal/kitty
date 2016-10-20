#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import namedtuple
from typing import Tuple

from PyQt5.QtGui import QFont, QFontInfo, QColor

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')

defaults = {}


def to_qcolor(x):
    ans = QColor(x)
    if not ans.isValid():
        raise ValueError('{} is not a valid color'.format(x))
    return ans


def to_font_size(x):
    return max(6, float(x))

type_map = {
    'scrollback_lines': int,
    'font_size': to_font_size,
    'cursor_opacity': float,
}
for name in 'foreground foreground_bold background cursor'.split():
    type_map[name] = to_qcolor


for line in '''
term xterm-kitty
foreground       #dddddd
foreground_bold  #ffffff
cursor           #eeeeee
cursor_opacity   0.8
background       #000000
font_family      monospace
font_size        10.0
scrollback_lines 10000

# black
color0   #000000
color8   #4d4d4d

# red
color1   #cc0403
color9   #f2201f

# green
color2   #19cb00
color10  #23fd00

# yellow
color3   #cecb00
color11  #fffd00

# blue
color4   #001cd1
color12  #1389f0

# magenta
color5   #cb1ed1
color13  #fd28ff

# cyan
color6   #0dcdcd
color14  #14ffff

# white
color7   #dddddd
color15  #ffffff
'''.splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    m = key_pat.match(line)
    if m is not None:
        key, val = m.groups()
        tm = type_map.get(key)
        if tm is not None:
            val = tm(val)
        defaults[key] = val
Options = namedtuple('Defaults', ','.join(defaults.keys()))
defaults = Options(**defaults)


def load_config(path: str) -> Options:
    if not path:
        return defaults
    ans = defaults._asdict()
    try:
        f = open(path)
    except FileNotFoundError:
        return defaults
    with f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = key_pat.match(line)
            if m is not None:
                key, val = m.groups()
                if key in ans:
                    tm = type_map.get(key)
                    if tm is not None:
                        val = tm(val)
                    ans[key] = val
    return Options(**ans)


def validate_font(opts: Options):
    if not QFontInfo(QFont(opts.font_family)).fixedPitch():
        raise ValueError('The font specified in the configuration "{}" is not a monospace font'.format(opts.font_family))


def build_ansi_color_tables(opts: Options) -> Tuple[dict, dict]:
    def col(i):
        return QColor(getattr(opts, 'color{}'.format(i)))
    fg = {30 + i: col(i) for i in range(8)}
    fg[39] = opts.foreground
    fg.update({90 + i: col(i + 8) for i in range(8)})
    fg[99] = opts.foreground_bold
    bg = {40 + i: col(i) for i in range(8)}
    bg[49] = opts.background
    bg.update({100 + i: col(i + 8) for i in range(8)})
    build_ansi_color_tables.fg, build_ansi_color_tables.bg = fg, bg
build_ansi_color_tables(defaults)


def fg_color_table():
    return build_ansi_color_tables.fg


def bg_color_table():
    return build_ansi_color_tables.bg
