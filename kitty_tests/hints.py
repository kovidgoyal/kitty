#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any
from unittest.mock import Mock

from kittens.hints.main import handle_result

from .base import BaseTest


class TestHints(BaseTest):
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
