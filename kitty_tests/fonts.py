#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from collections import OrderedDict

from kitty.constants import is_macos
from kitty.fast_data_types import (
    change_wcwidth, set_logical_dpi, set_send_sprite_to_gpu,
    sprite_map_set_layout, sprite_map_set_limits, test_render_line,
    test_sprite_position_for, wcwidth
)
from kitty.fonts.box_drawing import box_chars
from kitty.fonts.render import (
    prerender, render_string, set_font_family, shape_string
)

from . import BaseTest


class Rendering(BaseTest):

    def setUp(self):
        sprite_map_set_limits(100000, 100)
        self.sprites = OrderedDict()

        def send_to_gpu(x, y, z, data):
            self.sprites[(x, y, z)] = data

        set_send_sprite_to_gpu(send_to_gpu)
        set_logical_dpi(96.0, 96.0)
        self.cell_width, self.cell_height = set_font_family()
        prerender()
        self.assertEqual([k[0] for k in self.sprites], [0, 1, 2, 3, 4, 5])

    def tearDown(self):
        set_send_sprite_to_gpu(None)
        del self.sprites

    def test_sprite_map(self):
        sprite_map_set_limits(10, 2)
        sprite_map_set_layout(5, 5)
        self.ae(test_sprite_position_for(0), (0, 0, 0))
        self.ae(test_sprite_position_for(1), (1, 0, 0))
        self.ae(test_sprite_position_for(2), (0, 1, 0))
        self.ae(test_sprite_position_for(3), (1, 1, 0))
        self.ae(test_sprite_position_for(4), (0, 0, 1))
        self.ae(test_sprite_position_for(5), (1, 0, 1))
        self.ae(test_sprite_position_for(0, 1), (0, 1, 1))
        self.ae(test_sprite_position_for(0, 2), (1, 1, 1))
        self.ae(test_sprite_position_for(0, 2), (1, 1, 1))

    def test_box_drawing(self):
        prerendered = len(self.sprites)
        s = self.create_screen(cols=len(box_chars), lines=1, scrollback=0)
        s.draw(''.join(box_chars))
        line = s.line(0)
        test_render_line(line)
        self.assertEqual(len(self.sprites), prerendered + len(box_chars))

    def test_font_rendering(self):
        render_string('ab\u0347\u0305你好|\U0001F601|\U0001F64f|\U0001F63a|')
        text = 'He\u0347\u0305llo\u0341, w\u0302or\u0306l\u0354d!'
        # macOS has no fonts capable of rendering combining chars
        if is_macos:
            text = text.encode('ascii', 'ignore').decode('ascii')
        cells = render_string(text)[-1]
        self.ae(len(cells), len(text.encode('ascii', 'ignore')))
        text = '你好,世界'
        sz = sum(map(lambda x: wcwidth(ord(x)), text))
        cells = render_string(text)[-1]
        self.ae(len(cells), sz)

    def test_shaping(self):
        change_wcwidth(True)
        try:

            def groups(text, path=None):
                return [x[:2] for x in shape_string(text, path=path)]

            self.ae(groups('abcd'), [(1, 1) for i in range(4)])
            self.ae(groups('A=>>B!=C', path='kitty_tests/FiraCode-Medium.otf'), [(1, 1), (3, 3), (1, 1), (2, 2), (1, 1)])
            colon_glyph = shape_string('9:30', path='kitty_tests/FiraCode-Medium.otf')[1][2]
            self.assertNotEqual(colon_glyph, shape_string(':', path='kitty_tests/FiraCode-Medium.otf')[0][2])
            self.ae(colon_glyph, 998)
            self.ae(groups('9:30', path='kitty_tests/FiraCode-Medium.otf'), [(1, 1), (1, 1), (1, 1), (1, 1)])
            self.ae(groups('|\U0001F601|\U0001F64f|\U0001F63a|'), [(1, 1), (2, 1), (1, 1), (2, 1), (1, 1), (2, 1), (1, 1)])
            self.ae(groups('He\u0347\u0305llo\u0337,', path='kitty_tests/LiberationMono-Regular.ttf'),
                    [(1, 1), (1, 3), (1, 1), (1, 1), (1, 2), (1, 1)])
        finally:
            change_wcwidth(False)
