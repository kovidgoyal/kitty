#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from collections.abc import Sequence


class CLIOptions:
    def __repr__(self) -> str:
        return repr(vars(self))


LaunchCLIOptions = AskCLIOptions = ClipboardCLIOptions = DiffCLIOptions = CLIOptions
HintsCLIOptions = IcatCLIOptions = PanelCLIOptions = ResizeCLIOptions = CLIOptions
ErrorCLIOptions = UnicodeCLIOptions = RCOptions = RemoteFileCLIOptions = CLIOptions
BroadcastCLIOptions = ShowKeyCLIOptions = SaveAsSessionOptions = GotoSessionOptions = CLIOptions
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

    from daddies.ask.main import option_text

    do(option_text(), 'AskCLIOptions')

    from daddies.remote_file.main import option_text

    do(option_text(), 'RemoteFileCLIOptions')

    from daddies.clipboard.main import OPTIONS

    do(OPTIONS(), 'ClipboardCLIOptions')

    from daddies.show_key.main import OPTIONS

    do(OPTIONS(), 'ShowKeyCLIOptions')

    from daddies.diff.main import OPTIONS

    do(OPTIONS(), 'DiffCLIOptions')

    from daddies.hints.main import OPTIONS

    do(OPTIONS(), 'HintsCLIOptions')

    from daddies.broadcast.main import OPTIONS

    do(OPTIONS(), 'BroadcastCLIOptions')

    from daddies.icat.main import OPTIONS as OS

    do(OS, 'IcatCLIOptions')

    from daddies.panel.main import panel_daddy_options_spec

    do(panel_daddy_options_spec(), 'PanelCLIOptions')

    from daddies.resize_window.main import OPTIONS

    do(OPTIONS(), 'ResizeCLIOptions')

    from daddies.unicode_input.main import OPTIONS

    do(OPTIONS(), 'UnicodeCLIOptions')

    from daddies.themes.main import OPTIONS

    do(OPTIONS(), 'ThemesCLIOptions')

    from daddies.transfer.main import option_text

    do(option_text(), 'TransferCLIOptions')

    from datty.session import goto_session_options, save_as_session_options

    do(save_as_session_options(), 'SaveAsSessionOptions')
    do(goto_session_options(), 'GotoSessionOptions')

    from datty.rc.base import all_command_names, command_for_name

    for cmd_name in all_command_names():
        cmd = command_for_name(cmd_name)
        if cmd.options_spec:
            do(cmd.options_spec, f'{cmd.__class__.__name__}RCOptions')

    save_type_stub(text, __file__)


if __name__ == '__main__':
    import subprocess

    subprocess.Popen(['datty', '+runpy', 'from datty.cli_stub import generate_stub; generate_stub()'])
