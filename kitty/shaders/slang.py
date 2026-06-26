#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# This file is also run as a standalone module from setup.py to compile shaders
# so no top level kitty imports are allowed

import os
import re
import shutil
import time
from collections import OrderedDict
from contextlib import suppress
from enum import Enum
from functools import lru_cache
from typing import Iterator, NamedTuple


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

    @property
    def should_compile_to_ir(self) -> bool:
        return bool(self.module or self.entry_points)


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


def get_ordered_sources_in_tree(dirpath: str) -> OrderedDict[str, SlangFile]:
    g = build_import_graph(dirpath)
    return OrderedDict({k: g[k] for k in topological_sort(g)})



@lru_cache(2)
def slangc() -> tuple[str, ...]:
    try:
        from kitty.constants import slangc
    except ImportError:
        ans = shutil.which('slangc')
        if not ans:
            raise SystemExit('Could not find the slangc shader compiler on PATH')
        slangc = [ans]
    return tuple(slangc)


def future() -> float:
    return time.time() + 1000000


def safe_mtime(path: str, defval: float = 0) -> float:
    with suppress(OSError):
        return os.path.getmtime(path)
    return defval if defval >= 0 else future()


def read_deps_file(path: str) -> Iterator[str]:
    with open(path) as f:
        for line in f:
            line = line.partition(':')[2].strip()
            yield from line.split()


def get_newest_dep_time(path: str) -> float:
    with suppress(OSError):
        ans = 0.
        for deppath in read_deps_file(path):
            mtime = os.path.getmtime(deppath)
            ans = max(mtime, ans)
        return ans
    return future()


def commands_to_compile_dir_to_ir(dirpath: str, output_dirpath: str) -> Iterator[tuple[bool, list[str]]]:
    cmdbase = list(slangc())
    for name, sfile in get_ordered_sources_in_tree(dirpath).items():
        if sfile.should_compile_to_ir:
            parts = name.split('.')
            base_dest = os.path.join(output_dirpath, *parts)
            slang_module = f'{base_dest}.slang-module'
            deps_file = f'{base_dest}.deps'
            module_mtime = safe_mtime(slang_module)
            needs_build = module_mtime < get_newest_dep_time(deps_file)
            yield needs_build, cmdbase + [
                sfile.path, '-I', output_dirpath, '-I', dirpath, '-depfile', deps_file,
                '-target', 'none', '-o', slang_module
            ]
