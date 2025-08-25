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
    BLINK,
    BLIT_PROGRAM,
    CELL_BG_PROGRAM,
    CELL_FG_PROGRAM,
    CELL_PROGRAM,
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
    ROUNDED_RECT_PROGRAM,
    STRIKETHROUGH,
    TINT_PROGRAM,
    TRAIL_PROGRAM,
    compile_program,
    get_options,
    init_cell_program,
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
            self(allow_recompile=True)

    def __call__(self, allow_recompile: bool = False) -> None:
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
                BLINK_SHIFT=BLINK,
                DECORATION_SHIFT=DECORATION,
                MARK_SHIFT=MARK,
                MARK_MASK=MARK_MASK,
                DECORATION_MASK=DECORATION_MASK,
            )

        def resolve_cell_defines(only_fg: int, only_bg: int, src: str) -> str:
            r = self.cell_program_replacer.replacements
            r['ONLY_FOREGROUND'] = str(only_fg)
            r['ONLY_BACKGROUND'] = str(only_bg)
            r['DO_FG_OVERRIDE'] = '1' if self.text_fg_override_threshold.scaled_value else '0'
            r['FG_OVERRIDE_ALGO'] = '1' if self.text_fg_override_threshold.unit == '%' else '2'
            r['FG_OVERRIDE_THRESHOLD'] = str(self.text_fg_override_threshold.scaled_value)
            r['TEXT_NEW_GAMMA'] = '0' if self.text_old_gamma else '1'
            return self.cell_program_replacer(src)
        for prog, (only_fg, only_bg) in {
                CELL_PROGRAM: (0, 0), CELL_FG_PROGRAM: (1, 0), CELL_BG_PROGRAM: (0, 1),
        }.items():
            fn = partial(resolve_cell_defines, only_fg, only_bg)
            cell.apply_to_sources(vertex=fn, frag=fn)
            cell.compile(prog, allow_recompile)
        graphics = program_for('graphics')

        def resolve_graphics_fragment_defines(which: str, is_premult: bool, f: str) -> str:
            ans = f.replace('#define ALPHA_TYPE', f'#define {which}', 1)
            return ans.replace('TEXTURE_IS_NOT_PREMULTIPLIED', '0' if is_premult else '1')

        for p, (which, is_premult) in {
            GRAPHICS_PROGRAM: ('IMAGE', False),
            GRAPHICS_ALPHA_MASK_PROGRAM: ('ALPHA_MASK', False),
            GRAPHICS_PREMULT_PROGRAM: ('IMAGE', True),
        }.items():
            graphics.apply_to_sources(frag=partial(resolve_graphics_fragment_defines, which, is_premult))
            graphics.compile(p, allow_recompile)

        program_for('bgimage').compile(BGIMAGE_PROGRAM, allow_recompile)
        program_for('tint').compile(TINT_PROGRAM, allow_recompile)
        program_for('trail').compile(TRAIL_PROGRAM, allow_recompile)
        program_for('blit').compile(BLIT_PROGRAM, allow_recompile)
        program_for('rounded_rect').compile(ROUNDED_RECT_PROGRAM, allow_recompile)
        init_cell_program()


load_shader_programs = LoadShaderPrograms()
