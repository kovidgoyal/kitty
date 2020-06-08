#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import LastUsedLayoutRCOptions as CLIOptions


class LastUsedLayout(RemoteCommand):
    '''
    match: Which tab to change the layout of
    all: Boolean to match all tabs
    '''

    short_desc = 'Switch to the last used layout'
    desc = (
        'Switch to the last used window layout in the specified tab (or the active tab if not specified).'
    )
    options_spec = '''\
--all -a
type=bool-set
Change the layout in all tabs.


--no-response
type=bool-set
default=false
Don't wait for a response from kitty. This means that even if no matching tab is found,
the command will exit with a success code.
''' + '\n\n\n' + MATCH_TAB_OPTION

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if opts.no_response:
            global_opts.no_command_response = True
        return {'match': opts.match, 'all': opts.all}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                tab.last_used_layout()


last_used_layout = LastUsedLayout()
