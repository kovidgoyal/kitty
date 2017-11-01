#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

from collections import OrderedDict

from kitty.fast_data_types import set_send_sprite_to_gpu
from kitty.fonts.render import set_font_family

from . import BaseTest


class Rendering(BaseTest):

    sprites = OrderedDict()

    @classmethod
    def setUpClass(cls):
        def send_to_gpu(x, y, z, data):
            cls.sprites[(x, y, z)] = data

        set_send_sprite_to_gpu(send_to_gpu)
        cls.cell_width, cls.cell_height = set_font_family(override_dpi=(96.0, 96.0))

    @classmethod
    def tearDownClass(cls):
        set_send_sprite_to_gpu(None)
        cls.sprites.clear()

    def setUp(self):
        self.sprites.clear()

    def tearDown(self):
        self.sprites.clear()

    def test_box_drawing(self):
        pass
