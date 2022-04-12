#!/usr/bin/env python
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
    self: Boolean indicating whether to close the tab of the window the command is run in
    target_group: The target group to close
    '''

    short_desc = 'Close the specified tab(s)'
    options_spec = MATCH_TAB_OPTION + '''\n
--self
type=bool-set
If specified close the tab of the window this command is run in, rather than the active tab.


--target-group
choices=unactive-in-os-window,unactive,others,others-in-os-window,none
default=none
Close the specified group of tabs. When specified, this option takes precedence over other
options controlling which tabs to close.
unactive is all tabs in the kitty instance except the currently active tab.
unactive-in-os-window is the same as unactive except restricted to the OS Window with the currently active tab
others is all tabs except the tab containing the window this command was run in
others-in-os-window is the same as others except restricted to the OS window this command was run in
'''
    argspec = ''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'self': opts.self, 'target_group': opts.target_group}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        g = payload_get('target_group')
        if g == 'others' and window:
            avoid = boss.tab_for_window(window)
            for tab in boss.all_tabs:
                if tab is not avoid:
                    boss.close_tab_no_confirm(tab)
        elif g == 'others-in-os-window' and window:
            avoid = boss.tab_for_window(window)
            if avoid:
                tm = boss.os_window_map[avoid.os_window_id]
                for tab in tm:
                    if tab is not avoid:
                        boss.close_tab_no_confirm(tab)
        elif g == 'unactive':
            avoid = boss.active_tab
            for tab in boss.all_tabs:
                if tab is not avoid:
                    boss.close_tab_no_confirm(tab)
        elif g == 'unactive-in-os-window':
            avoid = boss.active_tab
            if avoid:
                tm = boss.os_window_map[avoid.os_window_id]
                for tab in tm:
                    if tab is not avoid:
                        boss.close_tab_no_confirm(tab)
        if g != 'none':
            return None
        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                boss.close_tab_no_confirm(tab)
        return None


close_tab = CloseTab()
