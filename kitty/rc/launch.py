#!/usr/bin/env python
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

    protocol_spec = __doc__ = '''
    args+/list.str: The command line to run in the new window, as a list, use an empty list to run the default shell
    match/str: The tab to open the new window in
    window_title/str: Title for the new window
    cwd/str: Working directory for the new window
    env/list.str: List of environment variables of the form NAME=VALUE
    tab_title/str: Title for the new tab
    type/choices.window.tab.os-window.overlay.background.clipboard.primary: The type of window to open
    keep_focus/bool: Boolean indicating whether the current window should retain focus or not
    copy_colors/bool: Boolean indicating whether to copy the colors from the current window
    copy_cmdline/bool: Boolean indicating whether to copy the cmdline from the current window
    copy_env/bool: Boolean indicating whether to copy the environ from the current window
    hold/bool: Boolean indicating whether to keep window open after cmd exits
    location/choices.first.after.before.neighbor.last.vsplit.hsplit.split.default: Where in the tab to open the new window
    allow_remote_control/bool: Boolean indicating whether to allow remote control from the new window
    remote_control_password/list.str: A list of remote control passwords
    stdin_source/choices.none.@selection.@screen.@screen_scrollback.@alternate.@alternate_scrollback.\
        @first_cmd_output_on_screen.@last_cmd_output.@last_visited_cmd_output: Where to get stdin for the process from
    stdin_add_formatting/bool: Boolean indicating whether to add formatting codes to stdin
    stdin_add_line_wrap_markers/bool: Boolean indicating whether to add line wrap markers to stdin
    spacing/list.str: A list of spacing specifications, see the docs for the set-spacing command
    marker/str: Specification for marker for new window, for example: "text 1 ERROR"
    logo/str: Path to window logo
    logo_position/str: Window logo position as string or empty string to use default
    logo_alpha/float: Window logo alpha or -1 to use default
    self/bool: Boolean, if True use tab the command was run in
    '''

    short_desc = 'Run an arbitrary process in a new window/tab'
    desc = (
        'Prints out the id of the newly opened window. Any command line arguments'
        ' are assumed to be the command line used to run in the new window, if none'
        ' are provided, the default shell is run. For example::\n\n'
        '    kitty @ launch --title=Email mutt'
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
        target_tab = None
        tabs = self.tabs_for_match_payload(boss, window, payload_get)
        if tabs and tabs[0]:
            target_tab = tabs[0]
        elif payload_get('type') not in ('background', 'os-window', 'tab', 'window'):
            return None
        w = do_launch(boss, opts, payload_get('args') or [], target_tab=target_tab)
        return None if payload_get('no_response') else str(getattr(w, 'id', 0))


launch = Launch()
