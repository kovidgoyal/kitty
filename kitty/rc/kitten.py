#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import KittenRCOptions as CLIOptions


class Kitten(RemoteCommand):

    protocol_spec = __doc__ = '''
    kitten+/str: The name of the kitten to run
    args/list.str: Arguments to pass to the kitten as a list
    match/str: The window to run the kitten over
    '''

    short_desc = 'Run a kitten'
    desc = (
        'Run a kitten over the specified windows (active window by default).'
        ' The :italic:`kitten_name` can be either the name of a builtin kitten'
        ' or the path to a Python file containing a custom kitten. If a relative path'
        ' is used it is searched for in the :ref:`kitty config directory <confloc>`. If the kitten is a'
        ' :italic:`no_ui` kitten and its handle response method returns a string or boolean, this'
        ' is printed out to stdout.'
    )
    options_spec = MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(spec='kitten_name', json_field='kitten', minimum_count=1, first_rest=('kitten', 'args'))

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('Must specify kitten name')
        return {'match': opts.match, 'args': list(args)[1:], 'kitten': args[0]}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        retval = None
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                retval = boss.run_kitten_with_metadata(payload_get('kitten'), args=tuple(payload_get('args') or ()), window=window)
                break
        if isinstance(retval, (str, bool)):
            return retval
        return None


kitten = Kitten()
