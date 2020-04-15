#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import KittenRCOptions as CLIOptions


class Kitten(RemoteCommand):

    '''
    kitten+: The name of the kitten to run
    args: Arguments to pass to the kitten as a list
    match: The window to run the kitten over
    '''

    short_desc = 'Run a kitten'
    desc = (
        'Run a kitten over the specified window (active window by default).'
        ' The :italic:`kitten_name` can be either the name of a builtin kitten'
        ' or the path to a python file containing a custom kitten. If a relative path'
        ' is used it is searched for in the kitty config directory. If the kitten is a'
        ' no_ui kitten and its handle response method returns a string or boolean, this'
        ' is printed out to stdout.'
    )
    options_spec = MATCH_WINDOW_OPTION
    argspec = 'kitten_name'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('Must specify kitten name')
        return {'match': opts.match, 'args': list(args)[1:], 'kitten': args[0]}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        windows = [window or boss.active_window]
        match = payload_get('match')
        if match:
            windows = list(boss.match_windows(match))
            if not windows:
                raise MatchError(match)
        retval = None
        for window in windows:
            if window:
                retval = boss._run_kitten(payload_get('kitten'), args=tuple(payload_get('args') or ()), window=window)
                break
        if isinstance(retval, (str, bool)):
            return retval


kitten = Kitten()
