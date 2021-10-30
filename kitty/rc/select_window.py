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

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ans = {'self': opts.self, 'match': opts.match}
        return ans

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        peer_id: int = payload_get('peer_id', missing=0)
        window_id: int = getattr(window, 'id', 0)

        def callback(tab: Optional['Tab'], window: Optional[Window]) -> None:
            from kitty.remote_control import send_response_to_client
            if window:
                send_response_to_client(data=window.id, peer_id=peer_id, window_id=window_id)
            else:
                send_response_to_client(error='No window selected', peer_id=peer_id, window_id=window_id)
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                boss.visual_window_select_action(tab, callback, 'Choose window')
                break
        return no_response


select_window = SelectWindow()
