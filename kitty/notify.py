#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Dict, Optional

from .constants import is_macos, logo_png_file

if is_macos:
    from .fast_data_types import cocoa_send_notification

    def notify(
        title: str,
        body: str,
        timeout: int = 5000,
        application: str = 'kitty',
        icon: bool = True,
        identifier: Optional[str] = None
    ) -> None:
        cocoa_send_notification(identifier, title, body, None)

else:

    from .fast_data_types import dbus_send_notification

    alloc_map: Dict[int, str] = {}
    identifier_map: Dict[str, int] = {}

    def dbus_notification_created(alloc_id: int, notification_id: int) -> None:
        identifier = alloc_map.pop(alloc_id, None)
        if identifier is not None:
            identifier_map[identifier] = notification_id

    def dbus_notification_activated(notification_id: int, action: str) -> None:
        rmap = {v: k for k, v in identifier_map.items()}
        identifier = rmap.get(notification_id)
        if identifier is not None:
            from .boss import notification_activated
            notification_activated(identifier)

    def notify(
        title: str,
        body: str,
        timeout: int = -1,
        application: str = 'kitty',
        icon: bool = True,
        identifier: Optional[str] = None
    ) -> None:
        icf = ''
        if icon is True:
            icf = logo_png_file
        alloc_id = dbus_send_notification(application, icf, title, body, 'Click to see changes', timeout)
        if alloc_id and identifier is not None:
            alloc_map[alloc_id] = identifier
