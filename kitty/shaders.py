#!/usr/bin/env python
# License: GPLv3 Copyright: 2023, Kovid Goyal <kovid at kovidgoyal.net>

import re
from functools import lru_cache, partial
from typing import Any, Callable, Iterator, Optional

from .constants import read_kitty_resource
from .fast_data_types import (
    BGIMAGE_PROGRAM,
    BLIT_PROGRAM,
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
    NUM_UNDERLINE_STYLES,
    REVERSE,
    STRIKETHROUGH,
    TINT_PROGRAM,
    compile_program,
    get_options,
    init_cell_program,
)


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


class LoadShaderPrograms:

    text_fg_override_threshold: float = 0
    text_old_gamma: bool = False
    semi_transparent: bool = False
    cell_program_replacer: MultiReplacer = null_replacer

    @property
    def needs_recompile(self) -> bool:
        opts = get_options()
        return opts.text_fg_override_threshold != self.text_fg_override_threshold or (opts.text_composition_strategy == 'legacy') != self.text_old_gamma

    def recompile_if_needed(self) -> None:
        if self.needs_recompile:
            self(self.semi_transparent, allow_recompile=True)

    def __call__(self, semi_transparent: bool = False, allow_recompile: bool = False) -> None:
        self.semi_transparent = semi_transparent
        opts = get_options()
        self.text_old_gamma = opts.text_composition_strategy == 'legacy'
        self.text_fg_override_threshold = max(0, min(opts.text_fg_override_threshold, 100)) * 0.01
        program_for('blit').compile(BLIT_PROGRAM, allow_recompile)
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
                STRIKE_SPRITE_INDEX=NUM_UNDERLINE_STYLES + 1,
            )

        def resolve_cell_vertex_defines(which: str, v: str) -> str:
            self.cell_program_replacer.replacements['WHICH_PROGRAM'] = which
            v = self.cell_program_replacer(v)
            if semi_transparent:
                v = v.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
            return v

        def resolve_cell_fragment_defines(which: str, f: str) -> str:
            f = f.replace('{WHICH_PROGRAM}', which)
            if self.text_fg_override_threshold != 0.:
                f = f.replace('#define NO_FG_OVERRIDE', f'#define FG_OVERRIDE {self.text_fg_override_threshold}')
            if self.text_old_gamma:
                f = f.replace('#define TEXT_NEW_GAMMA', '#define TEXT_OLD_GAMMA')
            if semi_transparent:
                f = f.replace('#define NOT_TRANSPARENT', '#define TRANSPARENT')
            return f

        for which, p in {
            'SIMPLE': CELL_PROGRAM,
            'BACKGROUND': CELL_BG_PROGRAM,
            'SPECIAL': CELL_SPECIAL_PROGRAM,
            'FOREGROUND': CELL_FG_PROGRAM,
        }.items():
            cell.apply_to_sources(
                vertex=partial(resolve_cell_vertex_defines, which),
                frag=partial(resolve_cell_fragment_defines, which),
            )
            cell.compile(p, allow_recompile)

        graphics = program_for('graphics')

        def resolve_graphics_fragment_defines(which: str, f: str) -> str:
            return f.replace('ALPHA_TYPE', which)

        for which, p in {
            'SIMPLE': GRAPHICS_PROGRAM,
            'PREMULT': GRAPHICS_PREMULT_PROGRAM,
            'ALPHA_MASK': GRAPHICS_ALPHA_MASK_PROGRAM,
        }.items():
            graphics.apply_to_sources(frag=partial(resolve_cell_fragment_defines, which))
            graphics.compile(p, allow_recompile)

        program_for('bgimage').compile(BGIMAGE_PROGRAM, allow_recompile)
        program_for('tint').compile(TINT_PROGRAM)
        init_cell_program()


load_shader_programs = LoadShaderPrograms()
