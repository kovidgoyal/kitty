#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetTabTitleRCOptions as CLIOptions


class SetTabTitle(RemoteCommand):

    '''
    title+: The new title
    match: Which tab to change the title of
    '''

    short_desc = 'Set the tab title'
    desc = (
        'Set the title for the specified tab(s). If you use the :option:`kitty @ set-tab-title --match` option'
        ' the title will be set for all matched tabs. By default, only the tab'
        ' in which the command is run is affected. If you do not specify a title, the'
        ' title of the currently active window in the tab is used.'
    )
    options_spec = MATCH_TAB_OPTION
    argspec = 'TITLE ...'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'title': ' '.join(args), 'match': opts.match}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                tab.set_title(payload_get('title'))


set_tab_title = SetTabTitle()
