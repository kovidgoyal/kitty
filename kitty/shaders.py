#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections.abc import Callable, Iterator
from functools import lru_cache, partial
from itertools import count
from typing import Any, Literal, NamedTuple, Optional

from .constants import read_kitty_resource
from .fast_data_types import (
    BGIMAGE_PROGRAM,
    CELL_BG_PROGRAM,
    CELL_FG_PROGRAM,
    CELL_PROGRAM,
    CELL_SPECIAL_PROGRAM,
    DECORATION,
    DECORATION_MASK,
    DIM,
    GLSL_VERSION,
    GRAPHICS_ALPHA_MASK_PROGRAM,
    GRAPHICS_PREMULT_PROGRAM,
    GRAPHICS_PROGRAM,
    MARK,
    MARK_MASK,
    REVERSE,
    STRIKETHROUGH,
    TINT_PROGRAM,
    TRAIL_PROGRAM,
    compile_program,
    get_options,
    init_cell_program,
    init_trail_program,
)


def identity(x: str) -> str:
    return x


class CompileError(ValueError):
    pass


class Program:

    include_pat: Optional['re.Pattern[str]'] = None
    filename_number_base: int = 7893000

    def __init__(self, name: str, vertex_name: str = '', fragment_name: str = '') -> None:
        self.name = name
        self.filename_number_counter = count(self.filename_number_base + 1)
        self.filename_map: dict[str, int] = {}
        if Program.include_pat is None:
            Program.include_pat = re.compile(r'^#pragma\s+kitty_include_shader\s+<(.+?)>', re.MULTILINE)
        self.vertex_name = vertex_name or f'{name}_vertex.glsl'
        self.fragment_name = fragment_name or f'{name}_fragment.glsl'
        self.original_vertex_sources = tuple(self._load_sources(self.vertex_name, set()))
        self.original_fragment_sources = tuple(self._load_sources(self.fragment_name, set()))
        self.vertex_sources = self.original_vertex_sources
        self.fragment_sources = self.original_fragment_sources

    def _load_sources(self, name: str, seen: set[str], level: int = 0) -> Iterator[str]:
        if level == 0:
            yield f'#version {GLSL_VERSION}\n'
        if name in seen:
            return
        seen.add(name)
        self.filename_map[name] = fnum = next(self.filename_number_counter)
        src = read_kitty_resource(name).decode('utf-8')
        pos = 0
        lnum = 0
        assert Program.include_pat is not None
        for m in Program.include_pat.finditer(src):
            prefix = src[pos:m.start()]
            if prefix:
                yield f'\n#line {lnum} {fnum}\n{prefix}'
                lnum += prefix.count('\n')
            iname = m.group(1)
            yield from self._load_sources(iname, seen, level+1)
            pos = m.end()
        if pos < len(src):
            yield f'\n#line {lnum} {fnum}\n{src[pos:]}'

    def apply_to_sources(self, vertex: Callable[[str], str] = identity, frag: Callable[[str], str] = identity) -> None:
        self.vertex_sources = self.original_vertex_sources if vertex is identity else tuple(map(vertex, self.original_vertex_sources))
        self.fragment_sources = self.original_fragment_sources if frag is identity else tuple(map(frag, self.original_fragment_sources))

    def compile(self, program_id: int, allow_recompile: bool = False) -> None:
        cerr: CompileError = CompileError()
        try:
            compile_program(program_id, self.vertex_sources, self.fragment_sources, allow_recompile)
            return
        except ValueError as err:
            lines = str(err).splitlines()
            msg = []
            pat = re.compile(r'\b(' + str(self.filename_number_base).replace('0', r'\d') + r')\b')
            rmap = {str(v): k for k, v in self.filename_map.items()}

            def sub(m: 're.Match[str]') -> str:
                return rmap.get(m.group(1), m.group(1))

            for line in lines:
                msg.append(pat.sub(sub, line))
            cerr = CompileError('\n'.join(msg))
        raise cerr


@lru_cache(maxsize=64)
def program_for(name: str) -> Program:
    return Program(name)


class MultiReplacer:

    pat: Optional['re.Pattern[str]'] = None

    def __init__(self, **replacements: Any):
        self.replacements = {k: str(v) for k, v in replacements.items()}
        if MultiReplacer.pat is None:
            MultiReplacer.pat = re.compile(r'\{([A-Z_]+)\}')

    def _sub(self, m: 're.Match[str]') -> str:
        return self.replacements.get(m.group(1), m.group(1))

    def __call__(self, src: str) -> str:
        assert self.pat is not None
        return self.pat.sub(self._sub, src)

null_replacer = MultiReplacer()


class TextFgOverrideThreshold(NamedTuple):
    value: float = 0
    unit: Literal['%', 'ratio'] = '%'
    scaled_value: float = 0


class LoadShaderPrograms:
    text_fg_override_threshold: TextFgOverrideThreshold = TextFgOverrideThreshold()
    text_old_gamma: bool = False
    semi_transparent: bool = False
    cell_program_replacer: MultiReplacer = null_replacer

    @property
    def needs_recompile(self) -> bool:
        opts = get_options()
        return (
            opts.text_fg_override_threshold != (self.text_fg_override_threshold.value, self.text_fg_override_threshold.unit)
            or (opts.text_composition_strategy == 'legacy') != self.text_old_gamma
        )

    def recompile_if_needed(self) -> None:
        if self.needs_recompile:
            self(self.semi_transparent, allow_recompile=True)

    def __call__(self, semi_transparent: bool = False, allow_recompile: bool = False) -> None:
        self.semi_transparent = semi_transparent
        opts = get_options()
        self.text_old_gamma = opts.text_composition_strategy == 'legacy'

        text_fg_override_threshold: float = opts.text_fg_override_threshold[0]
        match opts.text_fg_override_threshold[1]:
            case '%':
                text_fg_override_threshold = max(0, min(text_fg_override_threshold, 100.0)) * 0.01
            case 'ratio':
                text_fg_override_threshold = max(0, min(text_fg_override_threshold, 21.0))
        self.text_fg_override_threshold = TextFgOverrideThreshold(
                opts.text_fg_override_threshold[0], opts.text_fg_override_threshold[1], text_fg_override_threshold)

        cell = program_for('cell')
        if self.cell_program_replacer is null_replacer:
            self.cell_program_replacer = MultiReplacer(
                REVERSE_SHIFT=REVERSE,
                STRIKE_SHIFT=STRIKETHROUGH,
                DIM_SHIFT=DIM,
                DECORATION_SHIFT=DECORATION,
                MARK_SHIFT=MARK,
                MARK_MASK=MARK_MASK,
                DECORATION_MASK=DECORATION_MASK,
            )

        def resolve_cell_defines(which: str, src: str) -> str:
            r = self.cell_program_replacer.replacements
            r['WHICH_PHASE'] = f'PHASE_{which}'
            r['TRANSPARENT'] = '1' if semi_transparent else '0'
            r['DO_FG_OVERRIDE'] = '1' if self.text_fg_override_threshold.scaled_value else '0'
            r['FG_OVERRIDE_ALGO'] = '1' if self.text_fg_override_threshold.unit == '%' else '2'
            r['FG_OVERRIDE_THRESHOLD'] = str(self.text_fg_override_threshold.scaled_value)
            r['TEXT_NEW_GAMMA'] = '0' if self.text_old_gamma else '1'
            return self.cell_program_replacer(src)

        for which, p in {
            'BOTH': CELL_PROGRAM,
            'BACKGROUND': CELL_BG_PROGRAM,
            'SPECIAL': CELL_SPECIAL_PROGRAM,
            'FOREGROUND': CELL_FG_PROGRAM,
        }.items():
            cell.apply_to_sources(
                vertex=partial(resolve_cell_defines, which),
                frag=partial(resolve_cell_defines, which),
            )
            cell.compile(p, allow_recompile)

        graphics = program_for('graphics')

        def resolve_graphics_fragment_defines(which: str, f: str) -> str:
            return f.replace('#define ALPHA_TYPE', f'#define {which}', 1)

        for which, p in {
            'SIMPLE': GRAPHICS_PROGRAM,
            'PREMULT': GRAPHICS_PREMULT_PROGRAM,
            'ALPHA_MASK': GRAPHICS_ALPHA_MASK_PROGRAM,
        }.items():
            graphics.apply_to_sources(frag=partial(resolve_graphics_fragment_defines, which))
            graphics.compile(p, allow_recompile)

        program_for('bgimage').compile(BGIMAGE_PROGRAM, allow_recompile)
        program_for('tint').compile(TINT_PROGRAM, allow_recompile)
        init_cell_program()

        program_for('trail').compile(TRAIL_PROGRAM, allow_recompile)
        init_trail_program()


load_shader_programs = LoadShaderPrograms()
