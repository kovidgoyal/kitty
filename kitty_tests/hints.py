#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any
from unittest.mock import Mock, patch

from kittens.hints.main import handle_result

from .base import BaseTest


class TestHints(BaseTest):
    def test_multiple_selection_actions(self):
        for matches in ([], [''], ['alpha', 'beta']):
            for joiner, expected in (('auto', 'alpha beta'), ('json', '[\n\t"alpha",\n\t"beta"\n]'), ('0', 'alpha'), ('-1', 'beta')):
                with self.subTest(matches=matches, joiner=joiner):
                    boss: Any = Mock()
                    window = Mock()
                    boss.window_id_map = {1: window}
                    data = {
                        'customize_processing': '',
                        'type': 'word',
                        'programs': ['@', '*', '@test', '-'],
                        'match': matches,
                        'groupdicts': [{} for _ in matches],
                        'multiple_joiner': joiner,
                    }
                    with patch('kittens.hints.main.set_clipboard_string') as clipboard, patch('kittens.hints.main.set_primary_selection') as primary:
                        handle_result([], data, 1, boss)
                        if any(matches):
                            clipboard.assert_called_once_with(expected)
                            primary.assert_called_once_with(expected)
                            boss.set_clipboard_buffer.assert_called_once_with('test', expected)
                            window.paste_text.assert_called_once_with(expected)
                        else:
                            clipboard.assert_not_called()
                            primary.assert_not_called()
                            boss.set_clipboard_buffer.assert_not_called()
                            window.paste_text.assert_not_called()

    def test_custom_handler_receives_empty_selection(self):
        boss: Any = Mock()
        custom_handler = Mock()
        data = {'customize_processing': 'custom.py', 'type': 'word', 'match': [], 'groupdicts': [], 'extra_cli_args': ['extra']}
        with patch('kittens.hints.main.load_custom_processor', return_value={'handle_result': custom_handler}):
            handle_result([], data, 1, boss)
        custom_handler.assert_called_once_with([], data, 1, boss, ['extra'])

    def test_named_groups_are_passed_to_program(self):
        boss: Any = Mock()
        boss.window_id_map = {}
        handle_result(
            [],
            {
                'customize_processing': '',
                'type': 'regex',
                'programs': ['echo'],
                'match': ['ignored'],
                'groupdicts': [{'name': 'value', 'empty': None}],
                'multiple_joiner': '',
                'cwd': '/tmp',
            },
            1,
            boss,
        )
        boss.open_url.assert_called_once_with(['name=value', 'empty='], 'echo', cwd='/tmp')
