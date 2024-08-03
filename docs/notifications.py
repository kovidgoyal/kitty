#!/usr/bin/env python

# A sample script to process notifications. Save it as
# ~/.config/kitty/notifications.py

import subprocess

from kitty.notifications import NotificationCommand, Urgency


def log_notification(nc: NotificationCommand) -> None:
    # Log notifications to /tmp/notifications-log.txt
    with open('/tmp/notifications-log.txt', 'a') as log:
        print(f'title: {nc.title}', file=log)
        print(f'body: {nc.body}', file=log)
        print(f'app: {nc.application_name}', file=log)
        print(f'types: {nc.notification_types}', file=log)
        print('\n', file=log)


def on_notification_activated(nc: NotificationCommand, which: int) -> None:
    # do something when this notification is activated (clicked on)
    # remember to assign this to the on_activation field in main()
    pass


def main(nc: NotificationCommand) -> bool:
    '''
    This function should return True to filter out the notification
    '''
    log_notification(nc)

    # filter out notifications with 'unwanted' in their titles
    if 'unwanted' in nc.title.lower():
        return True

    # force the notification to be silent
    nc.sound_name = 'silent'

    # filter out notifications from the application badapp
    if nc.application_name == 'badapp':
        return True

    # filter out low urgency notifications
    if nc.urgency is Urgency.Low:
        return True

    # replace some bad text in the notification body
    nc.body = nc.body.replace('bad text', 'good text')

    # run a script if this notification is from myapp and has
    # type foo, passing in the title and body as command line args
    # to the script.
    if nc.application_name == 'myapp' and 'foo' in nc.notification_types:
        subprocess.Popen(['/path/to/my/script', nc.title, nc.body])

    # do some arbitrary actions when this notification is activated
    nc.on_activation = on_notification_activated

    # dont filter out this notification
    return False
