#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetWindowTitleRCOptions as CLIOptions


class SetWindowTitle(RemoteCommand):

    '''
    title: The new title
    match: Which windows to change the title in
    temporary: Boolean indicating if the change is temporary or permanent
    '''

    short_desc = 'Set the window title'
    desc = (
        'Set the title for the specified window(s). If you use the :option:`kitty @ set-window-title --match` option'
        ' the title will be set for all matched windows. By default, only the window'
        ' in which the command is run is affected. If you do not specify a title, the'
        ' last title set by the child process running in the window will be used.'
    )
    options_spec = '''\
--temporary
type=bool-set
By default, if you use :italic:`set-window-title` the title will be permanently changed
and programs running in the window will not be able to change it again. If you
want to allow other programs to change it afterwards, use this option.
    ''' + '\n\n' + MATCH_WINDOW_OPTION
    argspec = '[TITLE ...]'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ans = {'match': opts.match, 'temporary': opts.temporary}
        title = ' '.join(args)
        if title:
            ans['title'] = title
        return ans

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        windows = [window or boss.active_window]
        match = payload_get('match')
        if match:
            windows = list(boss.match_windows(match))
            if not windows:
                raise MatchError(match)
        for window in windows:
            if window:
                if payload_get('temporary'):
                    window.override_title = None
                    window.title_changed(payload_get('title'))
                else:
                    window.set_title(payload_get('title'))


set_window_title = SetWindowTitle()
