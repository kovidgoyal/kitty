#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache
from typing import Callable, Iterator, Optional

from .constants import read_kitty_resource
from .fast_data_types import GLSL_VERSION, compile_program


def identity(x: str) -> str:
    return x


class Program:

    include_pat: Optional['re.Pattern[str]'] = None

    def __init__(self, name: str, vertex_name: str = '', fragment_name: str = '') -> None:
        self.name = name
        if Program.include_pat is None:
            Program.include_pat = re.compile(r'^#pragma\s+kitty_include_shader\s+<(.+?)>', re.MULTILINE)
        self.vertex_name = vertex_name or f'{name}_vertex.glsl'
        self.fragment_name = fragment_name or f'{name}_fragment.glsl'
        self.original_vertex_sources = tuple(self._load_sources(self.vertex_name))
        self.original_fragment_sources = tuple(self._load_sources(self.fragment_name))
        self.vertex_sources = self.original_vertex_sources
        self.fragment_sources = self.original_fragment_sources

    def _load_sources(self, name: str, level: int = 0) -> Iterator[str]:
        if level == 0:
            yield f'#version {GLSL_VERSION}\n'
        src = read_kitty_resource(name).decode('utf-8')
        pos = 0
        assert Program.include_pat is not None
        for m in Program.include_pat.finditer(src):
            prefix = src[pos:m.start()]
            if prefix:
                yield prefix
            iname = m.group(1)
            yield from self._load_sources(iname, level+1)
            pos = m.start()
        if pos < len(src):
            yield src[pos:]

    def apply_to_sources(self, vertex: Callable[[str], str] = identity, frag: Callable[[str], str] = identity) -> None:
        self.vertex_sources = self.original_vertex_sources if vertex is identity else tuple(map(vertex, self.original_vertex_sources))
        self.fragment_sources = self.original_fragment_sources if frag is identity else tuple(map(frag, self.original_fragment_sources))

    def compile(self, program_id: int, allow_recompile: bool = False) -> None:
        compile_program(program_id, self.vertex_sources, self.fragment_sources, allow_recompile)


@lru_cache(maxsize=64)
def program_for(name: str) -> Program:
    return Program(name)
