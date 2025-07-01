#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>


import sys

from kitty.conf.types import Definition

definition = Definition(
    '!kittens.choose_files',
)

agr = definition.add_group
egr = definition.end_group
opt = definition.add_option
map = definition.add_map
mma = definition.add_mouse_map

agr('Appearance')
opt('color_scheme', 'no-preference', choices=('no-preference', 'dark', 'light'), long_text='''\
The color scheme for your system. This sets the initial value of the color scheme. It can be changed subsequently
by using :code:`kitten desktop-ui color-scheme`.
''')
opt('accent_color', 'cyan', long_text='The RGB accent color for your system, can be specified as a color name or in hex a decimal format.')
opt('contrast', 'normal', choices=('normal', 'high'), long_text='The preferred contrast level.')
egr()


def main(args: list[str]) -> None:
    raise SystemExit('This must be run as kitten desktop-ui')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__conf__':
    sys.options_definition = definition  # type: ignore
