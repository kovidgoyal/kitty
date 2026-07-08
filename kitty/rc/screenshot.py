#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
from base64 import standard_b64encode
from typing import TYPE_CHECKING

from kitty.fast_data_types import png_from_32bit_rgba_data
from kitty.types import AsyncResponse

from .base import (
    MATCH_TAB_OPTION,
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    MatchError,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    RemoteControlErrorWithoutTraceback,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import ScreenshotRCOptions as CLIOptions


class Screenshot(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: The window to screenshot
    match_tab/str: The tab to screenshot
    output_path/str: Path to save the PNG image to, on the computer kitty is running on. Empty to return the image data instead.
    '''

    short_desc = 'Take a screenshot of a kitty OS window, tab or window'
    desc = (
        'Take a screenshot, as a PNG image, of an entire kitty OS window. Restrict the screenshot to a single'
        ' kitty window or tab with :option:`--match`/:option:`--match-tab`. The specified window/tab must be'
        ' currently visible, i.e. it must be in the active tab of its OS window and, in the case of a window,'
        ' not hidden behind another window by the layout, otherwise this command will fail.\n\n'

        'By default, the PNG image data is written to STDOUT. If instead a file path is specified, kitty itself'
        ' (rather than this :program:`kitten` process) saves the screenshot to that path. Since kitty and the'
        ' kitten are typically running on the same computer, this avoids copying the (potentially large)'
        ' image data over the possibly slow remote control transport.'
    )
    options_spec = MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')
    args = RemoteCommand.Args(
        spec='[OUTPUT_FILE]', json_field='output_path',
        special_parse='!read_screenshot_args(io_data, args)',
        completion=RemoteCommand.CompletionSpec.from_string('type:file ext:png'),
    )
    is_asynchronous = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) > 1:
            self.fatal('Must specify at most one output file')
        return {
            'match': opts.match, 'match_tab': opts.match_tab,
            'output_path': args[0] if args else '',
        }

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        match = payload_get('match')
        match_tab = payload_get('match_tab')
        target_window_id = 0
        include_tab_bar = False

        if match:
            windows = list(boss.match_windows(match, window))
            if not windows:
                raise MatchError(match)
            w = windows[0]
            tab = w.tabref()
            tm = tab.tab_manager_ref() if tab is not None else None
            if tab is None or tm is None or tm.active_tab is not tab or not w.is_visible_in_layout:
                raise RemoteControlErrorWithoutTraceback(
                    'The matched window is not currently visible, screenshots can only be taken of visible windows')
            os_window_id = w.os_window_id
            target_window_id = w.id
        elif match_tab:
            tabs = list(boss.match_tabs(match_tab))
            if not tabs:
                raise MatchError(match_tab, 'tabs')
            tab = tabs[0]
            tm = tab.tab_manager_ref()
            if tm is None or tm.active_tab is not tab:
                raise RemoteControlErrorWithoutTraceback(
                    'The matched tab is not currently visible, screenshots can only be taken of visible tabs')
            os_window_id = tab.os_window_id
        else:
            atm = boss.active_tab_manager
            if atm is None:
                raise RemoteControlErrorWithoutTraceback('There is no active OS window to screenshot')
            os_window_id = atm.os_window_id
            include_tab_bar = True

        output_path = payload_get('output_path') or ''
        responder = self.create_async_responder(payload_get, window)

        def callback(cb_os_window_id: int, cb_window_id: int, pixels: bytes, width: int, height: int) -> None:
            if not pixels:
                responder.send_error('Failed to take screenshot, the OS window may have been closed')
                return
            try:
                png_data = png_from_32bit_rgba_data(pixels, width, height, True)
                if output_path:
                    with open(os.path.expanduser(output_path), 'wb') as f:
                        f.write(png_data)
                    responder.send_data(True)
                else:
                    responder.send_data(standard_b64encode(png_data).decode('ascii'))
            except Exception as e:
                responder.send_error(f'Failed to save screenshot: {e}')

        boss.request_thumbnail(
            os_window_id, callback, window_id=target_window_id, include_tab_bar=include_tab_bar, no_scaling=True)
        return AsyncResponse()


screenshot = Screenshot()
