#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import hashlib
import importlib.resources as ir
import json
import os
import shutil
import subprocess
import tempfile

from kitty.constants import slangc
from kitty.shaders.slang import (
    EntryPoint,
    SlangFile,
    Stage,
    build_custom_shader_pipeline_glsl,
    build_import_graph,
    clear_caches,
    custom_shader,
    parse_pipeline_definition,
    parse_slang_text,
    parse_var_directive,
    pipeline_definition,
    slangc_version,
    topological_layers,
    topological_sort,
)

from .base import BaseTest

_SUPPORT_SHADER_NAMES = frozenset(('types', 'pipeline'))


class TestSlang(BaseTest):
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
        self.assertFalse(invocation_tracker)

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

        _CACHE_DIR = os.path.join(cache_base, 'custom-shaders-slangc-cache')
        os.makedirs(_CACHE_DIR, exist_ok=True)
        failures: list[str] = []
        clear_caches()
        try:
            for name in shader_names:
                pipeline = parse_pipeline_definition(
                    ['startgroup', f'shaders {name}', 'endgroup'],
                    name,
                )
                try:
                    vert_src, frag_src, _ = build_custom_shader_pipeline_glsl(pipeline, cache_dir=_CACHE_DIR)
                except Exception as e:
                    failures.append(f'{name}: {e}')
                    continue
                if not vert_src:
                    failures.append(f'{name}: empty vertex GLSL')
                if not frag_src:
                    failures.append(f'{name}: empty fragment GLSL')
        finally:
            clear_caches()

        if failures:
            self.fail('Custom shader compilation failures:\n' + '\n'.join(failures))

        with open(_CACHE_FILE, 'w') as f:
            json.dump({'hash': current_hash}, f)

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
