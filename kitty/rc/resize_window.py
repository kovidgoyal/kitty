#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from math import isfinite
from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import ResizeWindowRCOptions as CLIOptions


class ResizeWindow(RemoteCommand):
    protocol_spec = __doc__ = """
    match/str: Which window to resize
    self/bool: Boolean indicating whether to resize the window the command is run in
    increment/int: Integer specifying the resize increment
    fraction/float: Fraction of the remaining resize steps to take, or zero for ordinary resizing
    axis/choices.horizontal.vertical.reset: One of :code:`horizontal, vertical` or :code:`reset`
    restore_entry_layout/bool: Restore an existing interactive Splits resize session on reset
    """

    short_desc = 'Resize the specified windows'
    desc = 'Resize the specified windows in the current layout. Note that not all layouts can resize all windows in all directions.'
    options_spec = (
        MATCH_WINDOW_OPTION
        + """\n
--increment -i
type=int
default=2
The number of cells to change the size by, can be negative to decrease the size.


--fraction
type=float
default=0
Take this fraction of the remaining resize steps, rounding up. Must be between
zero and one. Zero uses ordinary resizing. The increment sets the base step size.


--axis -a
type=choices
choices=horizontal,vertical,reset
default=horizontal
The axis along which to resize. If :code:`horizontal`,
it will make the window wider or narrower by the specified increment.
If :code:`vertical`, it will make the window taller or shorter by the specified increment.
The special value :code:`reset` will reset the layout to its default configuration.


--restore-entry-layout
type=bool-set
With :code:`--axis=reset`, restore the proportions saved by the interactive
resize page in Splits. When there is no such session, keep the default reset.


--self
type=bool-set
Resize the window this command is run in, rather than the active window.
"""
    )
    string_return_is_error = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        self.validate_fraction(opts.fraction)
        return {
            'match': opts.match,
            'increment': opts.increment,
            'axis': opts.axis,
            'self': opts.self,
            'fraction': opts.fraction,
            'restore_entry_layout': opts.restore_entry_layout,
        }

    @staticmethod
    def validate_fraction(fraction: float) -> None:
        if not isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError('Resize fraction must be between zero and one')

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_match_payload(boss, window, payload_get)
        fraction = payload_get('fraction', missing=0)
        self.validate_fraction(fraction)
        resized: bool | None | str = False
        if windows and windows[0]:
            if payload_get('axis') == 'reset' and payload_get('restore_entry_layout', missing=False):
                from .resize_window_edge import resize_window_edge

                handled, status = resize_window_edge.restore_session(windows[0])
                if handled:
                    return None if status.startswith('Restored') else status
            resized = boss.resize_layout_window(
                windows[0],
                increment=payload_get('increment'),
                is_horizontal=payload_get('axis') == 'horizontal',
                reset=payload_get('axis') == 'reset',
                fraction=fraction,
            )
        return resized


resize_window = ResizeWindow()
