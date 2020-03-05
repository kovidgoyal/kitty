# Update this file by running: python kitty/cli_stub.py
import typing


class CLIOptions:
    cls: str
    name: str
    title: str
    config: typing.Sequence[str]
    override: typing.Sequence[str]
    directory: str
    detach: bool
    session: str
    hold: bool
    single_instance: bool
    instance_group: str
    wait_for_single_instance_window_close: bool
    listen_on: str
    start_as: str
    version: bool
    dump_commands: bool
    replay_commands: str
    dump_bytes: str
    debug_gl: bool
    debug_keyboard: bool
    debug_font_fallback: bool
    debug_config: bool
    execute: bool


class LaunchCLIOptions:
    window_title: str
    tab_title: str
    type: str
    keep_focus: bool
    cwd: str
    env: typing.Sequence[str]
    copy_colors: bool
    copy_cmdline: bool
    copy_env: bool
    location: str
    allow_remote_control: bool
    stdin_source: str
    stdin_add_formatting: bool
    stdin_add_line_wrap_markers: bool
    marker: str


class AskCLIOptions:
    type: str
    message: str
    name: str


class ClipboardCLIOptions:
    get_clipboard: bool
    use_primary: bool
    wait_for_completion: bool


class DiffCLIOptions:
    context: int
    config: typing.Sequence[str]
    override: typing.Sequence[str]


class HintsCLIOptions:
    program: typing.Sequence[str]
    type: str
    regex: str
    linenum_action: str
    url_prefixes: str
    word_characters: str
    minimum_match_length: int
    multiple: bool
    multiple_joiner: str
    add_trailing_space: str
    hints_offset: int
    alphabet: str
    ascending: bool
    customize_processing: str


class IcatCLIOptions:
    align: str
    place: str
    scale_up: bool
    clear: bool
    transfer_mode: str
    detect_support: bool
    detection_timeout: float
    print_window_size: bool
    stdin: str
    silent: bool
    z_index: str


class PanelCLIOptions:
    lines: int
    columns: int
    edge: str
    config: typing.Sequence[str]
    override: typing.Sequence[str]


class ResizeCLIOptions:
    horizontal_increment: int
    vertical_increment: int


class ErrorCLIOptions:
    title: str


class UnicodeCLIOptions:
    emoji_variation: str


