#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

from enum import Enum


class BuildType(Enum):
    compile = 1
    link = 2
    generate = 3
