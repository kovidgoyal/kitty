#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, MatchError, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import LastUsedLayoutRCOptions as CLIOptions


class LastUsedLayout(RemoteCommand):
    '''
    match: Which tab to change the layout of
    '''

    short_desc = 'Switch to the last used layout'
    desc = (
        'Switch to the last used window layout in the specified tab (or the active tab if not specified).'
        ' You can use special match value :italic:`all` to set the layout in all tabs.'
    )
    options_spec = MATCH_TAB_OPTION

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match}

    def response_from_kitty(self, boss: 'Boss', window: 'Window', payload_get: PayloadGetType) -> ResponseType:
        match = payload_get('match')
        if match:
            if match == 'all':
                tabs = tuple(boss.all_tabs)
            else:
                tabs = tuple(boss.match_tabs(match))
            if not tabs:
                raise MatchError(match, 'tabs')
        else:
            tabs = tuple(boss.tab_for_window(window) if window else boss.active_tab)
        for tab in tabs:
            if tab:
                tab.last_used_layout()


last_used_layout = LastUsedLayout()
