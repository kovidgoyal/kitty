#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, ArgsType, Boss, MatchError, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import CloseTabRCOptions as CLIOptions


class CloseTab(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: Which tab to close
    self/bool: Boolean indicating whether to close the tab of the window the command is run in
    ignore_no_match/bool: Boolean indicating whether no matches should be ignored or return an error
    '''

    short_desc = 'Close the specified tabs'
    desc = '''\
Close an arbitrary set of tabs. The :code:`--match` option can be used to
specify complex sets of tabs to close. For example, to close all non-focused
tabs in the currently focused OS window, use::

    kitten @ close-tab --match "not state:focused and state:parent_focused"
'''
    options_spec = MATCH_TAB_OPTION + '''\n
--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


--self
type=bool-set
Close the tab of the window this command is run in, rather than the active tab.


--ignore-no-match
type=bool-set
Do not return an error if no tabs are matched to be closed.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'match': opts.match, 'self': opts.self, 'ignore_no_match': opts.ignore_no_match}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        try:
            tabs = self.tabs_for_match_payload(boss, window, payload_get)
        except MatchError:
            if payload_get('ignore_no_match'):
                return None
            raise
        for tab in tuple(tabs):
            if tab:
                boss.close_tab_no_confirm(tab)
        return None


close_tab = CloseTab()
