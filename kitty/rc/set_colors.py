#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


import os
from typing import TYPE_CHECKING, Dict, Optional, Union

from kitty.config import parse_config
from kitty.fast_data_types import patch_color_profiles
from kitty.rgb import Color, color_as_int

from .base import (
    MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetColorsRCOptions as CLIOptions


class SetColors(RemoteCommand):

    '''
    colors+: An object mapping names to colors as 24-bit RGB integers
    cursor_text_color: A 24-bit color for text under the cursor, or null to use background.
    match_window: Window to change colors in
    match_tab: Tab to change colors in
    all: Boolean indicating change colors everywhere or not
    configured: Boolean indicating whether to change the configured colors. Must be True if reset is True
    reset: Boolean indicating colors should be reset to startup values
    '''

    short_desc = 'Set terminal colors'
    desc = (
        'Set the terminal colors for the specified windows/tabs (defaults to active window).'
        ' You can either specify the path to a conf file'
        ' (in the same format as kitty.conf) to read the colors from or you can specify individual colors,'
        ' for example: kitty @ set-colors foreground=red background=white'
    )
    options_spec = '''\
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
this option, any color arguments are ignored and --configured and --all are implied.
''' + '\n\n' + MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')
    argspec = 'COLOR_OR_FILE ...'
    args_completion = {'files': ('CONF files', ('*.conf',))}

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        final_colors: Dict[str, int] = {}
        cursor_text_color: Optional[Union[int, bool]] = False
        if not opts.reset:
            colors: Dict[str, Optional[Color]] = {}
            for spec in args:
                if '=' in spec:
                    colors.update(parse_config((spec.replace('=', ' '),)))
                else:
                    with open(os.path.expanduser(spec), encoding='utf-8', errors='replace') as f:
                        colors.update(parse_config(f))
            ctc = colors.pop('cursor_text_color', False)
            if isinstance(ctc, Color):
                cursor_text_color = color_as_int(ctc)
            elif ctc is None:
                cursor_text_color = None
            final_colors = {k: color_as_int(v) for k, v in colors.items() if isinstance(v, Color)}
        ans = {
            'match_window': opts.match, 'match_tab': opts.match_tab,
            'all': opts.all or opts.reset, 'configured': opts.configured or opts.reset,
            'colors': final_colors, 'reset': opts.reset, 'dummy': 0
        }
        if cursor_text_color is not False:
            ans['cursor_text_color'] = cursor_text_color
        del ans['dummy']
        return ans

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_payload(boss, window, payload_get)
        colors = payload_get('colors')
        cursor_text_color = payload_get('cursor_text_color', missing=False)
        if payload_get('reset'):
            colors = {k: color_as_int(v) for k, v in boss.startup_colors.items()}
            cursor_text_color = boss.startup_cursor_text_color
        profiles = tuple(w.screen.color_profile for w in windows)
        if isinstance(cursor_text_color, (tuple, list, Color)):
            cursor_text_color = color_as_int(Color(*cursor_text_color))
        patch_color_profiles(colors, cursor_text_color, profiles, payload_get('configured'))
        boss.patch_colors(colors, cursor_text_color, payload_get('configured'))
        default_bg_changed = 'background' in colors
        for w in windows:
            if default_bg_changed:
                boss.default_bg_changed_for(w.id)
            w.refresh()


set_colors = SetColors()
