#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shutil
import time
from collections import OrderedDict
from contextlib import suppress
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple

from kitty.constants import slangc


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


class Command(NamedTuple):
    needs_build: bool
    description: str
    cmd: list[str]


def commands_to_compile_dir_to_ir(sources: dict[str, SlangFile], src_dir: str, output_dirpath: str) -> Iterator[Command]:
    cmdbase = list(slangc)
    for name, sfile in sources.items():
        if sfile.should_compile_to_ir:
            parts = name.split('.')
            base_dest = os.path.join(output_dirpath, *parts)
            slang_module = f'{base_dest}.slang-module'
            deps_file = f'{base_dest}.deps'
            module_mtime = safe_mtime(slang_module)
            needs_build = module_mtime < get_newest_dep_time(deps_file)
            yield Command(needs_build, f'Compiling |{name}.slang| ...', cmdbase + [
                sfile.path, '-I', output_dirpath, '-I', src_dir, '-depfile', deps_file,
                '-target', 'none', '-o', slang_module
            ])


def commands_to_compile_to_glsl(sources: dict[str, SlangFile], build_dir: str, dest_dir: str, built_glsl_files: list[str]) -> Iterator[Command]:
    cmdbase = list(slangc)
    for name, sfile in sources.items():
        if not sfile.entry_points:
            continue
        parts = name.split('.')
        base_dest = os.path.join(dest_dir, *parts)
        slang_module = f'{base_dest}.slang-module'
        output_mtime = future()
        cmd = cmdbase + ['-I', dest_dir, slang_module]
        dest_files = []
        for ep in sfile.entry_points:
            dest = f'{base_dest}-{ep.stage.name}.glsl'
            cmd += ['-entry', ep.name, '-stage', ep.stage.name, '-target', 'glsl', '-profile', 'glsl_330', '-o', dest]
            dest_files.append(dest)
            output_mtime = min(output_mtime, safe_mtime(dest))
        module_mtime = os.path.getmtime(slang_module)
        needs_build = output_mtime < module_mtime
        if needs_build:
            built_glsl_files.extend(dest_files)
        yield Command(needs_build, f'Linking |{name}.slang-module| to GLSL ...', cmd)


def fixup_opengl_code(glsl_code: str) -> str:
    lines = []
    for line in glsl_code.splitlines():
        if line.startswith('#version '):
            line = '#version 330 core'
        elif line.startswith('#extension ') or line in ('layout(row_major) buffer;', 'layout(push_constant)'):
            line = '// ' + line
        lines.append(line)
    return '\n'.join(lines)


def fixup_opengl_files(*paths: str) -> None:
    ' Convert the GLSL output of slangc to something that will work with OpenGL 3.3 '
    for path in paths:
        with open(path, 'r+') as f:
            glsl_code = f.read()
            f.seek(0)
            f.truncate()
            f.write(fixup_opengl_code(glsl_code))


ParallelRun = Callable[[Iterable[tuple[bool, str, list[str]]]], None]


def copy_files_preserving_structure(source_dir: str, dest_dir: str, extension: str) -> None:
    '''
    Copies all files with a specific extension from a source directory
    to a destination directory while preserving the subdirectory structure.
    '''
    source = Path(source_dir)
    destination = Path(dest_dir)
    if not extension.startswith('.'):
        extension = f".{extension}"
    # Recursively find all matching files
    for file_path in source.rglob(f"*{extension}"):
        if file_path.is_file():
            # Calculate relative path to maintain folder hierarchy
            relative_path = file_path.relative_to(source)
            target_path = destination / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Copy file while preserving original metadata
            shutil.copy2(file_path, target_path)


def compile_builtin_shaders(build_dir: str, dest_dir: str, parallel_run: ParallelRun) -> None:
    src_dir = os.path.abspath('kitty/shaders')
    source_tree = get_ordered_sources_in_tree(src_dir)
    # First ensure all IR is generated
    parallel_run(commands_to_compile_dir_to_ir(source_tree, src_dir, build_dir))
    # Copy IR to dest_dir
    copy_files_preserving_structure(build_dir, dest_dir, '.slang-module')
    # Now glsl shaders
    built_glsl_files: list[str] = []
    glsl_commands = commands_to_compile_to_glsl(source_tree, build_dir, dest_dir, built_glsl_files)

    # Now run all commands
    parallel_run(glsl_commands)
    fixup_opengl_files(*built_glsl_files)
