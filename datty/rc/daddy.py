#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from datty.cli_stub import DaddyRCOptions as CLIOptions


class Daddy(RemoteCommand):
    protocol_spec = __doc__ = """
    daddy+/str: The name of the daddy to run
    args/list.str: Arguments to pass to the daddy as a list
    match/str: The window to run the daddy over
    """

    short_desc = 'Run a daddy'
    desc = (
        'Run a daddy over the specified windows (active window by default).'
        ' The :italic:`daddy_name` can be either the name of a builtin daddy'
        ' or the path to a Python file containing a custom daddy. If a relative path'
        ' is used it is searched for in the :ref:`datty config directory <confloc>`. If the daddy is a'
        ' :italic:`no_ui` daddy and its handle response method returns a string or boolean, this'
        ' is printed out to stdout.'
    )
    options_spec = MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(spec='daddy_name', json_field='daddy', minimum_count=1, first_rest=('daddy', 'args'))

    def message_to_datty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('Must specify daddy name')
        return {'match': opts.match, 'args': list(args)[1:], 'daddy': args[0]}

    def response_from_datty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        retval = None
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                retval = boss.run_daddy_with_metadata(payload_get('daddy'), args=tuple(payload_get('args') or ()), window=window)
                break
        if isinstance(retval, (str, bool)):
            return retval
        return None


daddy = Daddy()
