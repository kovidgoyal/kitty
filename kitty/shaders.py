#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>

import re
from typing import Iterator, Tuple

from .constants import read_kitty_resource
from .fast_data_types import GLSL_VERSION


def load_shaders(name: str, vertex_name: str = '', fragment_name: str = '') -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    pat = re.compile(r'^#pragma\s+kitty_include_shader\s+<(.+?)>', re.MULTILINE)

    def load_sources(name: str, level: int = 0) -> Iterator[str]:
        if level == 0:
            yield f'#version {GLSL_VERSION}\n'
        src = read_kitty_resource(name).decode('utf-8')
        pos = 0
        for m in pat.finditer(src):
            prefix = src[pos:m.start()]
            if prefix:
                yield prefix
            iname = m.group(1)
            yield from load_sources(iname, level+1)
            pos = m.start()
        if pos < len(src):
            yield src[pos:]

    def load(which: str, lname: str = '') -> Tuple[str, ...]:
        lname = lname or name
        main = f'{lname}_{which}.glsl'
        return tuple(load_sources(main))

    return load('vertex', vertex_name), load('fragment', fragment_name)
