#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window, no_response
)

if TYPE_CHECKING:
    from kitty.cli_stub import LaunchRCOptions as CLIOptions
    from kitty.tabs import Tab


class SelectWindow(RemoteCommand):

    '''
    match: The tab to open the new window in
    self: Boolean, if True use tab the command was run in
    '''

    short_desc = 'Visually select a window in the specified tab'
    desc = (
        ' Prints out the id of the selected window. Other commands '
        ' can then be chained to make use of it.'
    )
    options_spec = MATCH_TAB_OPTION + '\n\n' + '''\
--response-timeout
type=float
default=60
The time in seconds to wait for the user to select a window.


--self
type=bool-set
If specified the tab containing the window this command is run in is used
instead of the active tab.
'''
    is_asynchronous = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ans = {'self': opts.self, 'match': opts.match}
        return ans

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        responder = self.create_async_responder(payload_get, window)

        def callback(tab: Optional['Tab'], window: Optional[Window]) -> None:
            if window:
                responder.send_data(window.id)
            else:
                responder.send_error('No window selected')
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                boss.visual_window_select_action(tab, callback, 'Choose window')
                break
        return no_response

    def cancel_async_request(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> None:
        boss.cancel_current_visual_select()


select_window = SelectWindow()
