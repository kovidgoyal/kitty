#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, ArgsType, Boss, MatchError, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import DetachTabRCOptions as CLIOptions


class DetachTab(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: Which tab to detach
    target_tab/str: Which tab to move the detached tab to the OS window it is run in
    self/bool: Boolean indicating whether to detach the tab the command is run in
    '''

    short_desc = 'Detach the specified tabs and place them in a different/new OS window'
    desc = (
        'Detach the specified tabs and either move them into a new OS window'
        ' or add them to the OS window containing the tab specified by :option:`kitten @ detach-tab --target-tab`'
    )
    options_spec = MATCH_TAB_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--target-tab -t') + '''\n
--self
type=bool-set
Detach the tab this command is run in, rather than the active tab.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'target_tab': opts.target_tab, 'self': opts.self}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        match = payload_get('target_tab')
        kwargs = {}
        if match:
            targets = tuple(boss.match_tabs(match))
            if not targets:
                raise MatchError(match, 'tabs')
            if targets[0]:
                kwargs['target_os_window_id'] = targets[0].os_window_id

        for tab in self.tabs_for_match_payload(boss, window, payload_get):
            if tab:
                boss._move_tab_to(tab=tab, **kwargs)
        return None


detach_tab = DetachTab()
