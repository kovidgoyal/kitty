#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys

OPTIONS = r'''
--app-name -a
default=kitten-notify
The application name for the notification.


--urgency -u
default=normal
choices=normal,low,critical
The urgency of the notification.


--expire-time -t
default=-1
type=int
The duration, in milliseconds, for the notification to appear on screen. The default is to
use the policy of the OS notification service. A value of 0 means the notification should
never expire, however, this may or may not work depending on the policies of the OS notification
service. Positive values guarantee the notification will be closed automatically
after that many milliseconds have elapsed. The notification could be closed before by user
action or OS policy.


--type -c
The notification type. Can be any string, it is used by users to create filter rules
for notifications, so choose something descriptive of the notifications, purpose.


--identifier -i
The identifier of this notification. If a notification with the same identifier
is already displayed, it is replaced/updated.


--print-identifier -p
type=bool-set
Print the identifier for the notification to STDOUT. Useful when not specifying
your own identifier via the --identifier option.


--wait-till-closed -w
type=bool-set
Wait until the notification is closed. If the user activates the notification,
"activated" is printed to STDOUT before quitting.


--only-print-escape-code
type=bool-set
Only print the escape code to STDOUT. Useful if using this kitten as part
of a larger application. If this is specified, the --wait-till-closed option
will be used for escape code generation, but no actual waiting will be done.
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
