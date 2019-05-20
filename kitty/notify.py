#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>


from .constants import is_macos, logo_png_file

if is_macos:
    from .fast_data_types import cocoa_send_notification

    def notify(
        title,
        body,
        timeout=5000,
        application='kitty',
        icon=True,
        identifier=None
    ):
        if icon is True:
            icon = None
        cocoa_send_notification(identifier, title, body, icon)

else:

    from .fast_data_types import dbus_send_notification
    from .constants import get_boss

    alloc_map = {}
    identifier_map = {}

    def dbus_notification_created(alloc_id, notification_id):
        identifier = alloc_map.pop(alloc_id, None)
        if identifier is not None:
            identifier_map[identifier] = notification_id

    def dbus_notification_activated(notification_id, action):
        rmap = {v: k for k, v in identifier_map.items()}
        identifier = rmap.get(notification_id)
        if identifier is not None:
            get_boss().notification_activated(identifier)

    def notify(
        title,
        body,
        timeout=-1,
        application='kitty',
        icon=True,
        identifier=None
    ):
        if icon is True:
            icon = logo_png_file
        alloc_id = dbus_send_notification(application, icon, title, body, 'Click to see changes', timeout)
        if alloc_id and identifier is not None:
            alloc_map[alloc_id] = identifier
