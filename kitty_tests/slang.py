#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import tempfile

from kitty.shaders.slang import EntryPoint, SlangFile, Stage, build_import_graph, parse_slang_text, specialize_cache, topological_sort

from . import BaseTest


class TestSlang(BaseTest):

    def test_slang_parser(self):
        def check(src: str, expected: SlangFile) -> None:
            actual = parse_slang_text(src)
            actual = actual._replace(text='')
            self.assertEqual(expected, actual)

        # Basic vertex + fragment entry points
        check('''
[shader("vertex")]
void drawTriangle(float4 pos : POSITION) {
    // vertex code
}

[shader("fragment")]
[numthreads(1, 1, 1)] // Handles intermediate attributes seamlessly
float4 psMain() : SV_Target {
    return float4(1, 0, 0, 1);
}
        ''', SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.vertex, 'drawTriangle'), EntryPoint(Stage.fragment, 'psMain')})))

        # Empty source
        check('', SlangFile())

        # Only line comments and block comments, no code
        check('// just a comment\n/* block comment */', SlangFile('', '', frozenset(), frozenset()))

        # Module and import declarations
        check('''
module mymodule;
import utils;
import helpers;
''', SlangFile('', '', frozenset({'utils', 'helpers'}), frozenset(), 'mymodule'))

        # pixel stage maps to Stage.fragment
        check('''
[shader("pixel")]
float4 pixelMain() : SV_Target { return float4(0); }
''', SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'pixelMain')})))

        # Block comment stripping removes multi-line comments before parsing
        check('''
/* This is a block comment
   spanning multiple lines */
[shader("vertex")]
void vertMain() {}
''', SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.vertex, 'vertMain')})))

        # Block comment containing a shader attribute must not create a false entry point
        check('''
/* [shader("vertex")]
void shouldNotBeDetected() {} */
[shader("fragment")]
void fragMain() {}
''', SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'fragMain')})))

        # Multiple [attr] lines between [shader(...)] and the function declaration are skipped
        check('''
[shader("fragment")]
[numthreads(4, 4, 1)]
[SomeOtherAttribute]
float4 fragMain() : SV_Target { return float4(0); }
''', SlangFile('', '', frozenset(), frozenset({EntryPoint(Stage.fragment, 'fragMain')})))

        # Multiple entry points: vertex, pixel, and fragment stages
        check('''
[shader("vertex")]
void vsMain(float4 pos : POSITION) {}

[shader("pixel")]
float4 psMain() : SV_Target { return float4(0); }

[shader("fragment")]
float4 fsMain() : SV_Target { return float4(0); }
''', SlangFile('', '', frozenset(), frozenset({
            EntryPoint(Stage.vertex, 'vsMain'),
            EntryPoint(Stage.fragment, 'psMain'),
            EntryPoint(Stage.fragment, 'fsMain'),
        })))

        # module, imports and entry points together
        check('''
module myshader;
import common;

[shader("vertex")]
void vsMain() {}
''', SlangFile('', '', frozenset({'common'}), frozenset({EntryPoint(Stage.vertex, 'vsMain')}), 'myshader'))

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

    def test_specialize_cell_shader(self):
        from kitty.constants import slangc
        from kitty.options.types import Options, defaults
        from kitty.shaders.slang import specialize_cell_shader

        def make_opts(**kwargs):
            d = defaults._asdict()
            d.update(kwargs)
            return Options(d)

        # No action when opts are the same as defaults
        self.assertEqual(specialize_cell_shader(opts=defaults), {})
        self.assertEqual(specialize_cell_shader(opts=None), {})
        # Explicitly constructed opts equal to defaults must also be a no-op
        self.assertEqual(specialize_cell_shader(opts=make_opts()), {})

        if not shutil.which(slangc[0]):
            self.skipTest(f'slangc ({slangc[0]}) not found in PATH')

        # Helper to run specialize_cell_shader with an isolated cache directory.
        # Returns (result_dict, cache_dir_path, create_cache_dir_callable).
        def compile_with_new_cache(opts):
            cache_dir = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, cache_dir, True)
            # Each call with the same callable returns the same directory so
            # that the caching logic inside specialize_cell_shader can kick in.
            def create_cache_dir():
                return cache_dir
            # Clear any pre-existing cache entry for this directory so tests
            # are fully independent of each other.
            specialize_cache.pop(f'cell-{cache_dir}', None)
            result = specialize_cell_shader(create_cache_dir=create_cache_dir, opts=opts)
            return result, cache_dir, create_cache_dir

        # Changing the options must produce non-empty output with compiled shaders.
        opts_legacy = make_opts(text_composition_strategy='legacy')
        result_legacy, cache1, ccdir1 = compile_with_new_cache(opts_legacy)
        self.assertNotEqual(result_legacy, {}, 'Expected non-empty result for non-default opts')

        # Output must include GLSL files whose content is valid GLSL text.
        glsl_items = {k: v.decode() for k, v in result_legacy.items() if k.endswith('.glsl')}
        self.assertTrue(glsl_items, 'Expected at least one .glsl file in the result')
        for name, glsl_text in glsl_items.items():
            self.assertIn('#version', glsl_text, f'{name} should contain a #version directive')

        # With TEXT_NEW_GAMMA=false the compiler eliminates the new-gamma code
        # path, so foreground_contrast_new must NOT appear in the fragment shader.
        frag_glsl = {k: v for k, v in glsl_items.items() if k.endswith('.frag.glsl')}
        self.assertTrue(frag_glsl, 'Expected at least one fragment GLSL file')
        for name, glsl_text in frag_glsl.items():
            self.assertNotIn('foreground_contrast_new', glsl_text,
                             f'{name}: legacy strategy should not contain foreground_contrast_new')

        # Calling with the same opts and the same cache dir must return the
        # identical dict object (cached, no recompilation).
        result_legacy_again = specialize_cell_shader(create_cache_dir=ccdir1, opts=opts_legacy)
        self.assertIs(result_legacy, result_legacy_again,
                      'Second call with unchanged opts must return the cached result')

        # Changing options a second time must produce a different result.
        opts_fg_override = make_opts(text_fg_override_threshold=(0.5, '%'))
        result_fg, cache2, ccdir2 = compile_with_new_cache(opts_fg_override)
        self.assertNotEqual(result_fg, {}, 'Expected non-empty result for fg_override opts')
        self.assertNotEqual(result_legacy, result_fg,
                            'Different opts must produce different compiled output')

        # Verify that the GLSL content actually differs between the two option sets.
        frag_glsl2 = {k: v.decode() for k, v in result_fg.items() if k.endswith('.frag.glsl')}
        for name in frag_glsl:
            if name in frag_glsl2:
                self.assertNotEqual(frag_glsl[name], frag_glsl2[name],
                                    f'{name}: GLSL content must differ between option sets')

        # Calling again with the second option set must also return the cached dict.
        result_fg_again = specialize_cell_shader(create_cache_dir=ccdir2, opts=opts_fg_override)
        self.assertIs(result_fg, result_fg_again,
                      'Second call with unchanged fg_override opts must return the cached result')

