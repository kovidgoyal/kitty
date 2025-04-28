#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.simple_cli_definitions import build_panel_cli_spec

help_text = 'A quick access terminal window that you can bring up instantly with a keypress or a command.'


def options_spec() -> str:
    if not (ans := getattr(options_spec, 'ans', '')):
        ans = build_panel_cli_spec({
            'lines': '25',
            'columns': '80',
            'edge': 'top',
            'layer': 'overlay',
            'toggle_visibility': 'yes',
            'single_instance': 'yes',
            'instance_group': 'quake',
            'focus_policy': 'exclusive',
            'cls': 'kitty-quick-access',
            'exclusive_zone': '0',
            'override_exclusive_zone': 'yes',
            'override': 'background_opacity=0.8',
        })
        setattr(options_spec, 'ans', ans)
    return ans


def main(args: list[str]) -> None:
    from ..panel.main import main as panel_main
    return panel_main(args)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd: dict = sys.cli_docs  # type: ignore
    cd['usage'] = '[cmdline-to-run ...]'
    cd['options'] = options_spec
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
