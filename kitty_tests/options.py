#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>


from . import BaseTest
from kitty.utils import log_error


class TestConfParsing(BaseTest):

    def setUp(self):
        self.error_messages = []
        log_error.redirect = self.error_messages.append

    def tearDown(self):
        del log_error.redirect

    def test_conf_parsing(self):
        from kitty.config import load_config, defaults
        from kitty.constants import is_macos
        from kitty.options.utils import to_modifiers
        bad_lines = []

        def p(*lines, bad_line_num=0):
            del bad_lines[:]
            del self.error_messages[:]
            ans = load_config(overrides=lines, accumulate_bad_lines=bad_lines)
            self.ae(len(bad_lines), bad_line_num)
            return ans

        def keys_for_func(opts, name):
            for key, action in opts.keymap.items():
                if action.func == name:
                    yield key

        opts = p('font_size 11.37', 'clear_all_shortcuts y', 'color23 red')
        self.ae(opts.font_size, 11.37)
        self.ae(opts.mouse_hide_wait, 0 if is_macos else 3)
        self.ae(tuple(opts.color23), (255, 0, 0))
        self.assertFalse(opts.keymap)
        opts = p('clear_all_shortcuts y', 'map f1 next_window')
        self.ae(len(opts.keymap), 1)
        opts = p('strip_trailing_spaces always')
        self.ae(opts.strip_trailing_spaces, 'always')
        self.assertFalse(bad_lines)
        opts = p('pointer_shape_when_grabbed XXX', bad_line_num=1)
        self.ae(opts.pointer_shape_when_grabbed, defaults.pointer_shape_when_grabbed)
        opts = p('env A=1', 'env B=x$A', 'clear_all_shortcuts y', 'kitten_alias a b --moo', 'map f1 kitten a')
        self.ae(opts.env, {'A': '1', 'B': 'x1'})
        ka = tuple(opts.keymap.values())[0]
        self.ae(ka.args, ('b', '--moo'))
        opts = p('kitty_mod alt')
        self.ae(opts.kitty_mod, to_modifiers('alt'))
        self.ae(next(keys_for_func(opts, 'next_layout')).mods, opts.kitty_mod)
        # deprecation handling
        opts = p('clear_all_shortcuts y', 'send_text all f1 hello')
        self.ae(len(opts.keymap), 1)
        opts = p('macos_hide_titlebar y' if is_macos else 'x11_hide_window_decorations y')
        self.assertTrue(opts.hide_window_decorations)
        self.ae(len(self.error_messages), 1)
