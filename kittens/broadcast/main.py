#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys

from kitty.rc.base import MATCH_TAB_OPTION, MATCH_WINDOW_OPTION

OPTIONS = (
    """
--hide-input-toggle
default=Ctrl+Alt+Esc
Key to press that will toggle hiding of the input in the broadcast window itself.
Useful while typing a password, prevents the password from being visible on the screen.


--end-session
default=Ctrl+Esc
Key to press to end the broadcast session.


"""
    + MATCH_WINDOW_OPTION
    + '\n\n'
    + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')
).format
help_text = 'Broadcast typed text to kitty windows. By default text is sent to all windows, unless one of the matching options is specified'
usage = '[initial text to send ...]'


def main(args: list[str]) -> None:
    raise SystemExit('This should be run as kitten broadcast')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Broadcast typed text to kitty windows'
