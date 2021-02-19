#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import importlib
import os
import sys

base = os.path.dirname(os.path.abspath(__file__))


def init_env() -> None:
    sys.path.insert(0, base)


def main() -> None:
    init_env()
    m = importlib.import_module('kitty_tests.main')
    m.run_tests()  # type: ignore


if __name__ == '__main__':
    main()
