#!./kitty/launcher/kitty +launch
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import re
import subprocess
from typing import List

from kitty.conf.generate import write_output


def patch_color_list(path: str, colors: List[str], name: str, spc: str = '    ') -> None:
    with open(path, 'r+') as f:
        raw = f.read()
        colors = sorted(colors)
        if path.endswith('.go'):
            spc = '\t'
            nraw = re.sub(
                fr'(// {name}_COLORS_START).+?(\s+// {name}_COLORS_END)',
                r'\1' + f'\n{spc}' + f'\n{spc}'.join(map(lambda x: f'"{x}":true,', colors)) + r'\2',
                raw, flags=re.DOTALL | re.MULTILINE)
        else:
            nraw = re.sub(
                fr'(# {name}_COLORS_START).+?(\s+# {name}_COLORS_END)',
                r'\1' + f'\n{spc}' + f'\n{spc}'.join(map(lambda x: f'{x!r},', colors)) + r'\2',
                raw, flags=re.DOTALL | re.MULTILINE)
        if nraw != raw:
            f.seek(0)
            f.truncate()
            f.write(nraw)
            f.flush()
            if path.endswith('.go'):
                subprocess.check_call(['gofmt', '-w', path])


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
    patch_color_list('tools/cmd/at/set_colors.go', nullable_colors, 'NULLABLE')
    patch_color_list('tools/themes/collection.go', all_colors, 'ALL')


if __name__ == '__main__':
    main()
