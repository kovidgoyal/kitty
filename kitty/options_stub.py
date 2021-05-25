#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


class Options:
    pass


DiffOptions = Options


def generate_stub():
    from .config_data import all_options
    from .conf.definition import as_type_stub, save_type_stub
    text = as_type_stub(
        all_options,
        preamble_lines=(
            'from kitty.types import SingleKey',
            'from kitty.config import KeyAction, KeyMap, SequenceMap, MouseMap',
            'from kitty.fonts import FontFeature',
        ),
        extra_fields=(
            ('keymap', 'KeyMap'),
            ('sequence_map', 'SequenceMap'),
            ('mousemap', 'MouseMap'),
        )
    )

    from kittens.diff.config_data import all_options
    text += as_type_stub(
        all_options,
        class_name='DiffOptions',
        preamble_lines=(
            'from kitty.conf.utils import KittensKeyAction',
            'from kitty.types import ParsedShortcut',
        ),
        extra_fields=(
            ('key_definitions', 'typing.Dict[ParsedShortcut, KittensKeyAction]'),
        )
    )

    save_type_stub(text, __file__)


if __name__ == '__main__':
    import subprocess
    subprocess.Popen([
        'kitty', '+runpy',
        'from kitty.options_stub import generate_stub; generate_stub()'
    ])
