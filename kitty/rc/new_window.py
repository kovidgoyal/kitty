#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Optional

from kitty.fast_data_types import focus_os_window
from kitty.tabs import SpecialWindow

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import NewWindowRCOptions as CLIOptions


class NewWindow(RemoteCommand):

    '''
    args+: The command line to run in the new window, as a list, use an empty list to run the default shell
    match: The tab to open the new window in
    title: Title for the new window
    cwd: Working directory for the new window
    tab_title: Title for the new tab
    window_type: One of :code:`kitty` or :code:`os`
    keep_focus: Boolean indicating whether the current window should retain focus or not
    '''

    short_desc = 'Open new window'
    desc = (
        'Open a new window in the specified tab. If you use the :option:`kitty @ new-window --match` option'
        ' the first matching tab is used. Otherwise the currently active tab is used.'
        ' Prints out the id of the newly opened window'
        ' (unless :option:`--no-response` is used). Any command line arguments'
        ' are assumed to be the command line used to run in the new window, if none'
        ' are provided, the default shell is run. For example:\n'
        ':italic:`kitty @ new-window --title Email mutt`'
    )
    options_spec = MATCH_TAB_OPTION + '''\n
--title
The title for the new window. By default it will use the title set by the
program running in it.


--cwd
The initial working directory for the new window. Defaults to whatever
the working directory for the kitty process you are talking to is.


--keep-focus
type=bool-set
Keep the current window focused instead of switching to the newly opened window


--window-type
default=kitty
choices=kitty,os
What kind of window to open. A kitty window or a top-level OS window.


--new-tab
type=bool-set
Open a new tab


--tab-title
When using --new-tab set the title of the tab.


--no-response
type=bool-set
default=false
Don't wait for a response giving the id of the newly opened window. Note that
using this option means that you will not be notified of failures and that
the id of the new window will not be printed out.
'''
    argspec = '[CMD ...]'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if opts.no_response:
            global_opts.no_command_response = True
        return {'match': opts.match, 'title': opts.title, 'cwd': opts.cwd,
                'new_tab': opts.new_tab, 'tab_title': opts.tab_title,
                'window_type': opts.window_type, 'no_response': opts.no_response,
                'keep_focus': opts.keep_focus, 'args': args or []}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        w = SpecialWindow(cmd=payload_get('args') or None, override_title=payload_get('title'), cwd=payload_get('cwd'))
        old_window = boss.active_window
        if payload_get('new_tab'):
            boss._new_tab(w)
            tab = boss.active_tab
            if payload_get('tab_title') and tab:
                tab.set_title(payload_get('tab_title'))
            aw = boss.active_window
            if payload_get('keep_focus') and old_window:
                boss.set_active_window(old_window)
            return None if not aw or payload_get('no_response') else str(aw.id)

        if payload_get('window_type') == 'os':
            boss._new_os_window(w)
            aw = boss.active_window
            if payload_get('keep_focus') and old_window:
                os_window_id = boss.set_active_window(old_window)
                if os_window_id:
                    focus_os_window(os_window_id)
            return None if not aw or payload_get('no_response') else str(aw.id)

        tab = self.tabs_for_match_payload(boss, window, payload_get)[0]
        ans = tab.new_special_window(w)
        if payload_get('keep_focus') and old_window:
            boss.set_active_window(old_window)
        return None if payload_get('no_response') else str(ans.id)


new_window = NewWindow()
