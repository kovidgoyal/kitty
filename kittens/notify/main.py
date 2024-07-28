#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

OPTIONS = r'''
--identifier -i
The identifier of this notification. If a notification with the same identifier
is already displayed, it is replaced/updated.


--wait-till-closed
type=bool-set
Wait until the notification is closed. If the user activates the notification,
"activated" is printed to STDOUT before quitting.
'''.format
help_text = '''\
Send notifications to the user that are displayed to them via the
desktop environment's notifications service. Works over SSH as well.
'''

usage = 'TITLE [BODY ...]'
if __name__ == '__main__':
    raise SystemExit('This should be run as kitten clipboard')
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Send notifications to the user'
