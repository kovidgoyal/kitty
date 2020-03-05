#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


class CLIOptions:
    pass


LaunchCLIOptions = AskCLIOptions = ClipboardCLIOptions = DiffCLIOptions = CLIOptions
HintsCLIOptions = IcatCLIOptions = PanelCLIOptions = ResizeCLIOptions = CLIOptions
ErrorCLIOptions = UnicodeCLIOptions = CLIOptions


def generate_stub() -> None:
    from .cli import parse_option_spec, as_type_stub
    from .conf.definition import save_type_stub
    text = 'import typing\n\n\n'

    def do(otext=None, cls: str = 'CLIOptions'):
        nonlocal text
        text += as_type_stub(*parse_option_spec(otext), class_name=cls)

    do()

    from .launch import options_spec
    do(options_spec(), 'LaunchCLIOptions')

    from kittens.ask.main import option_text
    do(option_text(), 'AskCLIOptions')

    from kittens.clipboard.main import OPTIONS
    do(OPTIONS(), 'ClipboardCLIOptions')

    from kittens.diff.main import OPTIONS
    do(OPTIONS(), 'DiffCLIOptions')

    from kittens.hints.main import OPTIONS
    do(OPTIONS(), 'HintsCLIOptions')

    from kittens.icat.main import OPTIONS
    do(OPTIONS, 'IcatCLIOptions')

    from kittens.panel.main import OPTIONS
    do(OPTIONS(), 'PanelCLIOptions')

    from kittens.resize_window.main import OPTIONS
    do(OPTIONS(), 'ResizeCLIOptions')

    from kittens.show_error.main import OPTIONS
    do(OPTIONS(), 'ErrorCLIOptions')

    from kittens.unicode_input.main import OPTIONS
    do(OPTIONS(), 'UnicodeCLIOptions')

    save_type_stub(text, __file__)


if __name__ == '__main__':
    import subprocess
    subprocess.Popen([
        'kitty', '+runpy',
        'from kitty.cli_stub import generate_stub; generate_stub()'
    ])
