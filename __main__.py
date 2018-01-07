#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys


def icat(args):
    from kitty.icat import main
    main(args)


def list_fonts(args):
    from kitty.fonts.list import main
    main(args)


def remote_control(args):
    from kitty.remote_control import main
    main(args)


def namespaced(args):
    func = namespaced_entry_points[args[0]]
    func(args[1:])


entry_points = {
    'icat': icat,
    'list-fonts': list_fonts,
    '+icat': icat,
    '+list-fonts': list_fonts,
    '@': remote_control,
    '+': namespaced,
}
namespaced_entry_points = {k: v for k, v in entry_points.items() if k[0] not in '+@'}


def main():
    first_arg = '' if len(sys.argv) < 2 else sys.argv[1]
    func = entry_points.get(first_arg)
    if func is None:
        from kitty.main import main
        main()
    else:
        func(sys.argv[1:])


if __name__ == '__main__':
    main()
