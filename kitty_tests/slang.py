#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import hashlib
import importlib.resources as ir
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

from kitty.constants import slangc
from kitty.shaders.slang import (
    EntryPoint,
    LoadShaderPrograms,
    SlangFile,
    SlangShaderQuery,
    Stage,
    apply_pipeline_specializations,
    build_custom_shader_pipeline_glsl,
    build_import_graph,
    cell_variant,
    cell_variations,
    clear_caches,
    custom_shader,
    defines_pointer_map,
    get_custom_pipeline_src,
    parse_pipeline_definition,
    parse_slang_declarations,
    parse_slang_text,
    parse_var_directive,
    pipeline_definition,
    pointer_map_shaders,
    slangc_version,
    text_contrast_is_identity,
    topological_layers,
    topological_sort,
    variant_name,
)

from .base import BaseTest

_SUPPORT_SHADER_NAMES = frozenset(('types', 'pipeline'))


class TestSlang(BaseTest):
    def test_animation_step_parsing(self):
        def step(val):
            return parse_pipeline_definition(['startgroup', f'animation_step {val}', 'shaders focus-highlight', 'endgroup'], 'test')['groups'][0][
                'animation_step'
            ]

        # 0 means "static effect, no periodic redraws" and must survive as 0
        self.ae(step(0), 0)
        self.ae(step(16), 16_000_000)
        self.assertRaises(ValueError, step, -1)

    def test_custom_shader_redraw_logic(self):
        from kitty.fast_data_types import custom_shader_needs_render, simulate_custom_shader_render_ticks

        NEVER = 2**63 - 1  # MONOTONIC_T_MAX, the "nothing scheduled" sentinel
        STEP = 50_000_000  # an animated group redrawing every 50ms
        NOW = 1_000_000_000

        def needs_render(before, after, events=0, now=NOW):
            return custom_shader_needs_render(before, after, events, now)

        idle = (False, NEVER, NEVER)
        static = (True, NEVER, NEVER)
        animating = (True, STEP, NEVER)

        # Nothing active and nothing pending: the shader layer must not ask for frames.
        self.assertFalse(needs_render(idle, idle))
        self.assertFalse(needs_render(idle, idle, events=1))
        # A static group only redraws when an event may have changed its output.
        self.assertFalse(needs_render(static, static))
        self.assertTrue(needs_render(static, static, events=1))
        # An animated group redraws every tick...
        self.assertTrue(needs_render(animating, animating))
        # ...and gets one final frame after it stops, so the effect is cleared.
        self.assertTrue(needs_render(animating, static))
        self.assertTrue(needs_render(animating, idle))
        # Groups turning on or off is always a visible change.
        self.assertTrue(needs_render(idle, static))
        self.assertTrue(needs_render(static, idle))
        # The tick on which a duration bounded animation expires needs a frame,
        # earlier ticks do not.
        self.assertTrue(needs_render((True, NEVER, NOW), static))
        self.assertTrue(needs_render((True, NEVER, NOW - 1), static))
        self.assertFalse(needs_render((True, NEVER, NOW + 1), static))

        # A window with no custom shaders configured must settle into asking for
        # no frames at all, otherwise an idle kitty redraws forever. Test both a
        # zero initialized window and one initialized the way add_os_window()
        # does it, since zero is not the MONOTONIC_T_MAX sentinel.
        self.ae(simulate_custom_shader_render_ticks(8, 0, True), [False] * 8)
        self.ae(simulate_custom_shader_render_ticks(8)[1:], [False] * 7)
        # Even a steady stream of shader events must not produce frames when
        # there are no shaders to draw.
        self.ae(simulate_custom_shader_render_ticks(8, 0xFF, True), [False] * 8)

    def test_custom_shader_user_events(self):
        from kitty.fast_data_types import MAX_SHADER_ANIM_USER_EVENTS, fire_custom_shader_event, simulate_custom_shader_animation
        from kitty.options.utils import KeyAction, parse_key_action

        def pipeline(*groups: str):
            lines = []
            for g in groups:
                lines.append('startgroup')
                lines.extend(g.splitlines())
                lines.append('shaders sample')
                lines.append('endgroup')
            return parse_pipeline_definition(lines, 'test')

        # Parsing
        g = pipeline('animation_start user:find-cursor|tab-change\nanimation_stop user:x.y_z')['groups'][0]
        self.ae(g['animation_start'], ('user:find-cursor', 'tab-change'))
        self.ae(g['animation_end_events'], ('user:x.y_z',))
        # Trailing comments, including empty ones
        for comment in ('# ', '#', '# some comment', '\t#x'):
            g = pipeline(f'animation_toggle user:toggle-notch {comment}\nanimation_duration 600 {comment}')['groups'][0]
            self.ae(g['animation_toggle'], ('user:toggle-notch',))
            self.ae(g['animation_duration'], 600_000_000)
        for bad in ('user:', 'user:a/b', 'user:' + 'x' * 100, 'usr:a'):
            self.assertRaises(ValueError, pipeline, f'animation_start {bad}')
        # A toggled group stays on until toggled off unless told otherwise
        self.ae(pipeline('animation_toggle user:t')['groups'][0]['animation_end_duration'], 0)
        self.ae(pipeline('animation_toggle user:t\nanimation_stop 100')['groups'][0]['animation_end_duration'], 100_000_000)
        self.ae(pipeline('animation_start user:s\nanimation_toggle user:t')['groups'][0]['animation_end_duration'], -1)
        many = '|'.join(f'user:e{i}' for i in range(MAX_SHADER_ANIM_USER_EVENTS + 1))
        self.assertRaises(ValueError, pipeline, f'animation_start {many}')
        pipeline(f'animation_start {many.rpartition("|")[0]}')

        # The action
        self.ae(parse_key_action('shader_event find-cursor'), KeyAction('shader_event', ('find-cursor', 'active')))
        self.ae(parse_key_action('shader_event user:notch ALL'), KeyAction('shader_event', ('notch', 'all')))
        for bad in ('a b c', 'a sideways', 'a/b'):
            self.assertRaises(ValueError, parse_key_action, f'shader_event {bad}')
        # Events not used by the current pipeline, here no pipeline at all, are ignored
        self.assertFalse(fire_custom_shader_event('find-cursor'))

        # The animation state machine
        p = pipeline(
            'animation_toggle user:t',
            'animation_start user:s\nanimation_stop 20',
            'attach',
            'animation_start user:on\nanimation_toggle user:t\nanimation_stop user:off|0',
            '',
        )
        ticks = [(), ('user:t',), (), ('user:t',), ('user:s', 'user:unknown'), (), (), ('user:on',), ('user:t',), ('user:t', 'user:off'), ('user:on', 'user:t')]
        expected = [
            (False, False, False, False, True),
            (True, False, False, True, True),  # toggled on
            (True, False, False, True, True),  # toggles stay on
            (False, False, False, False, True),  # toggled off
            (False, True, True, False, True),  # started, with the attached group
            (False, True, True, False, True),
            (False, False, False, False, True),  # duration expired
            (False, False, False, True, True),
            (True, False, False, False, True),  # toggles flip each group's own state
            (False, False, False, True, True),  # toggle wins over a simultaneous stop
            (True, False, False, False, True),  # and over a simultaneous start
        ]
        self.ae(simulate_custom_shader_animation(p, ticks), expected)

    def test_custom_shader_animation_progress(self):
        from kitty.fast_data_types import simulate_custom_shader_animation

        def pipeline(*groups: str):
            lines = []
            for g in groups:
                lines.append('startgroup')
                lines.extend(g.splitlines())
                lines.append('shaders sample')
                lines.append('endgroup')
            return parse_pipeline_definition(lines, 'test')

        def group(spec: str):
            return pipeline(spec)['groups'][0]

        def progress(spec: str, ticks: list[tuple[str, ...]]) -> list[float | None]:
            # The ticks are 10ms apart
            return [x[0] for x in simulate_custom_shader_animation(pipeline(spec, ''), ticks, True)]

        # Parsing
        self.ae(group('')['animation_duration'], -1)
        self.ae(group('animation_duration 300')['animation_duration'], 300_000_000)
        self.ae(group('')['animation_reverse'], 0)
        self.ae(group('animation_reverse yes')['animation_reverse'], -1)
        self.ae(group('animation_reverse no')['animation_reverse'], 0)
        self.ae(group('animation_reverse 200')['animation_reverse'], 200_000_000)
        self.ae(group('')['animation_loops'], 1)
        self.ae(group('animation_reverse yes\nanimation_loops 3')['animation_loops'], 3)
        for bad in (
            'animation_duration -1',
            'animation_duration x',
            'animation_reverse -1',
            'animation_reverse maybe',
            'animation_reverse yes\nanimation_loops 0',
            'animation_loops 2',
        ):
            self.assertRaises(ValueError, group, bad)

        on, off, none = ('user:t',), ('user:off',), ()
        # Without animation_duration progress follows the stop duration, and a
        # group with no stop duration has no progress
        self.ae(progress('animation_start user:t\nanimation_stop 40', [on, none, none, none, none]), [0, 0.25, 0.5, 0.75, None])
        self.ae(progress('animation_toggle user:t', [on, none, none]), [0, 0, 0])
        # animation_duration makes progress rise to one and stay there
        self.ae(progress('animation_toggle user:t\nanimation_duration 40', [on] + [none] * 5 + [on, none]), [0, 0.25, 0.5, 0.75, 1, 1, None, None])
        # Reversing on toggle off, over animation_duration with yes
        self.ae(
            progress('animation_toggle user:t\nanimation_duration 40\nanimation_reverse yes', [on] + [none] * 4 + [on] + [none] * 4),
            [0, 0.25, 0.5, 0.75, 1, 1, 0.75, 0.5, 0.25, None],
        )
        # ...or over its own duration
        self.ae(
            progress('animation_toggle user:t\nanimation_duration 40\nanimation_reverse 20', [on] + [none] * 4 + [on, none, none]),
            [0, 0.25, 0.5, 0.75, 1, 1, 0.5, None],
        )
        # Stopping part way reverses from the current progress, and restarting
        # while reversing continues rising from there
        self.ae(
            progress('animation_toggle user:t\nanimation_duration 40\nanimation_reverse yes', [on, none, on, on, none, none, none]),
            [0, 0.25, 0.5, 0.25, 0.5, 0.75, 1],
        )
        # Stop events are ignored while reversing, start events restart
        self.ae(
            progress('animation_start user:t\nanimation_stop user:off\nanimation_duration 40\nanimation_reverse yes', [on] + [none] * 4 + [off, off, on, none]),
            [0, 0.25, 0.5, 0.75, 1, 1, 0.75, 0.5, 0.75],
        )
        # The stop duration ending also reverses, with progress having reached one
        self.ae(progress('animation_start user:t\nanimation_stop 40\nanimation_reverse yes', [on] + [none] * 8), [0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, None])
        # Loops play the animation forwards and in reverse again after the
        # first reverse, without holding, for example, to blink three times
        self.ae(
            progress('animation_start user:t\nanimation_stop 20\nanimation_duration 20\nanimation_reverse yes\nanimation_loops 3', [on] + [none] * 12),
            [0, 0.5, 1, 0.5, 0, 0.5, 1, 0.5, 0, 0.5, 1, 0.5, None],
        )
        # Starting again while looping goes back to holding at one
        self.ae(
            progress(
                'animation_toggle user:t\nanimation_duration 20\nanimation_reverse yes\nanimation_loops 2', [on, none, none, on, none, none, on, none, none]
            ),
            [0, 0.5, 1, 1, 0.5, 0, 0.5, 1, 1],
        )
        # Attached groups without their own events share the progress, including
        # the easing curve and reversal, of the group they are attached to
        p = pipeline('animation_toggle user:t\nanimation_duration 40\nanimation_curve ease-in\nanimation_reverse yes', 'attach', '')
        results = simulate_custom_shader_animation(p, [on] + [none] * 4 + [on] + [none] * 4, True)
        self.ae([r[0] for r in results], [r[1] for r in results])
        eased = results[2][0]
        assert eased is not None
        self.assertLess(eased, 0.5)
        self.ae([r[1] is None for r in results], [False] * 9 + [True])

    def test_custom_shader_reenable(self):
        from kitty.fast_data_types import CUSTOM_END_PROGRAM
        from kitty.options.types import defaults

        loader = LoadShaderPrograms()
        pipeline = parse_pipeline_definition(['startgroup', 'animation_step 0', 'shaders focus-highlight', 'endgroup'], 'test')
        self.ae(pipeline['groups'][0]['animation_step'], 0)
        with (
            patch('kitty.shaders.slang.parse_pipeline', return_value=pipeline),
            patch('kitty.shaders.slang.build_custom_shader_pipeline_glsl', return_value=('vertex', 'fragment', {})),
            patch('kitty.shaders.slang.compile_program') as compile_program,
        ):
            for shaders in (('test',), (), ('test',)):
                loader.opts = defaults._replace(custom_shaders=shaders)
                loader.compile_custom_shaders(allow_recompile=True)
            operations = [c.args[1] for c in compile_program.call_args_list if c.args[0] == CUSTOM_END_PROGRAM]
            self.ae(operations, [('vertex',), (), ('vertex',)])

    def test_slang_parser(self):
        def check(src: str, expected: SlangFile) -> None:
            actual = parse_slang_text(src)
            actual = actual._replace(text='')
            self.assertEqual(expected, actual)

        # Basic vertex + fragment entry points
        check(
            """
[shader("vertex")]
void drawTriangle(float4 pos : POSITION) {
    // vertex code
}

[shader("fragment")]
[numthreads(1, 1, 1)] // Handles intermediate attributes seamlessly
float4 psMain() : SV_Target {
    return float4(1, 0, 0, 1);
}
        """,
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.vertex, 'drawTriangle'), EntryPoint(Stage.fragment, 'psMain')})),
        )

        # Empty source
        check('', SlangFile())

        # Only line comments and block comments, no code
        check('// just a comment\n/* block comment */', SlangFile('', '', frozenset(), frozenset()))

        # Module and import declarations
        check(
            """
module mymodule;
import utils;
import helpers;
""",
            SlangFile('', '', frozenset({'utils', 'helpers'}), frozenset(), 'mymodule'),
        )

        # pixel stage maps to Stage.fragment
        check(
            """
[shader("pixel")]
float4 pixelMain() : SV_Target { return float4(0); }
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'pixelMain')})),
        )

        # Block comment stripping removes multi-line comments before parsing
        check(
            """
/* This is a block comment
   spanning multiple lines */
[shader("vertex")]
void vertMain() {}
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.vertex, 'vertMain')})),
        )

        # Block comment containing a shader attribute must not create a false entry point
        check(
            """
/* [shader("vertex")]
void shouldNotBeDetected() {} */
[shader("fragment")]
void fragMain() {}
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'fragMain')})),
        )

        # Multiple [attr] lines between [shader(...)] and the function declaration are skipped
        check(
            """
[shader("fragment")]
[numthreads(4, 4, 1)]
[SomeOtherAttribute]
float4 fragMain() : SV_Target { return float4(0); }
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'fragMain')})),
        )

        # Multiple entry points: vertex, pixel, and fragment stages
        check(
            """
[shader("vertex")]
void vsMain(float4 pos : POSITION) {}

[shader("pixel")]
float4 psMain() : SV_Target { return float4(0); }

[shader("fragment")]
float4 fsMain() : SV_Target { return float4(0); }
""",
            SlangFile(
                '',
                '',
                frozenset(),
                frozenset(
                    {
                        EntryPoint(Stage.vertex, 'vsMain'),
                        EntryPoint(Stage.fragment, 'psMain'),
                        EntryPoint(Stage.fragment, 'fsMain'),
                    }
                ),
            ),
        )

        # module, imports and entry points together
        check(
            """
module myshader;
import common;

[shader("vertex")]
void vsMain() {}
""",
            SlangFile('', '', frozenset({'common'}), frozenset({EntryPoint(Stage.vertex, 'vsMain')}), 'myshader'),
        )

        # Autoformat style: return type on its own line before function name
        check(
            """
[shader("vertex")]
VertexOutput
vertex_main(uint vertex_id : SV_VertexID) {}
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.vertex, 'vertex_main')})),
        )

        # Autoformat style: return type on own line, function name + open-paren on next, params on following lines
        check(
            """
[shader("fragment")]
float4
fragment_main(
    float2 texcoord : TEXCOORD
) : SV_Target { return float4(0); }
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'fragment_main')})),
        )

        # Autoformat style: attribute lines between [shader] and split return-type/name declaration
        check(
            """
[shader("fragment")]
[numthreads(1, 1, 1)]
float4
psMain() : SV_Target { return float4(1, 0, 0, 1); }
""",
            SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'psMain')})),
        )

        # Autoformat style: vertex and fragment both split across lines
        check(
            """
[shader("vertex")]
VertexOutput
vsMain(uint id : SV_VertexID) {}

[shader("fragment")]
float4
fsMain(VertexOutput vo) : SV_Target { return float4(0); }
""",
            SlangFile(
                '',
                '',
                frozenset(),
                frozenset({EntryPoint(Stage.vertex, 'vsMain'), EntryPoint(Stage.fragment, 'fsMain')}),
            ),
        )

    def test_slang_ordering(self):
        # Test topological_sort with a manually constructed linear chain: a <- b <- c
        graph: dict[str, SlangFile] = {
            'a': SlangFile('', '', frozenset(), frozenset(), 'a'),
            'b': SlangFile('', '', frozenset({'a'}), frozenset(), 'b'),
            'c': SlangFile('', '', frozenset({'b'}), frozenset(), 'c'),
        }
        order = topological_sort(graph)
        self.assertLess(order.index('a'), order.index('b'))
        self.assertLess(order.index('b'), order.index('c'))

        # Diamond dependency: base <- left, base <- right, left + right <- top
        diamond: dict[str, SlangFile] = {
            'base': SlangFile('', '', frozenset(), frozenset(), 'base'),
            'left': SlangFile('', '', frozenset({'base'}), frozenset(), 'left'),
            'right': SlangFile('', '', frozenset({'base'}), frozenset(), 'right'),
            'top': SlangFile('', '', frozenset({'left', 'right'}), frozenset(), 'top'),
        }
        order2 = topological_sort(diamond)
        self.assertLess(order2.index('base'), order2.index('left'))
        self.assertLess(order2.index('base'), order2.index('right'))
        self.assertLess(order2.index('left'), order2.index('top'))
        self.assertLess(order2.index('right'), order2.index('top'))

        # Node with an import not present in the graph is silently skipped
        partial: dict[str, SlangFile] = {
            'x': SlangFile('', '', frozenset({'missing'}), frozenset(), 'x'),
        }
        self.assertEqual(topological_sort(partial), ['x'])

        # Empty graph
        self.assertEqual(topological_sort({}), [])

        # build_import_graph reads .slang files from a directory tree and parses them
        with tempfile.TemporaryDirectory() as tmpdir:
            files = {
                'a': 'module a;\n',
                'b': 'module b;\nimport a;\n',
                'c': 'module c;\nimport b;\n',
            }
            for name, content in files.items():
                with open(os.path.join(tmpdir, name + '.slang'), 'w') as f:
                    f.write(content)
            graph2 = build_import_graph(tmpdir)
            self.assertEqual(set(graph2.keys()), {'a', 'b', 'c'})
            self.assertEqual(graph2['a'].imports, frozenset())
            self.assertEqual(graph2['b'].imports, frozenset({'a'}))
            self.assertEqual(graph2['c'].imports, frozenset({'b'}))
            self.assertEqual(graph2['a'].module, 'a')

            # Topological sort of file-based graph respects import dependencies
            order3 = topological_sort(graph2)
            self.assertLess(order3.index('a'), order3.index('b'))
            self.assertLess(order3.index('b'), order3.index('c'))

            # Non-.slang files are ignored
            with open(os.path.join(tmpdir, 'ignored.txt'), 'w') as f:
                f.write('not a slang file\n')
            graph3 = build_import_graph(tmpdir)
            self.assertNotIn('ignored', graph3)

    def test_topological_layers(self):
        # Linear chain a <- b <- c produces three layers
        graph: dict[str, SlangFile] = {
            'a': SlangFile('', '', frozenset(), frozenset(), 'a'),
            'b': SlangFile('', '', frozenset({'a'}), frozenset(), 'b'),
            'c': SlangFile('', '', frozenset({'b'}), frozenset(), 'c'),
        }
        layers = topological_layers(graph)
        self.assertEqual(len(layers), 3)
        self.assertIn('a', layers[0])
        self.assertIn('b', layers[1])
        self.assertIn('c', layers[2])

        # Diamond: base <- left, base <- right, left+right <- top
        # base is layer 0, left and right are layer 1, top is layer 2
        diamond: dict[str, SlangFile] = {
            'base': SlangFile('', '', frozenset(), frozenset(), 'base'),
            'left': SlangFile('', '', frozenset({'base'}), frozenset(), 'left'),
            'right': SlangFile('', '', frozenset({'base'}), frozenset(), 'right'),
            'top': SlangFile('', '', frozenset({'left', 'right'}), frozenset(), 'top'),
        }
        layers2 = topological_layers(diamond)
        self.assertEqual(len(layers2), 3)
        self.assertIn('base', layers2[0])
        self.assertIn('left', layers2[1])
        self.assertIn('right', layers2[1])
        self.assertIn('top', layers2[2])

        # Node with import not in graph is treated as layer 0
        partial: dict[str, SlangFile] = {
            'x': SlangFile('', '', frozenset({'missing'}), frozenset(), 'x'),
        }
        layers3 = topological_layers(partial)
        self.assertEqual(len(layers3), 1)
        self.assertIn('x', layers3[0])

        # Empty graph
        self.assertEqual(topological_layers({}), [])

    def test_parse_var_directive(self):
        self.assertEqual(parse_var_directive(['var', 'uint', 'algo', '=', '1']), ('uint', 'algo', '1'))
        self.assertEqual(parse_var_directive(['var', 'float', 'intensity', '=', '0.5']), ('float', 'intensity', '0.5'))
        self.assertEqual(parse_var_directive(['var', 'bool', 'flag', 'true']), ('bool', 'flag', 'true'))
        self.assertEqual(
            parse_var_directive(['var', 'float4', 'tint', '=', 'float4(0,', '0.6,', '0.8,', '1)']),
            ('float4', 'tint', 'float4(0, 0.6, 0.8, 1)'),
        )
        self.assertRaises(ValueError, parse_var_directive, ['var', 'badtype', 'x', '=', '1'])
        self.assertRaises(ValueError, parse_var_directive, ['var', 'uint', '123bad', '=', '1'])
        self.assertRaises(ValueError, parse_var_directive, ['var', 'uint'])

    def test_pointer_map_shaders(self):
        def pms(src: str) -> tuple[tuple[int, int], ...]:
            p = parse_pipeline_definition(src.splitlines(), 'test')
            return pointer_map_shaders(p, lambda g, s: p['groups'][g]['shaders'][s] == 'crt')

        self.ae(pms('startgroup\nshaders crt\nendgroup'), ((0, 0),))
        self.ae(pms('startgroup\nshaders sample\nendgroup'), ())
        # The last shader to run is applied first
        self.ae(pms('startgroup\nshaders crt sample crt\nendgroup\nstartgroup\nshaders crt\nendgroup'), ((1, 0), (0, 2), (0, 0)))
        # Transient effects and passes that do not draw to the screen do not move pointer events
        self.ae(pms('startgroup\nanimation_start tab-change\nshaders crt\nendgroup'), ())
        self.ae(pms('startgroup\nanimation_start user:s\nanimation_stop 100\nshaders crt\nendgroup'), ())
        self.ae(pms('startgroup\nanimation_toggle user:t\nanimation_stop 100\nshaders crt\nendgroup'), ())
        # Effects that last until an event turns them off do
        self.ae(pms('startgroup\nanimation_toggle user:t\nshaders crt\nendgroup'), ((0, 0),))
        self.ae(pms('startgroup\nanimation_start user:s\nanimation_stop never\nshaders crt\nendgroup'), ((0, 0),))
        self.ae(pms('startgroup\nanimation_start user:s\nanimation_stop user:e\nshaders crt\nendgroup'), ((0, 0),))
        self.ae(pms('startgroup\nshaders sample\nendgroup\nstartgroup\nattach\nshaders crt\nendgroup'), ())
        self.ae(pms('textures a\nstartgroup\nshaders crt\noutput_texture a\nendgroup\nstartgroup\nshaders sample\nendgroup'), ())
        # Groups that draw only part of the screen do not move pointer events everywhere
        self.ae(pms('startgroup\nshaders crt\nviewport_size 0.5 1\nendgroup\nstartgroup\nshaders sample\nendgroup'), ())
        self.ae(pms('startgroup\nshaders crt\nviewport_pos 0.5 0\nendgroup\nstartgroup\nshaders sample\nendgroup'), ())

    def test_slang_declarations(self):
        d = parse_slang_declarations("""
#language slang 2026
module m;
import a.b;
// float2 commented_out(float2 pos) { return pos; }
/* float2 also_commented_out(float2 pos) */
static const float4 TINT = float4(0, 0.8, // the tint
    0.6, 1);
static const float ARR[2] = {1, 2};
extern static const bool FLAG;
struct S { float2 not_top_level(float2 p) { return p; } };
public float2
pointer_map(
    float2 pos, KittyCustomShaderData d) : SV_Target {
    static const float local = 1;
    return pos;
}
vector<float, 2> generic<T>(T x) { return float2(0); }
float2 prototype(float2 p);
[shader("fragment")] [numthreads(1, 1, 1)]
float4 frag() { string s = "float2 in_string(float2 p) {}"; return float4(0); }
""")
        self.ae(d.module, 'm')
        self.ae(d.imports, ('a.b',))
        self.ae([f.name for f in d.functions], ['pointer_map', 'generic', 'prototype', 'frag'])
        f = d.function('pointer_map')
        assert f is not None
        self.ae((f.return_type, f.modifiers, f.has_body), ('float2', frozenset({'public'}), True))
        self.ae(d.function('generic').return_type, 'vector<float,2>')
        self.assertFalse(d.function('prototype').has_body)
        self.ae(d.function('frag').attributes, (('shader', ('fragment',)), ('numthreads', ('1', '1', '1'))))
        self.ae(
            [(v.name, v.type, v.modifiers) for v in d.variables],
            [
                ('TINT', 'float4', frozenset({'static', 'const'})),
                ('ARR', 'float', frozenset({'static', 'const'})),
                ('FLAG', 'bool', frozenset({'extern', 'static', 'const'})),
            ],
        )
        self.ae(d.variable('FLAG').declaration, 'extern static const bool FLAG;')
        # # not at the start of a line is not a directive
        self.ae([f.name for f in parse_slang_declarations('float a = 1; # float2 f(float2 p) { return p; }').functions], ['f'])

    def test_cell_contrast_variants(self):
        self.assertFalse(text_contrast_is_identity('legacy'))
        self.assertTrue(text_contrast_is_identity('1'))
        self.assertTrue(text_contrast_is_identity('1.0 0'))
        self.assertFalse(text_contrast_is_identity('1.7 30'))
        self.assertFalse(text_contrast_is_identity('2 0'))
        self.ae(text_contrast_is_identity('platform'), sys.platform != 'darwin')
        variants = cell_variations()
        self.ae(len(variants), 27)
        self.ae(sum(v['TEXT_NEW_GAMMA'] == 'false' for v in variants), 9)
        self.ae(sum(v['TEXT_CONTRAST_IDENTITY'] == 'true' for v in variants), 9)
        for v in variants:
            if v['TEXT_NEW_GAMMA'] == 'false':
                self.ae(v['TEXT_CONTRAST_IDENTITY'], 'false')
        default = cell_variant()
        names = [variant_name(dict(v), default) for v in variants]
        self.ae(len(names), len(set(names)))
        self.assertIn('', names)

    def test_apply_pipeline_specializations(self):
        src = b"""static const float4 TINT = float4(0, 0.8,
    0.6, 1);  // keep me
// static const float SCAN = 0.5;
static const float SCAN = 0.5; static const float  WARP=1;
extern static const bool FLAG = false;
float f() { static const float SCAN = 2; return SCAN; }
"""
        self.ae(apply_pipeline_specializations(src, {}), src)
        merged_vars = {'TINT': ('float3', '0.1'), 'SCAN': ('float', '1'), 'WARP': ('float', '2'), 'FLAG': ('bool', 'true')}
        self.ae(
            apply_pipeline_specializations(src, merged_vars).decode(),
            """static const float3 TINT = 0.1;  // keep me
// static const float SCAN = 0.5;
static const float SCAN = 1; static const float WARP = 2;
extern static const bool FLAG = false;
float f() { static const float SCAN = 2; return SCAN; }
""",
        )

    def test_shader_query(self):
        if not shutil.which(slangc()[0]):
            self.skipTest(f'slangc ({slangc()[0]}) not found in PATH')

        def q(src: str) -> SlangShaderQuery:
            return SlangShaderQuery(src.encode(), 'test')

        def has_pm(src: str) -> bool:
            return defines_pointer_map(q(src))

        self.assertTrue(has_pm(custom_shader('crt')[2].decode()))
        self.assertFalse(has_pm(custom_shader('sample')[2].decode()))
        self.assertTrue(has_pm('public float2\npointer_map(float2 pos, KittyCustomShaderData d) { return pos; }'))
        self.assertTrue(has_pm('public vector<float, 2> pointer_map(float2 pos, KittyCustomShaderData d) { return pos; }'))
        # Comments, disabled code and strings do not count
        self.assertFalse(has_pm('// public float2 pointer_map(float2 pos, KittyCustomShaderData d) { return pos; }'))
        self.assertFalse(has_pm('#if 0\npublic float2 pointer_map(float2 pos, KittyCustomShaderData d) { return pos; }\n#endif'))
        self.assertFalse(has_pm('float2 f(float2 pos) { return pointer_map(pos); }'))
        # The preprocessor is applied
        self.assertTrue(has_pm('#define PM pointer_map\npublic float2 PM(float2 pos, KittyCustomShaderData d) { return pos; }'))
        # Mistakes are reported rather than ignored
        self.assertRaises(ValueError, has_pm, 'float2 pointer_map(float2 pos, KittyCustomShaderData d) { return pos; }')
        self.assertRaises(ValueError, has_pm, 'public float3 pointer_map(float2 pos, KittyCustomShaderData d) { return float3(pos, 0); }')
        # The preprocessor is run only when the answer could depend on it
        tracker: set[tuple[str, ...]] = set()
        self.assertIsNone(SlangShaderQuery(b'float4 f() { return float4(0); }', '', (), tracker).function('pointer_map'))
        self.assertFalse(tracker)

    def test_sample_pointer_map(self):
        import struct

        from kitty.fast_data_types import POINTER_MAP_SIZE, sample_pointer_map

        def grid(f) -> bytes:
            last = POINTER_MAP_SIZE - 1
            vals = []
            for y in range(POINTER_MAP_SIZE):
                for x in range(POINTER_MAP_SIZE):
                    vals.extend(f(x / last, y / last))
            return struct.pack(f'{len(vals)}f', *vals)

        def ae(a, b):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=5)

        identity = grid(lambda u, v: (u, v))
        for pos in ((0, 0), (1, 1), (0.5, 0.25), (0.123, 0.987), (1, 0)):
            ae(sample_pointer_map(identity, *pos), pos)
        # Positions outside the viewport are clamped to its edges
        ae(sample_pointer_map(identity, -0.5, 1.5), (0, 1))
        # Linear maps are reproduced exactly between grid points
        shrink = grid(lambda u, v: (0.1 + 0.8 * u, 1 - v))
        for u, v in ((0, 0), (0.3, 0.6), (1, 1)):
            ae(sample_pointer_map(shrink, u, v), (0.1 + 0.8 * u, 1 - v))
        self.assertRaises(ValueError, sample_pointer_map, b'', 0, 0)

    def test_parse_pipeline_definition_vars(self):
        p = parse_pipeline_definition(
            """
        var uint algo = 1
        var float intensity = 0.5
        startgroup
            shaders sample
        endgroup
        startgroup
            var uint algo = 2
            shaders sample
        endgroup
        """.splitlines(),
            'test',
        )
        self.assertEqual(p['vars'], {'algo': ('uint', '1'), 'intensity': ('float', '0.5')})
        self.assertEqual(p['groups'][0]['vars'], {})
        self.assertEqual(p['groups'][1]['vars'], {'algo': ('uint', '2')})
        # Groups still carry shaders correctly
        self.assertEqual(p['groups'][0]['shaders'], ('sample',))
        self.assertEqual(p['groups'][1]['shaders'], ('sample',))

    def test_build_custom_shader_pipeline_glsl(self):
        if not shutil.which(slangc()[0]):
            self.skipTest(f'slangc ({slangc()[0]}) not found in PATH')

        with tempfile.TemporaryDirectory() as cache_dir:
            # Clear the lru_cache so the temp cache_dir is actually used
            clear_caches()
            p = parse_pipeline_definition(
                """
            startgroup
                shaders sample sample
            endgroup
            """.splitlines(),
                'test',
            )
            try:
                vert_src, frag_src, metadata = build_custom_shader_pipeline_glsl(p, cache_dir=cache_dir)
                invocation_tracker = set()
                build_custom_shader_pipeline_glsl(p, cache_dir=cache_dir, invocation_tracker=invocation_tracker)
            finally:
                clear_caches()

        self.assertIsInstance(vert_src, str)
        self.assertIsInstance(frag_src, str)
        self.assertTrue(len(vert_src) > 0, 'vertex GLSL is empty')
        self.assertTrue(len(frag_src) > 0, 'fragment GLSL is empty')
        self.assertIsInstance(metadata, dict)
        self.assertFalse(metadata['has_pointer_map'])
        self.assertFalse(invocation_tracker)

        with tempfile.TemporaryDirectory() as cache_dir:
            clear_caches()
            # pointer_map() of a group turned on and off by events applies only while it is active
            p = parse_pipeline_definition(
                [
                    'startgroup',
                    'shaders crt',
                    'endgroup',
                    'startgroup',
                    'shaders sample',
                    'endgroup',
                    'startgroup',
                    'animation_toggle user:t',
                    'shaders crt',
                    'endgroup',
                ],
                'test',
            )
            try:
                _, pm_frag_src, pm_metadata = build_custom_shader_pipeline_glsl(p, cache_dir=cache_dir)
            finally:
                clear_caches()
        self.assertTrue(pm_metadata['has_pointer_map'])
        self.ae(pm_metadata['pointer_map_groups'], [0, 2])
        self.assertIn('active_groups', pm_frag_src)

        if not shutil.which('glslangValidator'):
            return

        for src, stage, ext in ((vert_src, 'vert', '.vert.glsl'), (frag_src, 'frag', '.frag.glsl')):
            with tempfile.NamedTemporaryFile(suffix=ext, mode='w', delete=False) as tf:
                tf.write(src)
                tf_path = tf.name
            try:
                cp = subprocess.run(
                    ['glslangValidator', '-S', stage, tf_path],
                    capture_output=True,
                )
                self.assertEqual(
                    cp.returncode,
                    0,
                    f'glslangValidator failed for {stage} shader:\n{cp.stdout.decode()}\n{cp.stderr.decode()}',
                )
            finally:
                os.unlink(tf_path)

    def _content_hash(self) -> str:
        h = hashlib.md5(usedforsecurity=False)
        pkg = ir.files('kitty.shaders.custom')
        for entry in sorted(pkg.iterdir(), key=lambda x: x.name):
            if entry.name.endswith(('.slang', '.pipeline')):
                h.update(entry.name.encode())
                h.update(entry.read_bytes())
        h.update(slangc_version().encode())
        return h.hexdigest()

    def test_all_custom_shaders_compile(self) -> None:
        if __file__ and os.path.isdir((local := os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.cache'))):
            cache_base = local
        else:
            cache_base = tempfile.gettempdir()
        cache_base = os.path.join(cache_base, 'kitty-test-cache')
        os.makedirs(cache_base, exist_ok=True)

        _CACHE_FILE = os.path.join(cache_base, 'custom-shaders-test.json')
        if not shutil.which(slangc()[0]):
            self.skipTest(f'slangc ({slangc()[0]}) not found in PATH')

        current_hash = self._content_hash()

        try:
            with open(_CACHE_FILE) as f:
                if json.load(f).get('hash') == current_hash:
                    return
        except (OSError, json.JSONDecodeError, KeyError):
            pass

        pkg = ir.files('kitty.shaders.custom')
        shader_names = sorted(
            entry.name[: -len('.slang')]
            for entry in pkg.iterdir()
            if entry.name.endswith('.slang') and entry.name[: -len('.slang')] not in _SUPPORT_SHADER_NAMES
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            failures: list[str] = []
            clear_caches()
            for name in shader_names:
                pipeline = parse_pipeline_definition(
                    ['startgroup', f'shaders {name}', 'endgroup'],
                    name,
                )
                try:
                    vert_src, frag_src, _ = build_custom_shader_pipeline_glsl(pipeline, cache_dir=cache_dir)
                except Exception as e:
                    failures.append(f'{name}: {e}')
                    continue
                if not vert_src:
                    failures.append(f'{name}: empty vertex GLSL')
                if not frag_src:
                    failures.append(f'{name}: empty fragment GLSL')
            clear_caches()
            # Builtin pipelines can override constants with var and chain
            # shaders, so compile them as well
            pipeline_names = sorted(entry.name[: -len('.pipeline')] for entry in pkg.iterdir() if entry.name.endswith('.pipeline'))
            for name in pipeline_names:
                try:
                    pipeline = parse_pipeline_definition(get_custom_pipeline_src(name).decode().splitlines(), name)
                    build_custom_shader_pipeline_glsl(pipeline, cache_dir=cache_dir)
                except Exception as e:
                    failures.append(f'{name}.pipeline: {e}')
            clear_caches()

        if failures:
            self.fail('Custom shader compilation failures:\n' + '\n'.join(failures))

        with open(_CACHE_FILE, 'w') as f:
            json.dump({'hash': current_hash}, f)

    def test_builtin_pipelines_bundled(self) -> None:
        # Packaging code filters files by extension, ensure builtin pipelines
        # and the shaders they reference survive in all build types
        pkg = ir.files('kitty.shaders.custom')
        available = {entry.name for entry in pkg.iterdir()}
        pipelines = sorted(x[: -len('.pipeline')] for x in available if x.endswith('.pipeline'))
        self.assertIn('cursor-trail-default', pipelines)
        for name in pipelines:
            p = parse_pipeline_definition(get_custom_pipeline_src(name).decode().splitlines(), name)
            for group in p['groups']:
                for shader in group['shaders']:
                    self.assertIn(f'{shader}.slang', available, f'Shader {shader} used by pipeline {name} is missing')

    def test_pipeline_absolute_path(self) -> None:
        pipeline_content = 'startgroup\n    shaders myshader\nendgroup\n'
        slang_content = b'// shader in pipeline dir\n'

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline_path = os.path.join(tmpdir, 'my.pipeline')
            with open(pipeline_path, 'w') as f:
                f.write(pipeline_content)
            with open(os.path.join(tmpdir, 'myshader.slang'), 'wb') as f:
                f.write(slang_content)

            clear_caches()
            try:
                # Absolute path with .pipeline extension - used as-is
                lines, pipeline_dir = pipeline_definition(pipeline_path)
                self.assertEqual(pipeline_dir, tmpdir)
                self.assertIn('startgroup', lines)

                # Absolute path without .pipeline extension - .pipeline is auto-appended
                clear_caches()
                lines2, pipeline_dir2 = pipeline_definition(pipeline_path[: -len('.pipeline')])
                self.assertEqual(pipeline_dir2, tmpdir)
                self.assertEqual(lines, lines2)

                # Shader lookup finds the file in the pipeline directory first
                found_path, import_dir, src, _ = custom_shader('myshader', tmpdir)
                self.assertEqual(src, slang_content)
                self.assertEqual(import_dir, tmpdir)
            finally:
                clear_caches()

    def test_custom_shader_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = os.path.join(tmpdir, 'pipelines')
            os.mkdir(pdir)

            def w(path: str, data: str) -> str:
                path = os.path.join(tmpdir, path)
                with open(path, 'w') as f:
                    f.write(data)
                return path

            effect = w('effect.slang', '// effect shader\n')
            w('effect.pipeline', 'startgroup\n    shaders effect\nendgroup\n')
            notch = w('notch.slang', '// notch shader\n')
            w('pipelines/other.slang', '// other\n')
            orig_home = os.environ.get('HOME')
            os.environ['HOME'] = tmpdir
            clear_caches()
            try:
                # absolute paths with the extension are not extended again
                self.assertEqual(custom_shader(effect)[0], effect)
                self.assertEqual(custom_shader(effect[: -len('.slang')])[0], effect)
                # ~ is expanded both at top level and inside a pipeline, even
                # when the pipeline is in the same directory as the shader
                self.assertEqual(custom_shader('~/effect.slang')[0], effect)
                self.assertEqual(custom_shader('~/notch', tmpdir)[0], notch)
                self.assertEqual(custom_shader('~/notch', pdir)[0], notch)
                self.assertEqual(custom_shader('other', pdir)[0], os.path.join(pdir, 'other.slang'))
                lines, pipeline_dir = pipeline_definition('~/effect')
                self.assertEqual(pipeline_dir, tmpdir)
                self.assertIn('    shaders effect', lines)
                # names ending with .slang never load pipelines
                with self.assertRaises(FileNotFoundError):
                    pipeline_definition('~/effect.slang')
                # builtins work with or without the extension
                self.assertEqual(custom_shader('crt.slang')[2], custom_shader('crt')[2])
                with self.assertRaises(FileNotFoundError) as cm:
                    custom_shader('~/does-not-exist')
                self.assertIn(os.path.join(tmpdir, 'does-not-exist.slang'), str(cm.exception))
            finally:
                if orig_home is None:
                    os.environ.pop('HOME', None)
                else:
                    os.environ['HOME'] = orig_home
                clear_caches()
