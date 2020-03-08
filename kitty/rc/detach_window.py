#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import (
    MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError,
    PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType,
    Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import DetachWindowRCOptions as CLIOptions


class DetachWindow(RemoteCommand):

    '''
    match: Which window to detach
    target: Which tab to move the detached window to
    self: Boolean indicating whether to detach the window the command is run in
    '''

    short_desc = 'Detach a window and place it in a different/new tab'
    desc = (
        'Detach the specified window and either move it into a new tab, a new OS window'
        ' or add it to the specified tab. Use the special value :code:`new` for --target-tab'
        ' to move to a new tab. If no target tab is specified the window is moved to a new OS window.'
    )
    options_spec = MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--target-tab -t') + '''\n
--self
type=bool-set
If specified detach the window this command is run in, rather than the active window.
'''
    argspec = ''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'target': opts.target_tab, 'self': opts.self}

    def response_from_kitty(self, boss: 'Boss', window: 'Window', payload_get: PayloadGetType) -> ResponseType:
        match = payload_get('match')
        if match:
            windows = tuple(boss.match_windows(match))
            if not windows:
                raise MatchError(match)
        else:
            windows = [window if window and payload_get('self') else boss.active_window]
        match = payload_get('target_tab')
        kwargs = {}
        if match:
            if match == 'new':
                kwargs['target_tab_id'] = 'new'
            else:
                tabs = tuple(boss.match_tabs(match))
                if not tabs:
                    raise MatchError(match, 'tabs')
                kwargs['target_tab_id'] = tabs[0].id
        if not kwargs:
            kwargs['target_os_window_id'] = 'new'

        for window in windows:
            boss._move_window_to(window=window, **kwargs)


detach_window = DetachWindow()
