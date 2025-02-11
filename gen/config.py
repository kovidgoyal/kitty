#!./kitty/launcher/kitty +launch
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import re
import subprocess
import sys

from kitty.conf.generate import write_output

if __name__ == '__main__' and not __package__:
    import __main__
    __main__.__package__ = 'gen'
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def patch_color_list(path: str, colors: list[str], name: str, spc: str = '    ') -> None:
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


def main(args: list[str]=sys.argv) -> None:
    from kitty.options.definition import definition
    nullable_colors = []
    all_colors = []
    for opt in definition.iter_all_options():
        if callable(opt.parser_func):
            if opt.parser_func.__name__ in ('to_color_or_none', 'cursor_text_color'):
                nullable_colors.append(opt.name)
                all_colors.append(opt.name)
            elif opt.parser_func.__name__ in ('to_color', 'titlebar_color', 'macos_titlebar_color'):
                all_colors.append(opt.name)
    patch_color_list('tools/cmd/at/set_colors.go', nullable_colors, 'NULLABLE')
    patch_color_list('tools/themes/collection.go', all_colors, 'ALL')
    nc = ',\n    '.join(f'{x!r}' for x in nullable_colors)
    write_output('kitty', definition, f'\nnullable_colors = frozenset({{\n    {nc}\n}})\n')


if __name__ == '__main__':
    import runpy
    m = runpy.run_path(os.path.dirname(os.path.abspath(__file__)))
    m['main']([sys.executable, 'config'])
