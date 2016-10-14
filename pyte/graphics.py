# -*- coding: utf-8 -*-
"""
    pyte.graphics
    ~~~~~~~~~~~~~

    This module defines graphic-related constants, mostly taken from
    :manpage:`console_codes(4)` and
    http://pueblo.sourceforge.net/doc/manual/ansi_color_codes.html.

    :copyright: (c) 2011-2012 by Selectel.
    :copyright: (c) 2012-2016 by pyte authors and contributors,
                    see AUTHORS for details.
    :license: LGPL, see LICENSE for more details.
"""

from __future__ import unicode_literals

#: A mapping of ANSI text style codes to style names, "+" means the:
#: attribute is set, "-" -- reset; example:
#:
#: >>> text[1]
#: '+bold'
#: >>> text[9]
#: '+strikethrough'
TEXT = {
    1: "+bold" ,
    3: "+italics",
    4: "+underscore",
    7: "+reverse",
    9: "+strikethrough",
    22: "-bold",
    23: "-italics",
    24: "-underscore",
    27: "-reverse",
    29: "-strikethrough",
}

#: A mapping of ANSI foreground color codes to color names.
#:
#: >>> FG_ANSI[30]
#: 'black'
#: >>> FG_ANSI[38]
#: 'default'
FG_ANSI = {
    30: "black",
    31: "red",
    32: "green",
    33: "brown",
    34: "blue",
    35: "magenta",
    36: "cyan",
    37: "white",
    39: "default"  # white.
}

#: An alias to :data:`~pyte.graphics.FG_ANSI` for compatibility.
FG = FG_ANSI

#: A mapping of non-standard ``aixterm`` foreground color codes to
#: color names. These are high intensity colors and thus should be
#: complemented by ``+bold``.
FG_AIXTERM = {
    90: "black",
    91: "red",
    92: "green",
    93: "brown",
    94: "blue",
    95: "magenta",
    96: "cyan",
    97: "white"
}

#: A mapping of ANSI background color codes to color names.
#:
#: >>> BG_ANSI[40]
#: 'black'
#: >>> BG_ANSI[48]
#: 'default'
BG_ANSI = {
    40: "black",
    41: "red",
    42: "green",
    43: "brown",
    44: "blue",
    45: "magenta",
    46: "cyan",
    47: "white",
    49: "default"  # black.
}

#: An alias to :data:`~pyte.graphics.BG_ANSI` for compatibility.
BG = BG_ANSI

#: A mapping of non-standard ``aixterm`` background color codes to
#: color names. These are high intensity colors and thus should be
#: complemented by ``+bold``.
BG_AIXTERM = {
    100: "black",
    101: "red",
    102: "green",
    103: "brown",
    104: "blue",
    105: "magenta",
    106: "cyan",
    107: "white"
}

#: SGR code for foreground in 256 or True color mode.
FG_256 = 38

#: SGR code for background in 256 or True color mode.
BG_256 = 48

#: A table of 256 foreground or background colors.
# The following code is part of the Pygments project (BSD licensed).
FG_BG_256 = [
    (0x00, 0x00, 0x00),  # 0
    (0xcd, 0x00, 0x00),  # 1
    (0x00, 0xcd, 0x00),  # 2
    (0xcd, 0xcd, 0x00),  # 3
    (0x00, 0x00, 0xee),  # 4
    (0xcd, 0x00, 0xcd),  # 5
    (0x00, 0xcd, 0xcd),  # 6
    (0xe5, 0xe5, 0xe5),  # 7
    (0x7f, 0x7f, 0x7f),  # 8
    (0xff, 0x00, 0x00),  # 9
    (0x00, 0xff, 0x00),  # 10
    (0xff, 0xff, 0x00),  # 11
    (0x5c, 0x5c, 0xff),  # 12
    (0xff, 0x00, 0xff),  # 13
    (0x00, 0xff, 0xff),  # 14
    (0xff, 0xff, 0xff),  # 15
]

# colors 16..232: the 6x6x6 color cube
valuerange = (0x00, 0x5f, 0x87, 0xaf, 0xd7, 0xff)

for i in range(217):
    r = valuerange[(i // 36) % 6]
    g = valuerange[(i // 6) % 6]
    b = valuerange[i % 6]
    FG_BG_256.append((r, g, b))

# colors 233..253: grayscale
for i in range(1, 22):
    v = 8 + i * 10
    FG_BG_256.append((v, v, v))

FG_BG_256 = ["{0:02x}{1:02x}{2:02x}".format(r, g, b) for r, g, b in FG_BG_256]
