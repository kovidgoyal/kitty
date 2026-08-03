#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import glob
import hashlib
import json
import os
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import zlib
from collections import OrderedDict
from contextlib import suppress
from enum import StrEnum, auto
from functools import lru_cache, partial
from itertools import chain, product
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Literal, NamedTuple, TypedDict, TypeGuard, get_args

from kitty.constants import read_kitty_resource, shaders_dir, slangc
from kitty.fast_data_types import (
    BGIMAGE_PROGRAM,
    BLINK,
    BLIT_PROGRAM,
    BORDERS_PROGRAM,
    CELL_BG_PROGRAM,
    CELL_FG_PROGRAM,
    CELL_PROGRAM,
    COLOR_IS_INDEX,
    COLOR_IS_RGB,
    COLOR_IS_SPECIAL,
    COLOR_NOT_SET,
    CUSTOM_END_PROGRAM,
    DECORATION,
    DECORATION_MASK,
    DIM,
    GLSL_VERSION,
    GRAPHICS_ALPHA_MASK_PROGRAM,
    GRAPHICS_PREMULT_PROGRAM,
    GRAPHICS_PROGRAM,
    MARK,
    MARK_MASK,
    PADDING_PROGRAM,
    REVERSE,
    ROUNDED_RECT_PROGRAM,
    SCREENSHOT_PROGRAM,
    STRIKETHROUGH,
    TINT_PROGRAM,
    TRAIL_PROGRAM,
    compile_program,
    get_options,
)
from kitty.options.types import Options, defaults
from kitty.types import run_once
from kitty.utils import lock_with_file, log_error, resolve_custom_file


@lru_cache(maxsize=64)
def get_shader_src(name: str) -> str:
    return read_kitty_resource(f'{name}.slang', 'kitty.shaders').decode()


@lru_cache(maxsize=64)
def get_custom_shader_src(name: str) -> bytes:
    return read_kitty_resource(f'{name}.slang', 'kitty.shaders.custom')


@lru_cache(maxsize=32)
def get_custom_pipeline_src(name: str) -> bytes:
    return read_kitty_resource(f'{name}.pipeline', 'kitty.shaders.custom')


@run_once
def slangc_version() -> str:
    return subprocess.check_output(list(slangc()) + ['-version'], stderr=subprocess.STDOUT).decode().strip()


def is_dir_ok(path: str, checks: dict[str, str]) -> bool:
    for fname, expected in checks.items():
        try:
            with open(os.path.join(path, fname)) as f:
                if f.read().strip() != expected:
                    return False
        except OSError:
            return False
    return True


def ensure_cache_dir(path: str) -> None:
    "Ensure the cache dir is for the current slangc version and slang.py version"
    os.makedirs(path, exist_ok=True)
    # slang IR is version dependent and the compiler often crashes when loading .slang-module from another version
    checks = {'slangc.version': slangc_version(), 'slangpy.version': get_hash_for_self()}
    if not is_dir_ok(path, checks):
        shutil.rmtree(path)
        os.makedirs(path)
        for fname, expected in checks.items():
            with open(os.path.join(path, fname), 'w') as f:
                f.write(expected)


class Stage(StrEnum):
    vertex = 'vertex'
    fragment = 'fragment'


class EntryPoint(NamedTuple):
    stage: Stage
    name: str

    def asdict(self) -> dict[str, str]:
        return {'stage': str(self.stage), 'name': self.name}

    @classmethod
    def fromdict(self, s: dict[str, str]) -> 'EntryPoint':
        return EntryPoint(Stage(s['stage']), s['name'])


class Specialization(NamedTuple):
    name: str
    variables: MappingProxyType[str, str]

    @property
    def filename_insert(self) -> str:
        return f'.{self.name}' if self.name else '.default-specialization'


def cell_variant(opts: Options = defaults, program: int = CELL_PROGRAM) -> dict[str, str]:
    text_fg_override_threshold: float = opts.text_fg_override_threshold[0]
    algo = '0'
    match opts.text_fg_override_threshold[1]:
        case '%':
            text_fg_override_threshold = max(0, min(text_fg_override_threshold, 100.0)) * 0.01
            algo = '1'
        case 'ratio':
            text_fg_override_threshold = max(0, min(text_fg_override_threshold, 21.0))
            algo = '2'
    if not text_fg_override_threshold:
        algo = '0'
    render_mode = (CELL_PROGRAM, CELL_BG_PROGRAM, CELL_FG_PROGRAM).index(program)
    return {
        'FG_OVERRIDE_ALGO': algo,
        'TEXT_NEW_GAMMA': 'false' if opts.text_composition_strategy == 'legacy' else 'true',
        'RENDER_MODE': str(render_mode),
    }


@lru_cache(maxsize=2)
def cell_variations() -> tuple[MappingProxyType[str, str], ...]:
    variations = {'FG_OVERRIDE_ALGO': ('0', '1', '2'), 'RENDER_MODE': ('0', '1', '2')}
    bool_variations = 'false', 'true'
    variants_dict = {k: variations.get(k, bool_variations) for k in cell_variant()}
    return tuple(MappingProxyType(dict(zip(variants_dict.keys(), comb))) for comb in product(*variants_dict.values()))


def variant_name(variant: dict[str, str], default: dict[str, str]) -> str:
    if variant == default:
        return ''
    data = ' '.join(f'{k}={variant[k]}' for k in sorted(default)).encode()
    key = hashlib.md5(data, usedforsecurity=False)
    return key.hexdigest()[:5]


def glsl_shaders(name: str, variant_name: str = '') -> tuple[str, str]:
    if variant_name:
        variant_name = '.' + variant_name
    with open(os.path.join(shaders_dir, f'{name}{variant_name}.vert.glsl')) as f:
        vert = f.read()
    with open(os.path.join(shaders_dir, f'{name}{variant_name}.frag.glsl')) as f:
        frag = f.read()
    return vert, frag


class LoadShaderPrograms:
    text_fg_override_threshold: tuple[float, Literal['%', 'ratio']] = 0, '%'
    text_old_gamma: bool = False
    custom_shaders: tuple[str, ...] = ()

    opts: Options | None = None

    def get_options(self) -> Options:
        try:
            return self.opts or get_options()
        except RuntimeError:
            return defaults

    @property
    def needs_recompile(self) -> bool:
        opts = self.get_options()
        return (
            bool(opts.text_fg_override_threshold[0]) != bool(self.text_fg_override_threshold[0])
            or opts.text_fg_override_threshold[1] != self.text_fg_override_threshold[1]
            or (opts.text_composition_strategy == 'legacy') != self.text_old_gamma
        )

    def recompile_if_needed(self) -> None:
        if self.needs_recompile:
            self(allow_recompile=True)
        else:
            opts = self.get_options()
            if opts.custom_shaders != self.custom_shaders:
                self.compile_custom_shaders(allow_recompile=True)

    def __call__(self, allow_recompile: bool = False) -> None:
        default_cell_variant = cell_variant()
        opts = self.get_options()
        self.text_old_gamma = opts.text_composition_strategy == 'legacy'
        self.text_fg_override_threshold = opts.text_fg_override_threshold
        metadata = load_glsl_metadata()

        def cell(prog: int) -> None:
            v = cell_variant(opts, program=prog)
            vert, frag = glsl_shaders('cell', variant_name(v, default_cell_variant))
            compile_program(prog, (vert,), (frag,), metadata['cell'], allow_recompile)

        cell(CELL_PROGRAM), cell(CELL_BG_PROGRAM), cell(CELL_FG_PROGRAM)
        for prog, vname in {
            GRAPHICS_PROGRAM: '',
            GRAPHICS_ALPHA_MASK_PROGRAM: 'alpha_mask',
            GRAPHICS_PREMULT_PROGRAM: 'premult',
        }.items():
            vert, frag = glsl_shaders('graphics', vname)
            compile_program(prog, (vert,), (frag,), metadata['graphics'], allow_recompile)
        for name, prog in {
            'bgimage': BGIMAGE_PROGRAM,
            'tint': TINT_PROGRAM,
            'trail': TRAIL_PROGRAM,
            'blit': BLIT_PROGRAM,
            'screenshot': SCREENSHOT_PROGRAM,
            'rounded_rect': ROUNDED_RECT_PROGRAM,
            'border': BORDERS_PROGRAM,
            'padding': PADDING_PROGRAM,
        }.items():
            vert, frag = glsl_shaders(name)
            compile_program(prog, (vert,), (frag,), metadata[name], allow_recompile)
        compile_program(-1, (), (), {})  # initialize programs
        self.compile_custom_shaders(allow_recompile)

    def compile_custom_shaders(self, allow_recompile: bool = False) -> None:
        opts = self.get_options()
        self.custom_shaders = tuple(opts.custom_shaders)
        pmap = {}
        for k in self.custom_shaders:
            try:
                d = parse_pipeline(k)
            except Exception as e:
                log_error(f'Failed to read custom shader pipeline definition from {k} with error: {e}')
                continue
            pmap[d['slot']] = d

        def do(prog: int, slot: str) -> None:
            pipeline = pmap.get(slot)
            if pipeline is None:
                compile_program(prog, (), (), {}, allow_recompile)
            else:
                try:
                    vert, frag, metadata = build_custom_shader_pipeline_glsl(pipeline)
                except Exception as e:
                    log_error(f'Failed to build custom shader for slot {slot} with error: {e}')
                    compile_program(prog, (), (), {}, allow_recompile)
                else:
                    try:
                        compile_program(prog, (vert,), (frag,), metadata, allow_recompile)
                    except Exception as e:
                        log_error(f'Failed to load custom shader for slot {slot} with error: {e}')
                        compile_program(prog, (), (), {}, allow_recompile)

        do(CUSTOM_END_PROGRAM, 'end')
        compile_program(-2, (), (), {})  # initialize programs


load_shader_programs = LoadShaderPrograms()


class SlangFile(NamedTuple):
    path: str = ''
    text: str = ''
    imports: frozenset[str] = frozenset()
    entry_points: frozenset[EntryPoint] = frozenset()
    module: str = ''
    specializable_variables: MappingProxyType[str, str] = MappingProxyType({})
    disable_warnings: frozenset[str] = frozenset()

    def asdict(self, skip_source: bool = False) -> dict[str, Any]:
        "Return a dict useable for serialization to JSON"
        ans = self._asdict()
        ans['imports'] = tuple(ans['imports'])
        ans['entry_points'] = tuple(ep.asdict() for ep in ans['entry_points'])
        ans['specializable_variables'] = dict(ans['specializable_variables'])
        ans['disable_warnings'] = tuple(ans['disable_warnings'])
        if skip_source:
            ans['text'] = ''
            ans['path'] = os.path.basename(ans['path'])
        return ans

    @classmethod
    def fromdict(cls, s: dict[str, Any]) -> 'SlangFile':
        return SlangFile(
            s['path'],
            s['text'],
            frozenset(s['imports']),
            frozenset(EntryPoint.fromdict(x) for x in s['entry_points']),
            s['module'],
            MappingProxyType(s['specializable_variables']),
            frozenset(s['disable_warnings']),
        )

    @property
    def should_compile_to_ir(self) -> bool:
        return bool(self.module or self.entry_points)

    @property
    def defines(self) -> MappingProxyType[str, str]:
        ans = {}
        match os.path.basename(self.path):
            case 'background.slang' | 'cell.slang':
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
                yield s('premult', texture_is_not_premultiplied='false')
            case 'cell.slang':
                d = cell_variant()
                seen = set()
                for variant in cell_variations():
                    name = variant_name(dict(variant), d)
                    if name in seen:
                        raise Exception('Variant names for cell shader not unique')
                    seen.add(name)
                    yield s(name, **variant)
            case _:
                yield s()


def parse_slang_text(src_code: str, path: str = '') -> SlangFile:
    text = re.sub(r'/\*[\s\S]*?\*/', '', src_code)
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
        path, src_code, frozenset(imports), frozenset(entry_points), module, MappingProxyType(specializable_variables), frozenset(disable_warnings)
    )


@lru_cache(4096)
def parse_slang_file(path: str) -> SlangFile:
    with open(path) as f:
        text = f.read()
    return parse_slang_text(text, path)


def build_import_graph(dirpath: str) -> dict[str, SlangFile]:
    graph: dict[str, SlangFile] = {}
    exclude = os.path.abspath(os.path.join(dirpath, 'custom'))
    for root, _, files in os.walk(os.path.abspath(dirpath)):
        if root == exclude:
            continue
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


def topological_layers(graph: dict[str, SlangFile]) -> list[list[str]]:
    layer_of: dict[str, int] = {}

    def compute_layer(node: str) -> int:
        if node in layer_of:
            return layer_of[node]
        if node not in graph:
            return -1
        layer = max((compute_layer(dep) + 1 for dep in graph[node].imports), default=0)
        layer_of[node] = layer
        return layer

    for node in graph:
        compute_layer(node)

    if not layer_of:
        return []
    max_layer = max(layer_of.values())
    layers: list[list[str]] = [[] for _ in range(max_layer + 1)]
    for node, layer in layer_of.items():
        layers[layer].append(node)
    return layers


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
        ans = 0.0
        for deppath in read_deps_file(path):
            mtime = os.path.getmtime(deppath)
            ans = max(mtime, ans)
        return ans
    return future()


def sanitize_code_object(code_obj: types.CodeType) -> types.CodeType:
    """
    Recursively strips environmental metadata (like file paths and first line numbers)
    from a code object so the hash remains identical across different machines.
    """
    # Recursively process nested constants (inner functions/classes)
    new_consts = []
    for const in code_obj.co_consts:
        if isinstance(const, types.CodeType):
            new_consts.append(sanitize_code_object(const))
        else:
            new_consts.append(const)

    # Rebuild the code object with sanitized file names and line numbers
    # (Using replace() is safe and fully compatible with Python 3.8+)
    return code_obj.replace(
        co_filename='slang.py',  # Forces a uniform mock filename
        co_firstlineno=1,  # Standardizes the line number offsets
        co_consts=tuple(new_consts),
    )


@run_once
def get_hash_for_self() -> str:
    """
    Climbs to the module scope, sanitizes it, and returns a unique
    SHA-256 hash representing the entire executable structure.
    """
    import hashlib
    import importlib.util
    import marshal
    from importlib.abc import InspectLoader

    if __name__ == '__main__':
        with open(__file__, 'rb') as f:
            serialized_bytes = f.read()
    else:
        spec = importlib.util.find_spec(__name__)
        assert spec is not None and isinstance(spec.loader, InspectLoader)
        top_code_obj = spec.loader.get_code(__name__)
        assert top_code_obj is not None
        clean_code_obj = sanitize_code_object(top_code_obj)
        serialized_bytes = marshal.dumps(clean_code_obj)
    return hashlib.md5(serialized_bytes).hexdigest()


class Command(NamedTuple):
    needs_build: bool
    description: str
    cmd: list[str]


def commands_to_compile_dir_to_ir(sources: dict[str, SlangFile], src_dir: str, output_dirpath: str) -> Iterator[Command]:
    cmdbase = list(slangc()) + ['-warnings-as-errors', 'all']
    for name, sfile in sources.items():
        if sfile.should_compile_to_ir:
            parts = name.split('.')
            base_dest = os.path.join(output_dirpath, *parts)
            slang_module = f'{base_dest}.slang-module'
            deps_file = f'{base_dest}.deps'
            module_mtime = safe_mtime(slang_module)
            needs_build = module_mtime < get_newest_dep_time(deps_file)
            defines = [f'-D{k}={v}' for k, v in sfile.defines.items()]
            yield Command(
                needs_build,
                f'Compiling |{name}.slang| ...',
                cmdbase
                + defines
                + [
                    '-I',
                    output_dirpath,
                    '-I',
                    src_dir,
                    '-depfile',
                    deps_file,
                    '-target',
                    'none',
                    '-o',
                    slang_module,
                    '--',
                    sfile.path,
                ],
            )


def iter_entry_point_shaders(sources: dict[str, SlangFile], build_dir: str, dest_dir: str) -> Iterator[tuple[str, str, str, list[str], SlangFile]]:
    cmdbase = list(slangc()) + ['-warnings-as-errors', 'all']
    for name, sfile in sources.items():
        if not sfile.entry_points:
            continue
        parts = name.split('.')
        base_dest = os.path.join(dest_dir, *parts)
        base_build = os.path.join(build_dir, *parts)
        slang_module = f'{base_build}.slang-module'
        cmd = list(cmdbase)
        if sfile.disable_warnings:
            cmd += ['-warnings-disable', ','.join(sfile.disable_warnings)]
        cmd += ['-I', build_dir, slang_module]
        yield base_dest, base_build, slang_module, cmd, sfile


def serialize_source_metadata(sources: dict[str, SlangFile], dest_dir: str) -> None:
    for base_dest, _, _, _, sfile in iter_entry_point_shaders(sources, dest_dir, dest_dir):
        dest = f'{base_dest}.json'
        with open(dest, 'w') as f:
            f.write(json.dumps(sfile.asdict(skip_source=True), indent=2, sort_keys=True))


def commands_to_compile_to_spirv(sources: dict[str, SlangFile], build_dir: str, dest_dir: str, built_files: list[str]) -> Iterator[Command]:
    # glsl 450 is vulkan 1.1 and spirv 1.3 released 2008
    base_cmd = ['-target', 'spirv', '-profile', 'glsl_450', '-capability', 'vk_mem_model', '-fvk-use-entrypoint-name']
    for base_dest, base_build, slang_module, scmd, sfile in iter_entry_point_shaders(sources, build_dir, dest_dir):
        for x in sfile.specializations:
            cmd = list(scmd)
            dest = f'{base_dest}.{x.name}.spv' if x.name else f'{base_dest}.spv'
            if x.variables:
                cmd.insert(-1, f'{base_build}{x.filename_insert}.slang-module')
            cmd += base_cmd + ['-o', dest, '-reflection-json', dest + '.json']
            output_mtime = safe_mtime(dest)
            module_mtime = os.path.getmtime(slang_module)
            needs_build = output_mtime < module_mtime
            if needs_build:
                built_files.append(dest)
            yield Command(needs_build, f'Linking |{os.path.basename(dest)}| ...', cmd)


# GLSL {{{
glsl_version = max(150, GLSL_VERSION)  # slangc fails with glsl_140 https://github.com/shader-slang/slang/issues/11898


def commands_to_compile_to_glsl(sources: dict[str, SlangFile], build_dir: str, dest_dir: str, built_glsl_files: list[str]) -> Iterator[Command]:
    for base_dest, base_build, slang_module, cmd, sfile in iter_entry_point_shaders(sources, build_dir, dest_dir):
        module_mtime = os.path.getmtime(slang_module)
        extra_cmd = ['-line-directive-mode', 'none', '-target', 'glsl', '-profile', f'glsl_{glsl_version}']
        for ep in sfile.entry_points:
            for sp in sfile.specializations:
                v = {Stage.vertex: 'vert', Stage.fragment: 'frag'}[ep.stage]
                c = list(cmd)
                dest = f'{base_dest}{sp.filename_insert}.{v}.glsl' if sp.name else f'{base_dest}.{v}.glsl'
                if sp.variables:
                    c.insert(-1, f'{base_build}{sp.filename_insert}.slang-module')
                c += extra_cmd + ['-entry', ep.name, '-stage', ep.stage.name, '-o', dest]
                output_mtime = safe_mtime(dest)
                needs_build = output_mtime < module_mtime
                if needs_build:
                    built_glsl_files.append(dest)
                yield Command(needs_build, f'Linking |{os.path.basename(slang_module)}| to GLSL {ep.stage.value} shader ...', c)


class GLSLMetadata:
    loose_uniforms: dict[str, str]
    uniform_structs: dict[str, dict[str, str]]
    input_locations: dict[str, int]
    uniform_struct_names: dict[str, str]
    fragment_inputs: dict[int, str]

    def __init__(self) -> None:
        self.loose_uniforms = {}
        self.uniform_structs = {}
        self.input_locations = {}
        self.uniform_struct_names = {}
        self.fragment_inputs = {}

    def merge(self, other: 'GLSLMetadata') -> None:
        self.loose_uniforms.update(other.loose_uniforms)
        self.uniform_structs.update(other.uniform_structs)
        self.uniform_struct_names.update(other.uniform_struct_names)
        self.input_locations.update(other.input_locations)

    def asdict(self) -> dict[str, Any]:
        return {
            'loose_uniforms': self.loose_uniforms,
            'uniform_structs': self.uniform_structs,
            'input_locations': self.input_locations,
            'uniform_struct_names': self.uniform_struct_names,
            'fragment_inputs': self.fragment_inputs,
        }

    @classmethod
    def fromdict(cls, d: dict[str, Any]) -> 'GLSLMetadata':
        ans = GLSLMetadata()
        ans.loose_uniforms = d['loose_uniforms']
        ans.uniform_structs = d['uniform_structs']
        ans.input_locations = d['input_locations']
        ans.uniform_struct_names = d['uniform_struct_names']
        ans.fragment_inputs = d['fragment_inputs']
        return ans


def fixup_opengl_code(glsl_code: str, shader_name: str, existing_metadata: GLSLMetadata | None) -> tuple[str, GLSLMetadata]:
    is_fragment_shader = existing_metadata is None
    shader_name += '.frag.glsl' if is_fragment_shader else '.vert.glsl'
    lines: list[str] = []
    in_uniform_block = False
    in_uniform_block_contents = False
    uniform_block_is_struct = False
    current_uniform_struct_members: dict[str, str] = {}
    current_uniform_struct_name: str = ''
    uniform_blocks = {}
    current_uniform_names: list[str] = []
    uniform_names: dict[str, str] = {}
    uniform_structs = {}
    uniform_struct_names = {}
    input_locations = {}
    named_interface_blocks = set()
    pipeline_io_vars: dict[int, str] = {}
    replacements = {
        'gl_VertexIndex': 'gl_VertexID',
        'gl_BaseVertex': '0',
        'gl_InstanceIndex': 'gl_InstanceID',
        'gl_BaseInstance': '0',
    }
    fragment_inputs = {} if existing_metadata is None else existing_metadata.fragment_inputs.copy()

    def register_pipeline_boundary_io(line: str, next_line: str) -> None:
        m = re.search(r'location = (\d+)', line)
        assert m is not None
        name = next_line.split()[-1].rstrip(';')
        location = int(m.group(1))
        if existing_metadata is None:
            if not next_line.startswith('out '):
                pipeline_io_vars[location] = name
        else:
            with suppress(KeyError):
                replacements[name] = fragment_inputs.pop(location)

    def add_uniform_name(name: str, uniform_names: dict[str, str] = uniform_names) -> str:
        name = name.rstrip(';')
        uniform_name = name.rpartition('_')[0]
        if uniform_name in uniform_names:
            raise KeyError(f'The uniform name {uniform_name} is used with multiple suffixes in {shader_name}')
        if '[' in name:
            name = name.partition('[')[0] + '[0]'
        uniform_names[uniform_name] = name
        return name

    src_lines = glsl_code.splitlines()

    for i, line in enumerate(src_lines):
        next_line = src_lines[i + 1] if i + 1 < len(src_lines) else ''
        if in_uniform_block:
            if in_uniform_block_contents:
                if line.startswith('}'):
                    in_uniform_block = in_uniform_block_contents = False
                    block_name = line.lstrip('}').rstrip(';').strip()
                    if uniform_block_is_struct:
                        uniform_structs[current_uniform_struct_name] = current_uniform_struct_members
                        named_interface_blocks.add(block_name)
                        line = '};'
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
                line = f'#version {GLSL_VERSION}'
                if not is_fragment_shader:
                    line += '\n#extension GL_ARB_explicit_attrib_location : require'
            elif line.startswith('#extension ') or line in ('layout(row_major) buffer;', 'layout(push_constant)'):
                line = '// ' + line
            elif line.startswith('layout(binding ='):
                line = '// ' + line
            elif line.startswith('layout(location =') and (is_fragment_shader or next_line.startswith('out ')):  # ))
                register_pipeline_boundary_io(line, next_line)
                line = '// ' + line
            elif line.startswith('flat layout(location ='):
                register_pipeline_boundary_io(line[len('flat ') :], next_line)
                line = 'flat'
            elif line:  # ))))
                words = line.split()
                if 'uniform' in words and line.startswith('layout('):  # )
                    in_uniform_block = True
                    in_uniform_block_contents = False
                    uniform_block_is_struct = line.startswith('layout(std140')  # )
                    if uniform_block_is_struct:
                        current_uniform_struct_name = words[-1]
                        assert current_uniform_struct_name.startswith('block_')
                        current_uniform_struct_name = current_uniform_struct_name[len('block_') :].rpartition('_')[0]
                        current_uniform_struct_members = {}
                        uniform_struct_names[current_uniform_struct_name] = words[-1]
                    else:
                        line = '// ' + line
                elif words[0] == 'uniform' and len(words) > 2 and words[1].removeprefix('u').removeprefix('i').startswith('sampler'):
                    add_uniform_name(words[2])
                elif not is_fragment_shader and words[0] == 'in':
                    name = words[-1].rstrip(';')
                    input_locations[name.rpartition('_')[0]] = int(lines[-1].split()[-1].rstrip(')'))
        lines.append(line)
    if fragment_inputs:
        raise ValueError(
            f'Could not match vertex outputs to fragment inputs for shader: {shader_name}. Leftover fragment inputs: {", ".join(fragment_inputs.values())}'
        )
    ans = '\n'.join(lines)
    for block_name, names in uniform_blocks.items():
        for u in names:
            u = u.partition('[')[0]  # ]
            replacements[f'{block_name}.{u}'] = u

    for x in named_interface_blocks:
        replacements[f'{x}.'] = ''

    def sub(m: re.Match[str]) -> str:
        return replacements[m.group(1)]

    ans = re.sub(r'\b(' + '|'.join(re.escape(word) for word in replacements) + r')\b', sub, ans)
    # Slang emits `{ }` style struct initializers which aren't valid in GLSL 140;
    # convert them to GLSL constructor call syntax.
    ans = re.sub(
        r'\b([A-Za-z_]\w*)\s+(\w+)\s*=\s*\{([^}]*)\}',
        lambda m: f'{m.group(1)} {m.group(2)} = {m.group(1)}({m.group(3)})',
        ans,
    )
    m = GLSLMetadata()
    m.loose_uniforms = uniform_names
    m.uniform_structs = uniform_structs
    m.input_locations = input_locations
    m.uniform_struct_names = uniform_struct_names
    if is_fragment_shader:
        m.fragment_inputs = pipeline_io_vars
    return ans, m


def shader_name_from_path(path: str) -> str:
    parts = os.path.basename(path).split('.')
    if parts[1] in ('vert', 'frag', 'glsl'):
        return parts[0]
    return '.'.join(parts[:2])


def fixup_opengl_files(paths: Iterable[str]) -> None:
    "Convert the GLSL output of slangc to something that will work with OpenGL 3.1"
    metadata_map: dict[str, GLSLMetadata] = {}
    dest_dir = ''
    for path in sorted(paths):
        dest_dir = os.path.dirname(path)
        with open(path, 'r') as f:
            glsl_code = f.read()
        shader_name = shader_name_from_path(path)
        try:
            fixed, metadata = fixup_opengl_code(glsl_code, shader_name, metadata_map.get(shader_name))
        except Exception:
            os.unlink(path)
            raise
        write_if_changed(path, fixed)
        if shader_name in metadata_map:
            metadata_map[shader_name].merge(metadata)
        else:
            metadata_map[shader_name] = metadata
    for name, gm in metadata_map.items():
        with open(os.path.join(dest_dir, f'{name}.glsl.json'), 'w') as f:
            f.write(json.dumps(gm.asdict()))


def write_if_changed(dest: str, text: str) -> None:
    with suppress(FileNotFoundError), open(dest) as f:
        existing = f.read()
        if existing == text:
            return
    with open(dest, 'w') as f:
        f.write(text)


def glsl_metadata_for_shader(path: str) -> dict[str, Any]:
    with open(path) as f:
        d = json.load(f)
    m = GLSLMetadata.fromdict(d)
    return {
        'loose_uniforms': m.loose_uniforms,
        'uniform_structs': m.uniform_structs,
        'input_locations': m.input_locations,
        'uniform_struct_names': m.uniform_struct_names,
    }


def write_glsl_metadata(dest_dir: str, dest: str = 'glsl-uniforms.json') -> None:
    metadata_map = {}
    for x in glob.glob(os.path.join(dest_dir, '*.glsl.json')):
        shader_name = shader_name_from_path(x)
        if '.' in shader_name:
            continue
        metadata_map[shader_name] = glsl_metadata_for_shader(x)
    write_if_changed(os.path.join(dest_dir, dest), json.dumps(metadata_map, indent=2, sort_keys=True))


@lru_cache(maxsize=1)
def load_glsl_metadata() -> dict[str, dict[str, Any]]:
    with open(os.path.join(shaders_dir, 'glsl-uniforms.json')) as f:
        return dict(json.load(f))


# }}}


ParallelRun = Callable[[Iterable[tuple[bool, str, list[str]]]], None]


def create_specialisations(sources: dict[str, SlangFile], build_dir: str) -> Iterator[Command]:
    for _, base_build, _, _, sfile in iter_entry_point_shaders(sources, build_dir, build_dir):
        if sfile.entry_points and sfile.specializations:
            for sp in sfile.specializations:
                if not sp.variables:
                    continue
                dest = f'{base_build}{sp.filename_insert}.slang'
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
                yield Command(needs_build, f'Compiling specialisation |{os.path.basename(dest)}| ...', list(slangc()) + [dest, '-o', dest + '-module'])


def compile_builtin_shaders(build_dir: str, dest_dir: str, parallel_run: ParallelRun) -> None:
    ensure_cache_dir(build_dir)
    ensure_cache_dir(dest_dir)
    src_dir = os.path.abspath('kitty/shaders')
    source_tree = get_ordered_sources_in_tree(src_dir)
    serialize_source_metadata(source_tree, dest_dir)

    # Compile IR layer by layer so each module's dependencies finish before it starts
    for layer in topological_layers(source_tree):
        layer_sources = {k: source_tree[k] for k in layer}
        parallel_run(commands_to_compile_dir_to_ir(layer_sources, src_dir, build_dir))
    # Create the specializations
    parallel_run(create_specialisations(source_tree, build_dir))
    # Now Vulkan shaders
    built_spirv_files: list[str] = []
    spirv_commands = commands_to_compile_to_spirv(source_tree, build_dir, dest_dir, built_spirv_files)
    # Now glsl files
    built_glsl_files: list[str] = []
    glsl_commands = commands_to_compile_to_glsl(source_tree, build_dir, dest_dir, built_glsl_files)
    # Now run all commands
    parallel_run(chain(spirv_commands, glsl_commands))
    fixup_opengl_files(built_glsl_files)
    if shutil.which('glslangValidator'):
        from kitty.shaders.validate_shaders import validation_command_for_file

        parallel_run((True, f'Validating |{os.path.basename(x)}| ...', validation_command_for_file(x)) for x in built_glsl_files)
    write_glsl_metadata(dest_dir)


def main() -> None:
    if not shutil.which(slangc()[0]):
        raise SystemExit(f'The shader slang compiler ({slangc()[0]}) not in PATH: {os.environ.get("PATH")}')
    setup = runpy.run_path('setup.py')
    verbose = sys.argv[-3] == 'verbose'
    Command = setup['Command']
    parallel_run = setup['parallel_run']
    emphasis = setup['emphasis']

    def prun(cmds: Iterable[tuple[bool, str, list[str]]]) -> None:
        cmds = tuple(cmds)
        needed = []
        for needs_build, desc, cmd in cmds:
            if needs_build:
                desc = re.sub(r'\|(.+?)\|', lambda m: emphasis(m.group(1)), desc)
                needed.append(Command(desc, cmd, lambda: True))
        parallel_run(needed, verbose)

    compile_builtin_shaders(sys.argv[-2], sys.argv[-1], prun)


class SlangFailed(Exception):
    def __init__(self, fname: str, cp: subprocess.CompletedProcess):
        args = cp.args
        stderr = cp.stderr
        if isinstance(args, str):
            cmd = args
        else:
            cmd = shlex.join(args)
        super().__init__(f'Failed to compile {fname} with command line:\n{cmd}\nand stderr:\n{stderr.decode()}')


def key(*items: str | bytes) -> bytes:
    ans = 0
    for data in items:
        if isinstance(data, str):
            data = data.encode()
        ans = zlib.crc32(data, ans)
    return hex(ans).encode()[2:]


@lru_cache(maxsize=64)
def custom_shader(name: str = '') -> tuple[str, str, bytes, bytes]:
    import_dir = ''
    if not name:
        src = get_custom_shader_src('types')
    else:
        path = resolve_custom_file(f'{name}.slang')
        try:
            with open(path, 'rb') as f:
                src = f.read()
            path = os.path.abspath(path)
            name = path
            import_dir = os.path.dirname(path)
        except FileNotFoundError:
            src = get_custom_shader_src(name)
    return name, import_dir, src, key(src)


@lru_cache(maxsize=64)
def pipeline_definition(name: str) -> tuple[str, ...]:
    path = resolve_custom_file(f'{name}.pipeline')
    try:
        with open(path, 'rb') as f:
            src = f.read()
    except FileNotFoundError:
        src = get_custom_pipeline_src(name)
    return tuple(src.decode().splitlines())


class NamedTexture(StrEnum):
    a = auto()
    b = auto()
    persist = auto()
    default = auto()


class Slot(StrEnum):
    end = auto()


def is_valid_named_texture(x: str) -> TypeGuard[NamedTexture]:
    return x in get_args(NamedTexture)


def is_valid_slot(x: str) -> TypeGuard[Slot]:
    return x in get_args(Slot)


class Group(TypedDict):
    viewport_pos: tuple[float, float]
    viewport_size: tuple[float, float]
    output_texture: NamedTexture
    shaders: tuple[str, ...]


class Pipeline(TypedDict):
    slot: Slot
    textures: tuple[NamedTexture, ...]
    groups: tuple[Group, ...]


def parse_pipeline_definition(lines: Iterable[str]) -> Pipeline:
    slot = Slot.end
    textures: tuple[NamedTexture, ...] = ()
    groups: list[Group] = []
    current_group: Group | None = None

    def unit_float(x: str) -> float:
        return max(0, min(float(x), 1))

    def commit_group() -> None:
        nonlocal current_group
        if current_group is not None:
            groups.append(current_group)
            current_group = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if current_group is None:
            match parts[0]:
                case 'slot':
                    if not is_valid_slot(parts[1]):
                        raise ValueError(f'slot {parts[1]} is not valid')
                    slot = parts[1]
                case 'textures':
                    textures = tuple(map(NamedTexture, parts[1:]))
                case 'startgroup':
                    commit_group()
                    current_group = {'viewport_pos': (0, 0), 'viewport_size': (1, 1), 'output_texture': NamedTexture.default, 'shaders': ()}
                case _:
                    raise ValueError(f'Unknown key {parts[0]}')
        else:
            match parts[0]:
                case 'viewport_pos':
                    current_group['viewport_pos'] = unit_float(parts[1]), unit_float(parts[1 if len(parts) < 3 else 2])
                case 'viewport_size':
                    current_group['viewport_size'] = unit_float(parts[1]), unit_float(parts[1 if len(parts) < 3 else 2])
                case 'output_texture':
                    if not is_valid_named_texture(parts[1]):
                        raise ValueError(f'output_texture {parts[1]} does not appear in textures')
                    current_group['output_texture'] = parts[1]
                case 'shaders':
                    current_group['shaders'] += tuple(parts[1:])
                case 'endgroup':
                    commit_group()
                case _:
                    raise ValueError(f'Unknown key {parts[0]}')
    if current_group is not None:
        raise ValueError('Unclosed group present')
    if not groups:
        raise ValueError('At least one group must be specified')
    if groups[-1]['output_texture'] is not NamedTexture.default:
        raise ValueError('The final group cannot output to a named texture')
    if groups[-1]['viewport_pos'] != (0, 0) or groups[-1]['viewport_size'] != (1, 1):
        raise ValueError('The final group must not specify a viewport')

    return {'slot': slot, 'textures': textures, 'groups': tuple(groups)}


@lru_cache(maxsize=32)
def parse_pipeline(name: str) -> Pipeline:
    return parse_pipeline_definition(pipeline_definition(name))


def build_custom_shader_pipeline_ir(pipeline: Pipeline, cache_dir: str) -> tuple[tuple[str, ...], str]:
    slot = pipeline['slot']
    slot_module_name = f'{slot.replace("-", "_")}'
    cache_dir = os.path.join(cache_dir, 'c')
    ensure_cache_dir(cache_dir)
    slot_dir = os.path.join(cache_dir, 'slots')
    libdir = os.path.join(cache_dir, 'lib')
    import_dirs = [slot_dir, libdir]
    bc = list(slangc()) + ['-warnings-as-errors', 'all', '-lang', 'slang', '-I', libdir]
    _, _, ct_shader, ct_key = custom_shader()
    os.makedirs(libdir, exist_ok=True)
    os.makedirs(slot_dir, exist_ok=True)
    j = partial(os.path.join, libdir)
    cache_ok = False
    mtime = 0
    get_hash_for_self()
    with suppress(FileNotFoundError), open(j('ct.key'), 'rb') as f:
        cache_ok = f.read() == ct_key
        mtime = max(mtime, os.fstat(f.fileno()).st_mtime_ns)
    if not cache_ok:
        cp = subprocess.run(
            bc + ['-module-name', 'kitty_custom_shader_types', '-o', j('kitty-custom-shader-types.slang-module'), '--', '-'],
            input=ct_shader,
            capture_output=True,
        )
        if cp.returncode != 0:
            raise SlangFailed('custom-types.slang', cp)
        with open(j('ct.key'), 'wb') as f:
            f.write(ct_key)
            mtime = max(mtime, os.fstat(f.fileno()).st_mtime_ns)

    module_names = {}
    shaders_content_key = b''
    flat_shader_list = []
    for group in pipeline['groups']:
        shaders_content_key += b'::'
        for name in group['shaders']:
            flat_shader_list.append(name)
            path, import_dir, src, content_key = custom_shader(name)
            if import_dir and import_dir not in import_dirs:
                import_dirs.append(import_dir)
            shaders_content_key += b':' + content_key
            path_key = key(path)
            path_key_file = j(path_key.decode()) + '.key'
            cache_ok = False
            module_names[name] = modname = 'm' + content_key.decode()
            with suppress(FileNotFoundError), open(path_key_file, 'rb') as f:
                cache_ok = f.read() == content_key
                mtime = max(mtime, os.fstat(f.fileno()).st_mtime_ns)
            if not cache_ok:
                inc = ['-I', import_dir] if import_dir else []
                cp = subprocess.run(
                    bc + inc + ['-module-name', modname, '-o', j(f'{modname}.slang-module'), '--', '-'],
                    input=src,
                    capture_output=True,
                )
                if cp.returncode != 0:
                    raise SlangFailed(name, cp)
                with open(path_key_file, 'wb') as f:
                    f.write(content_key)
                    mtime = max(mtime, os.fstat(f.fileno()).st_mtime_ns)
    shaders_content_key += b':' + str(mtime).encode()
    j = partial(os.path.join, slot_dir)
    cache_ok = False

    wrappers = {}
    entry_points = []
    for i, name in enumerate(flat_shader_list):
        module_name = module_names[name]
        entry_point = f'fragment_main{i}'
        wrapper_src = textwrap.dedent(f"""
        #language slang 2026
        implementing {slot_module_name};
        import kitty_custom_shader_types;
        import {module_name};

        public float4 {entry_point}(float4 inp, KittyTextures t, KittyCustomShaderData d) {{ return fragment_main(inp, t, d); }}
        """)
        wrappers[f'wrapper{i}.slang'] = wrapper_src
        entry_points.append(entry_point)

    # Generate group-branched PIPELINE code
    # sRGB conversion is emitted only in the last group's branch so intermediate
    # groups write back premultiplied linear RGB (not sRGB) to the ping-pong texture.
    pipeline_parts: list[str] = []
    ep_idx = 0
    num_groups = len(pipeline['groups'])
    for g_idx, group in enumerate(pipeline['groups']):
        n = len(group['shaders'])
        calls = '\n'.join(f'        color = fragment_main{ep_idx + j}(color, t, csd);' for j in range(n))
        is_last = g_idx == num_groups - 1
        if is_last:
            calls += '\n        color = float4(linear2srgb(color.rgb), color.a);'
        if g_idx == 0:
            pipeline_parts.append(f'    if (group == 0) {{\n{calls}')
        else:
            pipeline_parts.append(f'    }} else if (group == {g_idx}) {{\n{calls}')
        ep_idx += n
    pipeline_parts.append('    }')
    pipeline_code = '\n'.join(pipeline_parts)

    mod_src = get_custom_shader_src('pipeline').decode()
    mod_src = mod_src.replace('// IMPORTS', '\n'.join(f'__include "{w}";' for w in wrappers), 1)
    mod_src = mod_src.replace('// PIPELINE', pipeline_code, 1)
    # subprocess.run(['bat', '-P', '-l', 'cpp'], input=mod_src.encode())
    slot_key = key(slot, mod_src, shaders_content_key)

    with suppress(FileNotFoundError), open(j(f'{slot}.key'), 'rb') as f:
        cache_ok = f.read() == slot_key
    ans = os.path.join(slot_dir, f'{slot}.slang-module')
    if cache_ok:
        return tuple(import_dirs), ans
    with tempfile.TemporaryDirectory() as tdir:
        for wrapper_name, wrapper_src in wrappers.items():
            with open(os.path.join(tdir, wrapper_name), 'w') as f:
                f.write(wrapper_src)
        inc = ['-I', tdir]
        for x in import_dirs:
            inc.extend(('-I', x))
        cp = subprocess.run(
            bc + inc + ['-module-name', slot_module_name, '-o', ans, '--', '-'],
            cwd=tdir,
            capture_output=True,
            input=mod_src.encode(),
        )
        if cp.returncode != 0:
            raise SlangFailed(f'{slot}.slang', cp)

    with open(j(f'{slot}.key'), 'wb') as f:
        f.write(slot_key)
    return tuple(import_dirs), slot_dir


def module_wrapper_for_slot(slot: str) -> bytes:
    return """
#language slang 2026
import MODULE;

struct VertexOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};

[shader("vertex")]
VertexOutput vmain_wrap(uint vertex_id : SV_VertexID) {
    float4 c = pipeline_vertex_main(vertex_id);
    return {float2(c[0], c[1]), float4(c[2], c[3], 0, 1)};
}

[shader("fragment")]
float4 fmain_wrap(float2 texcoord : TEXCOORD, uniform int group) : SV_Target {
    return pipeline_fragment_main(texcoord, group);
}
        """.replace('MODULE', slot.replace('-', '_')).encode()


def build_custom_shader_pipeline_glsl(pipeline: Pipeline, cache_dir: str = '') -> tuple[str, str, dict[str, Any]]:
    import kitty.constants as kc

    cache_dir = os.path.join(cache_dir or kc.cache_dir(), 'shaders')
    os.makedirs(cache_dir, exist_ok=True)

    with lock_with_file(
        os.path.join(cache_dir, 'lock'),
    ):
        import_dirs, slang_module_path = build_custom_shader_pipeline_ir(pipeline, cache_dir)
        glsl_dir = os.path.join(os.path.dirname(os.path.dirname(slang_module_path)), 'glsl')
        os.makedirs(glsl_dir, exist_ok=True)
        module_mtime = safe_mtime(slang_module_path)
        slot = pipeline['slot']
        vertex = os.path.join(glsl_dir, f'{slot}.vert.glsl')
        fragment = os.path.join(glsl_dir, f'{slot}.frag.glsl')
        metadata = os.path.join(glsl_dir, f'{slot}.glsl.json')
        if module_mtime > safe_mtime(metadata):
            inc = []
            for x in import_dirs:
                inc.extend(('-I', x))
            cmd = (
                list(slangc())
                + inc
                + [
                    '-warnings-as-errors',
                    'all',
                    '-lang',
                    'slang',
                    '-target',
                    'glsl',
                    '-profile',
                    f'glsl_{glsl_version}',
                ]
            )
            vcmd = cmd + ['-stage', 'vertex', '-entry', 'vmain_wrap', '-o', vertex, '--', '-']
            fcmd = cmd + ['-stage', 'fragment', '-entry', 'fmain_wrap', '-o', fragment, '--', '-']
            src = module_wrapper_for_slot(slot)
            v = subprocess.Popen(vcmd, stderr=subprocess.PIPE, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
            f = subprocess.Popen(fcmd, stderr=subprocess.PIPE, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
            assert v.stdin is not None and f.stdin is not None
            assert v.stderr is not None and f.stderr is not None
            v.stdin.write(src), v.stdin.close()
            f.stdin.write(src), f.stdin.close()
            try:
                if (rc := v.wait()) != 0:
                    raise SlangFailed(f'{slot}.vert.glsl', subprocess.CompletedProcess(vcmd, rc, stderr=v.stderr.read()))
                if (rc := f.wait()) != 0:
                    raise SlangFailed(f'{slot}.frag.glsl', subprocess.CompletedProcess(fcmd, rc, stderr=f.stderr.read()))
            finally:
                v.stderr.close()
                f.stderr.close()
            fixup_opengl_files((fragment, vertex))
        with open(vertex) as vf, open(fragment) as ff:
            m = glsl_metadata_for_shader(metadata)
            m['pipeline'] = pipeline
            return vf.read(), ff.read(), m


def clear_caches() -> None:
    custom_shader.cache_clear()
    pipeline_definition.cache_clear()
    parse_pipeline.cache_clear()


def test_slang_build() -> None:

    if shutil.which(slangc()[0]) is None:
        raise AssertionError(f'The shader slang compiler ({slangc()[0]}) not in PATH: {os.environ.get("PATH")}')
    q = os.path.join(shaders_dir, 'graphics.spv')
    if not os.path.isfile(q):
        raise AssertionError(f'The compiled graphics shader {q} does not exist')
    if not get_shader_src('graphics'):
        raise AssertionError('Could not load graphics.slang shader source')
    src = b"""
#language slang 2026
[shader("vertex")]
float4 main(uint vertex_id : SV_VertexID) : SV_Position { return float4(vertex_id, 1, 0, 1); }
"""
    cp = subprocess.run(list(slangc()) + '-lang slang -entry main -stage vertex -target glsl -o /dev/stdout -- -'.split(), input=src, capture_output=True)
    if cp.returncode != 0:
        raise AssertionError(f'Test compile of shader to GLSL failed with returncode: {cp.returncode} and stderr: {cp.stderr.decode()}')


if __name__ == '__main__':
    main()
