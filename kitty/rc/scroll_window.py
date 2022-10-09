#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional, Tuple, Union

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import ScrollWindowRCOptions as CLIOptions


class ScrollWindow(RemoteCommand):

    protocol_spec = __doc__ = '''
    amount+/list.scroll_amount: The amount to scroll, a two item list with the first item being \
             either a number or the keywords, start and end. \
             And the second item being either 'p' for pages or 'l' for lines or 'u'
             for unscrolling by lines.
    match/str: The window to scroll
    '''

    short_desc = 'Scroll the specified windows'
    desc = (
        'Scroll the specified windows, if no window is specified, scroll the window this command is run inside.'
        ' :italic:`SCROLL_AMOUNT` can be either the keywords :code:`start` or :code:`end` or an'
        ' argument of the form :italic:`<number>[unit][+-]`. For example, :code:`30` will scroll down 30 lines, :code:`2p-`'
        ' will scroll up 2 pages and :code:`0.5p`will scroll down half page. :code:`3u` will *unscroll* by 3 lines, which means that 3 lines will move from the'
        ' scrollback buffer onto the top of the screen.'
    )
    argspec = 'SCROLL_AMOUNT'
    options_spec = MATCH_WINDOW_OPTION + '''\n
--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('Scroll amount must be specified')
        amt = args[0]
        amount: Tuple[Union[str, float], Optional[str]] = (amt, None)
        if amt not in ('start', 'end'):
            pages = 'p' in amt
            unscroll = 'u' in amt
            mult = -1 if amt.endswith('-') and not unscroll else 1
            q = float(amt.rstrip('+-plu'))
            if not pages and not q.is_integer():
                self.fatal('The number must be an integer')
            amount = q * mult, 'p' if pages else ('u' if unscroll else 'l')

        # defaults to scroll the window this command is run in
        return {'match': opts.match, 'amount': amount, 'self': True}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        amt = payload_get('amount')
        for window in self.windows_for_match_payload(boss, window, payload_get):
            if window:
                if amt[0] in ('start', 'end'):
                    getattr(window, {'start': 'scroll_home'}.get(amt[0], 'scroll_end'))()
                else:
                    amt, unit = amt
                    if unit == 'u':
                        window.screen.reverse_scroll(int(abs(amt)), True)
                    else:
                        unit = 'page' if unit == 'p' else 'line'
                        if unit == 'page' and not amt.is_integer():
                            amt = round(window.screen.lines * amt)
                            unit = 'line'
                        direction = 'up' if amt < 0 else 'down'
                        func = getattr(window, f'scroll_{unit}_{direction}')
                        for i in range(int(abs(amt))):
                            func()
        return None


scroll_window = ScrollWindow()
