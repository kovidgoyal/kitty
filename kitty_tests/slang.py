#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile

from kitty.shaders.slang import EntryPoint, SlangFile, Stage, build_import_graph, parse_slang_text, topological_sort

from .base import BaseTest


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
