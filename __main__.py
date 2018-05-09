#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

import sys


def icat(args):
    from kittens.icat.main import main
    main(args)


def list_fonts(args):
    from kitty.fonts.list import main
    main(args)


def remote_control(args):
    from kitty.remote_control import main
    main(args)


def runpy(args):
    sys.argv = ['kitty'] + args[2:]
    exec(args[1])


def launch(args):
    import runpy
    sys.argv = args[1:]
    runpy.run_path(args[1], run_name='__main__')


def run_kitten(args):
    kitten = args[1]
    sys.argv = args[1:]
    from kittens.runner import run_kitten
    run_kitten(kitten)


def namespaced(args):
    func = namespaced_entry_points[args[1]]
    func(args[1:])


entry_points = {
    # These two are here for backwards compat
    'icat': icat,
    'list-fonts': list_fonts,
    'runpy': runpy,
    'launch': launch,
    'kitten': run_kitten,

    '@': remote_control,
    '+': namespaced,
}
namespaced_entry_points = {k: v for k, v in entry_points.items() if k[0] not in '+@'}


def main():
    first_arg = '' if len(sys.argv) < 2 else sys.argv[1]
    func = entry_points.get(first_arg)
    if func is None:
        if first_arg.startswith('@'):
            remote_control(['@', first_arg[1:]] + sys.argv[2:])
        elif first_arg.startswith('+'):
            namespaced(['+', first_arg[1:]] + sys.argv[2:])
        else:
            from kitty.main import main
            main()
    else:
        func(sys.argv[1:])


if __name__ == '__main__':
    main()
