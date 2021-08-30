#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import os
import tempfile
from base64 import standard_b64decode, standard_b64encode
from collections import deque
from dataclasses import Field, dataclass, field, fields
from enum import Enum, auto
from functools import partial
from gettext import gettext as _
from time import monotonic
from typing import IO, Any, Deque, Dict, List, Optional, Tuple

from kitty.fast_data_types import OSC, add_timer, get_boss

from .utils import log_error, sanitize_control_codes

EXPIRE_TIME = 10  # minutes


class Action(Enum):
    send = auto()
    file = auto()
    data = auto()
    end_data = auto()
    receive = auto()
    invalid = auto()
    cancel = auto()
    status = auto()


class Compression(Enum):
    zlib = auto()
    none = auto()


class FileType(Enum):
    regular = auto()
    directory = auto()
    symlink = auto()
    link = auto()


class TransmissionType(Enum):
    simple = auto()
    resume = auto()
    rsync = auto()


class ErrorCode(Enum):
    EINVAL = auto()
    OK = auto()


class TransmissionError(Exception):

    def __init__(
        self, code: ErrorCode = ErrorCode.EINVAL,
        msg: str = 'Generic error',
        transmit: bool = True,
        file_id: str = ''
    ) -> None:
        Exception.__init__(self, msg)
        self.transmit = transmit
        self.file_id = file_id
        self.human_msg = msg
        self.code = code

    def as_escape_code(self, request_id: str = '') -> str:
        return FileTransmissionCommand(
            action=Action.status, id=request_id, file_id=self.file_id,
            name=f'{self.code.name}:{self.human_msg}'
        ).serialize()


@dataclass
class FileTransmissionCommand:

    action: Action = Action.invalid
    compression: Compression = Compression.none
    ftype: FileType = FileType.regular
    ttype: TransmissionType = TransmissionType.simple
    id: str = ''
    file_id: str = ''
    secret: str = ''
    mime: str = ''
    quiet: int = 0
    mtime: int = -1
    permissions: int = -1
    data: bytes = b''
    name: str = field(default='', metadata={'base64': True})

    def serialize(self) -> str:
        ans = []
        for k in fields(self):
            val = getattr(self, k.name)
            if val == k.default:
                continue
            if issubclass(k.type, Enum):
                ans.append(f'{k.name}={val.name}')
            elif k.type is bytes:
                ev = standard_b64encode(val).decode('ascii')
                ans.append(f'{k.name}={ev}')
            elif k.type is str:
                if k.metadata.get('base64'):
                    sval = standard_b64encode(self.name.encode('utf-8')).decode('ascii')
                else:
                    sval = val
                ans.append(f'{k.name}={sanitize_control_codes(sval)}')
            elif k.type is int:
                ans.append(f'{k.name}={val}')
            else:
                raise KeyError(f'Field of unknown type: {k.name}')

        def escape_semicolons(x: str) -> str:
            return x.replace(';', ';;')

        return ';'.join(map(escape_semicolons, ans))

    @classmethod
    def deserialize(cls, data: str) -> 'FileTransmissionCommand':
        ans = FileTransmissionCommand()
        parts = (x.replace('\0', ';').partition('=')[::2] for x in data.replace(';;', '\0').split(';'))
        if not hasattr(cls, 'fmap'):
            setattr(cls, 'fmap', {k.name: k for k in fields(cls)})
        fmap: Dict[str, Field] = getattr(cls, 'fmap')

        for k, v in parts:
            field = fmap.get(k)
            if field is None:
                continue
            if issubclass(field.type, Enum):
                setattr(ans, field.name, field.type[v])
            elif field.type is bytes:
                setattr(ans, field.name, standard_b64decode(v))
            elif field.type is int:
                setattr(ans, field.name, int(v))
            elif field.type is str:
                if field.metadata.get('base64'):
                    sval = standard_b64decode(v).decode('utf-8')
                else:
                    sval = v
                setattr(ans, field.name, sanitize_control_codes(sval))

        if ans.action is Action.invalid:
            raise ValueError('No valid action specified in file transmission command')

        return ans


class IdentityDecompressor:

    def __call__(self, data: bytes, is_last: bool = False) -> bytes:
        return data


class ZlibDecompressor:

    def __init__(self) -> None:
        import zlib
        self.d = zlib.decompressobj(wbits=0)

    def __call__(self, data: bytes, is_last: bool = False) -> bytes:
        ans = self.d.decompress(data)
        if is_last:
            ans += self.d.flush()
        return ans


class DestFile:

    def __init__(self, ftc: FileTransmissionCommand) -> None:
        self.name = ftc.name
        self.mtime = ftc.mtime
        self.permissions = ftc.permissions
        self.ftype = ftc.ftype
        self.ttype = ftc.ttype
        self.needs_data_sent = self.ttype is not TransmissionType.simple
        self.decompressor = ZlibDecompressor() if ftc.compression is Compression.zlib else IdentityDecompressor()
        self.closed = self.ftype is FileType.directory

    def close(self) -> None:
        if not self.closed:
            self.closed = True


class ActiveReceive:
    id: str
    files: Dict[str, DestFile]
    accepted: bool = False

    def __init__(self, id: str, quiet: int) -> None:
        self.id = id
        self.files = {}
        self.last_activity_at = monotonic()
        self.send_acknowledgements = quiet < 1
        self.send_errors = quiet < 2

    @property
    def is_expired(self) -> bool:
        return monotonic() - self.last_activity_at > (60 * EXPIRE_TIME)

    def close(self) -> None:
        for x in self.files.values():
            x.close()
        self.files = {}

    def cancel(self) -> None:
        self.close()

    def start_file(self, ftc: FileTransmissionCommand) -> DestFile:
        if ftc.file_id in self.files:
            raise TransmissionError(
                msg=f'The file_id {ftc.file_id} already exists',
                file_id=ftc.file_id,
            )
        self.files[ftc.file_id] = result = DestFile(ftc)
        return result


class FileTransmission:

    active_receives: Dict[str, ActiveReceive]

    def __init__(self, window_id: int):
        self.window_id = window_id
        self.active_receives = {}
        self.pending_receive_responses: Deque[Tuple[str, str]] = deque()
        self.pending_timer: Optional[int] = None

    def start_pending_timer(self) -> None:
        if self.pending_timer is None:
            self.pending_timer = add_timer(self.try_pending, 0.2, False)

    def try_pending(self, timer_id: Optional[int]) -> None:
        self.pending_timer = None
        while self.pending_receive_responses:
            request_id, payload = self.pending_receive_responses.popleft()
            ar = self.active_receives.get(request_id)
            if ar is None:
                continue
            if not self.write_osc_to_child(request_id, payload, appendleft=True):
                break
            ar.last_activity_at = monotonic()
        self.prune_expired()

    def __del__(self) -> None:
        for ar in self.active_receives.values():
            ar.close()
        self.active_receives = {}

    def drop_receive(self, receive_id: str) -> None:
        ar = self.active_receives.pop(receive_id, None)
        if ar is not None:
            ar.close()

    def prune_expired(self) -> None:
        for k in tuple(self.active_receives):
            if self.active_receives[k].is_expired:
                self.drop_receive(k)

    def handle_serialized_command(self, data: str) -> None:
        self.prune_expired()
        try:
            cmd = FileTransmissionCommand.deserialize(data)
        except Exception as e:
            log_error(f'Failed to parse file transmission command with error: {e}')
            return
        if cmd.id in self.active_receives or cmd.action is Action.send:
            self.handle_receive_cmd(cmd)

    def handle_receive_cmd(self, cmd: FileTransmissionCommand) -> None:
        if cmd.id in self.active_receives:
            ar = self.active_receives[cmd.id]
            if cmd.action is Action.send:
                log_error('File transmission send received for already active id, aborting')
                self.drop_receive(cmd.id)
                return
            if not ar.accepted:
                log_error(f'File transmission command received for rejected id: {cmd.id}, aborting')
                self.drop_receive(cmd.id)
                return
            ar.last_activity_at = monotonic()
        else:
            if cmd.action is not Action.send:
                log_error(f'File transmission command received for unknown or rejected id: {cmd.id}, ignoring')
                return
            ar = ActiveReceive(cmd.id, cmd.quiet)
            self.start_receive(ar.id)
            return

        if cmd.action is Action.cancel:
            self.drop_receive(ar.id)
        elif cmd.action is Action.file:
            try:
                ar.start_file(cmd)
            except TransmissionError as err:
                if ar.send_errors:
                    self.send_transmission_error(ar.id, err)
            except Exception as err:
                log_error(f'Transmission protocol failed to start file with error: {err}')
                if ar.send_errors:
                    te = TransmissionError(file_id=cmd.file_id, msg=str(err))
                    self.send_transmission_error(ar.id, te)
        elif cmd.action in (Action.data, Action.end_data):
            try:
                self.add_data(ar, cmd)
            except Exception:
                self.drop_receive(ar.id)
                raise
            if cmd.action is Action.end_data and cmd.id in self.active_cmds:
                try:
                    self.commit(cmd.id)
                except Exception:
                    self.drop_receive(cmd.id)

    def send_status_response(self, code: ErrorCode = ErrorCode.EINVAL, request_id: str = '', file_id: str = '', msg: str = '') -> bool:
        err = TransmissionError(code=code, msg=msg, file_id=file_id)
        data = err.as_escape_code(request_id)
        return self.write_osc_to_child(request_id, data)

    def send_transmission_error(self, request_id: str, err: TransmissionError) -> bool:
        return self.write_osc_to_child(request_id, err.as_escape_code())

    def write_osc_to_child(self, request_id: str, payload: str, appendleft: bool = False) -> bool:
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            queued = window.screen.send_escape_code_to_child(OSC, payload)
            if not queued:
                if appendleft:
                    self.pending_receive_responses.appendleft((request_id, payload))
                else:
                    self.pending_receive_responses.append((request_id, payload))
                self.start_pending_timer()
            return queued
        return False

    def start_receive(self, ar_id: str) -> None:
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            boss._run_kitten('ask', ['--type=yesno', '--message', _(
                'The remote machine wants to send some files to this computer. Do you want to allow the transfer?'
                )],
                window=window, custom_callback=partial(self.handle_send_confirmation, ar_id),
            )

    def handle_send_confirmation(self, cmd_id: str, data: Dict[str, str], *a: Any) -> None:
        ar = self.active_receives.get(cmd_id)
        if ar is None:
            return
        if data['response'] == 'y':
            ar.accepted = True
        else:
            self.drop_receive(ar.id)
        self.send_response(cmd.ftc, status='OK' if data['allowed'] else 'EPERM:User refused the transfer')

    def send_fail_on_os_error(self, ac: Optional[FileTransmissionCommand], err: OSError, msg: str) -> None:
        if ac is None or ac.quiet < 2:
            return
        errname = errno.errorcode.get(err.errno, 'EFAIL')
        self.send_response(ac, status=f'{errname}:{msg}')

    def abort_in_flight(self, cmd_id: str) -> None:
        c = self.active_cmds.pop(cmd_id, None)
        if c is not None:
            c.close()

    def add_data(self, cmd: FileTransmissionCommand) -> None:
        ac = self.active_cmds.get(cmd.id)

        def abort_in_flight() -> None:
            self.abort_in_flight(cmd.id)

        if ac is None or not ac.dest or ac.ftc.action is not Action.send:
            return abort_in_flight()

        if ac.file is None:
            try:
                os.makedirs(os.path.dirname(ac.dest), exist_ok=True)
            except OSError as e:
                self.send_fail_on_os_error(ac.ftc, e, 'Creating destination directory failed')
                return abort_in_flight()
            if ac.ftc.container_fmt is Container.none:
                try:
                    ac.file = open(ac.dest, 'wb')
                except OSError as e:
                    self.send_fail_on_os_error(ac.ftc, e, 'Creating destination file failed')
                    return abort_in_flight()
            else:
                try:
                    ac.file = tempfile.TemporaryFile(dir=os.path.dirname(ac.dest))
                except OSError as e:
                    self.send_fail_on_os_error(ac.ftc, e, 'Creating destination temp file failed')
                    return abort_in_flight()
        data = ac.decompressor(cmd.data, cmd.action is Action.end_data)
        try:
            ac.file.write(data)
        except OSError as e:
            self.send_fail_on_os_error(ac.ftc, e, 'Writing to destination file failed')
            return abort_in_flight()

    def commit(self, cmd_id: str) -> None:
        cmd = self.active_cmds.pop(cmd_id, None)
        if cmd is not None:
            try:
                if cmd.ftc.container_fmt is not Container.none and cmd.file is not None:
                    cmd.file.seek(0, os.SEEK_SET)
                    try:
                        Container.extractor_for_container_fmt(cmd.file, cmd.ftc.container_fmt)(cmd.dest)
                    except OSError as e:
                        self.send_fail_on_os_error(cmd.ftc, e, 'Failed to extract files from container')
                        raise
                    except Exception:
                        self.send_response(cmd.ftc, status='EFAIL:Failed to extract files from container')
                        raise
                if not cmd.ftc.quiet:
                    self.send_response(cmd.ftc, status='COMPLETED')
            finally:
                cmd.close()


class TestFileTransmission(FileTransmission):

    def __init__(self, allow: bool = True) -> None:
        super().__init__(0)
        self.test_responses: List[FileTransmissionCommand] = []
        self.allow = allow

    def write_osc_to_child(self, data: str) -> bool:
        self.test_responses.append(FileTransmissionCommand.deserialize(data))
        return True

    def start_receive(self, aid: str) -> None:
        self.handle_send_confirmation(aid, {'response': 'y' if self.allow else 'm'})
