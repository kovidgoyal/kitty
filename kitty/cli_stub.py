#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from collections.abc import Sequence


class CLIOptions:
    def __repr__(self) -> str:
        return repr(vars(self))


LaunchCLIOptions = AskCLIOptions = ClipboardCLIOptions = DiffCLIOptions = CLIOptions
HintsCLIOptions = IcatCLIOptions = PanelCLIOptions = ResizeCLIOptions = CLIOptions
ErrorCLIOptions = UnicodeCLIOptions = RCOptions = RemoteFileCLIOptions = CLIOptions
BroadcastCLIOptions = ShowKeyCLIOptions = CLIOptions
ThemesCLIOptions = TransferCLIOptions = LoadConfigRCOptions = ActionRCOptions = CLIOptions


def generate_stub() -> None:
    from .cli import as_type_stub
    from .conf.utils import save_type_stub
    from .simple_cli_definitions import parse_option_spec
    text = 'import typing\n\n\n'

    def do(otext: str | None = None, cls: str = 'CLIOptions', extra_fields: Sequence[str] = ()) -> None:
        nonlocal text
        text += as_type_stub(*parse_option_spec(otext), class_name=cls, extra_fields=extra_fields)

    do(extra_fields=('args: typing.List[str]',))

    from .launch import options_spec
    do(options_spec(), 'LaunchCLIOptions')

    from .remote_control import global_options_spec
    do(global_options_spec(), 'RCOptions')

    from kittens.ask.main import option_text
    do(option_text(), 'AskCLIOptions')

    from kittens.remote_file.main import option_text
    do(option_text(), 'RemoteFileCLIOptions')

    from kittens.clipboard.main import OPTIONS
    do(OPTIONS(), 'ClipboardCLIOptions')

    from kittens.show_key.main import OPTIONS
    do(OPTIONS(), 'ShowKeyCLIOptions')

    from kittens.diff.main import OPTIONS
    do(OPTIONS(), 'DiffCLIOptions')

    from kittens.hints.main import OPTIONS
    do(OPTIONS(), 'HintsCLIOptions')

    from kittens.broadcast.main import OPTIONS
    do(OPTIONS(), 'BroadcastCLIOptions')

    from kittens.icat.main import OPTIONS as OS
    do(OS, 'IcatCLIOptions')

    from kittens.panel.main import panel_kitten_options_spec
    do(panel_kitten_options_spec(), 'PanelCLIOptions')

    from kittens.resize_window.main import OPTIONS
    do(OPTIONS(), 'ResizeCLIOptions')

    from kittens.unicode_input.main import OPTIONS
    do(OPTIONS(), 'UnicodeCLIOptions')

    from kittens.themes.main import OPTIONS
    do(OPTIONS(), 'ThemesCLIOptions')

    from kittens.transfer.main import option_text
    do(option_text(), 'TransferCLIOptions')

    from kitty.rc.base import all_command_names, command_for_name
    for cmd_name in all_command_names():
        cmd = command_for_name(cmd_name)
        if cmd.options_spec:
            do(cmd.options_spec, f'{cmd.__class__.__name__}RCOptions')

    save_type_stub(text, __file__)


if __name__ == '__main__':
    import subprocess
    subprocess.Popen([
        'kitty', '+runpy',
        'from kitty.cli_stub import generate_stub; generate_stub()'
    ])
