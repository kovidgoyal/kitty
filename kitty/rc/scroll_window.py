#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional, Tuple, Union

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
             And the second item being either 'p' for pages or 'l' for lines or 'u'
             for unscrolling by lines.
    match: The window to scroll
    '''

    short_desc = 'Scroll the specified window'
    desc = (
        'Scroll the specified window, if no window is specified, scroll the window this command is run inside.'
        ' SCROLL_AMOUNT can be either the keywords :code:`start` or :code:`end` or an'
        ' argument of the form <number>[unit][+-]. For example, 30 will scroll down 30 lines and 2p- will'
        ' scroll up 2 pages. 3u will *unscroll* by 3 lines, which means that 3 lines will move from the'
        ' scrollback buffer onto the top of the screen.'
    )
    argspec = 'SCROLL_AMOUNT'
    options_spec = MATCH_WINDOW_OPTION

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        amt = args[0]
        amount: Tuple[Union[str, int], Optional[str]] = (amt, None)
        if amt not in ('start', 'end'):
            pages = 'p' in amt
            unscroll = 'u' in amt
            amt = amt.replace('p', '')
            mult = -1 if amt.endswith('-') and not unscroll else 1
            q = int(amt.replace('-', ''))
            amount = q * mult, 'p' if pages else ('u' if unscroll else 'l')

        return {'match': opts.match, 'amount': amount}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        windows = [window or boss.active_window]
        match = payload_get('match')
        amt = payload_get('amount')
        if match:
            windows = list(boss.match_windows(match))
            if not windows:
                raise MatchError(match)
        for window in windows:
            if window:
                if amt[0] in ('start', 'end'):
                    getattr(window, {'start': 'scroll_home'}.get(amt[0], 'scroll_end'))()
                else:
                    amt, unit = amt
                    if unit == 'u':
                        window.screen.reverse_scroll(abs(amt), True)
                    else:
                        unit = 'page' if unit == 'p' else 'line'
                        direction = 'up' if amt < 0 else 'down'
                        func = getattr(window, 'scroll_{}_{}'.format(unit, direction))
                        for i in range(abs(amt)):
                            func()


scroll_window = ScrollWindow()
