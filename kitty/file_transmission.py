#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import copy
import errno
import os
import tempfile
from base64 import standard_b64decode, standard_b64encode
from time import monotonic
from enum import Enum, auto
from functools import partial
from typing import IO, Any, Dict, List, Optional, Union
from gettext import gettext as _

from kitty.fast_data_types import OSC, get_boss

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


class Compression(Enum):
    zlib = auto()
    none = auto()


class FileType(Enum):
    regular = auto()
    directory = auto()
    symlink = auto()
    link = auto()


class TransmisstionType(Enum):
    simple = auto()
    resume = auto()
    rsync = auto()


class FileTransmissionCommand:

    action = Action.invalid
    compression = Compression.none
    ftype = FileType.regular
    ttype = TransmisstionType.simple
    id: str = ''
    file_id: str = ''
    secret: str = ''
    mime: str = ''
    quiet: int = 0
    name: str = ''
    mtime: int = -1
    permissions: int = -1
    data: bytes = b''

    def serialize(self) -> str:
        ans = [f'action={self.action.name}']
        if self.compression is not Compression.none:
            ans.append(f'compression={self.compression.name}')
        if self.ftype is not FileType.regular:
            ans.append(f'ftype={self.ftype.name}')
        if self.ttype is not TransmisstionType.simple:
            ans.append(f'ttype={self.ttype.name}')
        for x in ('id', 'file_id', 'secret', 'mime', 'quiet'):
            val = getattr(self, x)
            if val:
                ans.append(f'{x}={val}')
        for k in ('mtime', 'permissions'):
            val = getattr(self, k)
            if val >= 0:
                ans.append(f'{k}={val}')
        if self.name:
            val = standard_b64encode(self.name.encode('utf-8')).decode('ascii')
            ans.append(f'name={val}')
        if self.data:
            val = standard_b64encode(self.data).decode('ascii')
            ans.append(f'data={val}')

        def escape_semicolons(x: str) -> str:
            return x.replace(';', ';;')

        return ';'.join(map(escape_semicolons, ans))


def parse_command(data: str) -> FileTransmissionCommand:
    ans = FileTransmissionCommand()
    parts = data.replace(';;', '\0').split(';')

    for i, x in enumerate(parts):
        k, v = x.replace('\0', ';').partition('=')[::2]
        if k == 'action':
            ans.action = Action[v]
        elif k == 'compression':
            ans.compression = Compression[v]
        elif k == 'ftype':
            ans.ftype = FileType[v]
        elif k == 'ttype':
            ans.ttype = TransmisstionType[v]
        elif k in ('secret', 'mime', 'id', 'file_id'):
            setattr(ans, k, sanitize_control_codes(v))
        elif k in ('quiet',):
            setattr(ans, k, int(v))
        elif k in ('mtime', 'permissions'):
            mt = int(v)
            if mt >= 0:
                setattr(ans, k, mt)
        elif k in ('name', 'data'):
            val = standard_b64decode(v)
            if k == 'name':
                ans.name = sanitize_control_codes(val.decode('utf-8'))
            else:
                ans.data = val

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
        self.needs_data_sent = self.ttype is not TransmisstionType.simple
        self.decompressor = ZlibDecompressor() if ftc.compression is Compression.zlib else IdentityDecompressor()

    def close(self) -> None:
        pass


class ActiveReceive:
    id: str
    files: Dict[str, DestFile]
    accepted: bool = False

    def __init__(self, id: str) -> None:
        self.id = id
        self.files = {}
        self.last_activity_at = monotonic()

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
            raise KeyError(f'The file_id {ftc.file_id} already exists')
        self.files[ftc.file_id] = result = DestFile(ftc)
        return result


class FileTransmission:

    active_receives: Dict[str, ActiveReceive]

    def __init__(self, window_id: int):
        self.window_id = window_id
        self.active_receives = {}

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
            cmd = parse_command(data)
        except Exception as e:
            log_error(f'Failed to parse file transmission command with error: {e}')
            return
        if cmd.id in self.active_receives or cmd.action is Action.send:
            self.handle_receive_cmd(cmd)

    def handle_receive_cmd(self, cmd: FileTransmissionCommand) -> None:
        if cmd.id in self.active_receives:
            if cmd.action is Action.send:
                log_error('File transmission send received for already active id, aborting')
                self.drop_receive(cmd.id)
                return
            ar = self.active_receives[cmd.id]
            if not ar.accepted:
                log_error(f'File transmission command received for rejected id: {cmd.id}, aborting')
                self.drop_receive(cmd.id)
                return
            ar.last_activity_at = monotonic()
        else:
            if cmd.action is not Action.send:
                log_error(f'File transmission command received for unknown or rejected id: {cmd.id}, ignoring')
                return
            ar = ActiveReceive(cmd.id)
            self.start_receive(ar.id)
            return

        if cmd.action is Action.cancel:
            self.drop_receive(ar.id)
        elif cmd.action is Action.file:
            ar.start_file(cmd)
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

    def send_response(self, id: str = '', **fields: str) -> bool:
        if 'id' not in fields and id:
            fields['id'] = id
        return self.write_response_to_child(fields)

    def write_response_to_child(self, fields: Dict[str, str]) -> bool:
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            return window.screen.send_escape_code_to_child(OSC, ';'.join(f'{k}={v}' for k, v in fields.items()))
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
        self.test_responses: List[Dict[str, str]] = []
        self.allow = allow

    def write_response_to_child(self, fields: Dict[str, str]) -> bool:
        self.test_responses.append(fields)
        return True

    def start_receive(self, aid: str) -> None:
        self.handle_send_confirmation(aid, {'response': 'y' if self.allow else 'm'})
