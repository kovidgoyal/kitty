#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import ScrollWindowRCOptions as CLIOptions


class ScrollWindow(RemoteCommand):

    '''
    amount+: The amount to scroll, a two item list with the first item being \
             either a number or the keywords, start and end. \
             And the second item being either 'p' for pages or 'l' for lines.
    match: The window to scroll
    '''

    short_desc = 'Scroll the specified window'
    desc = (
        'Scroll the specified window, if no window is specified, scroll the window this command is run inside.'
        ' SCROLL_AMOUNT can be either the keywords :code:`start` or :code:`end` or an'
        ' argument of the form <number>[unit][+-]. For example, 30 will scroll down 30 lines and 2p- will'
        ' scroll up 2 pages.'
    )
    argspec = 'SCROLL_AMOUNT'
    options_spec = MATCH_WINDOW_OPTION

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        amt = args[0]
        ans = {'match': opts.match}
        if amt in ('start', 'end'):
            ans['amount'] = amt, None
        else:
            pages = 'p' in amt
            amt = amt.replace('p', '')
            mult = -1 if amt.endswith('-') else 1
            amt = int(amt.replace('-', ''))
            ans['amount'] = [amt * mult, 'p' if pages else 'l']
        return ans

    def response_from_kitty(self, boss: 'Boss', window: 'Window', payload_get: PayloadGetType) -> ResponseType:
        windows = [window or boss.active_window]
        match = payload_get('match')
        amt = payload_get('amount')
        if match:
            windows = tuple(boss.match_windows(match))
            if not windows:
                raise MatchError(match)
        for window in windows:
            if window:
                if amt[0] in ('start', 'end'):
                    getattr(window, {'start': 'scroll_home'}.get(amt[0], 'scroll_end'))()
                else:
                    amt, unit = amt
                    unit = 'page' if unit == 'p' else 'line'
                    direction = 'up' if amt < 0 else 'down'
                    func = getattr(window, 'scroll_{}_{}'.format(unit, direction))
                    for i in range(abs(amt)):
                        func()


scroll_window = ScrollWindow()
