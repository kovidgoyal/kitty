#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional

from kitty.cli_stub import LaunchCLIOptions
from kitty.launch import (
    launch as do_launch, options_spec as launch_options_spec,
    parse_launch_args
)

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import LaunchRCOptions as CLIOptions


class Launch(RemoteCommand):

    '''
    args+: The command line to run in the new window, as a list, use an empty list to run the default shell
    match: The tab to open the new window in
    window_title: Title for the new window
    cwd: Working directory for the new window
    env: List of environment variables of the form NAME=VALUE
    tab_title: Title for the new tab
    type: The type of window to open
    keep_focus: Boolean indicating whether the current window should retain focus or not
    copy_colors: Boolean indicating whether to copy the colors from the current window
    copy_cmdline: Boolean indicating whether to copy the cmdline from the current window
    copy_env: Boolean indicating whether to copy the environ from the current window
    location: Where in the tab to open the new window
    allow_remote_control: Boolean indicating whether to allow remote control from the new window
    stdin_source: Where to get stdin for thew process from
    stdin_add_formatting: Boolean indicating whether to add formatting codes to stdin
    stdin_add_line_wrap_markers: Boolean indicating whether to add line wrap markers to stdin
    no_response: Boolean indicating whether to send back the window id
    marker: Specification for marker for new window, for example: "text 1 ERROR"
    '''

    short_desc = 'Run an arbitrary process in a new window/tab'
    desc = (
        ' Prints out the id of the newly opened window. Any command line arguments'
        ' are assumed to be the command line used to run in the new window, if none'
        ' are provided, the default shell is run. For example:'
        ' :italic:`kitty @ launch --title Email mutt`.'
    )
    options_spec = MATCH_TAB_OPTION + '\n\n' + '''\
--no-response
type=bool-set
Do not print out the id of the newly created window.


--self
type=bool-set
If specified the tab containing the window this command is run in is used
instead of the active tab
    ''' + '\n\n' + launch_options_spec().replace(':option:`launch', ':option:`kitty @ launch')
    argspec = '[CMD ...]'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if opts.no_response:
            global_opts.no_command_response = True
        ans = {'args': args or []}
        for attr, val in opts.__dict__.items():
            ans[attr] = val
        return ans

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        default_opts = parse_launch_args()[0]
        opts = LaunchCLIOptions()
        for key, default_value in default_opts.__dict__.items():
            val = payload_get(key)
            if val is None:
                val = default_value
            setattr(opts, key, val)
        tab = self.tabs_for_match_payload(boss, window, payload_get)[0]
        w = do_launch(boss, opts, payload_get('args') or [], target_tab=tab)
        return None if payload_get('no_response') else str(getattr(w, 'id', 0))


launch = Launch()
