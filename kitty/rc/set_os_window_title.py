#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from kitty.fast_data_types import set_os_window_title as set_os_window_title_impl

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SetOsWindowTitleRCOptions as CLIOptions


class SetOsWindowTitle(RemoteCommand):
    protocol_spec = __doc__ = """
    title/str: The new title
    match/str: Which OS windows to change, matched via their contained windows
    """

    short_desc = 'Set the OS window title'
    desc = (
        'Set the title for the OS windows containing the specified windows. If you use the '
        ':option:`kitten @ set-os-window-title --match` option the title will be set for all matched OS windows. '
        'By default, only the OS window in which the command is run is affected. If you do not specify a title, the '
        'title of the currently active window in each OS window is used.'
    )
    options_spec = MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(spec='[TITLE ...]', json_field='title', special_parse='expand_ansi_c_escapes_in_args(args...)')

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ans = {'match': opts.match, 'self': True}
        title = ' '.join(args)
        if title:
            ans['title'] = title
        return ans

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        title = payload_get('title') or ''
        for os_window_id in {w.os_window_id for w in self.windows_for_match_payload(boss, window, payload_get) if w}:
            set_os_window_title_impl(os_window_id, title)
        return None


set_os_window_title = SetOsWindowTitle()
