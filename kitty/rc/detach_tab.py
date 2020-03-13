#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, MatchError, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import DetachTabRCOptions as CLIOptions


class DetachTab(RemoteCommand):

    '''
    match: Which tab to detach
    target: Which OS Window to move the detached tab to
    self: Boolean indicating whether to detach the tab the command is run in
    '''

    short_desc = 'Detach a tab and place it in a different/new OS Window'
    desc = (
        'Detach the specified tab and either move it into a new OS window'
        ' or add it to the OS Window containing the tab specified by --target-tab'
    )
    options_spec = MATCH_TAB_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--target-tab -t') + '''\n
--self
type=bool-set
If specified detach the tab this command is run in, rather than the active tab.
'''
    argspec = ''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'target': opts.target_tab, 'self': opts.self}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        match = payload_get('match')
        if match:
            tabs = list(boss.match_tabs(match))
            if not tabs:
                raise MatchError(match)
        else:
            if payload_get('self') and window:
                tab = window.tabref() or boss.active_tab
            else:
                tab = boss.active_tab
            tabs = [tab] if tab else []
        match = payload_get('target_tab')
        kwargs = {}
        if match:
            targets = tuple(boss.match_tabs(match))
            if not targets:
                raise MatchError(match, 'tabs')
            kwargs['target_os_window_id'] = targets[0].os_window_id

        for tab in tabs:
            boss._move_tab_to(tab=tab, **kwargs)


detach_tab = DetachTab()
