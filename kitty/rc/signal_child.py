#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SignalChildRCOptions as CLIOptions


class SignalChild(RemoteCommand):

    protocol_spec = __doc__ = '''
    signals+/list.str: The signals, a list of names, such as :code:`SIGTERM`, :code:`SIGKILL`, :code:`SIGUSR1`, etc.
    match/str: Which windows to send the signals to
    '''

    short_desc = 'Send a signal to the foreground process in the specified windows'
    desc = (
        'Send one or more signals to the foreground process in the specified windows.'
        ' If you use the :option:`kitten @ signal-child --match` option'
        ' the signal will be sent for all matched windows. By default, only the active'
        ' window is affected. If you do not specify any signals, :code:`SIGINT` is sent by default.'
        ' You can also map :ac:`signal_child` to a shortcut in :file:`kitty.conf`, for example::\n\n'
        '    map f1 signal_child SIGTERM'
    )
    options_spec = '''\
--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
    ''' + '\n\n' + MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(json_field='signals', spec='[SIGNAL_NAME ...]', value_if_unspecified=('SIGINT',))

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        # defaults to signal the window this command is run in
        return {'match': opts.match, 'self': True, 'signals': [x.upper() for x in args] or ['SIGINT']}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        import signal
        signals = tuple(getattr(signal, x) for x in payload_get('signals'))
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                window.signal_child(*signals)
        return None


signal_child = SignalChild()
