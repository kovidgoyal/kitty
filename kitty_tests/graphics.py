#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os

from . import BaseTest


def img_path(name):
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


class TestGraphics(BaseTest):

    def test_load_images(self):
        s = self.create_screen()
        # c = s.callbacks
        g = s.grman
        print(g)
