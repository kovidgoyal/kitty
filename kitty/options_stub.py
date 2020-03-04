#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os


class Options:
    pass


def generate_stub():
    from .config_data import all_options
    from .conf.definition import as_type_stub
    text = as_type_stub(
        all_options,
        special_types={
            'symbol_map': 'typing.Dict[typing.Tuple[int, int], str]'
        }
    )
    with open(__file__ + 'i', 'w') as f:
        print(
            '# Update this file by running: python {}'.format(os.path.relpath(os.path.abspath(__file__))),
            file=f
        )
        f.write(text)


if __name__ == '__main__':
    import subprocess
    subprocess.Popen([
        'kitty', '+runpy',
        'from kitty.options_stub import generate_stub; generate_stub()'
    ])
