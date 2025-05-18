#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import FocusTabRCOptions as CLIOptions


class FocusTab(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: The tab to focus
    '''

    short_desc = 'Focus the specified tab'
    desc = 'The active window in the specified tab will be focused.'
    options_spec = MATCH_TAB_OPTION + '''

--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'no_response': opts.no_response}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                boss.set_active_tab(tab)
                break
        return None


focus_tab = FocusTab()
