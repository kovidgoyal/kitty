#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import re
from kitty.conf.generate import write_output


def main() -> None:
    from kitty.options.definition import definition
    write_output('kitty', definition)
    nullable_colors = []
    for opt in definition.iter_all_options():
        if callable(opt.parser_func) and opt.parser_func.__name__ in ('to_color_or_none', 'cursor_text_color'):
            nullable_colors.append(opt.name)
    with open('kitty/rc/set_colors.py', 'r+') as f:
        raw = f.read()
        nraw = re.sub(
            r'(# NULLABLE_COLORS_START).+?(\s+# NULLABLE_COLORS_END)',
            r'\1' + '\n    ' + '\n    '.join(map(lambda x: f'{x!r},', sorted(nullable_colors))) + r'\2',
            raw, flags=re.DOTALL | re.MULTILINE)
        if nraw != raw:
            f.seek(0)
            f.truncate()
            f.write(nraw)

    from kittens.diff.options.definition import definition as kd
    write_output('kittens.diff', kd)


if __name__ == '__main__':
    main()
