#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SetWindowTitleRCOptions as CLIOptions


class SetWindowTitle(RemoteCommand):

    protocol_spec = __doc__ = '''
    title/str: The new title
    match/str: Which windows to change the title in
    temporary/bool: Boolean indicating if the change is temporary or permanent
    '''

    short_desc = 'Set the window title'
    desc = (
        'Set the title for the specified windows. If you use the :option:`kitten @ set-window-title --match` option'
        ' the title will be set for all matched windows. By default, only the window'
        ' in which the command is run is affected. If you do not specify a title, the'
        ' last title set by the child process running in the window will be used.'
    )
    options_spec = '''\
--temporary
type=bool-set
By default, the title will be permanently changed and programs running in the window will not be able to change it
again. If you want to allow other programs to change it afterwards, use this option.
    ''' + '\n\n' + MATCH_WINDOW_OPTION
    args = RemoteCommand.Args(json_field='title', spec='[TITLE ...]', special_parse='expand_ansi_c_escapes_in_args(args...)')

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ans = {'match': opts.match, 'temporary': opts.temporary}
        title = ' '.join(args)
        if title:
            ans['title'] = title
        # defaults to set the window title this command is run in
        ans['self'] = True
        return ans

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        title = payload_get('title')
        if payload_get('temporary') and title is not None:
            title = memoryview(title.encode('utf-8'))
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                if payload_get('temporary'):
                    window.override_title = None
                    window.title_changed(title)
                else:
                    window.set_title(title)
        return None


set_window_title = SetWindowTitle()
