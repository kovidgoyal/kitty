#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from collections import OrderedDict

from kitty.fast_data_types import set_send_sprite_to_gpu, test_render_line, sprite_map_set_limits
from kitty.fonts.render import set_font_family
from kitty.fonts.box_drawing import box_chars

from . import BaseTest


class Rendering(BaseTest):

    def setUp(self):
        self.sprites = OrderedDict()

        def send_to_gpu(x, y, z, data):
            self.sprites[(x, y, z)] = data

        set_send_sprite_to_gpu(send_to_gpu)
        sprite_map_set_limits(100000, 100)
        self.cell_width, self.cell_height = set_font_family(override_dpi=(96.0, 96.0))
        self.assertEqual([k[0] for k in self.sprites], [0, 1, 2, 3, 4])

    def tearDown(self):
        set_send_sprite_to_gpu(None)
        del self.sprites

    def test_box_drawing(self):
        prerendered = len(self.sprites)
        s = self.create_screen(cols=len(box_chars), lines=1, scrollback=0)
        s.draw(''.join(box_chars))
        line = s.line(0)
        test_render_line(line)
        print(self.sprites.keys())
        self.assertEqual(len(self.sprites), prerendered + len(box_chars))
