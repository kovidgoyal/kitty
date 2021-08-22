#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import copy
import errno
import os
import tempfile
from base64 import standard_b64decode
from enum import Enum, auto
from typing import IO, TYPE_CHECKING, Any, Dict, List, Optional, Union

from kitty.fast_data_types import OSC, get_boss

from .utils import log_error, sanitize_control_codes

if TYPE_CHECKING:
    from kittens.transfer_ask.main import Response


class Action(Enum):
    send = auto()
    data = auto()
    end_data = auto()
    receive = auto()
    invalid = auto()


class Container(Enum):
    zip = auto()
    tar = auto()
    tgz = auto()
    tbz2 = auto()
    txz = auto()
    none = auto()

    @classmethod
    def extractor_for_container_fmt(cls, fobj: IO[bytes], container_fmt: 'Container') -> Union['ZipExtractor', 'TarExtractor']:
        if container_fmt is Container.tar:
            return TarExtractor(fobj, 'r|')
        if container_fmt is Container.tgz:
            return TarExtractor(fobj, 'r|gz')
        if container_fmt is Container.tbz2:
            return TarExtractor(fobj, 'r|bz2')
        if container_fmt is Container.txz:
            return TarExtractor(fobj, 'r|xz')
        if container_fmt is Container.zip:
            return ZipExtractor(fobj)
        raise KeyError(f'Unknown container format: {container_fmt}')


class Compression(Enum):
    zlib = auto()
    none = auto()


class FileTransmissionCommand:

    action = Action.invalid
    container_fmt = Container.none
    compression = Compression.none
    id: str = ''
    secret: str = ''
    mime: str = ''
    quiet: int = 0
    dest: str = ''
    data: bytes = b''


def parse_command(data: str) -> FileTransmissionCommand:
    ans = FileTransmissionCommand()
    parts = data.replace(';;', '\0').split(';')

    for i, x in enumerate(parts):
        k, v = x.partition('=')[::2]
        v = v.replace('\0', ';')
        if k == 'action':
            ans.action = Action[v]
        elif k == 'container_fmt':
            ans.container_fmt = Container[v]
        elif k == 'compression':
            ans.compression = Compression[v]
        elif k in ('secret', 'mime', 'id'):
            setattr(ans, k, v)
        elif k in ('quiet',):
            setattr(ans, k, int(v))
        elif k in ('dest', 'data'):
            val = standard_b64decode(v)
            if k == 'dest':
                ans.dest = sanitize_control_codes(val.decode('utf-8'))
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


def resolve_name(name: str, base: str) -> Optional[str]:
    if name.startswith('/') or os.path.isabs(name):
        return None
    base = os.path.abspath(base)
    q = os.path.abspath(os.path.join(base, name))
    return q if q.startswith(base) else None


class TarExtractor:

    def __init__(self, fobj: IO[bytes], mode: str):
        import tarfile
        self.tf = tarfile.open(mode=mode, fileobj=fobj)

    def __call__(self, dest: str) -> None:
        directories = []
        for tinfo in self.tf:
            targetpath = resolve_name(tinfo.name, dest)
            if targetpath is None:
                continue
            if tinfo.isdir():
                self.tf.makedir(tinfo, targetpath)
                directories.append((targetpath, copy.copy(tinfo)))
                continue
            if tinfo.isfile():
                self.tf.makefile(tinfo, targetpath)
            elif tinfo.isfifo():
                self.tf.makefifo(tinfo, targetpath)
            elif tinfo.ischr() or tinfo.isblk():
                self.tf.makedev(tinfo, targetpath)
            elif tinfo.islnk() or tinfo.issym():
                self.tf.makelink(tinfo, targetpath)
            else:
                continue
            if not tinfo.issym():
                self.tf.chmod(tinfo, targetpath)
                self.tf.utime(tinfo, targetpath)
        directories.sort(reverse=True, key=lambda x: x[0])
        for targetpath, tinfo in directories:
            self.tf.chmod(tinfo, targetpath)
            self.tf.utime(tinfo, targetpath)


class ZipExtractor:

    def __init__(self, fobj: IO[bytes]):
        import zipfile
        self.zf = zipfile.ZipFile(fobj)

    def __call__(self, dest: str) -> None:
        for zinfo in self.zf.infolist():
            targetpath = resolve_name(zinfo.filename, dest)
            if targetpath is None:
                continue
            self.zf.extract(zinfo, targetpath)


class FileTransmission:

    active_cmd: Optional[FileTransmissionCommand] = None
    active_file: Optional[IO[bytes]] = None
    active_dest: str = ''
    active_decompressor: Union[IdentityDecompressor, ZlibDecompressor] = IdentityDecompressor()

    def __init__(self, window_id: int):
        self.window_id = window_id

    def handle_serialized_command(self, data: str) -> None:
        try:
            cmd = parse_command(data)
        except Exception as e:
            log_error(f'Failed to parse file transmission command with error: {e}')
            return
        if self.active_cmd is not None:
            if cmd.action not in (Action.data, Action.end_data):
                log_error('File transmission command received while another is in flight, aborting')
                self.abort_in_flight()
        if cmd.action is Action.send:
            self.start_send(cmd)
        elif cmd.action in (Action.data, Action.end_data):
            self.add_data(cmd)
            if cmd.action is Action.end_data and self.active_cmd is not None:
                self.commit()

    def send_response(self, **fields: str) -> None:
        ac = self.active_cmd
        if ac is None:
            return
        if 'id' not in fields and ac.id:
            fields['id'] = ac.id
        self.write_response_to_child(fields)

    def write_response_to_child(self, fields: Dict[str, str]) -> None:
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            window.screen.send_escape_code_to_child(OSC, ';'.join(f'{k}={v}' for k, v in fields.items()))

    def start_send(self, cmd: FileTransmissionCommand) -> None:
        self.active_cmd = cmd
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            boss._run_kitten(
                'transfer_ask', ['put', 'multiple' if cmd.container_fmt else 'single', cmd.dest],
                window=window, custom_callback=self.handle_send_confirmation
            )

    def handle_send_confirmation(self, data: 'Response', *a: Any) -> None:
        cmd = self.active_cmd
        if cmd is None:
            return
        if data['allowed']:
            self.active_dest = os.path.abspath(os.path.realpath(os.path.abspath(data['dest'])))
            self.active_decompressor = ZlibDecompressor() if cmd.compression is Compression.zlib else IdentityDecompressor()
            if cmd.quiet:
                return
        else:
            self.active_cmd = None
            self.active_dest = ''
            if cmd.quiet > 1:
                return
        self.send_response(status='OK' if data['allowed'] else 'EPERM:User refused the transfer')

    def send_fail_on_os_error(self, err: OSError, msg: str) -> None:
        ac = self.active_cmd
        if ac is None or ac.quiet < 2:
            return
        errname = errno.errorcode.get(err.errno, 'EFAIL')
        self.send_response(status=f'{errname}:{msg}')

    def add_data(self, cmd: FileTransmissionCommand) -> None:
        ac = self.active_cmd
        if ac is None or not self.active_dest:
            return
        if self.active_file is None:
            try:
                os.makedirs(os.path.dirname(self.active_dest), exist_ok=True)
            except OSError as e:
                self.send_fail_on_os_error(e, 'Creating destination directory failed')
                return self.abort_in_flight()
            if ac.container_fmt is Container.none:
                try:
                    self.active_file = open(self.active_dest, 'wb')
                except OSError as e:
                    self.send_fail_on_os_error(e, 'Creating destination file failed')
                    return self.abort_in_flight()
            else:
                try:
                    self.active_file = tempfile.TemporaryFile(dir=os.path.dirname(self.active_dest))
                except OSError as e:
                    self.send_fail_on_os_error(e, 'Creating destination temp file failed')
                    return self.abort_in_flight()
        data = self.active_decompressor(cmd.data, cmd.action is Action.end_data)
        try:
            self.active_file.write(data)
        except OSError as e:
            self.send_fail_on_os_error(e, 'Writing to destination file failed')
            return self.abort_in_flight()

    def commit(self) -> None:
        cmd = self.active_cmd
        if cmd is None:
            return
        try:
            if cmd.container_fmt and self.active_file is not None:
                self.active_file.seek(0, os.SEEK_SET)
                Container.extractor_for_container_fmt(self.active_file, cmd.container_fmt)(self.active_dest)
        finally:
            self.active_cmd = None
            self.active_dest = ''
            if self.active_file is not None:
                self.active_file.close()
                self.active_file = None

    def abort_in_flight(self) -> None:
        self.active_cmd = None
        self.active_dest = ''
        if self.active_file is not None:
            self.active_file.close()
            self.active_file = None


class TestFileTransmission(FileTransmission):

    def __init__(self, dest: str = '') -> None:
        super().__init__(0)
        self.test_responses: List[Dict[str, str]] = []
        self.test_dest = dest

    def write_response_to_child(self, fields: Dict[str, str]) -> None:
        self.test_responses.append(fields)

    def start_send(self, cmd: FileTransmissionCommand) -> None:
        self.active_cmd = cmd
        self.handle_send_confirmation({'dest': self.test_dest, 'allowed': bool(self.test_dest)})
