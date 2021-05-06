#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2017, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import sys
import tempfile
import unittest
from functools import partial
try:
    from importlib.resources import read_binary
except ImportError:
    from importlib_resources import read_binary

from kitty.constants import is_macos
from kitty.fast_data_types import (
    DECAWM, get_fallback_font, sprite_map_set_layout, sprite_map_set_limits,
    test_render_line, test_sprite_position_for, wcwidth
)
from kitty.fonts.box_drawing import box_chars
from kitty.fonts.render import (
    coalesce_symbol_maps, render_string, setup_for_testing, shape_string
)

from . import BaseTest


class Rendering(BaseTest):

    def setUp(self):
        self.test_ctx = setup_for_testing()
        self.test_ctx.__enter__()
        self.sprites, self.cell_width, self.cell_height = self.test_ctx.__enter__()
        try:
            self.assertEqual([k[0] for k in self.sprites], [0, 1, 2, 3, 4, 5, 6, 7, 8])
        except Exception:
            self.test_ctx.__exit__()
            del self.test_ctx
            raise
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        self.test_ctx.__exit__()
        del self.sprites, self.cell_width, self.cell_height, self.test_ctx
        shutil.rmtree(self.tdir)

    def test_sprite_map(self):
        sprite_map_set_limits(10, 2)
        sprite_map_set_layout(5, 5)
        self.ae(test_sprite_position_for(0), (0, 0, 0))
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
        s = self.create_screen(cols=len(box_chars) + 1, lines=1, scrollback=0)
        s.draw(''.join(box_chars))
        line = s.line(0)
        test_render_line(line)
        self.assertEqual(len(self.sprites) - prerendered, len(box_chars))

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

        font_path_cache = {}

        def path_for_font(name):
            if name not in font_path_cache:
                with open(os.path.join(self.tdir, name), 'wb') as f:
                    font_path_cache[name] = f.name
                    data = read_binary(__name__.rpartition('.')[0], name)
                    f.write(data)
            return font_path_cache[name]

        def ss(text, font=None):
            path = path_for_font(font) if font else None
            return shape_string(text, path=path)

        def groups(text, font=None):
            return [x[:2] for x in ss(text, font)]

        for font in ('FiraCode-Medium.otf', 'CascadiaCode-Regular.otf'):
            g = partial(groups, font=font)
            self.ae(g('abcd'), [(1, 1) for i in range(4)])
            self.ae(g('----'), [(4, 4)])
            self.ae(g('A===B!=C'), [(1, 1), (3, 3), (1, 1), (2, 2), (1, 1)])
            self.ae(g('F--a--'), [(1, 1), (2, 2), (1, 1), (2, 2)])
            self.ae(g('===--<>=='), [(3, 3), (2, 2), (2, 2), (2, 2)])
            self.ae(g('==!=<>==<><><>'), [(4, 4), (2, 2), (2, 2), (2, 2), (2, 2), (2, 2)])
            self.ae(g('A=>>B!=C'), [(1, 1), (3, 3), (1, 1), (2, 2), (1, 1)])
            self.ae(g('-' * 18), [(18, 18)])
        colon_glyph = ss('9:30', font='FiraCode-Medium.otf')[1][2]
        self.assertNotEqual(colon_glyph, ss(':', font='FiraCode-Medium.otf')[0][2])
        self.ae(colon_glyph, 1031)
        self.ae(groups('9:30', font='FiraCode-Medium.otf'), [(1, 1), (1, 1), (1, 1), (1, 1)])

        self.ae(groups('|\U0001F601|\U0001F64f|\U0001F63a|'), [(1, 1), (2, 1), (1, 1), (2, 1), (1, 1), (2, 1), (1, 1)])
        self.ae(groups('He\u0347\u0305llo\u0337,', font='LiberationMono-Regular.ttf'),
                [(1, 1), (1, 3), (1, 1), (1, 1), (1, 2), (1, 1)])

        self.ae(groups('i\u0332\u0308', font='LiberationMono-Regular.ttf'), [(1, 2)])
        self.ae(groups('u\u0332 u\u0332\u0301', font='LiberationMono-Regular.ttf'), [(1, 2), (1, 1), (1, 2)])

    def test_emoji_presentation(self):
        s = self.create_screen()
        s.draw('\u2716\u2716\ufe0f')
        self.ae((s.cursor.x, s.cursor.y), (3, 0))
        s.draw('\u2716\u2716')
        self.ae((s.cursor.x, s.cursor.y), (5, 0))
        s.draw('\ufe0f')
        self.ae((s.cursor.x, s.cursor.y), (2, 1))
        self.ae(str(s.line(0)), '\u2716\u2716\ufe0f\u2716')
        self.ae(str(s.line(1)), '\u2716\ufe0f')
        s.draw('\u2716' * 3)
        self.ae((s.cursor.x, s.cursor.y), (5, 1))
        self.ae(str(s.line(1)), '\u2716\ufe0f\u2716\u2716\u2716')
        self.ae((s.cursor.x, s.cursor.y), (5, 1))
        s.reset_mode(DECAWM)
        s.draw('\ufe0f')
        s.set_mode(DECAWM)
        self.ae((s.cursor.x, s.cursor.y), (5, 1))
        self.ae(str(s.line(1)), '\u2716\ufe0f\u2716\u2716\ufe0f')
        s.cursor.y = s.lines - 1
        s.draw('\u2716' * s.columns)
        self.ae((s.cursor.x, s.cursor.y), (5, 4))
        s.draw('\ufe0f')
        self.ae((s.cursor.x, s.cursor.y), (2, 4))
        self.ae(str(s.line(s.cursor.y)), '\u2716\ufe0f')

    @unittest.skipUnless(is_macos, 'Only macOS has a Last Resort font')
    def test_fallback_font_not_last_resort(self):
        # Ensure that the LastResort font is not reported as a fallback font on
        # macOS. See https://github.com/kovidgoyal/kitty/issues/799
        from io import StringIO
        orig, buf = sys.stderr, StringIO()
        sys.stderr = buf
        try:
            self.assertRaises(ValueError, get_fallback_font, '\U0010FFFF', False, False)
        finally:
            sys.stderr = orig
        self.assertIn('LastResort', buf.getvalue())

    def test_coalesce_symbol_maps(self):
        q = {(2, 3): 'a', (4, 6): 'b', (5, 5): 'b', (7, 7): 'b', (9, 9): 'b', (1, 1): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 3): 'a', (4, 7): 'b', (9, 9): 'b'})
        q = {(1, 4): 'a', (2, 3): 'b'}
        self.ae(coalesce_symbol_maps(q), {(1, 1): 'a', (2, 3): 'b', (4, 4): 'a'})
        q = {(2, 3): 'b', (1, 4): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 4): 'a'})
        q = {(1, 4): 'a', (2, 5): 'b'}
        self.ae(coalesce_symbol_maps(q), {(1, 1): 'a', (2, 5): 'b'})
        q = {(2, 5): 'b', (1, 4): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 4): 'a', (5, 5): 'b'})
        q = {(1, 4): 'a', (2, 5): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 5): 'a'})
        q = {(1, 4): 'a', (4, 5): 'b'}
        self.ae(coalesce_symbol_maps(q), {(1, 3): 'a', (4, 5): 'b'})
        q = {(4, 5): 'b', (1, 4): 'a'}
        self.ae(coalesce_symbol_maps(q), {(1, 4): 'a', (5, 5): 'b'})
        q = {(0, 30): 'a', (10, 10): 'b', (11, 11): 'b', (2, 2): 'c', (1, 1): 'c'}
        self.ae(coalesce_symbol_maps(q), {
            (0, 0): 'a', (1, 2): 'c', (3, 9): 'a', (10, 11): 'b', (12, 30): 'a'})
