#!/usr/bin/env python
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

    alloc_map = {}
    identifier_map = {}

    def dbus_notification_created(alloc_id, notification_id):
        identifier = alloc_map.get(alloc_id)
        if identifier is not None:
            identifier_map[identifier] = notification_id

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
        alloc_id = dbus_send_notification(application, icon, title, body, timeout)
        if alloc_id and identifier is not None:
            alloc_map[alloc_id] = identifier
