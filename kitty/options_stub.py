#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


class Options:
    pass


def generate_stub():
    from .config_data import all_options
    from .conf.definition import as_type_stub, save_type_stub
    text = as_type_stub(
        all_options,
        special_types={
            'symbol_map': 'typing.Dict[typing.Tuple[int, int], str]'
        },
        preamble_lines=(
            'from kitty.config import KeyAction',
            'KeySpec = typing.Tuple[int, bool, int]',
            'KeyMap = typing.Dict[KeySpec, KeyAction]',
        ),
        extra_fields=(
            ('keymap', 'KeyMap'),
            ('sequence_map', 'typing.Dict[KeySpec, KeyMap]'),
        )
    )
    save_type_stub(text, __file__)


if __name__ == '__main__':
    import subprocess
    subprocess.Popen([
        'kitty', '+runpy',
        'from kitty.options_stub import generate_stub; generate_stub()'
    ])
