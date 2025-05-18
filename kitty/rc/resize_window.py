#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import ResizeWindowRCOptions as CLIOptions


class ResizeWindow(RemoteCommand):
    protocol_spec = __doc__ = '''
    match/str: Which window to resize
    self/bool: Boolean indicating whether to resize the window the command is run in
    increment/int: Integer specifying the resize increment
    axis/choices.horizontal.vertical.reset: One of :code:`horizontal, vertical` or :code:`reset`
    '''

    short_desc = 'Resize the specified windows'
    desc = (
        'Resize the specified windows in the current layout.'
        ' Note that not all layouts can resize all windows in all directions.'
    )
    options_spec = MATCH_WINDOW_OPTION + '''\n
--increment -i
type=int
default=2
The number of cells to change the size by, can be negative to decrease the size.


--axis -a
type=choices
choices=horizontal,vertical,reset
default=horizontal
The axis along which to resize. If :code:`horizontal`,
it will make the window wider or narrower by the specified increment.
If :code:`vertical`, it will make the window taller or shorter by the specified increment.
The special value :code:`reset` will reset the layout to its default configuration.


--self
type=bool-set
Resize the window this command is run in, rather than the active window.
'''
    string_return_is_error = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'increment': opts.increment, 'axis': opts.axis, 'self': opts.self}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_match_payload(boss, window, payload_get)
        resized: bool | None | str = False
        if windows and windows[0]:
            resized = boss.resize_layout_window(
                windows[0], increment=payload_get('increment'), is_horizontal=payload_get('axis') == 'horizontal',
                reset=payload_get('axis') == 'reset'
            )
        return resized


resize_window = ResizeWindow()
