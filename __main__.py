#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys

first_arg = '' if len(sys.argv) < 2 else sys.argv[1]


def icat(args):
    from kitty.icat import main
    main(args)


def list_fonts(args):
    from kitty.fonts.list import main
    main(args)


if first_arg in ('icat', '+icat'):
    icat(sys.argv[1:])
elif first_arg in ('list-fonts', '+list-fonts'):
    list_fonts(sys.argv[1:])
elif first_arg == '+' and len(sys.argv) > 2:
    q = sys.argv[2]
    if q == 'icat':
        icat(sys.argv[2:])
    elif q == 'list-fonts':
        list_fonts(sys.argv[2:])
else:
    from kitty.main import main
    main()
