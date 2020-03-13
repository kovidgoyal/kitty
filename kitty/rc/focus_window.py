#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional

from kitty.fast_data_types import focus_os_window

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType,
    RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import FocusWindowRCOptions as CLIOptions


class FocusWindow(RemoteCommand):
    '''
    match: The window to focus
    '''

    short_desc = 'Focus the specified window'
    desc = 'Focus the specified window, if no window is specified, focus the window this command is run inside.'
    argspec = ''
    options_spec = MATCH_WINDOW_OPTION + '''\n\n
--no-response
type=bool-set
default=false
Don't wait for a response from kitty. This means that even if no matching window is found,
the command will exit with a success code.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if opts.no_response:
            global_opts.no_command_response = True
        return {'match': opts.match, 'no_response': opts.no_response}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                os_window_id = boss.set_active_window(window)
                if os_window_id:
                    focus_os_window(os_window_id, True)
                break


focus_window = FocusWindow()
