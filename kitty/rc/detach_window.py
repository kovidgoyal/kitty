#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import DetachWindowRCOptions as CLIOptions


class DetachWindow(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: Which window to detach
    target_tab/str: Which tab to move the detached window to
    self/bool: Boolean indicating whether to detach the window the command is run in
    stay_in_tab/bool: Boolean indicating focus should remain in the active tab after windows are moved
    '''

    short_desc = 'Detach the specified windows and place them in a different/new tab'
    desc = (
        'Detach the specified windows and either move them into a new tab, a new OS window'
        ' or add them to the specified tab. Use the special value :code:`new` for :option:`kitten @ detach-window --target-tab`'
        ' to move to a new tab. If no target tab is specified the windows are moved to a new OS window.'
    )
    options_spec = (
        MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--target-tab -t') +
        '''Use the special value :code:`new` to move to a new tab.


--self
type=bool-set
Detach the window this command is run in, rather than the active window.


--stay-in-tab
type=bool-set
Keep the focus on a window in the currently focused tab after moving the specified windows.
''')

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'target_tab': opts.target_tab, 'self': opts.self, 'stay_in_tab': opts.stay_in_tab}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_match_payload(boss, window, payload_get)
        match = payload_get('target_tab')
        target_tab_id: str | int | None = None
        newval: str | int = 'new'
        if match:
            if match == 'new':
                target_tab_id = newval
            else:
                tabs = tuple(boss.match_tabs(match))
                if not tabs:
                    raise MatchError(match, 'tabs')
                target_tab_id = tabs[0].id
        kwargs = {'target_os_window_id': newval} if target_tab_id is None else {'target_tab_id': target_tab_id}
        tab = boss.active_tab
        for window in windows:
            if window:
                boss._move_window_to(window=window, **kwargs)
        if payload_get('stay_in_tab') and tab is not None:
            tab.make_active()
        return None


detach_window = DetachWindow()
