#!/usr/bin/env python
# License: GPL v3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys
import unittest

from . import BaseTest

_plat = sys.platform.lower()
is_macos = 'darwin' in _plat


class TestGLFW(BaseTest):

    def test_os_window_size_calculation(self):
        from kitty.utils import get_new_os_window_size

        def t(w, h, width=0, height=0, unit='cells', incremental=False):
            self.ae((w, h), get_new_os_window_size(metrics, width, height, unit, incremental, has_window_scaling))

        with self.subTest(has_window_scaling=False):
            has_window_scaling = False
            metrics = {
                'width': 200, 'height': 100,
                'framebuffer_width': 200, 'framebuffer_height': 100,
                'xscale': 2.0, 'yscale': 2.0, 'xdpi': 192.0, 'ydpi': 192.0,
                'cell_width': 8, 'cell_height': 16
            }
            t(80 * metrics['cell_width'], 100, 80)
            t(80 * metrics['cell_width'] + metrics['width'], 100, 80, incremental=True)
            t(1217, 100, 1217, unit='pixels')
            t(1217 + metrics['width'], 100, 1217, unit='pixels', incremental=True)

        with self.subTest(has_window_scaling=True):
            has_window_scaling = True
            metrics['framebuffer_width'] = metrics['width'] * 2
            metrics['framebuffer_height'] = metrics['height'] * 2
            t(80 * metrics['cell_width'] / metrics['xscale'], 100, 80)
            t(80 * metrics['cell_width'] / metrics['xscale'] + metrics['width'], 100, 80, incremental=True)
            t(1217, 100, 1217, unit='pixels')
            t(1217 + metrics['width'], 100, 1217, unit='pixels', incremental=True)

    @unittest.skipIf(is_macos, 'Skipping test on macOS because glfw-cocoa.so is not built with backend_utils')
    def test_utf_8_strndup(self):
        import ctypes

        from kitty.constants import glfw_path

        backend_utils = glfw_path('x11')
        lib = ctypes.CDLL(backend_utils)
        libc = ctypes.CDLL(None)

        class allocated_c_char_p(ctypes.c_char_p):
            def __del__(self):
                libc.free(self)

        utf_8_strndup = lib.utf_8_strndup
        utf_8_strndup.restype = allocated_c_char_p
        utf_8_strndup.argtypes = (ctypes.c_char_p, ctypes.c_size_t)

        def test(string):
            string_bytes = bytes(string, 'utf-8')
            prev_part_bytes = b''
            prev_length_bytes = -1
            for length in range(len(string) + 1):
                part = string[:length]
                part_bytes = bytes(part, 'utf-8')
                length_bytes = len(part_bytes)
                for length_bytes_2 in range(prev_length_bytes + 1, length_bytes):
                    self.ae(utf_8_strndup(string_bytes, length_bytes_2).value, prev_part_bytes)
                self.ae(utf_8_strndup(string_bytes, length_bytes).value, part_bytes)
                prev_part_bytes = part_bytes
                prev_length_bytes = length_bytes
            self.ae(utf_8_strndup(string_bytes, len(string_bytes) + 1).value, string_bytes)  # Try to go one character after the end of the string

        self.ae(utf_8_strndup(None, 2).value, None)
        self.ae(utf_8_strndup(b'', 2).value, b'')

        test('ö')
        test('>a<')
        test('>ä<')
        test('>ế<')
        test('>𐍈<')
        test('∮ E⋅da = Q,  n → ∞, 𐍈∑ f(i) = ∏ g(i)')
        self.ae(utf_8_strndup(b'\xf0\x9f\x98\xb8', 3).value, b'')
        self.ae(utf_8_strndup(b'\xc3\xb6\xf0\x9f\x98\xb8', 4).value, b'\xc3\xb6')
