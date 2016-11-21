#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import sys
from collections import namedtuple
from itertools import repeat

import glfw_constants as glfw

from .fast_data_types import CURSOR_BLOCK, CURSOR_BEAM, CURSOR_UNDERLINE

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

for name in 'foreground foreground_bold background cursor'.split():
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

    try:
        mods = frozenset(getattr(glfw, 'GLFW_MOD_' + map_mod(m.upper())) for m in parts[:-1])
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


default_config = '''
term xterm-kitty
# The foreground color
foreground       #dddddd
# The background color
background       #000000

# The high intensity foreground color
foreground_bold  #ffffff

# The cursor color
cursor           #ffffff

# The cursor opacity
cursor_opacity   0.7

# The cursor shape can be one of (block, beam, underline)
cursor_shape     block

# Whether to blink the cursor or not
cursor_blink     no

# Font family
font_family      monospace

# Font size (in pts)
font_size        11.0

# Number of lines of history to keep in memory for scrolling back
scrollback_lines 2000

# Delay (in milliseconds) between screen updates. Decreasing it, increases fps
# at the cost of more CPU usage. The default value yields ~50fps which is more
# that sufficient for most uses.
repaint_delay    20

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

# Key mapping
# For a list of key names, see: http://www.glfw.org/docs/latest/group__keys.html
# For a list of modifier names, see: http://www.glfw.org/docs/latest/group__mods.html
map ctrl+shift+v paste_from_clipboard
map ctrl+shift+s paste_from_selection
map ctrl+shift+c copy_to_clipboard
map ctrl+shift+up scroll_line_up
map ctrl+shift+down scroll_line_down
map ctrl+shift+page_up scroll_page_up
map Ctrl+Shift+page_down scroll_page_down
'''


defaults = parse_config(default_config.splitlines())


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
    ans = list(repeat(0, 120))
    fg = {30 + i: col(i) for i in range(8)}
    fg[39] = as_int(opts.foreground)
    fg.update({90 + i: col(i + 8) for i in range(8)})
    fg[99] = as_int(opts.foreground_bold)
    bg = {40 + i: col(i) for i in range(8)}
    bg[49] = as_int(opts.background)
    bg.update({100 + i: col(i + 8) for i in range(8)})
    for k, val in fg.items():
        ans[k] = val
    for k, val in bg.items():
        ans[k] = val
    return ans
