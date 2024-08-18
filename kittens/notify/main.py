#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import sys


def OPTIONS() -> str:
    from kitty.constants import standard_icon_names
    return  f'''
--icon -n
type=list
The name of the icon to use for the notification. An icon with this name
will be searched for on the computer running the terminal emulator. Can
be specified multiple times, the first name that is found will be used.
Standard names: {', '.join(sorted(standard_icon_names))}


--icon-path -p
Path to an image file in PNG/JPEG/GIF formats to use as the icon. If both
name and path are specified then first the name will be looked for and if not found
then the path will be used.


--app-name -a
default=kitten-notify
The application name for the notification.


--button -b
type=list
Add a button with the specified text to the notification. Can be specified multiple times for multiple buttons.
If --wait-till-closed is used then the kitten will print the button number to STDOUT if the user clicks a button.
1 for the first button, 2 for the second button and so on.


--urgency -u
default=normal
choices=normal,low,critical
The urgency of the notification.


--expire-after -e
The duration, for the notification to appear on screen. The default is to
use the policy of the OS notification service. A value of :code:`never` means the notification should
never expire, however, this may or may not work depending on the policies of the OS notification
service. Time is specified in the form NUMBER[SUFFIX] where SUFFIX can be :code:`s` for seconds, :code:`m` for minutes,
:code:`h` for hours or :code:`d` for days. Non-integer numbers are allowed.
If not specified, seconds is assumed. The notification is guaranteed to be closed automatically
after the specified time has elapsed. The notification could be closed before by user
action or OS policy.


--sound-name -s
default=system
The name of the sound to play with the notification. :code:`system` means let the
notification system use whatever sound it wants. :code:`silent` means prevent
any sound from being played. Any other value is passed to the desktop's notification system
which may or may not honor it.


--type -t
The notification type. Can be any string, it is used by users to create filter rules
for notifications, so choose something descriptive of the notification's purpose.


--identifier -i
The identifier of this notification. If a notification with the same identifier
is already displayed, it is replaced/updated.


--print-identifier -P
type=bool-set
Print the identifier for the notification to STDOUT. Useful when not specifying
your own identifier via the --identifier option.


--wait-till-closed --wait-for-completion -w
type=bool-set
Wait until the notification is closed. If the user activates the notification,
"0" is printed to STDOUT before quitting. If a button on the notification is pressed the
number corresponding to the button is printed to STDOUT. Press the Esc or Ctrl+C keys
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

To update an existing notification, specify the identifier of the notification
with the --identifier option. The value should be the same as the identifier specified for
the notification you wish to update.

If no title is specified and an identifier is specified using the --identifier
option, then instead of creating a new notification, an existing notification
with the specified identifier is closed.
'''

usage = 'TITLE [BODY ...]'
if __name__ == '__main__':
    raise SystemExit('This should be run as `kitten notify ...`')
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = 'Send notifications to the user'
