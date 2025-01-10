#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import LastUsedLayoutRCOptions as CLIOptions


class LastUsedLayout(RemoteCommand):
    protocol_spec = __doc__ = '''
    match/str: Which tab to change the layout of
    all/bool: Boolean to match all tabs
    '''

    short_desc = 'Switch to the last used layout'
    desc = (
        'Switch to the last used window layout in the specified tabs (or the active tab if not specified).'
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
        return {'match': opts.match, 'all': opts.all, 'no_response': opts.no_response}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                tab.last_used_layout()
        return None


last_used_layout = LastUsedLayout()
