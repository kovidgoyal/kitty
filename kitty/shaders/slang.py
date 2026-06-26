#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# This file is also run as a standalone module from setup.py to compile shaders
# so no top level kitty imports are allowed

import os
import re
import shutil
from enum import Enum
from functools import lru_cache
from typing import NamedTuple


class Stage(Enum):
    vertex = 'vertex'
    fragment = 'fragment'


class EntryPoint(NamedTuple):
    stage: Stage
    name: str


class SlangFile(NamedTuple):
    path: str
    text: str
    imports: frozenset[str]
    entry_points: frozenset[EntryPoint]
    module: str


def parse_slang_text(text: str, path: str = '') -> SlangFile:
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    entry_points, imports = [], set()
    module = ''
    found_entry_point = ''
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        words = line.split()
        if found_entry_point:
            if words[0].startswith('['):  # ]
                continue
            for q in words:
                if '(' in q:
                    name = q.partition('(')[0]  # ))
                    match found_entry_point:
                        case 'vertex':
                            entry_points.append(EntryPoint(Stage.vertex, name))
                        case 'fragment' | 'pixel':
                            entry_points.append(EntryPoint(Stage.fragment, name))
                    break
            found_entry_point = ''
        else:
            match words[0]:
                case 'module':
                    module = words[1].removesuffix(';')
                case 'import':
                    imports.add(words[1].removesuffix(';'))
                case _:
                    if words[0].startswith('[shader('):  # ])
                        text = words[0].partition('(')[2].partition(')')[0].strip()
                        found_entry_point = text[1:-1]
    return SlangFile(path, text, frozenset(imports), frozenset(entry_points), module)


@lru_cache(4096)
def parse_slang_file(path: str) -> SlangFile:
    with open(path) as f:
        text = f.read()
    return parse_slang_text(text, path)


def build_import_graph(dirpath: str) -> dict[str, SlangFile]:
    graph: dict[str, SlangFile] = {}
    for root, _, files in os.walk(os.path.abspath(dirpath)):
        for file in files:
            if file.endswith('.slang'):
                full_path = os.path.abspath(os.path.join(root, file))
                relpath = os.path.relpath(full_path, root)
                modname = os.path.splitext(relpath.replace(os.sep, '.'))[0]
                graph[modname] = parse_slang_file(full_path)
    return graph


def topological_sort(graph: dict[str, SlangFile]) -> list[str]:
    visited = set()
    order = []

    def visit(node: str) -> None:
        if node in visited or node not in graph:
            return
        for dep in graph[node].imports:
            visit(dep)
        visited.add(node)
        order.append(node)

    for node in graph:
        visit(node)
    return order


def get_ordered_sources_in_tree(dirpath: str) -> dict[str, SlangFile]:
    ans = build_import_graph(dirpath)
    topological_sort(ans)
    return ans



@lru_cache(2)
def slangc() -> tuple[str, ...]:
    try:
        from kitty.constants import slangc
    except ImportError:
        ans = shutil.which('slangc')
        if not ans:
            raise SystemExit('Could not find the slangc shader compiler on PATH')
        slangc = [ans]
    return tuple(slangc + ['-std', '2026'])
