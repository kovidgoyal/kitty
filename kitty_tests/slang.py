#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>


from kitty.shaders.slang import EntryPoint, SlangFile, Stage, parse_slang_text

from . import BaseTest


class TestSlang(BaseTest):

    def test_slang_parser(self):
        for src, expected in {
            '''
[shader("vertex")]
void drawTriangle(float4 pos : POSITION) {
    // vertex code
}

[shader("fragment")]
[numthreads(1, 1, 1)] // Handles intermediate attributes seamlessly
float4 psMain() : SV_Target {
    return float4(1, 0, 0, 1);
}
            ''': SlangFile(
                '', '', frozenset(), frozenset({EntryPoint(Stage.vertex, 'drawTriangle'), EntryPoint(Stage.fragment, 'psMain')}), ''),
                }.items():
            actual = parse_slang_text(src)
            actual = actual._replace(text='')
            self.assertEqual(expected, actual)

    def test_slang_ordering(self):
        pass  # TODO: Test get_ordered_sources_in_tree()
