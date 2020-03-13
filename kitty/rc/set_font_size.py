#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from .base import (
    ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand,
    ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetFontSizeRCOptions as CLIOptions


class SetFontSize(RemoteCommand):
    '''
    size+: The new font size in pts (a positive number)
    all: Boolean whether to change font size in the current window or all windows
    increment_op: The string ``+`` or ``-`` to interpret size as an increment
    '''

    short_desc = 'Set the font size in the active top-level OS window'
    desc = (
        'Sets the font size to the specified size, in pts. Note'
        ' that in kitty all sub-windows in the same OS window'
        ' must have the same font size. A value of zero'
        ' resets the font size to default. Prefixing the value'
        ' with a + or - increments the font size by the specified'
        ' amount.'
    )
    argspec = 'FONT_SIZE'
    args_count = 1
    options_spec = '''\
--all -a
type=bool-set
By default, the font size is only changed in the active OS window,
this option will cause it to be changed in all OS windows.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if not args:
            self.fatal('No font size specified')
        fs = args[0]
        inc = fs[0] if fs and fs[0] in '+-' else None
        return {'size': abs(float(fs)), 'all': opts.all, 'increment_op': inc}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        boss.change_font_size(
            payload_get('all'),
            payload_get('increment_op'), payload_get('size'))


set_font_size = SetFontSize()
