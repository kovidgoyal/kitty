#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile
from unittest.mock import patch

from kitty.options.types import defaults
from kitty.shaders.slang import specialize_cache, specialize_cell_shader

from . import BaseTest


class TestShaders(BaseTest):

    def test_specialize_cell_shader(self):
        specialize_cache.clear()

        # No action when opts are the same as defaults
        self.assertEqual(specialize_cell_shader(opts=defaults), {})

        # Mock out compilation to avoid needing slangc
        call_count = [0]

        def fake_specialize_shaders_to(sources, dest_dir):
            call_count[0] += 1
            with open(os.path.join(dest_dir, 'cell.glsl'), 'wb') as f:
                f.write(b'fake shader ' + str(call_count[0]).encode())

        def fake_ensure_cache_dir(path):
            os.makedirs(path, exist_ok=True)

        with patch('kitty.shaders.slang.specialize_shaders_to', fake_specialize_shaders_to), \
             patch('kitty.shaders.slang.ensure_cache_dir', fake_ensure_cache_dir):

            # Changing options produces non-empty shaders
            opts1 = defaults._replace(text_composition_strategy='legacy')
            with tempfile.TemporaryDirectory() as dir1:
                result1 = specialize_cell_shader(create_cache_dir=lambda: dir1, opts=opts1)
            self.assertNotEqual(result1, {})

            # Changing to different options produces different shaders
            opts2 = defaults._replace(text_fg_override_threshold=(10.0, '%'))
            with tempfile.TemporaryDirectory() as dir2:
                result2 = specialize_cell_shader(create_cache_dir=lambda: dir2, opts=opts2)
            self.assertNotEqual(result2, {})
            self.assertNotEqual(result1, result2)

            # Calling twice with the same options returns the same object
            opts3 = defaults._replace(text_composition_strategy='legacy')
            with tempfile.TemporaryDirectory() as dir3:
                get_dir3 = lambda: dir3
                result3a = specialize_cell_shader(create_cache_dir=get_dir3, opts=opts3)
                result3b = specialize_cell_shader(create_cache_dir=get_dir3, opts=opts3)
            self.assertIs(result3a, result3b)
