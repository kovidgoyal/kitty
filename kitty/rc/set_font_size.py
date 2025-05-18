#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SetFontSizeRCOptions as CLIOptions


class SetFontSize(RemoteCommand):
    protocol_spec = __doc__ = '''
    size+/float: The new font size in pts (a positive number). If absent is assumed to be zero which means reset to default.
    all/bool: Boolean whether to change font size in the current window or all windows
    increment_op/choices.+.-.*./: The string ``+``, ``-``, ``*`` or ``/`` to interpret size as an increment
    '''

    short_desc = 'Set the font size in the active top-level OS window'
    desc = (
        'Sets the font size to the specified size, in pts. Note'
        ' that in kitty all sub-windows in the same OS window'
        ' must have the same font size. A value of zero'
        ' resets the font size to default. Prefixing the value'
        ' with a :code:`+`, :code:`-`, :code:`*` or :code:`/` changes the font size by the specified'
        ' amount. Use -- before using - to have it not mistaken for a option. For example:'
        ' kitten @ set-font-size -- -2'
    )
    args = RemoteCommand.Args(spec='FONT_SIZE', count=1, special_parse='+increment_op:parse_set_font_size(args[0], &payload)', json_field='size')
    options_spec = '''\
--all -a
type=bool-set
By default, the font size is only changed in the active OS window,
this option will cause it to be changed in all OS windows. It also changes
the font size for any newly created OS Windows in the future.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if not args:
            self.fatal('No font size specified')
        fs = args[0]
        inc = fs[0] if fs and fs[0] in '+-' else None
        return {'size': abs(float(fs)), 'all': opts.all, 'increment_op': inc}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        boss.change_font_size(
            payload_get('all'),
            payload_get('increment_op'), payload_get('size') or 0)
        return None


set_font_size = SetFontSize()
