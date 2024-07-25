#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import re
from collections import OrderedDict
from contextlib import suppress
from enum import Enum
from itertools import count
from typing import Any, Callable, Dict, FrozenSet, List, NamedTuple, Optional, Tuple, Union

from .constants import is_macos, logo_png_file
from .fast_data_types import ESC_OSC, current_focused_os_window_id, get_boss
from .types import run_once
from .typing import WindowType
from .utils import get_custom_window_icon, log_error, sanitize_control_codes

debug_desktop_integration = False


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

    def __init__(self) -> None:
        self.buf: List[bytes] = []

    def __call__(self, data: bytes) -> None:
        self.buf.append(data)

    def finalise(self) -> bytes:
        return b''.join(self.buf)


class EncodedDataStore:

    def __init__(self, data_store: DataStore) -> None:
        self.current_leftover_bytes = memoryview(b'')
        self.data_store = data_store

    def add_unencoded_data(self, data: Union[str, bytes]) -> None:
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.flush_encoded_data()
        self.data_store(data)

    def add_base64_data(self, data: Union[str, bytes]) -> None:
        if isinstance(data, str):
            data = data.encode('ascii')

        def write_saving_leftover_bytes(data: bytes) -> None:
            if len(data) == 0:
                return
            extra = len(data) % 4
            if extra > 0:
                mv = memoryview(data)
                self.current_leftover_bytes = memoryview(bytes(mv[-extra:]))
                mv = mv[:-extra]
                if len(mv) > 0:
                    self._write_base64_data(mv)
            else:
                self._write_base64_data(data)

        if len(self.current_leftover_bytes) > 0:
            extra = 4 - len(self.current_leftover_bytes)
            if len(data) >= extra:
                self._write_base64_data(memoryview(bytes(self.current_leftover_bytes) + data[:extra]))
                self.current_leftover_bytes = memoryview(b'')
                data = memoryview(data)[extra:]
                write_saving_leftover_bytes(data)
            else:
                self.current_leftover_bytes = memoryview(bytes(self.current_leftover_bytes) + data)
        else:
            write_saving_leftover_bytes(data)

    def _write_base64_data(self, b: bytes) -> None:
        from base64 import standard_b64decode
        d = standard_b64decode(b)
        self.data_store(d)

    def flush_encoded_data(self) -> None:
        b = self.current_leftover_bytes
        self.current_leftover_bytes = memoryview(b'')
        padding = 4 - len(b)
        if padding in (1, 2):
            self._write_base64_data(memoryview(bytes(b) + b'=' * padding))

    def finalise(self) -> bytes:
        self.flush_encoded_data()
        return self.data_store.finalise()


def limit_size(x: str) -> str:
    if len(x) > 1024:
        x = x[:1024]
    return x


class NotificationCommand:

    done: bool = True
    identifier: str = ''
    channel_id: int = 0
    desktop_notification_id: int = -1
    title: str = ''
    body: str = ''
    actions: FrozenSet[Action] = frozenset((Action.focus,))
    only_when: OnlyWhen = OnlyWhen.unset
    urgency: Optional[Urgency] = None
    close_response_requested: Optional[bool] = None

    # payload handling
    current_payload_type: PayloadType = PayloadType.title
    current_payload_buffer: Optional[EncodedDataStore] = None

    # desktop integration specific fields
    created_by_desktop: bool = False
    activation_token: str = ''

    # event callbacks
    on_activation: Optional[Callable[['NotificationCommand'], None]] = None

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
        if not prev.done and prev.identifier == self.identifier:
            self.actions = prev.actions.union(self.actions)
            self.title = prev.title
            self.body = prev.body
            if self.only_when is OnlyWhen.unset:
                self.only_when = prev.only_when
            if self.urgency is None:
                self.urgency = prev.urgency
            if self.close_response_requested is None:
                self.close_response_requested = prev.close_response_requested

        return payload_type, payload_is_encoded

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
                self.commit_data(prev_cmd.current_payload_buffer.finalise())
        if self.current_payload_buffer is None:
            self.current_payload_buffer = self.create_payload_buffer(payload_type)
        if payload_is_encoded:
            self.current_payload_buffer.add_base64_data(payload)
        else:
            self.current_payload_buffer.add_unencoded_data(payload)

    def commit_data(self, data: bytes) -> None:
        if not data:
            return
        if self.current_payload_type.is_text:
            text = data.decode('utf-8', 'replace')
        if self.current_payload_type is PayloadType.title:
            self.title = limit_size(self.title + text)
        elif self.current_payload_type is PayloadType.body:
            self.body = limit_size(self.body + text)

    def finalise(self) -> None:
        if self.current_payload_buffer:
            self.commit_data(self.current_payload_buffer.finalise())
            self.current_payload_buffer = None


class DesktopIntegration:

    def __init__(self, notification_manager: 'NotificationManager'):
        self.notification_manager = notification_manager
        self.initialize()

    def initialize(self) -> None:
        pass

    def dispatch_event_from_desktop(self, *a: Any) -> None:
        raise NotImplementedError('Implement me in subclass')

    def close_notification(self, desktop_notification_id: int) -> bool:
        raise NotImplementedError('Implement me in subclass')

    def notify(self,
        title: str,
        body: str,
        timeout: int = -1,
        application: str = 'kitty',
        icon: bool = True,
        subtitle: Optional[str] = None,
        urgency: Urgency = Urgency.Normal,
    ) -> int:
        raise NotImplementedError('Implement me in subclass')

    def on_new_version_notification_activation(self, cmd: NotificationCommand) -> None:
        from .update_check import notification_activated
        notification_activated()


class MacOSIntegration(DesktopIntegration):

    def initialize(self) -> None:
        from .fast_data_types import cocoa_set_notification_activated_callback
        self.id_counter = count()
        cocoa_set_notification_activated_callback(self.notification_activated)

    def notify(self,
        title: str,
        body: str,
        timeout: int = -1,
        application: str = 'kitty',
        icon: bool = True,
        subtitle: Optional[str] = None,
        urgency: Urgency = Urgency.Normal,
    ) -> int:
        desktop_notification_id = next(self.id_counter)
        from .fast_data_types import cocoa_send_notification
        cocoa_send_notification(str(desktop_notification_id), title, body, subtitle, urgency.value)
        return desktop_notification_id

    def notification_activated(self, ident: str) -> None:
        try:
            desktop_notification_id = int(ident)
        except Exception:
            log_error(f'Got unexpected notification activated event with id: {ident!r} from cocoa')
        else:
            self.notification_manager.notification_activated(desktop_notification_id)


class FreeDesktopIntegration(DesktopIntegration):

    def close_notification(self, desktop_notification_id: int) -> bool:
        from .fast_data_types import dbus_close_notification
        close_succeeded = dbus_close_notification(desktop_notification_id)
        if debug_desktop_integration:
            log_error(f'Close request for {desktop_notification_id=} {"succeeded" if close_succeeded else "failed"}')
        return close_succeeded

    def dispatch_event_from_desktop(self, *args: Any) -> None:
        event_type: str = args[0]
        dbus_notification_id: int = args[1]
        if debug_desktop_integration:
            log_error(f'Got notification event from desktop: {args=}')
        if event_type == 'created':
            self.notification_manager.notification_created(dbus_notification_id)
        elif event_type == 'activation_token':
            token: str = args[2]
            self.notification_manager.notification_activation_token_received(dbus_notification_id, token)
        elif event_type == 'activated':
            self.notification_manager.notification_activated(dbus_notification_id)
        elif event_type == 'closed':
            self.notification_manager.notification_closed(dbus_notification_id)

    def notify(self,
        title: str,
        body: str,
        timeout: int = -1,
        application: str = 'kitty',
        icon: bool = True,
        subtitle: Optional[str] = None,
        urgency: Urgency = Urgency.Normal,
    ) -> int:
        icf = ''
        if icon is True:
            icf = get_custom_window_icon()[1] or logo_png_file
        from .fast_data_types import dbus_send_notification
        desktop_notification_id = dbus_send_notification(application, icf, title, body, 'Click to see changes', timeout, urgency.value)
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
        boss = get_boss()
        if w := self.window_for_id(channel_id):
            boss.set_active_window(w, switch_os_window_if_needed=True, activation_token=activation_token)


sanitize_text = sanitize_control_codes

@run_once
def sanitize_identifier_pat() -> 're.Pattern[str]':
    return re.compile(r'[^a-zA-Z0-9-_+.]+')


def sanitize_id(v: str) -> str:
    return sanitize_identifier_pat().sub('', v)


class Log:
    def __call__(self, *a: Any, **kw: str) -> None:
        log_error(*a, **kw)


class NotificationManager:

    def __init__(
        self,
        desktop_integration: Optional[DesktopIntegration] = None,
        channel: Channel = Channel(),
        log: Log = Log(),
    ):
        if desktop_integration is None:
            self.desktop_integration = MacOSIntegration(self) if is_macos else FreeDesktopIntegration(self)
        else:
            self.desktop_integration = desktop_integration
        self.channel = channel
        self.log = log
        self.reset()

    def reset(self) -> None:
        self.in_progress_notification_commands: 'OrderedDict[int, NotificationCommand]' = OrderedDict()
        self.in_progress_notification_commands_by_client_id: Dict[str, NotificationCommand] = {}
        self.pending_commands: Dict[int, NotificationCommand] = {}

    def dispatch_event_from_desktop(self, *args: Any) -> None:
        self.desktop_integration.dispatch_event_from_desktop(*args)

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
                    self.log(e)

    def notification_closed(self, desktop_notification_id: int) -> None:
        if n := self.in_progress_notification_commands.get(desktop_notification_id):
            self.purge_notification(n)
            if n.close_response_requested:
                self.send_closed_response(n.channel_id, n.identifier)

    def send_test_notification(self) -> None:
        boss = get_boss()
        if w := boss.active_window:
            from time import monotonic
            cmd = NotificationCommand()
            now = monotonic()
            cmd.title = f'Test {now}'
            cmd.body = f'At: {now}'
            cmd.on_activation = print
            self.notify_with_command(cmd, w.id)

    def send_new_version_notification(self, version: str) -> None:
        cmd = NotificationCommand()
        cmd.title = 'kitty update available!'
        cmd.body = f'kitty version {version} released'
        cmd.on_activation = self.desktop_integration.on_new_version_notification_activation
        self.notify_with_command(cmd, 0)

    def is_notification_allowed(self, cmd: NotificationCommand, channel_id: int) -> bool:
        if cmd.only_when is not OnlyWhen.always and cmd.only_when is not OnlyWhen.unset:
            ui_state = self.channel.ui_state(channel_id)
            if ui_state.has_keyboard_focus:
                return False
            if cmd.only_when is OnlyWhen.invisible and ui_state.is_visible:
                return False
        return True

    def notify_with_command(self, cmd: NotificationCommand, channel_id: int) -> Optional[int]:
        cmd.channel_id = channel_id
        cmd.finalise()
        title = cmd.title or cmd.body
        body = cmd.body if cmd.title else ''
        if not title or not self.is_notification_allowed(cmd, channel_id):
            return None
        urgency = Urgency.Normal if cmd.urgency is None else cmd.urgency
        desktop_notification_id = self.desktop_integration.notify(title=sanitize_text(title), body=sanitize_text(body), urgency=urgency)
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

    def parse_notification_cmd(self, prev_cmd: NotificationCommand, channel_id: int, raw: str) -> Optional[NotificationCommand]:
        metadata, payload = raw.partition(';')[::2]
        cmd = NotificationCommand()
        try:
            payload_type, payload_is_encoded = cmd.parse_metadata(metadata, prev_cmd)
        except Exception:
            self.log('Malformed metadata section in OSC 99: ' + metadata)
            return None
        if payload_type is PayloadType.query:
            actions = ','.join(x.value for x in Action)
            when = ','.join(x.value for x in OnlyWhen if x.value)
            urgency = ','.join(str(x.value) for x in Urgency)
            i = f'i={cmd.identifier or "0"}:'
            p = ','.join(x.value for x in PayloadType if x.value)
            self.channel.send(channel_id, f'99;{i}p=?;a={actions}:o={when}:u={urgency}:p={p}')
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
            cmd = self.pending_commands.pop(channel_id, None) or NotificationCommand()
            q = self.parse_notification_cmd(cmd, channel_id, raw)
            if q is not None:
                if q.done:
                    self.notify_with_command(q, channel_id)
                else:
                    self.pending_commands[channel_id] = q
        elif osc_code == 9:
            n = NotificationCommand()
            n.title = raw
            self.notify_with_command(n, channel_id)
        elif osc_code == 777:
            n = NotificationCommand()
            parts = raw.split(';', 1)
            n.title, n.body = parts[0], (parts[1] if len(parts) > 1 else '')
            self.notify_with_command(n, channel_id)
