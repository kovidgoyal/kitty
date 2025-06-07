#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from enum import Enum
from functools import partial
from itertools import count
from typing import Any, NamedTuple, Set
from weakref import ReferenceType, ref

from .constants import cache_dir, config_dir, is_macos, logo_png_file, standard_icon_names, standard_sound_names, supports_window_occlusion
from .fast_data_types import (
    ESC_OSC,
    StreamingBase64Decoder,
    add_timer,
    base64_decode,
    current_focused_os_window_id,
    get_boss,
    get_options,
    os_window_is_invisible,
)
from .types import run_once
from .typing_compat import WindowType
from .utils import get_custom_window_icon, log_error, sanitize_control_codes

debug_desktop_integration = False  # set by NotificationManager


def image_type(data: bytes) -> str:
    if data[:8] == b"\211PNG\r\n\032\n":
        return 'png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[:2] == b'\xff\xd8':
        return 'jpeg'
    return 'unknown'


class IconDataCache:

    def __init__(self, base_cache_dir: str = '', max_cache_size: int = 128 * 1024 * 1024):
        self.max_cache_size = max_cache_size
        self.key_map: dict[str, str] = {}
        self.hash_map: 'OrderedDict[str, Set[str]]' = OrderedDict()
        self.base_cache_dir = base_cache_dir
        self.cache_dir = ''
        self.total_size = 0
        import struct
        self.seed: int = struct.unpack("!Q", os.urandom(8))[0]

    def _ensure_state(self) -> str:
        if not self.cache_dir:
            self.cache_dir = os.path.join(self.base_cache_dir or cache_dir(), 'notifications-icons', str(os.getpid()))
            os.makedirs(self.cache_dir, exist_ok=True, mode=0o700)
            b = get_boss()
            if hasattr(b, 'atexit'):
                b.atexit.rmtree(self.cache_dir)
        return self.cache_dir

    def __del__(self) -> None:
        if self.cache_dir:
            import shutil
            with suppress(FileNotFoundError):
                shutil.rmtree(self.cache_dir)
            self.cache_dir = ''

    def keys(self) -> Iterator[str]:
        yield from self.key_map.keys()

    def hash(self, data: bytes) -> str:
        from kittens.transfer.rsync import xxh128_hash_with_seed
        d = xxh128_hash_with_seed(data, self.seed)
        return d.hex() + '.' + image_type(data)

    def add_icon(self, key: str, data: bytes) -> str:
        self._ensure_state()
        data_hash = self.hash(data)
        path = os.path.join(self.cache_dir, data_hash)
        if not os.path.exists(path):
            with open(path, 'wb') as f:
                f.write(data)
            self.total_size += len(data)
            self.hash_map[data_hash] = self.hash_map.pop(data_hash, set()) | {key} # mark this data as being used recently
        if key:
            self.key_map[key] = data_hash
        self.prune()
        return path

    def get_icon(self, key: str) -> str:
        self._ensure_state()
        data_hash = self.key_map.get(key)
        if data_hash:
            self.hash_map[data_hash] = self.hash_map.pop(data_hash, set()) | {key} # mark this data as being used recently
            return os.path.join(self.cache_dir, data_hash)
        return ''

    def clear(self) -> None:
        while self.hash_map:
            data_hash, keys = self.hash_map.popitem(False)
            for key in keys:
                self.key_map.pop(key, None)
            self._remove_data_file(data_hash)

    def prune(self) -> None:
        self._ensure_state()
        while self.total_size > self.max_cache_size and self.hash_map:
            data_hash, keys = self.hash_map.popitem(False)
            for key in keys:
                self.key_map.pop(key, None)
            self._remove_data_file(data_hash)

    def _remove_data_file(self, data_hash: str) -> None:
        path = os.path.join(self.cache_dir, data_hash)
        with suppress(FileNotFoundError):
            sz = os.path.getsize(path)
            os.remove(path)
            self.total_size -= sz

    def remove_icon(self, key: str) -> None:
        self._ensure_state()
        data_hash = self.key_map.pop(key, None)
        if data_hash:
            for key in self.hash_map.pop(data_hash, set()):
                self.key_map.pop(key, None)
            self._remove_data_file(data_hash)


class Urgency(Enum):
    Low = 0
    Normal = 1
    Critical = 2


class PayloadType(Enum):
    unknown = ''
    title = 'title'
    body = 'body'
    query = '?'
    close = 'close'
    icon = 'icon'
    alive = 'alive'
    buttons = 'buttons'

    @property
    def is_text(self) -> bool:
        return self in (PayloadType.title, PayloadType.body, PayloadType.buttons)


class OnlyWhen(Enum):
    unset = ''
    always = 'always'
    unfocused = 'unfocused'
    invisible = 'invisible'


class Action(Enum):
    focus = 'focus'
    report = 'report'


class DataStore:

    def __init__(self, max_size: int = 4 * 1024 * 1024) -> None:
        self.buf: list[bytes] = []
        self.current_size = 0
        self.max_size = max_size
        self.truncated = 0

    def __call__(self, data: bytes) -> None:
        if data:
            if self.current_size > self.max_size:
                self.truncated += len(data)
            else:
                self.current_size += len(data)
                self.buf.append(data)

    def finalise(self) -> bytes:
        return b''.join(self.buf)


class EncodedDataStore:

    def __init__(self, data_store: DataStore) -> None:
        self.decoder = StreamingBase64Decoder()
        self.data_store = data_store

    @property
    def truncated(self) -> int:
        return self.data_store.truncated

    def add_unencoded_data(self, data: str | bytes) -> None:
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.flush_encoded_data()
        self.data_store(data)

    def add_base64_data(self, data: str | bytes) -> None:
        if isinstance(data, str):
            data = data.encode('ascii')
        try:
            decoded = self.decoder.decode(data)
        except ValueError:
            log_error('Ignoring invalid base64 encoded data in notification request')
        else:
            self.data_store(decoded)

    def flush_encoded_data(self) -> None:
        if self.decoder.needs_more_data():
            log_error('Received incomplete encoded data for notification request')
        self.decoder.reset()

    def finalise(self) -> bytes:
        self.flush_encoded_data()
        return self.data_store.finalise()


def limit_size(x: str, limit: int = 1024) -> str:
    if len(x) > limit:
        x = x[:limit]
    return x


class NotificationCommand:

    # data received from client and eventually displayed/processed
    title: str = ''
    body: str = ''
    actions: frozenset[Action] = frozenset((Action.focus,))
    only_when: OnlyWhen = OnlyWhen.unset
    urgency: Urgency | None = None
    icon_data_key: str = ''
    icon_names: tuple[str, ...] = ()
    application_name: str = ''
    notification_types: tuple[str, ...] = ()
    timeout: int = -2
    buttons: tuple[str, ...] = ()
    sound_name: str = ''

    # event callbacks
    on_activation: Callable[['NotificationCommand', int], None] | None = None
    on_close: Callable[['NotificationCommand'], None] | None = None
    on_update: Callable[['NotificationCommand', 'NotificationCommand'], None] | None = None

    # metadata
    identifier: str = ''
    done: bool = True
    channel_id: int = 0
    desktop_notification_id: int = -1
    close_response_requested: bool | None = None
    icon_path: str = ''

    # payload handling
    current_payload_type: PayloadType = PayloadType.title
    current_payload_buffer: EncodedDataStore | None = None

    # desktop integration specific fields
    created_by_desktop: bool = False
    activation_token: str = ''

    def __init__(self, icon_data_cache: 'ReferenceType[IconDataCache]', log: 'Log') -> None:
        self.icon_data_cache_ref = icon_data_cache
        self.log = log

    @property
    def report_requested(self) -> bool:
        return Action.report in self.actions

    @property
    def focus_requested(self) -> bool:
        return Action.focus in self.actions

    def __repr__(self) -> str:
        fields = {}
        for x in ('title', 'body', 'identifier', 'actions', 'urgency', 'done'):
            val = getattr(self, x)
            if val:
                fields[x] = val
        return f'NotificationCommand{fields}'

    def parse_metadata(self, metadata: str, prev: 'NotificationCommand') -> tuple[PayloadType, bool]:
        payload_type = PayloadType.title
        payload_is_encoded = False
        if metadata:
            for part in metadata.split(':'):
                if not part:
                    continue
                k, v = part.split('=', 1)
                if k == 'p':
                    try:
                        payload_type = PayloadType(v)
                    except ValueError:
                        payload_type = PayloadType.unknown
                elif k == 'i':
                    self.identifier = sanitize_id(v)
                elif k == 'e':
                    payload_is_encoded = v == '1'
                elif k == 'd':
                    self.done = v != '0'
                elif k == 'a':
                    for ax in v.split(','):
                        if remove := ax.startswith('-'):
                            ax = ax.lstrip('+-')
                        try:
                            ac = Action(ax)
                        except ValueError:
                            pass
                        else:
                            if remove:
                                self.actions -= {ac}
                            else:
                                self.actions = self.actions.union({ac})
                elif k == 'o':
                    with suppress(ValueError):
                        self.only_when = OnlyWhen(v)
                elif k == 'u':
                    with suppress(Exception):
                        self.urgency = Urgency(int(v))
                elif k == 'c':
                    self.close_response_requested = v != '0'
                elif k == 'g':
                    self.icon_data_key = sanitize_id(v)
                elif k == 'n':
                    try:
                        self.icon_names += (base64_decode(v).decode('utf-8'),)
                    except Exception:
                        self.log(f'Ignoring invalid icon name in notification: {v!r}')
                elif k == 'f':
                    try:
                        self.application_name = base64_decode(v).decode('utf-8')
                    except Exception:
                        self.log(f'Ignoring invalid application_name in notification: {v!r}')
                elif k == 't':
                    try:
                        self.notification_types += (base64_decode(v).decode('utf-8'),)
                    except Exception:
                        self.log(f'Ignoring invalid notification type in notification: {v!r}')
                elif k == 'w':
                    try:
                        self.timeout = max(-1, int(v))
                    except Exception:
                        self.log(f'Ignoring invalid timeout in notification: {v!r}')
                elif k == 's':
                    try:
                        self.sound_name = base64_decode(v).decode('utf-8')
                    except Exception:
                        self.log(f'Ignoring invalid sound name in notification: {v!r}')
        if not prev.done and prev.identifier == self.identifier:
            self.merge_metadata(prev)
        return payload_type, payload_is_encoded

    def merge_metadata(self, prev: 'NotificationCommand') -> None:
        self.actions = prev.actions.union(self.actions)
        self.title = prev.title
        self.body = prev.body
        if self.only_when is OnlyWhen.unset:
            self.only_when = prev.only_when
        if self.urgency is None:
            self.urgency = prev.urgency
        if self.close_response_requested is None:
            self.close_response_requested = prev.close_response_requested
        if not self.icon_data_key:
            self.icon_data_key = prev.icon_data_key
        if prev.icon_names:
            self.icon_names = prev.icon_names + self.icon_names
        if not self.application_name:
            self.application_name = prev.application_name
        if prev.notification_types:
            self.notification_types = prev.notification_types + self.notification_types
        if prev.buttons:
            self.buttons += prev.buttons
        if not self.sound_name:
            self.sound_name = prev.sound_name
        if self.timeout < -1:
            self.timeout = prev.timeout
        self.icon_path = prev.icon_path

    def create_payload_buffer(self, payload_type: PayloadType) -> EncodedDataStore:
        self.current_payload_type = payload_type
        return EncodedDataStore(DataStore())

    def set_payload(self, payload_type: PayloadType, payload_is_encoded: bool, payload: str, prev_cmd: 'NotificationCommand') -> None:
        if prev_cmd.current_payload_type is payload_type:
            self.current_payload_type = payload_type
            self.current_payload_buffer = prev_cmd.current_payload_buffer
            prev_cmd.current_payload_buffer = None
        else:
            if prev_cmd.current_payload_buffer:
                self.current_payload_type = prev_cmd.current_payload_type
                self.commit_data(prev_cmd.current_payload_buffer.finalise(), prev_cmd.current_payload_buffer.truncated)
        if self.current_payload_buffer is None:
            self.current_payload_buffer = self.create_payload_buffer(payload_type)
        if payload_is_encoded:
            self.current_payload_buffer.add_base64_data(payload)
        else:
            self.current_payload_buffer.add_unencoded_data(payload)

    def commit_data(self, data: bytes, truncated: int) -> None:
        if not data:
            return
        if self.current_payload_type.is_text:
            if truncated:
                text = ' too long, truncated'
            else:
                text = data.decode('utf-8', 'replace')
        if self.current_payload_type is PayloadType.title:
            self.title = limit_size(self.title + text)
        elif self.current_payload_type is PayloadType.body:
            self.body = limit_size(self.body + text)
        elif self.current_payload_type is PayloadType.icon:
            if truncated:
                self.log('Ignoring too long notification icon data')
            else:
                icd = self.icon_data_cache_ref()
                if icd:
                    self.icon_path = icd.add_icon(self.icon_data_key, data)
        elif self.current_payload_type is PayloadType.buttons:
            self.buttons += tuple(limit_size(x, 256) for x in text.split('\u2028') if x)
            self.buttons = self.buttons[:8]

    def finalise(self) -> None:
        if self.current_payload_buffer:
            self.commit_data(self.current_payload_buffer.finalise(), self.current_payload_buffer.truncated)
            self.current_payload_buffer = None
        if self.icon_data_key and not self.icon_path:
            icd = self.icon_data_cache_ref()
            if icd:
                self.icon_path = icd.get_icon(self.icon_data_key)
        if self.title:
            self.title = sanitize_text(self.title)
            self.body = sanitize_text(self.body)
        else:
            self.title = sanitize_text(self.body)
            self.body = ''
        self.urgency = Urgency.Normal if self.urgency is None else self.urgency
        self.close_response_requested = bool(self.close_response_requested)
        self.timeout = max(-1, self.timeout)
        self.sound_name = self.sound_name or 'system'

    def matches_rule_item(self, location:str, query:str) -> bool:
        import re
        pat = re.compile(query)
        if location == 'type':
            for x in self.notification_types:
                if pat.search(x) is not None:
                    return True
        val = {'title': self.title, 'body': self.body, 'app': self.application_name}[location]
        return pat.search(val) is not None

    def matches_rule(self, rule: str) -> bool:
        if rule == 'all':
            return True
        from .search_query_parser import search
        def get_matches(location: str, query: str, candidates: set['NotificationCommand']) -> set['NotificationCommand']:
            return {x for x in candidates if x.matches_rule_item(location, query)}
        try:
            return self in search(rule, ('title', 'body', 'app', 'type'), {self}, get_matches)
        except Exception as e:
            self.log(f'Ignoring invalid filter_notification rule: {rule} with error: {e}')
        return False


class DesktopIntegration:

    supports_close_events: bool = True
    supports_body: bool = True
    supports_buttons: bool = True
    supports_sound: bool = True
    supports_sound_names: str = 'xdg-names'
    supports_timeout_natively: bool = True

    def __init__(self, notification_manager: 'NotificationManager'):
        self.notification_manager = notification_manager
        self.initialize()

    def initialize(self) -> None:
        pass

    def query_live_notifications(self, channel_id: int, identifier: str) -> None:
        raise NotImplementedError('Implement me in subclass')

    def close_notification(self, desktop_notification_id: int) -> bool:
        raise NotImplementedError('Implement me in subclass')

    def notify(self, nc: NotificationCommand, existing_desktop_notification_id: int | None) -> int:
        raise NotImplementedError('Implement me in subclass')

    def on_new_version_notification_activation(self, cmd: NotificationCommand, which: int) -> None:
        from .update_check import notification_activated
        notification_activated()

    def payload_type_supported(self, x: PayloadType) -> bool:
        if x is PayloadType.body and not self.supports_body:
            return False
        if x is PayloadType.buttons and not self.supports_buttons:
            return False
        return True

    def query_response(self, identifier: str) -> str:
        actions = ','.join(x.value for x in Action)
        when = ','.join(x.value for x in OnlyWhen if x.value)
        urgency = ','.join(str(x.value) for x in Urgency)
        i = f'i={identifier or "0"}:'
        p = ','.join(x.value for x in PayloadType if x.value and self.payload_type_supported(x))
        c = ':c=1' if self.supports_close_events else ''
        s = 'system,silent,' + ','.join(sorted(standard_sound_names))
        return f'99;{i}p=?;a={actions}:o={when}:u={urgency}:p={p}{c}:w=1:s={s}'


class MacOSNotificationCategory(NamedTuple):
    id: str
    buttons: tuple[str, ...] = ()
    button_ids: tuple[str, ...] = ()


class MacOSIntegration(DesktopIntegration):

    supports_close_events: bool = False
    supports_sound_names: str = ''
    supports_timeout_natively: bool = False

    def initialize(self) -> None:
        from .fast_data_types import cocoa_set_notification_activated_callback
        self.id_counter = count(start=1)
        self.live_notification_queries: list[tuple[int, str]] = []
        self.failed_icons: OrderedDict[str, bool] = OrderedDict()
        self.icd_key_prefix = os.urandom(16).hex()
        self.category_cache: OrderedDict[tuple[str, ...], MacOSNotificationCategory] = OrderedDict()
        self.category_id_counter = count(start=2)
        self.buttons_id_counter = count(start=1)
        self.default_category = MacOSNotificationCategory('1')
        self.current_categories: frozenset[MacOSNotificationCategory] = frozenset()
        cocoa_set_notification_activated_callback(self.notification_activated)

    def query_live_notifications(self, channel_id: int, identifier: str) -> None:
        from .fast_data_types import cocoa_live_delivered_notifications
        if not cocoa_live_delivered_notifications():
            self.notification_manager.send_live_response(channel_id, identifier, ())
        else:
            self.live_notification_queries.append((channel_id, identifier))

    def close_notification(self, desktop_notification_id: int) -> bool:
        from .fast_data_types import cocoa_remove_delivered_notification
        close_succeeded = cocoa_remove_delivered_notification(str(desktop_notification_id))
        if debug_desktop_integration:
            log_error(f'Close request for {desktop_notification_id=} {"succeeded" if close_succeeded else "failed"}')
        return close_succeeded

    def get_icon_for_name(self, name: str) -> str:
        from .fast_data_types import cocoa_bundle_image_as_png
        if name in self.failed_icons:
            return ''
        image_type, image_name = 1, name
        if sic := standard_icon_names.get(name):
            image_name = sic[1]
            image_type = 2
        icd = self.notification_manager.icon_data_cache
        icd_key = self.icd_key_prefix + name
        ans = icd.get_icon(icd_key)
        if ans:
            return ans
        try:
            data = cocoa_bundle_image_as_png(image_name, image_type=image_type)
        except Exception as err:
            if debug_desktop_integration:
                self.notification_manager.log(f'Failed to get icon for {name} with error: {err}')
            self.failed_icons[name] = True
            if len(self.failed_icons) > 256:
                self.failed_icons.popitem(False)
        else:
            return icd.add_icon(icd_key, data)
        return ''

    def category_for_notification(self, nc: NotificationCommand) -> MacOSNotificationCategory:
        key = nc.buttons
        if not key:
            return self.default_category
        if ans := self.category_cache.get(key):
            self.category_cache.pop(key)
            self.category_cache[key] = ans
            return ans
        ans = self.category_cache[key] = MacOSNotificationCategory(
            str(next(self.category_id_counter)), nc.buttons, tuple(str(next(self.buttons_id_counter)) for x in nc.buttons)
        )
        if len(self.category_cache) > 32:
            self.category_cache.popitem(False)
        return ans

    def notify(self, nc: NotificationCommand, existing_desktop_notification_id: int | None) -> int:
        desktop_notification_id = existing_desktop_notification_id or next(self.id_counter)
        from .fast_data_types import cocoa_send_notification
        # If the body is not set macos makes the title the body and uses
        # "kitty" as the title. So use a single space for the body in this
        # case. Although https://developer.apple.com/documentation/usernotifications/unnotificationcontent/body?language=objc
        # says printf style strings are stripped this does not actually happen, so dont double % for %% escaping.
        body = (nc.body or ' ')
        assert nc.urgency is not None
        image_path = ''
        if nc.icon_names:
            for name in nc.icon_names:
                if image_path := self.get_icon_for_name(name):
                    break
        image_path = image_path or nc.icon_path
        if not image_path and nc.application_name:
            image_path = self.get_icon_for_name(nc.application_name)
        category = self.category_for_notification(nc)
        categories = tuple(self.category_cache.values())
        sc = frozenset(categories)
        if sc == self.current_categories:
            categories = ()
        else:
            self.current_categories = sc

        cocoa_send_notification(
            nc.application_name or 'kitty', str(desktop_notification_id), nc.title, body,
            category=category, categories=categories, image_path=image_path, urgency=nc.urgency.value,
            muted=nc.sound_name == 'silent' or nc.sound_name in standard_sound_names,
        )
        return desktop_notification_id

    def notification_activated(self, event: str, ident: str, button_id: str) -> None:
        if event == 'live':
            live_ids = tuple(int(x) for x in ident.split(',') if x)
            if debug_desktop_integration:
                log_error(f'Live notifications: {live_ids}')
            self.notification_manager.purge_dead_notifications(live_ids)
            self.live_notification_queries, queries = [], self.live_notification_queries
            for channel_id, req_id in queries:
                self.notification_manager.send_live_response(channel_id, req_id, live_ids)
            return
        if debug_desktop_integration:
            log_error(f'Notification {ident=} {event=} {button_id=}')
        try:
            desktop_notification_id = int(ident)
        except Exception:
            log_error(f'Got unexpected notification activated event with id: {ident!r} from cocoa')
            return
        if event == 'created':
            n = self.notification_manager.notification_created(desktop_notification_id)
            # so that we purge dead notifications, check for live notifications
            # after a few seconds, cant check right away as cocoa does not
            # report the created notification as live.
            add_timer(self.check_live_delivered_notifications, 5.0, False)
            if n and n.sound_name in standard_sound_names:
                from .fast_data_types import cocoa_play_system_sound_by_id_async
                cocoa_play_system_sound_by_id_async(standard_sound_names[n.sound_name][1])
        elif event == 'activated':
            self.notification_manager.notification_activated(desktop_notification_id, 0)
        elif event == 'creation_failed':
            self.notification_manager.notification_closed(desktop_notification_id)
        elif event == 'closed':  # sadly Crapple never delivers these events
            self.notification_manager.notification_closed(desktop_notification_id)
        elif event == 'button':
            if n := self.notification_manager.in_progress_notification_commands.get(desktop_notification_id):
                if debug_desktop_integration:
                    log_error('Button matches notification:', n)
                for c in self.current_categories:
                    if c.buttons == n.buttons and button_id in c.button_ids:
                        if debug_desktop_integration:
                            log_error('Button number:', c.button_ids.index(button_id) + 1)
                        self.notification_manager.notification_activated(desktop_notification_id, c.button_ids.index(button_id) + 1)
                        break
                else:
                    if debug_desktop_integration:
                        log_error('No category found with buttons:', n.buttons)
                        log_error('Current categories:', self.current_categories)

    def check_live_delivered_notifications(self, *a: object) -> None:
        from .fast_data_types import cocoa_live_delivered_notifications
        cocoa_live_delivered_notifications()


class FreeDesktopIntegration(DesktopIntegration):

    supports_body_markup: bool = True

    def initialize(self) -> None:
        from .fast_data_types import dbus_set_notification_callback
        dbus_set_notification_callback(self.dispatch_event_from_desktop)
        # map the id returned by the notification daemon to the
        # desktop_notification_id we use for the notification
        self.dbus_to_desktop: 'OrderedDict[int, int]' = OrderedDict()
        self.desktop_to_dbus: dict[int, int] = {}

    def query_live_notifications(self, channel_id: int, identifier: str) -> None:
        self.notification_manager.send_live_response(channel_id, identifier, tuple(self.desktop_to_dbus))

    def close_notification(self, desktop_notification_id: int) -> bool:
        from .fast_data_types import dbus_close_notification
        close_succeeded = False
        if dbus_id := self.get_dbus_notification_id(desktop_notification_id, 'close_request'):
            close_succeeded = dbus_close_notification(dbus_id)
            if debug_desktop_integration:
                log_error(f'Close request for {desktop_notification_id=} {"succeeded" if close_succeeded else "failed"}')
        return close_succeeded

    def get_desktop_notification_id(self, dbus_notification_id: int, event: str) -> int | None:
        q = self.dbus_to_desktop.get(dbus_notification_id)
        if q is None:
            if debug_desktop_integration:
                log_error(f'Could not find desktop_notification_id for {dbus_notification_id=} for event {event}')
        return q

    def get_dbus_notification_id(self, desktop_notification_id: int, event: str) ->int | None:
        q = self.desktop_to_dbus.get(desktop_notification_id)
        if q is None:
            if debug_desktop_integration:
                log_error(f'Could not find dbus_notification_id for {desktop_notification_id=} for event {event}')
        return q

    def created(self, dbus_notification_id: int, desktop_notification_id: int) -> None:
        self.dbus_to_desktop[desktop_notification_id] = dbus_notification_id
        self.desktop_to_dbus[dbus_notification_id] = desktop_notification_id
        if len(self.dbus_to_desktop) > 128:
            k, v = self.dbus_to_desktop.popitem(False)
            self.desktop_to_dbus.pop(v, None)
        if n := self.notification_manager.notification_created(dbus_notification_id):
            # self.supports_sound does not tell us if the notification server
            # supports named sounds or not so we play the named sound
            # ourselves and tell the server to mute any sound it might play.
            if n.sound_name not in ('system', 'silent'):
                sn = standard_sound_names[n.sound_name][0] if n.sound_name in standard_sound_names else n.sound_name
                from .fast_data_types import play_desktop_sound_async
                play_desktop_sound_async(sn, event_id='desktop notification')

    def dispatch_event_from_desktop(self, event_type: str, dbus_notification_id: int, extra: int | str) -> None:
        if event_type == 'capabilities':
            capabilities = frozenset(str(extra).splitlines())
            self.supports_body = 'body' in capabilities
            self.supports_buttons = 'actions' in capabilities
            self.supports_body_markup = 'body-markup' in capabilities
            self.supports_sound = 'sound' in capabilities
            if debug_desktop_integration:
                log_error('Got notification server capabilities:', capabilities)
            return
        if debug_desktop_integration:
            log_error(f'Got notification event from desktop: {event_type=} {dbus_notification_id=} {extra=}')
        if event_type == 'created':
            self.created(dbus_notification_id, int(extra))
            return
        if desktop_notification_id := self.get_desktop_notification_id(dbus_notification_id, event_type):
            if event_type == 'activation_token':
                self.notification_manager.notification_activation_token_received(desktop_notification_id, str(extra))
            elif event_type == 'activated':
                button = 0 if extra == 'default' else int(extra)
                self.notification_manager.notification_activated(desktop_notification_id, button)
            elif event_type == 'closed':
                self.notification_manager.notification_closed(desktop_notification_id)

    def notify(self, nc: NotificationCommand, existing_desktop_notification_id: int | None) -> int:
        from .fast_data_types import dbus_send_notification
        from .xdg import icon_exists, icon_for_appname
        app_icon = ''
        if nc.icon_names:
            for name in nc.icon_names:
                if sn := standard_icon_names.get(name):
                    app_icon = sn[0]
                    break
                if icon_exists(name):
                    app_icon = name
                    break
            if not app_icon:
                app_icon = nc.icon_path or nc.icon_names[0]
        else:
            app_icon = nc.icon_path or icon_for_appname(nc.application_name)
        if not app_icon:
            app_icon = get_custom_window_icon()[1] or logo_png_file

        body = nc.body
        if self.supports_body_markup:
            body = body.replace('<', '<\u200c').replace('&', '&\u200c')  # prevent HTML markup from being recognized
        assert nc.urgency is not None
        replaces_dbus_id = 0
        if existing_desktop_notification_id:
            replaces_dbus_id = self.get_dbus_notification_id(existing_desktop_notification_id, 'notify') or 0
        actions = {'default': ' '}  # dbus requires string to not be empty
        for i, b in enumerate(nc.buttons):
            actions[str(i+1)] = b
        desktop_notification_id = dbus_send_notification(
            app_name=nc.application_name or 'kitty', app_icon=app_icon, title=nc.title, body=body, actions=actions,
            timeout=nc.timeout, urgency=nc.urgency.value, replaces=replaces_dbus_id,
            category=(nc.notification_types or ('',))[0], muted=nc.sound_name == 'silent' or nc.sound_name != 'system',
        )
        if debug_desktop_integration:
            log_error(f'Requested creation of notification with {desktop_notification_id=}')
        if existing_desktop_notification_id and replaces_dbus_id:
            self.dbus_to_desktop.pop(replaces_dbus_id, None)
            self.desktop_to_dbus.pop(existing_desktop_notification_id, None)
        return desktop_notification_id


class UIState(NamedTuple):
    has_keyboard_focus: bool
    is_visible: bool


class Channel:

    def window_for_id(self, channel_id: int) -> WindowType | None:
        boss = get_boss()
        if channel_id:
            return boss.window_id_map.get(channel_id)
        return boss.active_window

    def ui_state(self, channel_id: int) -> UIState:
        has_focus = is_visible = False
        boss = get_boss()
        if w := self.window_for_id(channel_id):
            os_window_active = w.os_window_id == current_focused_os_window_id()
            has_focus = w.is_active and os_window_active
            is_visible = os_window_active
            if supports_window_occlusion():
                is_visible = not os_window_is_invisible(w.os_window_id)
            is_visible = is_visible and w.tabref() is boss.active_tab and w.is_visible_in_layout
        return UIState(has_focus, is_visible)

    def send(self, channel_id: int, osc_escape_code: str) -> bool:
        if w := self.window_for_id(channel_id):
            if not w.destroyed:
                w.screen.send_escape_code_to_child(ESC_OSC, osc_escape_code)
                return True
        return False

    def focus(self, channel_id: int, activation_token: str) -> None:
        if debug_desktop_integration:
            log_error(f'Focusing window: {channel_id} with activation_token: {activation_token}')
        boss = get_boss()
        if w := self.window_for_id(channel_id):
            boss.set_active_window(w, switch_os_window_if_needed=True, activation_token=activation_token)


sanitize_text = sanitize_control_codes

@run_once
def sanitize_identifier_pat() -> 're.Pattern[str]':
    return re.compile(r'[^a-zA-Z0-9-_+.]+')


def sanitize_id(v: str) -> str:
    return sanitize_identifier_pat().sub('', v)[:512]


class Log:
    def __call__(self, *a: Any, **kw: str) -> None:
        log_error(*a, **kw)


class NotificationManager:

    def __init__(
        self,
        desktop_integration: MacOSIntegration | FreeDesktopIntegration | None = None,
        channel: Channel = Channel(),
        log: Log = Log(),
        debug: bool = False,
        base_cache_dir: str = '',
    ):
        global debug_desktop_integration
        debug_desktop_integration = debug
        if desktop_integration is None:
            self.desktop_integration = MacOSIntegration(self) if is_macos else FreeDesktopIntegration(self)
        else:
            self.desktop_integration = desktop_integration
        self.channel = channel
        self.base_cache_dir = base_cache_dir
        self.log = log
        self.icon_data_cache = IconDataCache(base_cache_dir=self.base_cache_dir)
        script_path = os.path.join(config_dir, 'notifications.py')
        self.filter_script: Callable[[NotificationCommand], bool] = lambda nc: False
        if os.path.exists(script_path):
            import runpy
            try:
                m = runpy.run_path(script_path)
                self.filter_script = m['main']
            except Exception as e:
                self.log(f'Failed to load {script_path} with error: {e}')
        self.reset()

    def reset(self) -> None:
        self.icon_data_cache.clear()
        self.in_progress_notification_commands: 'OrderedDict[int, NotificationCommand]' = OrderedDict()
        self.in_progress_notification_commands_by_client_id: dict[str, NotificationCommand] = {}
        self.pending_commands: dict[int, NotificationCommand] = {}

    def notification_created(self, desktop_notification_id: int) -> NotificationCommand | None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            n.created_by_desktop = True
            if n.timeout > 0 and not self.desktop_integration.supports_timeout_natively:
                add_timer(partial(self.expire_notification, desktop_notification_id, id(n)), n.timeout / 1000, False)
            return n
        return None

    def notification_activation_token_received(self, desktop_notification_id: int, token: str) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            n.activation_token = token

    def notification_activated(self, desktop_notification_id: int, button: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            if not n.close_response_requested:
                self.purge_notification(n)
            if n.focus_requested:
                self.channel.focus(n.channel_id, n.activation_token)
            if n.report_requested:
                self.channel.send(n.channel_id, f'99;i={n.identifier or "0"};{button or ""}')
            if n.on_activation:
                try:
                    n.on_activation(n, button)
                except Exception as e:
                    self.log('Notification on_activation handler failed with error:', e)

    def notification_replaced(self, old_cmd: NotificationCommand, new_cmd: NotificationCommand) -> None:
        if old_cmd.desktop_notification_id != new_cmd.desktop_notification_id:
            self.in_progress_notification_commands.pop(old_cmd.desktop_notification_id, None)
        if old_cmd.on_update is not None:
            try:
                old_cmd.on_update(old_cmd, new_cmd)
            except Exception as e:
                self.log('Notification on_update handler failed with error:', e)

    def notification_closed(self, desktop_notification_id: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            self.purge_notification(n)
            if n.close_response_requested and self.desktop_integration.supports_close_events:
                self.send_closed_response(n.channel_id, n.identifier)
            if n.on_close is not None:
                try:
                    n.on_close(n)
                except Exception as e:
                    self.log('Notification on_close handler failed with error:', e)

    def create_notification_cmd(self) -> NotificationCommand:
        return NotificationCommand(ref(self.icon_data_cache), self.log)

    def send_test_notification(self) -> None:
        boss = get_boss()
        if w := boss.active_window:
            from time import monotonic
            cmd = self.create_notification_cmd()
            now = monotonic()
            cmd.title = f'Test {now}'
            cmd.body = f'At: {now}'
            cmd.on_activation = print
            self.notify_with_command(cmd, w.id)

    def send_new_version_notification(self, version: str) -> None:
        cmd = self.create_notification_cmd()
        cmd.title = 'kitty update available!'
        cmd.body = f'kitty version {version} released'
        cmd.on_activation = self.desktop_integration.on_new_version_notification_activation
        self.notify_with_command(cmd, 0)

    def is_notification_allowed(self, cmd: NotificationCommand, channel_id: int, apply_filter_rules: bool = True) -> bool:
        if cmd.only_when is not OnlyWhen.always and cmd.only_when is not OnlyWhen.unset:
            ui_state = self.channel.ui_state(channel_id)
            if ui_state.has_keyboard_focus:
                return False
            if cmd.only_when is OnlyWhen.invisible and ui_state.is_visible:
                return False
        return True

    @property
    def filter_rules(self) -> Iterator[str]:
        return iter(get_options().filter_notification.keys())

    def is_notification_filtered(self, cmd: NotificationCommand) -> bool:
        if self.filter_script(cmd):
            self.log(f'Notification {cmd.title!r} filtered out by script')
            return True
        for rule in self.filter_rules:
            if cmd.matches_rule(rule):
                self.log(f'Notification {cmd.title!r} filtered out by filter_notification rule: {rule}')
                return True
        return False

    def notify_with_command(self, cmd: NotificationCommand, channel_id: int) -> int | None:
        cmd.channel_id = channel_id
        cmd.finalise()
        if not cmd.title or not self.is_notification_allowed(cmd, channel_id) or self.is_notification_filtered(cmd):
            return None
        existing_desktop_notification_id: int | None = None
        existing_cmd = self.in_progress_notification_commands_by_client_id.get(cmd.identifier) if cmd.identifier else None
        if existing_cmd:
            existing_desktop_notification_id = existing_cmd.desktop_notification_id
        desktop_notification_id = self.desktop_integration.notify(cmd, existing_desktop_notification_id)
        self.register_in_progress_notification(cmd, desktop_notification_id)
        if existing_cmd:
            self.notification_replaced(existing_cmd, cmd)
        if not self.desktop_integration.supports_close_events and cmd.close_response_requested:
            self.send_closed_response(channel_id, cmd.identifier, untracked=True)
        return desktop_notification_id

    def expire_notification(self, desktop_notification_id: int, command_id: int, timer_id: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            if id(n) == command_id:
                self.desktop_integration.close_notification(desktop_notification_id)

    def register_in_progress_notification(self, cmd: NotificationCommand, desktop_notification_id: int) -> None:
        cmd.desktop_notification_id = desktop_notification_id
        self.in_progress_notification_commands[desktop_notification_id] = cmd
        if cmd.identifier:
            self.in_progress_notification_commands_by_client_id[cmd.identifier] = cmd
        if len(self.in_progress_notification_commands) > 128:
            _, cmd = self.in_progress_notification_commands.popitem(False)
            self.in_progress_notification_commands_by_client_id.pop(cmd.identifier, None)

    def parse_notification_cmd(
        self, prev_cmd: NotificationCommand, channel_id: int, raw: str
    ) -> NotificationCommand | None:
        metadata, payload = raw.partition(';')[::2]
        cmd = self.create_notification_cmd()
        try:
            payload_type, payload_is_encoded = cmd.parse_metadata(metadata, prev_cmd)
        except Exception:
            self.log('Malformed metadata section in OSC 99: ' + metadata)
            return None
        if payload_type is PayloadType.query:
            self.channel.send(channel_id, self.desktop_integration.query_response(cmd.identifier))
            return None
        if payload_type is PayloadType.alive:
            if cmd.identifier:
                self.desktop_integration.query_live_notifications(channel_id, cmd.identifier)
            return None
        if payload_type is PayloadType.close:
            if cmd.identifier:
                to_close = self.in_progress_notification_commands_by_client_id.get(cmd.identifier)
                if to_close:
                    if not self.desktop_integration.close_notification(to_close.desktop_notification_id):
                        if to_close.close_response_requested:
                            self.send_closed_response(to_close.channel_id, to_close.identifier)
                        self.purge_notification(to_close)
            return None

        if payload_type is PayloadType.unknown:
            self.log(f'OSC 99: unknown payload type: {payload_type}, ignoring payload')
            payload = ''

        cmd.set_payload(payload_type, payload_is_encoded, payload, prev_cmd)
        return cmd

    def send_closed_response(self, channel_id: int, client_id: str, untracked: bool = False) -> None:
        payload = 'untracked' if untracked else ''
        self.channel.send(channel_id, f'99;i={client_id}:p={PayloadType.close.value};{payload}')

    def send_live_response(self, channel_id: int, client_id: str, live_desktop_ids: Sequence[int]) -> None:
        ids = []
        for desktop_notification_id in live_desktop_ids:
            if n := self.in_progress_notification_commands.get(desktop_notification_id):
                if n.identifier and n.channel_id == channel_id:
                    ids.append(n.identifier)
        self.channel.send(channel_id, f'99;i={client_id}:p={PayloadType.alive.value};{",".join(ids)}')

    def purge_dead_notifications(self, live_desktop_ids: Sequence[int]) -> None:
        for d in set(self.in_progress_notification_commands) - set(live_desktop_ids):
            if debug_desktop_integration:
                log_error(f'Purging dead notification {d} from list of live notifications:', live_desktop_ids)
            self.purge_notification(self.in_progress_notification_commands[d])

    def purge_notification(self, cmd: NotificationCommand) -> None:
        self.in_progress_notification_commands_by_client_id.pop(cmd.identifier, None)
        self.in_progress_notification_commands.pop(cmd.desktop_notification_id, None)

    def handle_notification_cmd(self, channel_id: int, osc_code: int, raw: str) -> None:
        if osc_code == 99:
            cmd = self.pending_commands.pop(channel_id, None) or self.create_notification_cmd()
            q = self.parse_notification_cmd(cmd, channel_id, raw)
            if q is not None:
                if q.done:
                    self.notify_with_command(q, channel_id)
                else:
                    self.pending_commands[channel_id] = q
        elif osc_code == 9:
            n = self.create_notification_cmd()
            n.title = raw
            self.notify_with_command(n, channel_id)
        elif osc_code == 777:
            n = self.create_notification_cmd()
            parts = raw.split(';', 1)
            n.title, n.body = parts[0], (parts[1] if len(parts) > 1 else '')
            self.notify_with_command(n, channel_id)

    def close_notification(self, desktop_notification_id: int) -> None:
        self.desktop_integration.close_notification(desktop_notification_id)

    def cleanup(self) -> None:
        del self.icon_data_cache
