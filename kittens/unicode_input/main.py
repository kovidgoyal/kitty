#!/usr/bin/env python3
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

from typing import List, Optional

from kitty.typing import BossType

from ..tui.handler import result_handler

help_text = 'Input a Unicode character'
usage = ''
OPTIONS = '''
--emoji-variation
type=choices
default=none
choices=none,graphic,text
Whether to use the textual or the graphical form for emoji. By default the
default form specified in the Unicode standard for the symbol is used.


'''.format


@result_handler(has_ready_notification=True)
def handle_result(args: List[str], current_char: str, target_window_id: int, boss: BossType) -> None:
    w = boss.window_id_map.get(target_window_id)
    if w is not None:
        w.paste_text(current_char)

def main(args: List[str]) -> Optional[str]:
    raise SystemExit('This should be run as kitten unicode_input')

if __name__ == '__main__':
    main([])
elif __name__ == '__doc__':
    import sys
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Browse and select unicode characters by name'
