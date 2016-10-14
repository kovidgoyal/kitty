#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import namedtuple

key_pat = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s+(.+)$')

defaults = {}

for line in '''
term xterm-termite
foreground       #dddddd
foreground_bold  #ffffff
cursor           #dddddd
background       #000000

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
        defaults[key] = val
Options = namedtuple('Defaults', ','.join(defaults.keys()))
defaults = Options(**defaults)


def load_config(path):
    if not path:
        return defaults
    ans = defaults._asdict()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = key_pat.match(line)
            if m is not None:
                key, val = m.groups()
                if key in ans:
                    ans[key] = val
    return Options(**ans)
