#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>


import os
import sys


def main(args: list[str]=sys.argv) -> None:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.getcwd())
    if len(args) == 1:
        raise SystemExit('usage: python gen which')
    which = args[1]
    del args[1]
    if which == 'apc-parsers':
        from gen.apc_parsers import main
        main(args)
    elif which == 'config':
        from gen.config import main
        main(args)
    elif which == 'srgb-lut':
        from gen.srgb_lut import main
        main(args)
    elif which == 'key-constants':
        from gen.key_constants import main
        main(args)
    elif which == 'go-code':
        from gen.go_code import main
        main(args)
    elif which == 'wcwidth':
        from gen.wcwidth import main
        main(args)
    elif which == 'cursors':
        from gen.cursors import main
        main(args)
    else:
        raise SystemExit(f'Unknown which: {which}')


if __name__ == '__main__':
    main()
