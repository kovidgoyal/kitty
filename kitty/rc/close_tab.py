#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import CloseTabRCOptions as CLIOptions


class CloseTab(RemoteCommand):

    '''
    match: Which tab to close
    self: Boolean indicating whether to close the window the command is run in
    '''

    short_desc = 'Close the specified tab(s)'
    options_spec = MATCH_TAB_OPTION + '''\n
--self
type=bool-set
If specified close the tab this command is run in, rather than the active tab.
'''
    argspec = ''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'self': opts.self}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                boss.close_tab_no_confirm(tab)


close_tab = CloseTab()
