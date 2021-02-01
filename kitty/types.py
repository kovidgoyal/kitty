#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from typing import NamedTuple, Union


class ParsedShortcut(NamedTuple):
    mods: int
    key_name: str


class Edges(NamedTuple):
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


class FloatEdges(NamedTuple):
    left: float = 0
    top: float = 0
    right: float = 0
    bottom: float = 0


class ScreenGeometry(NamedTuple):
    xstart: float
    ystart: float
    xnum: int
    ynum: int
    dx: float
    dy: float


class WindowGeometry(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int
    xnum: int
    ynum: int
    spaces: Edges = Edges()


class SingleKey(NamedTuple):
    mods: int = 0
    is_native: bool = False
    key: int = -1


ConvertibleToNumbers = Union[str, bytes, int, float]
