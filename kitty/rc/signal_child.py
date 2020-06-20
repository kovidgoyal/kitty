#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SignalChildRCOptions as CLIOptions


class SignalChild(RemoteCommand):

    '''
    signals: The signals, a list of names, such as SIGTERM, SIGKILL, SIGUSR1, etc.
    match: Which windows to change the title in
    '''

    short_desc = 'Send a signal to the foreground process in the specified window'
    desc = (
        'Send one or more signals to the foreground process in the specified window(s).'
        ' If you use the :option:`kitty @ signal-child --match` option'
        ' the title will be set for all matched windows. By default, only the active'
        ' window is affected. If you do not specify any signals, :code:`SIGINT` is sent by default.'
        ' You can also map this to a keystroke in kitty.conf, for example::\n\n'
        '    map F1 signal_child SIGTERM'
    )
    options_spec = '''\
    ''' + '\n\n' + MATCH_WINDOW_OPTION
    argspec = '[SIGNAL_NAME ...]'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'signals': [x.upper() for x in args] or ['SIGINT']}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        import signal
        windows = [window or boss.active_window]
        match = payload_get('match')
        if match:
            windows = list(boss.match_windows(match))
            if not windows:
                raise MatchError(match)
        signals = tuple(getattr(signal, x) for x in payload_get('signals'))
        for window in windows:
            if window:
                window.signal_child(*signals)


signal_child = SignalChild()
