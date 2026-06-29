#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile

from kitty.shaders.slang import (
    Command, EntryPoint, Specialization, SlangFile, Stage, build_import_graph,
    commands_to_compile_to_glsl, commands_to_compile_to_spirv, create_specialisations,
    parse_slang_text, topological_sort,
)

from . import BaseTest


def make_slang_file(
    path: str = '',
    text: str = '',
    imports: 'frozenset[str] | None' = None,
    entry_points: 'frozenset[EntryPoint] | None' = None,
    module: str = '',
    specializable_variables: 'dict[str, str] | None' = None,
    specializations: 'tuple[Specialization, ...]' = (),
) -> SlangFile:
    return SlangFile(
        path,
        text,
        frozenset() if imports is None else imports,
        frozenset() if entry_points is None else entry_points,
        module,
        {} if specializable_variables is None else specializable_variables,
        specializations,
    )


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
        ''', make_slang_file(entry_points=frozenset({EntryPoint(Stage.vertex, 'drawTriangle'), EntryPoint(Stage.fragment, 'psMain')})))

        # Empty source
        check('', make_slang_file())

        # Only line comments and block comments, no code
        check('// just a comment\n/* block comment */', make_slang_file())

        # Module and import declarations
        check('''
module mymodule;
import utils;
import helpers;
''', make_slang_file(imports=frozenset({'utils', 'helpers'}), module='mymodule'))

        # pixel stage maps to Stage.fragment
        check('''
[shader("pixel")]
float4 pixelMain() : SV_Target { return float4(0); }
''', make_slang_file(entry_points=frozenset({EntryPoint(Stage.fragment, 'pixelMain')})))

        # Block comment stripping removes multi-line comments before parsing
        check('''
/* This is a block comment
   spanning multiple lines */
[shader("vertex")]
void vertMain() {}
''', make_slang_file(entry_points=frozenset({EntryPoint(Stage.vertex, 'vertMain')})))

        # Block comment containing a shader attribute must not create a false entry point
        check('''
/* [shader("vertex")]
void shouldNotBeDetected() {} */
[shader("fragment")]
void fragMain() {}
''', make_slang_file(entry_points=frozenset({EntryPoint(Stage.fragment, 'fragMain')})))

        # Multiple [attr] lines between [shader(...)] and the function declaration are skipped
        check('''
[shader("fragment")]
[numthreads(4, 4, 1)]
[SomeOtherAttribute]
float4 fragMain() : SV_Target { return float4(0); }
''', make_slang_file(entry_points=frozenset({EntryPoint(Stage.fragment, 'fragMain')})))

        # Multiple entry points: vertex, pixel, and fragment stages
        check('''
[shader("vertex")]
void vsMain(float4 pos : POSITION) {}

[shader("pixel")]
float4 psMain() : SV_Target { return float4(0); }

[shader("fragment")]
float4 fsMain() : SV_Target { return float4(0); }
''', make_slang_file(entry_points=frozenset({
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
''', make_slang_file(imports=frozenset({'common'}), entry_points=frozenset({EntryPoint(Stage.vertex, 'vsMain')}), module='myshader'))

    def test_slang_ordering(self):
        # Test topological_sort with a manually constructed linear chain: a <- b <- c
        graph: dict[str, SlangFile] = {
            'a': make_slang_file(module='a'),
            'b': make_slang_file(imports=frozenset({'a'}), module='b'),
            'c': make_slang_file(imports=frozenset({'b'}), module='c'),
        }
        order = topological_sort(graph)
        self.assertLess(order.index('a'), order.index('b'))
        self.assertLess(order.index('b'), order.index('c'))

        # Diamond dependency: base <- left, base <- right, left + right <- top
        diamond: dict[str, SlangFile] = {
            'base': make_slang_file(module='base'),
            'left': make_slang_file(imports=frozenset({'base'}), module='left'),
            'right': make_slang_file(imports=frozenset({'base'}), module='right'),
            'top': make_slang_file(imports=frozenset({'left', 'right'}), module='top'),
        }
        order2 = topological_sort(diamond)
        self.assertLess(order2.index('base'), order2.index('left'))
        self.assertLess(order2.index('base'), order2.index('right'))
        self.assertLess(order2.index('left'), order2.index('top'))
        self.assertLess(order2.index('right'), order2.index('top'))

        # Node with an import not present in the graph is silently skipped
        partial: dict[str, SlangFile] = {
            'x': make_slang_file(imports=frozenset({'missing'}), module='x'),
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

    def test_slang_specialization_parsing(self):
        def check(src: str, expected: SlangFile) -> None:
            actual = parse_slang_text(src)
            actual = actual._replace(text='')
            self.assertEqual(expected, actual)

        # Single specialization with one variable
        check(
            '// specialize: my_spec: VAR=1\n',
            make_slang_file(specializations=(Specialization('my_spec', {'VAR': '1'}),)))

        # Single specialization with multiple variables on one line
        check(
            '// specialize: spec1: A=hello B=world\n',
            make_slang_file(specializations=(Specialization('spec1', {'A': 'hello', 'B': 'world'}),)))

        # Multiple specializations produce an ordered tuple
        check('''
// specialize: spec_a: X=1
// specialize: spec_b: X=2
''', make_slang_file(specializations=(
            Specialization('spec_a', {'X': '1'}),
            Specialization('spec_b', {'X': '2'}),
        )))

        # extern static const is captured as a specializable variable
        check(
            'extern static const float myVar = 1.0;\n',
            make_slang_file(specializable_variables={'myVar': 'extern static const float myVar = 1.0;'}))

        # Multiple extern static const declarations are all captured
        check('''
extern static const int WIDTH = 8;
extern static const int HEIGHT = 4;
''', make_slang_file(specializable_variables={
            'WIDTH': 'extern static const int WIDTH = 8;',
            'HEIGHT': 'extern static const int HEIGHT = 4;',
        }))

        # extern without static const is NOT captured as specializable
        check('extern float myVar;\n', make_slang_file())
        check('extern const float myVar = 0.0;\n', make_slang_file())

        # Combined: specializable variables, specializations, imports and entry points
        check('''
module myshader;
import common;
extern static const float MAX_CELLS = 10.0;
// specialize: large_cells: MAX_CELLS=100.0
// specialize: small_cells: MAX_CELLS=2.0

[shader("fragment")]
void fragMain() {}
''', make_slang_file(
            module='myshader',
            imports=frozenset({'common'}),
            entry_points=frozenset({EntryPoint(Stage.fragment, 'fragMain')}),
            specializable_variables={'MAX_CELLS': 'extern static const float MAX_CELLS = 10.0;'},
            specializations=(
                Specialization('large_cells', {'MAX_CELLS': '100.0'}),
                Specialization('small_cells', {'MAX_CELLS': '2.0'}),
            ),
        ))

        # Specialization comment inside a block comment is stripped and never processed
        check('/* // specialize: ignored_spec: VAR=1 */', make_slang_file())

        # Specialization comment alongside ordinary line comments
        check('''
// regular comment
// specialize: sp: A=1
// another regular comment
''', make_slang_file(specializations=(Specialization('sp', {'A': '1'}),)))

    def test_slang_create_specialisations(self):
        ep = EntryPoint(Stage.fragment, 'fragMain')
        sv = {'MAX_CELLS': 'extern static const int MAX_CELLS = 10;'}

        with tempfile.TemporaryDirectory() as tmpdir:
            base_name = 'myshader'
            base_dest = os.path.join(tmpdir, base_name)

            def make_sfile(**kw: object) -> SlangFile:
                return make_slang_file(
                    path=os.path.join(tmpdir, 'myshader.slang'),
                    entry_points=frozenset({ep}),
                    specializable_variables=sv,
                    **kw,  # type: ignore[arg-type]
                )

            sfile = make_sfile(specializations=(Specialization('large', {'MAX_CELLS': '100'}),))
            sources = {base_name: sfile}

            # First call: file does not exist yet, needs_build=True
            cmds = list(create_specialisations(sources, tmpdir, tmpdir))
            self.assertEqual(len(cmds), 1)
            cmd = cmds[0]
            self.assertIsInstance(cmd, Command)
            self.assertTrue(cmd.needs_build)

            # Generated .slang file exists and has the right content:
            # 'extern' replaced by 'export', value overridden
            spec_slang = f'{base_dest}.large.slang'
            self.assertTrue(os.path.exists(spec_slang))
            with open(spec_slang) as f:
                content = f.read()
            self.assertIn('export static const int MAX_CELLS', content)
            self.assertIn('= 100;', content)
            self.assertNotIn('extern', content)

            # Second call with identical content: needs_build=False (idempotent)
            cmds2 = list(create_specialisations(sources, tmpdir, tmpdir))
            self.assertEqual(len(cmds2), 1)
            self.assertFalse(cmds2[0].needs_build)

            # Changing the specialization value: needs_build=True again
            sfile_changed = make_sfile(specializations=(Specialization('large', {'MAX_CELLS': '999'}),))
            cmds3 = list(create_specialisations({base_name: sfile_changed}, tmpdir, tmpdir))
            self.assertEqual(len(cmds3), 1)
            self.assertTrue(cmds3[0].needs_build)

            # Multiple specializations: one command (and file) per specialization
            sfile_multi = make_sfile(specializations=(
                Specialization('small', {'MAX_CELLS': '5'}),
                Specialization('large', {'MAX_CELLS': '200'}),
            ))
            cmds4 = list(create_specialisations({base_name: sfile_multi}, tmpdir, tmpdir))
            self.assertEqual(len(cmds4), 2)
            generated_files = {os.path.basename(c.cmd[-3]) for c in cmds4}
            self.assertIn('myshader.small.slang', generated_files)
            self.assertIn('myshader.large.slang', generated_files)

            # No entry_points: no commands emitted even with specializations
            sfile_no_ep = make_slang_file(
                path=os.path.join(tmpdir, 'myshader.slang'),
                specializable_variables=sv,
                specializations=(Specialization('large', {'MAX_CELLS': '100'}),),
            )
            self.assertEqual(list(create_specialisations({base_name: sfile_no_ep}, tmpdir, tmpdir)), [])

            # No specializations: no commands emitted even with entry_points
            sfile_no_sp = make_sfile()
            self.assertEqual(list(create_specialisations({base_name: sfile_no_sp}, tmpdir, tmpdir)), [])

    def test_slang_commands_with_specializations(self):
        ep_frag = EntryPoint(Stage.fragment, 'fragMain')
        ep_vert = EntryPoint(Stage.vertex, 'vsMain')
        sv = {'MAX_CELLS': 'extern static const int MAX_CELLS = 10;'}

        with tempfile.TemporaryDirectory() as tmpdir:
            base_name = 'myshader'
            base_dest = os.path.join(tmpdir, base_name)
            slang_module = f'{base_dest}.slang-module'
            # Module file must exist for mtime-based needs_build checks
            open(slang_module, 'w').close()

            def make_sources(**kw: object) -> dict[str, SlangFile]:
                return {base_name: make_slang_file(
                    path=f'{base_dest}.slang',
                    entry_points=frozenset({ep_frag}),
                    **kw,  # type: ignore[arg-type]
                )}

            # --- SPIRV: no specializations ---
            built: list[str] = []
            cmds = list(commands_to_compile_to_spirv(make_sources(), tmpdir, tmpdir, built))
            self.assertEqual(len(cmds), 1)
            # Output is the bare .spv, no spec name in filename
            self.assertEqual(cmds[0].cmd[-1], f'{base_dest}.spv')
            # Output is recorded in built_files list when needs_build=True
            self.assertIn(f'{base_dest}.spv', built)

            # --- SPIRV: one specialization produces two commands (base + specialized) ---
            built2: list[str] = []
            cmds2 = list(commands_to_compile_to_spirv(
                make_sources(specializable_variables=sv, specializations=(Specialization('large', {'MAX_CELLS': '100'}),)),
                tmpdir, tmpdir, built2,
            ))
            self.assertEqual(len(cmds2), 2)
            dests2 = {c.cmd[-1] for c in cmds2}
            self.assertIn(f'{base_dest}.spv', dests2)
            self.assertIn(f'{base_dest}.large.spv', dests2)
            # The specialized command includes the spec module before the main module
            large_cmd = next(c for c in cmds2 if c.cmd[-1] == f'{base_dest}.large.spv')
            self.assertIn(f'{base_dest}.large.slang-module', large_cmd.cmd)

            # --- SPIRV: two specializations produce three commands ---
            built3: list[str] = []
            cmds3 = list(commands_to_compile_to_spirv(
                make_sources(specializable_variables=sv, specializations=(
                    Specialization('small', {'MAX_CELLS': '5'}),
                    Specialization('large', {'MAX_CELLS': '100'}),
                )),
                tmpdir, tmpdir, built3,
            ))
            self.assertEqual(len(cmds3), 3)
            dests3 = {c.cmd[-1] for c in cmds3}
            self.assertIn(f'{base_dest}.spv', dests3)
            self.assertIn(f'{base_dest}.small.spv', dests3)
            self.assertIn(f'{base_dest}.large.spv', dests3)

            # --- GLSL: no specializations, one entry point -> one command ---
            built_g: list[str] = []
            gcmds = list(commands_to_compile_to_glsl(make_sources(), tmpdir, tmpdir, built_g))
            self.assertEqual(len(gcmds), 1)
            self.assertEqual(gcmds[0].cmd[-1], f'{base_dest}.fragment.glsl')

            # --- GLSL: one specialization, one entry point -> two commands ---
            built_g2: list[str] = []
            gcmds2 = list(commands_to_compile_to_glsl(
                make_sources(specializable_variables=sv, specializations=(Specialization('large', {'MAX_CELLS': '100'}),)),
                tmpdir, tmpdir, built_g2,
            ))
            self.assertEqual(len(gcmds2), 2)
            gdests2 = {c.cmd[-1] for c in gcmds2}
            self.assertIn(f'{base_dest}.fragment.glsl', gdests2)
            self.assertIn(f'{base_dest}.large.fragment.glsl', gdests2)
            # Specialized command includes the spec module
            large_gcmd = next(c for c in gcmds2 if c.cmd[-1] == f'{base_dest}.large.fragment.glsl')
            self.assertIn(f'{base_dest}.large.slang-module', large_gcmd.cmd)

            # --- GLSL: two entry points, one specialization -> four commands ---
            built_g3: list[str] = []
            gcmds3 = list(commands_to_compile_to_glsl(
                {base_name: make_slang_file(
                    path=f'{base_dest}.slang',
                    entry_points=frozenset({ep_frag, ep_vert}),
                    specializable_variables=sv,
                    specializations=(Specialization('large', {'MAX_CELLS': '100'}),),
                )},
                tmpdir, tmpdir, built_g3,
            ))
            self.assertEqual(len(gcmds3), 4)
            gdests3 = {c.cmd[-1] for c in gcmds3}
            self.assertIn(f'{base_dest}.fragment.glsl', gdests3)
            self.assertIn(f'{base_dest}.vertex.glsl', gdests3)
            self.assertIn(f'{base_dest}.large.fragment.glsl', gdests3)
            self.assertIn(f'{base_dest}.large.vertex.glsl', gdests3)
