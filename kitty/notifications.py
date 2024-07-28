#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
from collections import OrderedDict
from contextlib import suppress
from enum import Enum
from itertools import count
from typing import Any, Callable, Dict, FrozenSet, Iterator, List, NamedTuple, Optional, Set, Tuple, Union
from weakref import ReferenceType, ref

from .constants import cache_dir, config_dir, is_macos, logo_png_file
from .fast_data_types import ESC_OSC, StreamingBase64Decoder, base64_decode, current_focused_os_window_id, get_boss, get_options
from .types import run_once
from .typing import WindowType
from .utils import get_custom_window_icon, log_error, sanitize_control_codes

debug_desktop_integration = False


class IconDataCache:


    def __init__(self, base_cache_dir: str = '', max_cache_size: int = 128 * 1024 * 1024):
        self.max_cache_size = max_cache_size
        self.key_map: 'OrderedDict[str, str]' = OrderedDict()
        self.base_cache_dir = base_cache_dir
        self.cache_dir = ''
        self.total_size = 0
        import struct
        self.seed: int = struct.unpack("!Q", os.urandom(8))[0]

    def _ensure_state(self) -> str:
        if not self.cache_dir:
            self.cache_dir = os.path.join(self.base_cache_dir or cache_dir(), 'notifications-icons', str(os.getpid()))
            os.makedirs(self.cache_dir, exist_ok=True, mode=0o700)
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
        return d.hex()

    def add_icon(self, key: str, data: bytes) -> str:
        self._ensure_state()
        data_hash = self.hash(data)
        path = os.path.join(self.cache_dir, data_hash)
        if not os.path.exists(path):
            with open(path, 'wb') as f:
                f.write(data)
            self.total_size += len(data)
        self.key_map.pop(key, None)  # mark this key as being used recently
        self.key_map[key] = data_hash
        self.prune()
        return path

    def get_icon(self, key: str) -> str:
        self._ensure_state()
        data_hash = self.key_map.pop(key, None)
        if data_hash:
            self.key_map[key] = data_hash  # mark this key as being used recently
            return os.path.join(self.cache_dir, data_hash)
        return ''

    def clear(self) -> None:
        while self.key_map:
            key, data_hash = self.key_map.popitem(False)
            self._remove_data_hash(data_hash)

    def prune(self) -> None:
        self._ensure_state()
        while self.total_size > self.max_cache_size and self.key_map:
            key, data_hash = self.key_map.popitem(False)
            self._remove_data_hash(data_hash)

    def _remove_data_hash(self, data_hash: str) -> None:
        path = os.path.join(self.cache_dir, data_hash)
        with suppress(FileNotFoundError):
            sz = os.path.getsize(path)
            os.remove(path)
            self.total_size -= sz

    def remove_icon(self, key: str) -> None:
        self._ensure_state()
        data_hash = self.key_map.pop(key, None)
        if data_hash:
            self._remove_data_hash(data_hash)


class Urgency(Enum):
    Low: int = 0
    Normal: int = 1
    Critical: int = 2


class PayloadType(Enum):
    unknown = ''
    title = 'title'
    body = 'body'
    query = '?'
    close = 'close'
    icon = 'icon'

    @property
    def is_text(self) -> bool:
        return self in (PayloadType.title, PayloadType.body)


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
        self.buf: List[bytes] = []
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
        self.decoder = StreamingBase64Decoder(initial_capacity=4096)
        self.data_store = data_store

    @property
    def truncated(self) -> int:
        return self.data_store.truncated

    def add_unencoded_data(self, data: Union[str, bytes]) -> None:
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.flush_encoded_data()
        self.data_store(data)

    def add_base64_data(self, data: Union[str, bytes]) -> None:
        if isinstance(data, str):
            data = data.encode('ascii')
        self.decoder.add(data)
        if len(self.decoder) >= self.data_store.max_size:
            self.data_store(self.decoder.take_output())

    def flush_encoded_data(self) -> None:
        self.decoder.flush()
        if len(self.decoder):
            self.data_store(self.decoder.take_output())

    def finalise(self) -> bytes:
        self.flush_encoded_data()
        return self.data_store.finalise()


def limit_size(x: str) -> str:
    if len(x) > 1024:
        x = x[:1024]
    return x


class NotificationCommand:

    # data received from client and eventually displayed/processed
    title: str = ''
    body: str = ''
    actions: FrozenSet[Action] = frozenset((Action.focus,))
    only_when: OnlyWhen = OnlyWhen.unset
    urgency: Optional[Urgency] = None
    icon_data_key: str = ''
    icon_name: str = ''
    application_name: str = ''
    notification_type: str = ''

    # event callbacks
    on_activation: Optional[Callable[['NotificationCommand'], None]] = None
    on_close: Optional[Callable[['NotificationCommand'], None]] = None

    # metadata
    identifier: str = ''
    done: bool = True
    channel_id: int = 0
    desktop_notification_id: int = -1
    close_response_requested: Optional[bool] = None
    icon_path: str = ''

    # payload handling
    current_payload_type: PayloadType = PayloadType.title
    current_payload_buffer: Optional[EncodedDataStore] = None

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
        return (
            f'NotificationCommand(identifier={self.identifier!r}, title={self.title!r}, body={self.body!r},'
            f'actions={self.actions}, done={self.done!r}, urgency={self.urgency})')

    def parse_metadata(self, metadata: str, prev: 'NotificationCommand') -> Tuple[PayloadType, bool]:
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
                    self.icon_name = v
                elif k == 'f':
                    try:
                        self.application_name = base64_decode(v).decode('utf-8', 'replace')
                    except Exception:
                        self.log('Ignoring invalid application_name in notification: {v!r}')
                elif k == 't':
                    try:
                        self.notification_type = base64_decode(v).decode('utf-8', 'replace')
                    except Exception:
                        self.log('Ignoring invalid notification type in notification: {v!r}')
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
        if not self.icon_name:
            self.icon_name = prev.icon_name
        if not self.application_name:
            self.application_name = prev.application_name
        if not self.notification_type:
            self.notification_type = prev.notification_type
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
                if self.icon_data_key:
                    icd = self.icon_data_cache_ref()
                    if icd:
                        self.icon_path = icd.add_icon(self.icon_data_key, data)
                else:
                    self.log('Ignoring notification icon data because no icon data key specified')

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

    def matches_rule_item(self, location:str, query:str) -> bool:
        import re
        pat = re.compile(query)
        val = {'title': self.title, 'body': self.body, 'app': self.application_name, 'type': self.notification_type}[location]
        return pat.search(val) is not None

    def matches_rule(self, rule: str) -> bool:
        if rule == 'all':
            return True
        from .search_query_parser import search
        def get_matches(location: str, query: str, candidates: Set['NotificationCommand']) -> Set['NotificationCommand']:
            return {x for x in candidates if x.matches_rule_item(location, query)}
        try:
            return self in search(rule, ('title', 'body', 'app', 'type'), {self}, get_matches)
        except Exception as e:
            self.log(f'Ignoring invalid filter_notification rule: {rule} with error: {e}')
        return False


class DesktopIntegration:

    supports_close_events: bool = True

    def __init__(self, notification_manager: 'NotificationManager'):
        self.notification_manager = notification_manager
        self.initialize()

    def initialize(self) -> None:
        pass

    def close_notification(self, desktop_notification_id: int) -> bool:
        raise NotImplementedError('Implement me in subclass')

    def notify(self, nc: NotificationCommand) -> int:
        raise NotImplementedError('Implement me in subclass')

    def on_new_version_notification_activation(self, cmd: NotificationCommand) -> None:
        from .update_check import notification_activated
        notification_activated()

    def query_response(self, identifier: str) -> str:
        actions = ','.join(x.value for x in Action)
        when = ','.join(x.value for x in OnlyWhen if x.value)
        urgency = ','.join(str(x.value) for x in Urgency)
        i = f'i={identifier or "0"}:'
        p = ','.join(x.value for x in PayloadType if x.value)
        c = ':c=1' if self.supports_close_events else ''
        return f'99;{i}p=?;a={actions}:o={when}:u={urgency}:p={p}{c}'


class MacOSIntegration(DesktopIntegration):

    def initialize(self) -> None:
        from .fast_data_types import cocoa_set_notification_activated_callback
        self.id_counter = count(start=1)
        cocoa_set_notification_activated_callback(self.notification_activated)

    def close_notification(self, desktop_notification_id: int) -> bool:
        from .fast_data_types import cocoa_remove_delivered_notification
        close_succeeded = cocoa_remove_delivered_notification(str(desktop_notification_id))
        if debug_desktop_integration:
            log_error(f'Close request for {desktop_notification_id=} {"succeeded" if close_succeeded else "failed"}')
        return close_succeeded

    def notify(self, nc: NotificationCommand) -> int:
        desktop_notification_id = next(self.id_counter)
        from .fast_data_types import cocoa_send_notification
        # If the body is not set macos makes the title the body and uses
        # "kitty" as the title. So use a single space for the body in this
        # case. Although https://developer.apple.com/documentation/usernotifications/unnotificationcontent/body?language=objc
        # says printf style strings are stripped this doesnt actually happen,
        # so dont double %
        # for %% escaping.
        body = (nc.body or ' ')
        assert nc.urgency is not None
        cocoa_send_notification(str(desktop_notification_id), nc.title, body, '', nc.urgency.value)
        return desktop_notification_id

    def notification_activated(self, event: str, ident: str) -> None:
        if debug_desktop_integration:
            log_error(f'Notification {ident} {event=}')
        try:
            desktop_notification_id = int(ident)
        except Exception:
            log_error(f'Got unexpected notification activated event with id: {ident!r} from cocoa')
            return
        if event == "created":
            self.notification_manager.notification_created(desktop_notification_id)
        elif event == "activated":
            self.notification_manager.notification_activated(desktop_notification_id)
        elif event == "closed":
            self.notification_manager.notification_closed(desktop_notification_id)


class FreeDesktopIntegration(DesktopIntegration):

    def initialize(self) -> None:
        from .fast_data_types import dbus_set_notification_callback
        dbus_set_notification_callback(self.dispatch_event_from_desktop)
        # map the id returned by the notification daemon to the
        # desktop_notification_id we use for the notification
        self.creation_id_map: 'OrderedDict[int, int]' = OrderedDict()

    def close_notification(self, desktop_notification_id: int) -> bool:
        from .fast_data_types import dbus_close_notification
        close_succeeded = False
        if dbus_id := self.get_dbus_notification_id(desktop_notification_id, 'close_request'):
            close_succeeded = dbus_close_notification(dbus_id)
            if debug_desktop_integration:
                log_error(f'Close request for {desktop_notification_id=} {"succeeded" if close_succeeded else "failed"}')
        return close_succeeded

    def get_desktop_notification_id(self, dbus_notification_id: int, event: str) -> Optional[int]:
        q = self.creation_id_map.get(dbus_notification_id)
        if q is None:
            if debug_desktop_integration:
                log_error(f'Could not find desktop_notification_id for {dbus_notification_id=} for event {event}')
        return q

    def get_dbus_notification_id(self, desktop_notification_id: int, event: str) ->Optional[int]:
        for dbus_id, q in self.creation_id_map.items():
            if q == desktop_notification_id:
                return dbus_id
        if debug_desktop_integration:
            log_error(f'Could not find dbus_notification_id for {desktop_notification_id=} for event {event}')
        return None

    def dispatch_event_from_desktop(self, event_type: str, dbus_notification_id: int, extra: Union[int, str]) -> None:
        if debug_desktop_integration:
            log_error(f'Got notification event from desktop: {event_type=} {dbus_notification_id=} {extra=}')
        if event_type == 'created':
            self.creation_id_map[int(extra)] = dbus_notification_id
            if len(self.creation_id_map) > 128:
                self.creation_id_map.popitem(False)
            self.notification_manager.notification_created(dbus_notification_id)
            return
        if desktop_notification_id := self.get_desktop_notification_id(dbus_notification_id, event_type):
            if event_type == 'activation_token':
                self.notification_manager.notification_activation_token_received(desktop_notification_id, str(extra))
            elif event_type == 'activated':
                self.notification_manager.notification_activated(desktop_notification_id)
            elif event_type == 'closed':
                self.notification_manager.notification_closed(desktop_notification_id)

    def notify(self, nc: NotificationCommand) -> int:
        from .fast_data_types import dbus_send_notification
        app_icon = nc.icon_name or nc.icon_path or get_custom_window_icon()[1] or logo_png_file
        body = nc.body.replace('<', '<\u200c').replace('&', '&\u200c')  # prevent HTML markup from being recognized
        assert nc.urgency is not None
        desktop_notification_id = dbus_send_notification(
            app_name=nc.application_name or 'kitty', app_icon=app_icon, title=nc.title, body=body, timeout=-1, urgency=nc.urgency.value)
        if debug_desktop_integration:
            log_error(f'Created notification with {desktop_notification_id=}')
        return desktop_notification_id


class UIState(NamedTuple):
    has_keyboard_focus: bool
    is_visible: bool


class Channel:

    def window_for_id(self, channel_id: int) -> Optional[WindowType]:
        boss = get_boss()
        if channel_id:
            return boss.window_id_map.get(channel_id)
        return boss.active_window

    def ui_state(self, channel_id: int) -> UIState:
        has_focus = is_visible = False
        boss = get_boss()
        if w := self.window_for_id(channel_id):
            has_focus = w.is_active and w.os_window_id == current_focused_os_window_id()
            # window is in the active OS window and the active tab and is visible in the tab layout
            is_visible = w.os_window_id == current_focused_os_window_id() and w.tabref() is boss.active_tab and w.is_visible_in_layout
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
        desktop_integration: Optional[DesktopIntegration] = None,
        channel: Channel = Channel(),
        log: Log = Log(),
        debug: bool = False,
        base_cache_dir: str = ''
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
        self.in_progress_notification_commands_by_client_id: Dict[str, NotificationCommand] = {}
        self.pending_commands: Dict[int, NotificationCommand] = {}

    def notification_created(self, desktop_notification_id: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            n.created_by_desktop = True

    def notification_activation_token_received(self, desktop_notification_id: int, token: str) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            n.activation_token = token

    def notification_activated(self, desktop_notification_id: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            if not n.close_response_requested:
                self.purge_notification(n)
            if n.focus_requested:
                self.channel.focus(n.channel_id, n.activation_token)
            if n.report_requested:
                ident = n.identifier or '0'
                self.channel.send(n.channel_id, f'99;i={ident};')
            if n.on_activation:
                try:
                    n.on_activation(n)
                except Exception as e:
                    self.log('Notification on_activation handler failed with error:', e)

    def notification_closed(self, desktop_notification_id: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            self.purge_notification(n)
            if n.close_response_requested:
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

    def notify_with_command(self, cmd: NotificationCommand, channel_id: int) -> Optional[int]:
        cmd.channel_id = channel_id
        cmd.finalise()
        if not cmd.title or not self.is_notification_allowed(cmd, channel_id) or self.is_notification_filtered(cmd):
            return None
        desktop_notification_id = self.desktop_integration.notify(cmd)
        self.register_in_progress_notification(cmd, desktop_notification_id)
        return desktop_notification_id

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
    ) -> Optional[NotificationCommand]:
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

    def send_closed_response(self, channel_id: int, client_id: str) -> None:
        self.channel.send(channel_id, f'99;i={client_id}:p=close;')

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
