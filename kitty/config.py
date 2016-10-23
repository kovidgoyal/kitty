#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import namedtuple
from typing import Tuple

from .fonts import validate_monospace_font


key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')
# Color definitions  {{{
color_pat = re.compile(r'^#([a-fA-F0-9]{3}|[a-fA-F0-9]{6})$')
color_names = {
    'aliceblue': 'f0f8ff',
    'antiquewhite': 'faebd7',
    'aqua': '00ffff',
    'aquamarine': '7fffd4',
    'azure': 'f0ffff',
    'beige': 'f5f5dc',
    'bisque': 'ffe4c4',
    'black': '000000',
    'blanchedalmond': 'ffebcd',
    'blue': '0000ff',
    'blueviolet': '8a2be2',
    'brown': 'a52a2a',
    'burlywood': 'deb887',
    'cadetblue': '5f9ea0',
    'chartreuse': '7fff00',
    'chocolate': 'd2691e',
    'coral': 'ff7f50',
    'cornflowerblue': '6495ed',
    'cornsilk': 'fff8dc',
    'crimson': 'dc143c',
    'cyan': '00ffff',
    'darkblue': '00008b',
    'darkcyan': '008b8b',
    'darkgoldenrod': 'b8860b',
    'darkgray': 'a9a9a9',
    'darkgrey': 'a9a9a9',
    'darkgreen': '006400',
    'darkkhaki': 'bdb76b',
    'darkmagenta': '8b008b',
    'darkolivegreen': '556b2f',
    'darkorange': 'ff8c00',
    'darkorchid': '9932cc',
    'darkred': '8b0000',
    'darksalmon': 'e9967a',
    'darkseagreen': '8fbc8f',
    'darkslateblue': '483d8b',
    'darkslategray': '2f4f4f',
    'darkslategrey': '2f4f4f',
    'darkturquoise': '00ced1',
    'darkviolet': '9400d3',
    'deeppink': 'ff1493',
    'deepskyblue': '00bfff',
    'dimgray': '696969',
    'dimgrey': '696969',
    'dodgerblue': '1e90ff',
    'firebrick': 'b22222',
    'floralwhite': 'fffaf0',
    'forestgreen': '228b22',
    'fuchsia': 'ff00ff',
    'gainsboro': 'dcdcdc',
    'ghostwhite': 'f8f8ff',
    'gold': 'ffd700',
    'goldenrod': 'daa520',
    'gray': '808080',
    'grey': '808080',
    'green': '008000',
    'greenyellow': 'adff2f',
    'honeydew': 'f0fff0',
    'hotpink': 'ff69b4',
    'indianred': 'cd5c5c',
    'indigo': '4b0082',
    'ivory': 'fffff0',
    'khaki': 'f0e68c',
    'lavender': 'e6e6fa',
    'lavenderblush': 'fff0f5',
    'lawngreen': '7cfc00',
    'lemonchiffon': 'fffacd',
    'lightblue': 'add8e6',
    'lightcoral': 'f08080',
    'lightcyan': 'e0ffff',
    'lightgoldenrodyellow': 'fafad2',
    'lightgray': 'd3d3d3',
    'lightgrey': 'd3d3d3',
    'lightgreen': '90ee90',
    'lightpink': 'ffb6c1',
    'lightsalmon': 'ffa07a',
    'lightseagreen': '20b2aa',
    'lightskyblue': '87cefa',
    'lightslategray': '778899',
    'lightslategrey': '778899',
    'lightsteelblue': 'b0c4de',
    'lightyellow': 'ffffe0',
    'lime': '00ff00',
    'limegreen': '32cd32',
    'linen': 'faf0e6',
    'magenta': 'ff00ff',
    'maroon': '800000',
    'mediumaquamarine': '66cdaa',
    'mediumblue': '0000cd',
    'mediumorchid': 'ba55d3',
    'mediumpurple': '9370db',
    'mediumseagreen': '3cb371',
    'mediumslateblue': '7b68ee',
    'mediumspringgreen': '00fa9a',
    'mediumturquoise': '48d1cc',
    'mediumvioletred': 'c71585',
    'midnightblue': '191970',
    'mintcream': 'f5fffa',
    'mistyrose': 'ffe4e1',
    'moccasin': 'ffe4b5',
    'navajowhite': 'ffdead',
    'navy': '000080',
    'oldlace': 'fdf5e6',
    'olive': '808000',
    'olivedrab': '6b8e23',
    'orange': 'ffa500',
    'orangered': 'ff4500',
    'orchid': 'da70d6',
    'palegoldenrod': 'eee8aa',
    'palegreen': '98fb98',
    'paleturquoise': 'afeeee',
    'palevioletred': 'db7093',
    'papayawhip': 'ffefd5',
    'peachpuff': 'ffdab9',
    'per': 'cd853f',
    'pink': 'ffc0cb',
    'plum': 'dda0dd',
    'powderblue': 'b0e0e6',
    'purple': '800080',
    'red': 'ff0000',
    'rosybrown': 'bc8f8f',
    'royalblue': '4169e1',
    'saddlebrown': '8b4513',
    'salmon': 'fa8072',
    'sandybrown': 'f4a460',
    'seagreen': '2e8b57',
    'seashell': 'fff5ee',
    'sienna': 'a0522d',
    'silver': 'c0c0c0',
    'skyblue': '87ceeb',
    'slateblue': '6a5acd',
    'slategray': '708090',
    'slategrey': '708090',
    'snow': 'fffafa',
    'springgreen': '00ff7f',
    'steelblue': '4682b4',
    'tan': 'd2b48c',
    'teal': '008080',
    'thistle': 'd8bfd8',
    'tomato': 'ff6347',
    'turquoise': '40e0d0',
    'violet': 'ee82ee',
    'wheat': 'f5deb3',
    'white': 'ffffff',
    'whitesmoke': 'f5f5f5',
    'yellow': 'ffff00',
    'yellowgreen': '9acd32',
}
Color = namedtuple('Color', 'red green blue')
# }}}

defaults = {}


def to_color(raw, validate=False):
    x = raw.strip().lower()
    m = color_pat.match(x)
    val = None
    if m is not None:
        val = m.group(1)
        if len(val) == 3:
            val = ''.join(2 * s for s in val)
    else:
        val = color_names.get(x)
    if val is None:
        if validate:
            raise ValueError('Invalid color name: {}'.format(raw))
        return
    return Color(int(val[:2], 16), int(val[2:4], 16), int(val[4:], 16))


def to_font_size(x):
    return max(6, float(x))


def to_cursor_shape(x):
    shapes = 'block underline beam'
    x = x.lower()
    if x not in shapes.split():
        raise ValueError('Invalid cursor shape: {} allowed values are {}'.format(x, shapes))
    return x


def to_bool(x):
    return x.lower() in 'y yes true'.split()


type_map = {
    'scrollback_lines': int,
    'font_size': to_font_size,
    'cursor_opacity': float,
    'cursor_shape': to_cursor_shape,
    'cursor_blink': to_bool,
    'font_family': validate_monospace_font,
}

for name in 'foreground foreground_bold background cursor'.split():
    type_map[name] = lambda x: to_color(x, validate=True)
for i in range(16):
    type_map['color%d' % i] = lambda x: to_color(x, validate=True)


for line in '''
term xterm-kitty
foreground       #dddddd
foreground_bold  #ffffff
cursor           #eeeeee
cursor_shape     block
cursor_blink     no
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
color4  #0d73cc
color12 #1a8fff

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


def build_ansi_color_tables(opts: Options) -> Tuple[dict, dict]:
    def col(i):
        return getattr(opts, 'color{}'.format(i))
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
