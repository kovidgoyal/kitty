#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from collections import OrderedDict

from kitty.fast_data_types import (
    set_send_sprite_to_gpu, sprite_map_set_layout, sprite_map_set_limits,
    test_render_line, test_sprite_position_for
)
from kitty.fonts.box_drawing import box_chars
from kitty.fonts.render import set_font_family

from . import BaseTest


class Rendering(BaseTest):

    def setUp(self):
        sprite_map_set_limits(100000, 100)
        self.sprites = OrderedDict()

        def send_to_gpu(x, y, z, data):
            self.sprites[(x, y, z)] = data

        set_send_sprite_to_gpu(send_to_gpu)
        self.cell_width, self.cell_height = set_font_family(override_dpi=(96.0, 96.0))
        self.assertEqual([k[0] for k in self.sprites], [0, 1, 2, 3, 4])

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
