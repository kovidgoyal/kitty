#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import re
from typing import List

from kitty.conf.generate import write_output


def patch_color_list(path: str, colors: List[str], name: str, spc: str = '    ') -> None:
    with open(path, 'r+') as f:
        raw = f.read()
        nraw = re.sub(
            fr'(# {name}_COLORS_START).+?(\s+# {name}_COLORS_END)',
            r'\1' + f'\n{spc}' + f'\n{spc}'.join(map(lambda x: f'{x!r},', sorted(colors))) + r'\2',
            raw, flags=re.DOTALL | re.MULTILINE)
        if nraw != raw:
            f.seek(0)
            f.truncate()
            f.write(nraw)


def main() -> None:
    from kitty.options.definition import definition
    write_output('kitty', definition)
    nullable_colors = []
    all_colors = []
    for opt in definition.iter_all_options():
        if callable(opt.parser_func):
            if opt.parser_func.__name__ in ('to_color_or_none', 'cursor_text_color'):
                nullable_colors.append(opt.name)
                all_colors.append(opt.name)
            elif opt.parser_func.__name__ in ('to_color', 'titlebar_color', 'macos_titlebar_color'):
                all_colors.append(opt.name)
    patch_color_list('kitty/rc/set_colors.py', nullable_colors, 'NULLABLE')
    patch_color_list('kittens/themes/collection.py', all_colors, 'ALL', ' ' * 8)

    from kittens.diff.options.definition import definition as kd
    write_output('kittens.diff', kd)
    from kittens.ssh.options.definition import definition as sd
    write_output('kittens.ssh', sd)


if __name__ == '__main__':
    main()
