#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from kitty.fast_data_types import get_os_window_size

from .base import (
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    RemoteControlErrorWithoutTraceback,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import ResizeOSWindowRCOptions as CLIOptions


class ResizeOSWindow(RemoteCommand):
    protocol_spec = __doc__ = '''
    match/str: Which window to resize
    self/bool: Boolean indicating whether to close the window the command is run in
    incremental/bool: Boolean indicating whether to adjust the size incrementally
    action/choices.resize.toggle-fullscreen.toggle-maximized: One of :code:`resize, toggle-fullscreen` or :code:`toggle-maximized`
    unit/choices.cells.pixels: One of :code:`cells` or :code:`pixels`
    width/int: Integer indicating desired window width
    height/int: Integer indicating desired window height
    '''

    short_desc = 'Resize the specified OS Windows'
    desc = (
        'Resize the specified OS Windows.'
        ' Note that some window managers/environments do not allow applications to resize'
        ' their windows, for example, tiling window managers.'
    )
    options_spec = MATCH_WINDOW_OPTION + '''\n
--action
default=resize
choices=resize,toggle-fullscreen,toggle-maximized
The action to perform.


--unit
default=cells
choices=cells,pixels
The unit in which to interpret specified sizes.


--width
default=0
type=int
Change the width of the window. Zero leaves the width unchanged.


--height
default=0
type=int
Change the height of the window. Zero leaves the height unchanged.


--incremental
type=bool-set
Treat the specified sizes as increments on the existing window size
instead of absolute sizes.


--self
type=bool-set
Resize the window this command is run in, rather than the active window.


--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {
            'match': opts.match, 'action': opts.action, 'unit': opts.unit,
            'width': opts.width, 'height': opts.height, 'self': opts.self,
            'incremental': opts.incremental
        }

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_match_payload(boss, window, payload_get)
        if windows:
            ac = payload_get('action')
            for os_window_id in {w.os_window_id for w in windows if w}:
                metrics = get_os_window_size(os_window_id)
                if metrics is None:
                    raise RemoteControlErrorWithoutTraceback(f'The OS Window {os_window_id} does not exist')
                if metrics['is_layer_shell']:
                    raise RemoteControlErrorWithoutTraceback(f'The OS Window {os_window_id} is a panel and cannot be resized')
                if ac == 'resize':
                    boss.resize_os_window(
                        os_window_id, width=payload_get('width'), height=payload_get('height'),
                        unit=payload_get('unit'), incremental=payload_get('incremental'), metrics=metrics,
                    )
                elif ac == 'toggle-fullscreen':
                    boss.toggle_fullscreen(os_window_id)
                elif ac == 'toggle-maximized':
                    boss.toggle_maximized(os_window_id)
        return None


resize_os_window = ResizeOSWindow()
