#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from kitty.cli import emph

from .base import (
    MATCH_TAB_OPTION,
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    ParsingOfArgsFailed,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    RemoteControlErrorWithoutTraceback,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetColorsRCOptions as CLIOptions
    from kitty.colors import TransparentBackgroundColors


class SetColors(RemoteCommand):
    protocol_spec = __doc__ = """
    colors+/dict.colors: Map of names to 24-bit RGB ints or null for nullable colors. transparent_background_colors is a string, empty to clear, absent to keep.
    match_window/str: Window to change colors in
    match_tab/str: Tab to change colors in
    all/bool: Boolean indicating change colors everywhere or not
    configured/bool: Boolean indicating whether to change the configured colors. Must be True if reset is True
    reset/bool: Boolean indicating colors should be reset to startup values
    """

    short_desc = 'Set terminal colors'
    desc = (
        'Set the terminal colors for the specified windows/tabs (defaults to active window).'
        ' You can either specify the path to a conf file'
        ' (in the same format as :file:`kitty.conf`) to read the colors from or you can specify individual colors,'
        ' for example::\n\n'
        '    kitten @ set-colors foreground=red background=white'
    )
    options_spec = (
        """\
--all -a
type=bool-set
By default, colors are only changed for the currently active window. This option will
cause colors to be changed in all windows.


--configured -c
type=bool-set
Also change the configured colors (i.e. the colors kitty will use for new
windows or after a reset).


--reset
type=bool-set
Restore all colors to the values they had at kitty startup. Note that if you specify
this option, any color arguments are ignored and :option:`kitten @ set-colors --configured` and :option:`kitten @ set-colors --all` are implied.
"""
        + '\n\n'
        + MATCH_WINDOW_OPTION
        + '\n\n'
        + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')
    )
    args = RemoteCommand.Args(
        spec='COLOR_OR_FILE ...',
        json_field='colors',
        special_parse='+all,configured,reset:parse_colors_and_files(args, options_set_colors, &payload)',
        completion=RemoteCommand.CompletionSpec.from_string('type:file group:"CONF files", ext:conf'),
    )

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        final_colors: dict[str, int | None | str] = {}
        transparent_background_colors: 'TransparentBackgroundColors | None' = None
        from kitty.colors import parse_colors

        if not opts.reset:
            try:
                fc, transparent_background_colors = parse_colors(args)
            except FileNotFoundError as err:
                raise ParsingOfArgsFailed(f'The colors configuration file {emph(err.filename)} was not found.') from err
            except Exception as err:
                raise ParsingOfArgsFailed(str(err)) from err
            final_colors.update(fc)
        if transparent_background_colors is not None:
            final_colors['transparent_background_colors'] = ' '.join(f'{c.as_sharp}@{f}' for c, f in transparent_background_colors)
        ans = {
            'match_window': opts.match,
            'match_tab': opts.match_tab,
            'all': opts.all or opts.reset,
            'configured': opts.configured or opts.reset,
            'colors': final_colors,
            'reset': opts.reset,
        }
        return ans

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        from kitty.colors import patch_colors

        colors: dict[str, int | None] = {}
        tbc: TransparentBackgroundColors | None = None
        # reset implies all and configured, enforce it here as not all clients set them
        reset = bool(payload_get('reset'))
        configured = reset or bool(payload_get('configured'))
        windows = list(boss.all_windows) if reset else self.windows_for_payload(boss, window, payload_get)
        if reset:
            colors = {k: None if v is None else int(v) for k, v in boss.color_settings_at_startup.items()}
            tbc = boss.transparent_background_colors_at_startup
        else:
            payload_colors: dict[str, int | str | None] = payload_get('colors') or {}
            for k, v in payload_colors.items():
                if k == 'transparent_background_colors':
                    tbc = self.parse_transparent_background_colors(v)
                elif isinstance(v, str):
                    raise RemoteControlErrorWithoutTraceback(f'The color {k} must be an integer or null, not a string')
                else:
                    colors[k] = v
        patch_colors(colors, tbc, configured, windows=windows, replace_window_colors=True)
        return None

    def parse_transparent_background_colors(self, spec: int | str | None) -> 'TransparentBackgroundColors':
        from kitty.options.utils import transparent_background_colors

        if not isinstance(spec, str):
            raise RemoteControlErrorWithoutTraceback('transparent_background_colors must be a string')
        try:
            return transparent_background_colors(spec)
        except ValueError as err:
            raise RemoteControlErrorWithoutTraceback(f'Invalid transparent_background_colors: {spec!r} with error: {err}') from err


set_colors = SetColors()
