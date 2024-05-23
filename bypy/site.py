#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import _sitebuiltins
import builtins
import sys


def set_quit() -> None:
    eof = 'Ctrl-D (i.e. EOF)'
    builtins.quit = _sitebuiltins.Quitter('quit', eof)
    builtins.exit = _sitebuiltins.Quitter('exit', eof)


def set_helper() -> None:
    builtins.help = _sitebuiltins._Helper()


def main() -> None:
    sys.argv[0] = sys.calibre_basename
    set_helper()
    set_quit()
    mod = __import__(sys.calibre_module, fromlist=[1])
    func = getattr(mod, sys.calibre_function)
    return func()


if __name__ == '__main__':
    main()
