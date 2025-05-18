#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from kitty.types import AsyncResponse

from .base import MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SelectWindowRCOptions as CLIOptions
    from kitty.tabs import Tab


class SelectWindow(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: The tab to open the new window in
    self/bool: Boolean, if True use tab the command was run in
    title/str: A title for this selection
    exclude_active/bool: Exclude the currently active window from the list to pick
    reactivate_prev_tab/bool: Reactivate the previously activated tab when finished
    '''

    short_desc = 'Visually select a window in the specified tab'
    desc = (
        'Prints out the id of the selected window. Other commands'
        ' can then be chained to make use of it.'
    )
    options_spec = MATCH_TAB_OPTION + '\n\n' + '''\
--response-timeout
type=float
default=60
The time in seconds to wait for the user to select a window.


--self
type=bool-set
Select window from the tab containing the window this command is run in,
instead of the active tab.


--title
A title that will be displayed to the user to describe what this selection is for.


--exclude-active
type=bool-set
Exclude the currently active window from the list of windows to pick.


--reactivate-prev-tab
type=bool-set
When the selection is finished, the tab in the same OS window that was activated
before the selection will be reactivated. The last activated OS window will also
be refocused.
'''
    is_asynchronous = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ans = {'self': opts.self, 'match': opts.match, 'title': opts.title, 'exclude_active': opts.exclude_active,
               'reactivate_prev_tab': opts.reactivate_prev_tab}
        return ans

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        responder = self.create_async_responder(payload_get, window)

        def callback(tab: Optional['Tab'], window: Window | None) -> None:
            if window:
                responder.send_data(window.id)
            else:
                responder.send_error('No window selected')
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                if payload_get('exclude_active'):
                    wids = tab.all_window_ids_except_active_window
                else:
                    wids = set()
                boss.visual_window_select_action(
                    tab, callback, payload_get('title') or 'Choose window', only_window_ids=wids,
                    reactivate_prev_tab=payload_get('reactivate_prev_tab')
                )
                break
        return AsyncResponse()

    def cancel_async_request(self, boss: 'Boss', window: Optional['Window'], payload_get: PayloadGetType) -> None:
        boss.cancel_current_visual_select()


select_window = SelectWindow()
