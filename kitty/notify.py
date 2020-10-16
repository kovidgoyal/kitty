#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2019, Kovid Goyal <kovid at kovidgoyal.net>

from base64 import standard_b64decode
from collections import OrderedDict
from itertools import count
from typing import Dict, Optional, Callable

from .constants import is_macos, logo_png_file
from .fast_data_types import get_boss
from .utils import log_error

if is_macos:
    from .fast_data_types import cocoa_send_notification

    def notify(
        title: str,
        body: str,
        timeout: int = 5000,
        application: str = 'kitty',
        icon: bool = True,
        identifier: Optional[str] = None,
        subtitle: Optional[str] = None,
    ) -> None:
        cocoa_send_notification(identifier, title, body, subtitle)

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
            notification_activated(identifier)

    def notify(
        title: str,
        body: str,
        timeout: int = -1,
        application: str = 'kitty',
        icon: bool = True,
        identifier: Optional[str] = None,
        subtitle: Optional[str] = None,
    ) -> None:
        icf = ''
        if icon is True:
            icf = logo_png_file
        alloc_id = dbus_send_notification(application, icf, title, body, 'Click to see changes', timeout)
        if alloc_id and identifier is not None:
            alloc_map[alloc_id] = identifier


class NotificationCommand:

    done: bool = True
    identifier: str = '0'
    title: str = ''
    body: str = ''
    actions: str = ''


def parse_osc_9(raw: str) -> NotificationCommand:
    ans = NotificationCommand()
    ans.title = raw
    return ans


def parse_osc_99(raw: str) -> NotificationCommand:
    cmd = NotificationCommand()
    metadata, payload = raw.partition(';')[::2]
    payload_is_encoded = False
    payload_type = 'title'
    if metadata:
        for part in metadata.split(':'):
            try:
                k, v = part.split('=', 1)
            except Exception:
                log_error('Malformed OSC 99: metadata is not key=value pairs')
                return cmd
            if k == 'p':
                payload_type = v
            elif k == 'i':
                cmd.identifier = v
            elif k == 'e':
                payload_is_encoded = v == '1'
            elif k == 'd':
                cmd.done = v != '0'
            elif k == 'a':
                cmd.actions += ',' + v
    if payload_type not in ('body', 'title'):
        log_error(f'Malformed OSC 99: unknown payload type: {payload_type}')
        return NotificationCommand()
    if payload_is_encoded:
        try:
            payload = standard_b64decode(payload).decode('utf-8')
        except Exception:
            log_error('Malformed OSC 99: payload is not base64 encoded UTF-8 text')
            return NotificationCommand()
    if payload_type == 'title':
        cmd.title = payload
    else:
        cmd.body = payload
    return cmd


def limit_size(x: str) -> str:
    if len(x) > 1024:
        x = x[:1024]
    return x


def merge_osc_99(prev: NotificationCommand, cmd: NotificationCommand) -> NotificationCommand:
    if prev.done or prev.identifier != cmd.identifier:
        return cmd
    cmd.actions = limit_size(prev.actions + ',' + cmd.actions)
    cmd.title = limit_size(prev.title + cmd.title)
    cmd.body = limit_size(prev.body + cmd.body)
    return cmd


identifier_registry: "OrderedDict[str, RegisteredNotification]" = OrderedDict()
id_counter = count()


class RegisteredNotification:
    identifier: str
    window_id: int
    focus: bool = True
    report: bool = False

    def __init__(self, cmd: NotificationCommand, window_id: int):
        self.window_id = window_id
        for x in cmd.actions.strip(',').split(','):
            val = not x.startswith('-')
            x = x.lstrip('+-')
            if x == 'focus':
                self.focus = val
            elif x == 'report':
                self.report = val
        self.identifier = cmd.identifier


def register_identifier(identifier: str, cmd: NotificationCommand, window_id: int) -> None:
    identifier_registry[identifier] = RegisteredNotification(cmd, window_id)
    if len(identifier_registry) > 100:
        identifier_registry.popitem(False)


def notification_activated(identifier: str, activated_implementation: Optional[Callable] = None) -> None:
    if identifier == 'new-version':
        from .update_check import notification_activated as do
        do()
    elif identifier.startswith('test-notify-'):
        log_error(f'Test notification {identifier} activated')
    else:
        r = identifier_registry.pop(identifier, None)
        if r is not None and (r.focus or r.report):
            if activated_implementation is None:
                get_boss().notification_activated(r.identifier, r.window_id, r.focus, r.report)
            else:
                activated_implementation(r.identifier, r.window_id, r.focus, r.report)


def reset_registry() -> None:
    global id_counter
    identifier_registry.clear()
    id_counter = count()


def notify_with_command(cmd: NotificationCommand, window_id: int, notify: Callable = notify) -> None:
    title = cmd.title or cmd.body
    body = cmd.body if cmd.title else ''
    if title:
        identifier = 'i' + str(next(id_counter))
        notify(title, body, identifier=identifier)
        register_identifier(identifier, cmd, window_id)


def handle_notification_cmd(
    osc_code: int,
    raw_data: str,
    window_id: int,
    prev_cmd: NotificationCommand,
    notify_implementation: Callable = notify
) -> Optional[NotificationCommand]:
    if osc_code == 99:
        cmd = merge_osc_99(prev_cmd, parse_osc_99(raw_data))
        if cmd.done:
            notify_with_command(cmd, window_id, notify_implementation)
            cmd = NotificationCommand()
        return cmd
    if osc_code == 9:
        cmd = parse_osc_9(raw_data)
        notify_with_command(cmd, window_id, notify_implementation)
