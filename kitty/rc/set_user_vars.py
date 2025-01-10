#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SetUserVarsRCOptions as CLIOptions


class SetUserVars(RemoteCommand):

    protocol_spec = __doc__ = '''
    var/list.str: List of user variables of the form NAME=VALUE
    match/str: Which windows to change the title in
    '''

    short_desc = 'Set user variables on a window'
    desc = (
        'Set user variables for the specified windows. If you use the :option:`kitten @ set-user-vars --match` option'
        ' the variables will be set for all matched windows. By default, only the window'
        ' in which the command is run is affected. If you do not specify any variables, the'
        ' current variables are printed out, one per line. To unset a variable specify just its name.'
    )
    options_spec = MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(json_field='var', spec='[NAME=VALUE ...]')

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'var': args, 'self': True}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        val = {}
        for x in payload_get('var') or ():
            a, sep, b = x.partition('=')
            if sep:
                val[a] = b
            else:
                val[a] = None
        lines = []
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                if val:
                    for k, v in val.items():
                        window.set_user_var(k, v)
                else:
                    lines.append('\n'.join(f'{k}={v}' for k, v in window.user_vars.items()))
        return '\n\n'.join(lines)


set_user_vars = SetUserVars()
