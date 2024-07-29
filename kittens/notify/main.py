#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys


def OPTIONS() -> str:
    from kitty.constants import standard_icon_names
    return  f'''
--icon -i
type=list
The name of the icon to use for the notification. An icon with this name
will be searched for on the computer running the terminal emulator. Can
be specified multiple times, the first name that is found will be used.
Standard names: {', '.join(sorted(standard_icon_names))}


--icon-path -I
Path to an image file in PNG/JPEG/WEBP/GIF formats to use as the icon. If both
name and path are specified then first the name will be looked for and if not found
then the path will be used. Other image formats are supported if ImageMagick is
installed on the system.


--app-name -a
default=kitten-notify
The application name for the notification.


--urgency -u
default=normal
choices=normal,low,critical
The urgency of the notification.


--expire-time -t
The duration, for the notification to appear on screen. The default is to
use the policy of the OS notification service. A value of :code:`never` means the notification should
never expire, however, this may or may not work depending on the policies of the OS notification
service. Time is specified in the form NUMBER[SUFFIX] where SUFFIX can be :code:`s` for seconds, :code:`m` for minutes,
:code:`h` for hours or :code:`d` for days. Non-integer numbers are allowed.
If not specified, seconds is assumed. The notification is guaranteed to be closed automatically
after the specified time has elapsed. The notification could be closed before by user
action or OS policy.


--type -c
The notification type. Can be any string, it is used by users to create filter rules
for notifications, so choose something descriptive of the notifications, purpose.


--identifier
The identifier of this notification. If a notification with the same identifier
is already displayed, it is replaced/updated.


--print-identifier -p
type=bool-set
Print the identifier for the notification to STDOUT. Useful when not specifying
your own identifier via the --identifier option.


--wait-till-closed -w
type=bool-set
Wait until the notification is closed. If the user activates the notification,
"activated" is printed to STDOUT before quitting. Press the Esc or Ctrl+C keys
to close the notification manually.


--only-print-escape-code
type=bool-set
Only print the escape code to STDOUT. Useful if using this kitten as part
of a larger application. If this is specified, the --wait-till-closed option
will be used for escape code generation, but no actual waiting will be done.


--icon-cache-id -g
Identifier to use when caching icons in the terminal emulator. Using an identifier means
that icon data needs to be transmitted only once using --icon-path. Subsequent invocations
will use the cached icon data, at least until the terminal instance is restarted. This is useful
if this kitten is being used inside a larger application, with --only-print-escape-code.
'''

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
