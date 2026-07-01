#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import re
import runpy
import shutil
import sys
import time
from collections import OrderedDict
from contextlib import suppress
from enum import Enum
from functools import lru_cache
from itertools import chain
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, NamedTuple

from kitty.constants import read_kitty_resource, shaders_dir, slangc
from kitty.fast_data_types import (
    BLINK,
    COLOR_IS_INDEX,
    COLOR_IS_RGB,
    COLOR_IS_SPECIAL,
    COLOR_NOT_SET,
    DECORATION,
    DECORATION_MASK,
    DIM,
    MARK,
    MARK_MASK,
    REVERSE,
    STRIKETHROUGH,
    get_options,
)
from kitty.options.types import defaults


@lru_cache(maxsize=64)
def get_shader_src(name: str) -> str:
    return read_kitty_resource(f'{name}.slang', 'kitty.shaders').decode()


class Stage(Enum):
    vertex = 'vertex'
    fragment = 'fragment'


class EntryPoint(NamedTuple):
    stage: Stage
    name: str


class Specialization(NamedTuple):
    name: str
    variables: MappingProxyType[str, str]

    @property
    def filename_insert(self) -> str:
        return f'.{self.name}' if self.name else '.default-specialization'


class SlangFile(NamedTuple):
    path: str = ''
    text: str = ''
    imports: frozenset[str] = frozenset()
    entry_points: frozenset[EntryPoint] = frozenset()
    module: str = ''
    specializable_variables: MappingProxyType[str, str] = MappingProxyType({})
    disable_warnings: frozenset[str] = frozenset()

    @property
    def should_compile_to_ir(self) -> bool:
        return bool(self.module or self.entry_points)

    @property
    def defines(self) -> MappingProxyType[str, str]:
        ans = {}
        match os.path.basename(self.path):
            case 'cell.slang':
                ans['MARK_MASK'] = str(MARK_MASK)
                ans['REVERSE_SHIFT'] = str(REVERSE)
                ans['STRIKE_SHIFT'] = str(STRIKETHROUGH)
                ans['DIM_SHIFT'] = str(DIM)
                ans['BLINK_SHIFT'] = str(BLINK)
                ans['DECORATION_SHIFT'] = str(DECORATION)
                ans['MARK_SHIFT'] = str(MARK)
                ans['DECORATION_MASK'] = str(DECORATION_MASK)
                ans['COLOR_NOT_SET'] = str(COLOR_NOT_SET)
                ans['COLOR_IS_SPECIAL'] = str(COLOR_IS_SPECIAL)
                ans['COLOR_IS_INDEX'] = str(COLOR_IS_INDEX)
                ans['COLOR_IS_RGB'] = str(COLOR_IS_RGB)
        return MappingProxyType(ans)

    @property
    def specializations(self) -> Iterator[Specialization]:
        def s(name: str = '', **kwargs: str) -> Specialization:
            return Specialization(name, MappingProxyType(kwargs))

        match os.path.basename(self.path):
            case 'graphics.slang':
                yield s()
                yield s('alpha_mask', is_alpha_mask='true')
                yield s('premult', texture_is_not_premultiplied='true')
            case 'cell.slang':
                opts = defaults
                with suppress(RuntimeError):
                    opts = get_options() or defaults
                text_fg_override_threshold: float = opts.text_fg_override_threshold[0]
                match opts.text_fg_override_threshold[1]:
                    case '%':
                        text_fg_override_threshold = max(0, min(text_fg_override_threshold, 100.0)) * 0.01
                        algo = '1'
                    case 'ratio':
                        text_fg_override_threshold = max(0, min(text_fg_override_threshold, 21.0))
                        algo = '2'
                base = {k:str(v) for k, v in dict(
                    DO_FG_OVERRIDE='true' if text_fg_override_threshold else 'false',
                    FG_OVERRIDE_ALGO=algo,
                    FG_OVERRIDE_THRESHOLD=text_fg_override_threshold,
                    TEXT_NEW_GAMMA='false' if opts.text_composition_strategy == 'legacy' else 'true',
                    ONLY_FOREGROUND='false',
                    ONLY_BACKGROUND='false',
                ).items()}
                yield s('', **base)
                base['ONLY_FOREGROUND'] = 'true'
                yield s('fg', **base)
                base['ONLY_FOREGROUND'] = 'false'
                base['ONLY_BACKGROUND'] = 'true'
                yield s('bg', **base)
            case _:
                yield s()


def parse_slang_text(text: str, path: str = '') -> SlangFile:
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    entry_points, imports = [], set()
    module = ''
    found_entry_point = ''
    specializable_variables = {}
    disable_warnings = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('//'):
            if line.startswith('// warnings-disable: '):
                words = line.split()
                for word in words[2:]:
                    for w in word.split(','):
                        disable_warnings.append(w)
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
                case 'extern':
                    if len(words) > 3 and words[1:3] == ['static', 'const']:
                        specializable_variables[line.partition('=')[0].split()[-1].rstrip(';')] = line
                case _:
                    if words[0].startswith('[shader('):  # ])
                        text = words[0].partition('(')[2].partition(')')[0].strip()
                        found_entry_point = text[1:-1]
    return SlangFile(
            path, text, frozenset(imports), frozenset(entry_points), module,
            MappingProxyType(specializable_variables), frozenset(disable_warnings))


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
    cmdbase = list(slangc) + ['-warnings-as-errors', 'all']
    for name, sfile in sources.items():
        if sfile.should_compile_to_ir:
            parts = name.split('.')
            base_dest = os.path.join(output_dirpath, *parts)
            slang_module = f'{base_dest}.slang-module'
            deps_file = f'{base_dest}.deps'
            module_mtime = safe_mtime(slang_module)
            needs_build = module_mtime < get_newest_dep_time(deps_file)
            defines = [f'-D{k}={v}' for k, v in sfile.defines.items()]
            yield Command(needs_build, f'Compiling |{name}.slang| ...', cmdbase + defines + [
                '-I', output_dirpath, '-I', src_dir, '-depfile', deps_file,
                '-target', 'none', '-o', slang_module, '--', sfile.path,
            ])


def iter_entry_point_shaders(sources: dict[str, SlangFile], build_dir: str, dest_dir: str) -> Iterator[tuple[str, str, list[str], SlangFile]]:
    cmdbase = list(slangc) + ['-warnings-as-errors', 'all']
    for name, sfile in sources.items():
        if not sfile.entry_points:
            continue
        parts = name.split('.')
        base_dest = os.path.join(dest_dir, *parts)
        slang_module = f'{base_dest}.slang-module'
        cmd = list(cmdbase)
        if sfile.disable_warnings:
            cmd += ['-warnings-disable', ','.join(sfile.disable_warnings)]
        cmd += ['-I', dest_dir, slang_module]
        yield base_dest, slang_module, cmd, sfile


def commands_to_compile_to_spirv(sources: dict[str, SlangFile], build_dir: str, dest_dir: str, built_files: list[str]) -> Iterator[Command]:
    # glsl 450 is vulkan 1.1 and spirv 1.3 released 2008
    base_cmd = ['-target', 'spirv', '-profile', 'glsl_450', '-capability', 'vk_mem_model', '-fvk-use-entrypoint-name']
    for base_dest, slang_module, scmd, sfile in iter_entry_point_shaders(sources, build_dir, dest_dir):
        for x in sfile.specializations:
            cmd = list(scmd)
            dest = f'{base_dest}.{x.name}.spv' if x.name else f'{base_dest}.spv'
            if x.variables:
                cmd.insert(-1, f'{base_dest}{x.filename_insert}.slang-module')
            cmd += base_cmd + ['-o', dest, '-reflection-json', dest + '.json']
            output_mtime = safe_mtime(dest)
            module_mtime = os.path.getmtime(slang_module)
            needs_build = output_mtime < module_mtime
            if needs_build:
                built_files.append(dest)
            yield Command(needs_build, f'Linking |{os.path.basename(dest)}| ...', cmd)


def commands_to_compile_to_glsl(sources: dict[str, SlangFile], build_dir: str, dest_dir: str, built_glsl_files: list[str]) -> Iterator[Command]:
    for base_dest, slang_module, cmd, sfile in iter_entry_point_shaders(sources, build_dir, dest_dir):
        module_mtime = os.path.getmtime(slang_module)
        extra_cmd = ['-line-directive-mode', 'none', '-target', 'glsl', '-profile', 'glsl_330']
        for ep in sfile.entry_points:
            for sp in sfile.specializations:
                v = {Stage.vertex: 'vert', Stage.fragment: 'frag'}[ep.stage]
                dest = f'{base_dest}.{v}.glsl'
                c = list(cmd)
                if sp.name:
                    dest = f'{base_dest}{sp.filename_insert}.{v}.glsl'
                    c.insert(-1, f'{base_dest}.{sp.name}.slang-module')
                c += extra_cmd + ['-entry', ep.name, '-stage', ep.stage.name, '-o', dest]
                output_mtime = safe_mtime(dest)
                needs_build = output_mtime < module_mtime
                if needs_build:
                    built_glsl_files.append(dest)
                yield Command(needs_build, f'Linking |{os.path.basename(slang_module)}| to GLSL {ep.stage.value} shader ...', c)


def fixup_opengl_code(glsl_code: str) -> tuple[str, dict[str, Any]]:
    lines = []
    in_uniform_block = False
    in_uniform_block_contents = False
    uniform_block_is_struct = False
    current_uniform_struct_members: dict[str, str] = {}
    uniform_blocks = {}
    current_uniform_names: list[str] = []
    uniform_names: dict[str, str] = {}
    uniform_structs = {}

    def add_uniform_name(name: str, uniform_names: dict[str, str] = uniform_names) -> str:
        name = name.rstrip(';')
        uniform_name = name.rpartition('_')[0]
        if uniform_name in uniform_names:
            raise KeyError(f'The uniform name {uniform_name} is used with multiple suffixes')
        uniform_names[uniform_name] = name
        return name

    for line in glsl_code.splitlines():
        if in_uniform_block:
            if in_uniform_block_contents:
                if line.startswith('}'):
                    in_uniform_block = in_uniform_block_contents = False
                    block_name = line.lstrip('}').rstrip(';').strip()
                    if uniform_block_is_struct:
                        uniform_structs[block_name.rpartition('_')[0]] = {
                            'name': block_name, 'members': current_uniform_struct_members}
                    else:
                        uniform_blocks[block_name] = current_uniform_names
                        line = '// ' + line
                    current_uniform_names = []
                else:
                    if uniform_block_is_struct:
                        current_uniform_names.append(add_uniform_name(line.split()[-1], current_uniform_struct_members))
                    else:
                        line = line.strip()
                        current_uniform_names.append(add_uniform_name(line.split()[-1]))
                        line = 'uniform ' + line
            elif line.startswith('{'):  # }}
                if not uniform_block_is_struct:
                    line = '// ' + line
                in_uniform_block_contents = True
                current_uniform_names = []
        else:
            if line.startswith('#version '):
                line = '#version 330 core'
            elif line.startswith('#extension ') or line in ('layout(row_major) buffer;', 'layout(push_constant)'):
                line = '// ' + line
            elif line.startswith('layout(location =') or line.startswith('layout(binding ='):
                line = '// ' + line
            elif line.startswith('flat layout(location ='):
                line = 'flat'
            elif line:  # ))))
                words = line.split()
                if 'uniform' in words and line.startswith('layout('):  # )
                    in_uniform_block = True
                    in_uniform_block_contents = False
                    uniform_block_is_struct = line.startswith('layout(std140')  # )
                    if uniform_block_is_struct:
                        current_uniform_struct_members = {}
                    else:
                        line = '// ' + line
                elif '] = {' in line:  # }] this is https://github.com/shader-slang/slang/issues/11802
                    typename = words[0]
                    if words[0] == 'const':
                        typename = words[1]
                    line = line.replace('{', f'{typename}[](', 1)  # }])
                    line = line.removesuffix('};') + ');'
                elif words[0] == 'uniform' and len(words) > 2 and words[1].startswith('sampler'):
                    add_uniform_name(words[2])
        lines.append(line)
    ans = '\n'.join(lines)
    for block_name, names in uniform_blocks.items():
        for u in names:
            u = u.partition('[')[0]
            ans = ans.replace(f'{block_name}.{u}', u)
    ans = ans.replace('gl_VertexIndex', 'gl_VertexID')
    ans = ans.replace('gl_BaseVertex', '0')
    return ans, {'loose_uniforms': uniform_names, 'uniform_structs': uniform_structs}


def fixup_opengl_files(*paths: str) -> None:
    ' Convert the GLSL output of slangc to something that will work with OpenGL 3.3 '
    for path in paths:
        with open(path, 'r+') as f:
            glsl_code = f.read()
            f.seek(0)
            f.truncate()
            fixed, uniform_names = fixup_opengl_code(glsl_code)
            f.write(fixed)
        with open(path + '.json', 'w') as f:
            f.write(json.dumps(uniform_names))


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


def create_specialisations(sources: dict[str, SlangFile], build_dir: str, dest_dir: str) -> Iterator[Command]:
    for base_dest, slang_module, cmd, sfile in iter_entry_point_shaders(sources, build_dir, dest_dir):
        if sfile.entry_points and sfile.specializations:
            for sp in sfile.specializations:
                dest = f'{base_dest}{sp.filename_insert}.slang'
                payload = existing = ''
                if sp.variables:
                    lines = []
                    for key, val in sp.variables.items():
                        declaration = sfile.specializable_variables[key].rpartition('=')[0]
                        if not declaration:
                            declaration = sfile.specializable_variables[key].rstrip(';')
                        declaration = declaration.replace('extern ', 'export ', 1)
                        lines.append(f'{declaration} = {val};')
                    payload = '\n'.join(lines)
                with suppress(FileNotFoundError), open(dest) as f:
                    existing = f.read()
                if needs_build := payload != existing:
                    if payload:
                        with open(dest, 'w') as fw:
                            fw.write(payload)
                    else:
                        os.remove(dest)
                yield Command(needs_build, f'Compiling specialisation |{os.path.basename(dest)}| ...',
                              list(slangc) + [dest, '-o', dest + '-module'])


def compile_builtin_shaders(build_dir: str, dest_dir: str, parallel_run: ParallelRun) -> None:
    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(dest_dir, exist_ok=True)
    src_dir = os.path.abspath('kitty/shaders')
    source_tree = get_ordered_sources_in_tree(src_dir)
    # First ensure all IR is generated
    parallel_run(commands_to_compile_dir_to_ir(source_tree, src_dir, build_dir))
    # Copy IR to dest_dir
    copy_files_preserving_structure(build_dir, dest_dir, '.slang-module')
    # Create the specializations
    parallel_run(create_specialisations(source_tree, build_dir, dest_dir))
    # Now Vulkan shaders
    built_spirv_files: list[str] = []
    spirv_commands = commands_to_compile_to_spirv(source_tree, build_dir, dest_dir, built_spirv_files)
    # Now glsl files
    built_glsl_files: list[str] = []
    glsl_commands = commands_to_compile_to_glsl(source_tree, build_dir, dest_dir, built_glsl_files)
    # Now run all commands
    parallel_run(chain(spirv_commands, glsl_commands))
    fixup_opengl_files(*built_glsl_files)
    if shutil.which('glslangValidator'):
        from kitty.shaders.validate_shaders import validation_command_for_file
        parallel_run((True, f'Validating |{os.path.basename(x)}| ...', validation_command_for_file(x)) for x in built_glsl_files)


def main() -> None:
    if not shutil.which(slangc[0]):
        raise SystemExit(f'The shader slang compiler ({slangc[0]}) not in PATH: {os.environ.get("PATH")}')
    setup = runpy.run_path('setup.py')
    Command = setup['Command']
    parallel_run = setup['parallel_run']
    emphasis = setup['emphasis']
    def prun(cmds: Iterable[tuple[bool, str, list[str]]]) -> None:
        needed = []
        for (needs_build, desc, cmd) in cmds:
            if needs_build:
                desc = re.sub(r'\|(.+?)\|', lambda m: emphasis(m.group(1)), desc)
                needed.append(Command(desc, cmd, lambda: True))
        parallel_run(needed)
    compile_builtin_shaders(sys.argv[-2], sys.argv[-1], prun)


def test_slang_build() -> None:
    import subprocess
    if shutil.which(slangc[0]) is None:
        raise AssertionError(f'The shader slang compiler ({slangc[0]}) not in PATH: {os.environ.get("PATH")}')
    q = os.path.join(shaders_dir, 'graphics.spv')
    if not os.path.isfile(q):
        raise AssertionError(f'The compiled graphics shader {q} does not exist')
    if not get_shader_src('graphics'):
        raise AssertionError('Could not load graphics.slang shader source')
    src = b'''
#language slang 2026
[shader("vertex")]
float4 main(uint vertex_id : SV_VertexID) : SV_Position { return float4(vertex_id, 1, 0, 1); }
'''
    cp = subprocess.run(slangc + '-lang slang -entry main -stage vertex -target glsl -o /dev/stdout -- -'.split(),
                        input=src, capture_output=True)
    if cp.returncode != 0:
        raise AssertionError(f'Test compile of shader to GLSL failed with returncode: {cp.returncode} and stderr: {cp.stderr.decode()}')


if __name__ == '__main__':
    main()
