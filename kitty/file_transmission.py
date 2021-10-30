#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import os
import stat
import tempfile
from base64 import standard_b64decode, standard_b64encode
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import Field, dataclass, field, fields
from enum import Enum, auto
from functools import partial
from gettext import gettext as _
from itertools import chain
from time import monotonic
from typing import (
    IO, Any, Callable, DefaultDict, Deque, Dict, Iterable, Iterator, List,
    Optional, Tuple, Union, cast
)

from kittens.transfer.librsync import PatchFile, signature_of_file
from kittens.transfer.utils import abspath, expand_home, home_path
from kitty.fast_data_types import (
    FILE_TRANSFER_CODE, OSC, add_timer, get_boss, get_options
)

from .utils import log_error, sanitize_control_codes

EXPIRE_TIME = 10  # minutes
MAX_ACTIVE_RECEIVES = MAX_ACTIVE_SENDS = 10
ftc_prefix = str(FILE_TRANSFER_CODE)


def escape_semicolons(x: str) -> str:
    return x.replace(';', ';;')


def as_unicode(x: Union[str, bytes]) -> str:
    if isinstance(x, bytes):
        x = x.decode('ascii')
    return x


def encode_bypass(request_id: str, bypass: str) -> str:
    import hashlib
    q = request_id + ';' + bypass
    return 'sha256:' + hashlib.sha256(q.encode('utf-8', 'replace')).hexdigest()


def split_for_transfer(
    data: Union[bytes, bytearray, memoryview],
    session_id: str = '', file_id: str = '',
    mark_last: bool = False,
    chunk_size: int = 4096
) -> Iterator['FileTransmissionCommand']:
    if isinstance(data, (bytes, bytearray)):
        data = memoryview(data)
    while len(data):
        ac = Action.data
        if mark_last and len(data) <= chunk_size:
            ac = Action.end_data
        yield FileTransmissionCommand(action=ac, id=session_id, file_id=file_id, data=data[:chunk_size])
        data = data[chunk_size:]


def iter_file_metadata(file_specs: Iterable[Tuple[str, str]]) -> Iterator[Union['FileTransmissionCommand', 'TransmissionError']]:
    file_map: DefaultDict[str, List[FileTransmissionCommand]] = defaultdict(list)

    def make_ftc(path: str, spec_id: str, sr: Optional[os.stat_result] = None, parent: str = '') -> FileTransmissionCommand:
        if sr is None:
            sr = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(sr.st_mode):
            ftype = FileType.symlink
        elif stat.S_ISDIR(sr.st_mode):
            ftype = FileType.directory
        elif stat.S_ISREG(sr.st_mode):
            ftype = FileType.regular
        else:
            raise ValueError('Not an appropriate file type')
        return FileTransmissionCommand(
            action=Action.file, file_id=spec_id, mtime=sr.st_mtime_ns, permissions=stat.S_IMODE(sr.st_mode),
            name=path, status=f'{sr.st_dev}:{sr.st_ino}', size=sr.st_size, ftype=ftype, parent=parent
        )

    for spec_id, spec in file_specs:
        path = spec
        if not os.path.isabs(path):
            path = expand_home(path)
            if not os.path.isabs(path):
                path = abspath(path, use_home=True)
        try:
            sr = os.stat(path, follow_symlinks=False)
            read_ok = os.access(path, os.R_OK, follow_symlinks=False)
        except OSError as err:
            errname = errno.errorcode.get(err.errno, 'EFAIL')
            yield TransmissionError(file_id=spec_id, code=errname, msg='Failed to read spec')
            continue
        if not read_ok:
            yield TransmissionError(file_id=spec_id, code='EPERM', msg='No permission to read spec')
            continue
        try:
            ftc = make_ftc(path, spec_id, sr)
        except ValueError:
            yield TransmissionError(file_id=spec_id, code='EINVAL', msg='Not a valid filetype')
            continue
        file_map[ftc.status].append(ftc)
        if ftc.ftype is FileType.directory:
            try:
                x_ok = os.access(path, os.X_OK)
                di = os.walk(path)
            except OSError:
                x_ok = False
            if x_ok:
                for dirpath, dirnames, filenames in di:
                    for dname in chain(dirnames, filenames):
                        try:
                            dftc = make_ftc(os.path.join(dirpath, dname), spec_id, parent=ftc.status)
                        except (ValueError, OSError):
                            continue
                        file_map[dftc.status].append(dftc)
    for fkey, cmds in file_map.items():
        base = cmds[0]
        if base.ftype is FileType.symlink:
            try:
                dest = os.path.realpath(base.name)
            except OSError:
                pass
            else:
                try:
                    s = os.stat(dest, follow_symlinks=False)
                except OSError:
                    pass
                else:
                    fkey = f'{s.st_dev}:{s.st_ino}'
                    if fkey in file_map:
                        base.data = fkey.encode('utf-8', 'replace')
        yield base
        if len(cmds) > 1 and base.ftype is FileType.regular:
            for q in cmds[1:]:
                if q.ftype is FileType.regular:
                    q.ftype = FileType.link
                    q.data = base.status.encode('utf-8', 'replace')
                    yield q


class NameReprEnum(Enum):

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}.{self.name}>'


class Action(NameReprEnum):
    send = auto()
    file = auto()
    data = auto()
    end_data = auto()
    receive = auto()
    invalid = auto()
    cancel = auto()
    status = auto()
    finish = auto()


class Compression(NameReprEnum):
    zlib = auto()
    none = auto()


class FileType(NameReprEnum):
    regular = auto()
    directory = auto()
    symlink = auto()
    link = auto()

    @property
    def short_text(self) -> str:
        return {FileType.regular: 'fil', FileType.directory: 'dir', FileType.symlink: 'sym', FileType.link: 'lnk'}[self]

    @property
    def color(self) -> str:
        return {FileType.regular: 'yellow', FileType.directory: 'magenta', FileType.symlink: 'blue', FileType.link: 'green'}[self]


class TransmissionType(NameReprEnum):
    simple = auto()
    rsync = auto()


ErrorCode = Enum('ErrorCode', 'OK STARTED CANCELED PROGRESS EINVAL EPERM EISDIR ENOENT')


class TransmissionError(Exception):

    def __init__(
        self, code: Union[ErrorCode, str] = ErrorCode.EINVAL,
        msg: str = 'Generic error',
        transmit: bool = True,
        file_id: str = '',
        name: str = '',
        size: int = -1,
        ttype: TransmissionType = TransmissionType.simple,
    ) -> None:
        super().__init__(msg)
        self.transmit = transmit
        self.file_id = file_id
        self.human_msg = msg
        self.code = code
        self.name = name
        self.size = size
        self.ttype = ttype

    def as_ftc(self, request_id: str) -> 'FileTransmissionCommand':
        name = self.code if isinstance(self.code, str) else self.code.name
        if self.human_msg:
            name += ':' + self.human_msg
        return FileTransmissionCommand(
            action=Action.status, id=request_id, file_id=self.file_id, status=name, name=self.name, size=self.size, ttype=self.ttype
        )


@dataclass
class FileTransmissionCommand:

    action: Action = Action.invalid
    compression: Compression = Compression.none
    ftype: FileType = FileType.regular
    ttype: TransmissionType = TransmissionType.simple
    id: str = ''
    file_id: str = ''
    bypass: str = field(default='', metadata={'base64': True})
    quiet: int = 0
    mtime: int = -1
    permissions: int = -1
    size: int = -1
    name: str = field(default='', metadata={'base64': True})
    status: str = field(default='', metadata={'base64': True})
    parent: str = field(default='', metadata={'base64': True})
    data: bytes = field(default=b'', repr=False)

    def __repr__(self) -> str:
        ans = []
        for k in fields(self):
            if not k.repr:
                continue
            val = getattr(self, k.name)
            if val != k.default:
                ans.append(f'{k.name}={val!r}')
        return 'FTC(' + ', '.join(ans) + ')'

    def asdict(self, keep_defaults: bool = False) -> Dict[str, Union[str, int, bytes]]:
        ans = {}
        for k in fields(self):
            val = getattr(self, k.name)
            if not keep_defaults and val == k.default:
                continue
            if issubclass(k.type, Enum):
                val = val.name
            ans[k.name] = val
        return ans

    def get_serialized_fields(self, prefix_with_osc_code: bool = False) -> Iterator[Union[str, bytes]]:
        found = False
        if prefix_with_osc_code:
            yield ftc_prefix
            found = True

        for k in fields(self):
            name = k.name
            val = getattr(self, name)
            if val == k.default:
                continue
            if found:
                yield ';'
            else:
                found = True
            yield name
            yield '='
            if issubclass(k.type, Enum):
                yield val.name
            elif k.type is bytes:
                yield standard_b64encode(val)
            elif k.type is str:
                if k.metadata.get('base64'):
                    yield standard_b64encode(val.encode('utf-8'))
                else:
                    yield escape_semicolons(sanitize_control_codes(val))
            elif k.type is int:
                yield str(val)
            else:
                raise KeyError(f'Field of unknown type: {k.name}')

    def serialize(self, prefix_with_osc_code: bool = False) -> str:
        return ''.join(map(as_unicode, self.get_serialized_fields(prefix_with_osc_code)))

    @classmethod
    def deserialize(cls, data: Union[str, bytes, memoryview]) -> 'FileTransmissionCommand':
        ans = FileTransmissionCommand()
        fmap: Dict[bytes, 'Field[Union[str, int, bytes, Enum]]'] = getattr(cls, 'fmap', None)
        if not fmap:
            fmap = {k.name.encode('ascii'): k for k in fields(cls)}
            setattr(cls, 'fmap', fmap)
        from kittens.transfer.rsync import decode_utf8_buffer, parse_ftc

        def handle_item(key: memoryview, val: memoryview, has_semicolons: bool) -> None:
            field = fmap.get(key)
            if field is None:
                return
            if issubclass(field.type, Enum):
                setattr(ans, field.name, field.type[decode_utf8_buffer(val)])
            elif field.type is bytes:
                setattr(ans, field.name, standard_b64decode(val))
            elif field.type is int:
                setattr(ans, field.name, int(val))
            elif field.type is str:
                if field.metadata.get('base64'):
                    sval = standard_b64decode(val).decode('utf-8')
                else:
                    sval = decode_utf8_buffer(val)
                    if has_semicolons:
                        sval = sval.replace(';;', ';')
                setattr(ans, field.name, sanitize_control_codes(sval))

        parse_ftc(data, handle_item)
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
        if not os.path.isabs(self.name):
            self.name = os.path.expanduser(self.name)
            if not os.path.isabs(self.name):
                self.name = os.path.join(tempfile.gettempdir(), self.name)
        try:
            self.existing_stat: Optional[os.stat_result] = os.stat(self.name, follow_symlinks=False)
        except OSError:
            self.existing_stat = None
        self.needs_unlink = self.existing_stat is not None and (self.existing_stat.st_nlink > 1 or stat.S_ISLNK(self.existing_stat.st_mode))
        self.mtime = ftc.mtime
        self.file_id = ftc.file_id
        self.permissions = ftc.permissions
        if self.permissions != FileTransmissionCommand.permissions:
            self.permissions = stat.S_IMODE(self.permissions)
        self.ftype = ftc.ftype
        self.ttype = ftc.ttype
        self.link_target = b''
        self.needs_data_sent = self.ttype is not TransmissionType.simple
        self.decompressor: Union[ZlibDecompressor, IdentityDecompressor] = ZlibDecompressor() if ftc.compression is Compression.zlib else IdentityDecompressor()
        self.closed = self.ftype is FileType.directory
        self.actual_file: Union[PatchFile, IO[bytes], None] = None
        self.failed = False
        self.bytes_written = 0

    def __repr__(self) -> str:
        return f'DestFile(name={self.name}, file_id={self.file_id}, actual_file={self.actual_file})'

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            if self.actual_file is not None:
                self.actual_file.close()
                self.actual_file = None

    def make_parent_dirs(self) -> str:
        d = os.path.dirname(self.name)
        if d:
            os.makedirs(d, exist_ok=True)
        return d

    def apply_metadata(self, is_symlink: bool = False) -> None:
        if self.permissions != FileTransmissionCommand.permissions:
            if is_symlink:
                with suppress(NotImplementedError):
                    os.chmod(self.name, self.permissions, follow_symlinks=False)
            else:
                os.chmod(self.name, self.permissions)
        if self.mtime != FileTransmissionCommand.mtime:
            if is_symlink:
                with suppress(NotImplementedError):
                    os.utime(self.name, ns=(self.mtime, self.mtime), follow_symlinks=False)
            else:
                os.utime(self.name, ns=(self.mtime, self.mtime))

    def unlink_existing_if_needed(self, force: bool = False) -> None:
        if force or self.needs_unlink:
            with suppress(FileNotFoundError):
                os.unlink(self.name)
            self.existing_stat = None
            self.needs_unlink = False

    def write_data(self, all_files: Dict[str, 'DestFile'], data: bytes, is_last: bool) -> None:
        if self.ftype is FileType.directory:
            raise TransmissionError(code=ErrorCode.EISDIR, file_id=self.file_id, msg='Cannot write data to a directory entry')
        if self.closed:
            raise TransmissionError(file_id=self.file_id, msg='Cannot write to a closed file')
        if self.ftype in (FileType.symlink, FileType.link):
            self.link_target += data
            self.bytes_written += len(data)
            if is_last:
                lt = self.link_target.decode('utf-8', 'replace')
                base = self.make_parent_dirs()
                self.unlink_existing_if_needed(force=True)
                if lt.startswith('fid:'):
                    lt = all_files[lt[4:]].name
                    if self.ftype is FileType.symlink:
                        try:
                            cp = os.path.commonpath((self.name, lt))
                        except ValueError:
                            pass
                        else:
                            if cp:
                                lt = os.path.relpath(lt, cp)
                elif lt.startswith('fid_abs:'):
                    lt = all_files[lt[8:]].name
                elif lt.startswith('path:'):
                    lt = lt[5:]
                    if not os.path.isabs(lt) and self.ftype is FileType.link:
                        lt = os.path.join(base, lt)
                    lt = lt.replace('/', os.sep)
                else:
                    raise TransmissionError(msg='Unknown link target type', file_id=self.file_id)
                if self.ftype is FileType.symlink:
                    os.symlink(lt, self.name)
                else:
                    os.link(lt, self.name)
                self.close()
                self.apply_metadata(is_symlink=True)
        elif self.ftype is FileType.regular:
            decompressed = self.decompressor(data, is_last=is_last)
            if self.actual_file is None:
                self.make_parent_dirs()
                if self.ttype is TransmissionType.rsync:
                    self.actual_file = PatchFile(self.name)
                else:
                    self.unlink_existing_if_needed()
                    flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_BINARY', 0)
                    self.actual_file = open(os.open(self.name, flags, self.permissions), mode='r+b', closefd=True)
            af = cast(Union[IO[bytes], PatchFile], self.actual_file)
            if decompressed or is_last:
                af.write(decompressed)
                self.bytes_written = af.tell()
            if is_last:
                self.close()
                self.apply_metadata()


class ActiveReceive:
    id: str
    files: Dict[str, DestFile]
    accepted: bool = False

    def __init__(self, request_id: str, quiet: int, bypass: str) -> None:
        self.id = request_id
        self.bypass_ok: Optional[bool] = None
        if bypass:
            byp = get_options().file_transfer_confirmation_bypass
            self.bypass_ok = (encode_bypass(request_id, byp) == bypass) if byp else False
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
        self.last_activity_at = monotonic()
        if ftc.file_id in self.files:
            raise TransmissionError(
                msg=f'The file_id {ftc.file_id} already exists',
                file_id=ftc.file_id,
            )
        self.files[ftc.file_id] = df = DestFile(ftc)
        return df

    def add_data(self, ftc: FileTransmissionCommand) -> DestFile:
        self.last_activity_at = monotonic()
        df = self.files.get(ftc.file_id)
        if df is None:
            raise TransmissionError(file_id=ftc.file_id, msg='Cannot write to a file without first starting it')
        if df.failed:
            return df
        try:
            df.write_data(self.files, ftc.data, ftc.action is Action.end_data)
        except Exception:
            df.failed = True
            df.close()
            raise
        return df

    def commit(self, send_os_error: Callable[[OSError, str, 'ActiveReceive', str], None]) -> None:
        directories = sorted((df for df in self.files.values() if df.ftype is FileType.directory), key=lambda x: len(x.name), reverse=True)
        for df in directories:
            with suppress(OSError):
                # we ignore failures to apply directory metadata as we have already sent an OK for the dir
                df.apply_metadata()


class ActiveSend:

    def __init__(self, request_id: str, quiet: int, bypass: str, num_of_args: int) -> None:
        self.id = request_id
        self.expected_num_of_args = num_of_args
        self.bypass_ok: Optional[bool] = None
        self.accepted = False
        if bypass:
            byp = get_options().file_transfer_confirmation_bypass
            self.bypass_ok = (encode_bypass(request_id, byp) == bypass) if byp else False
        self.last_activity_at = monotonic()
        self.send_acknowledgements = quiet < 1
        self.send_errors = quiet < 2
        self.last_activity_at = monotonic()
        self.file_specs: List[Tuple[str, str]] = []

    @property
    def spec_complete(self) -> bool:
        return self.expected_num_of_args <= len(self.file_specs)

    def add_file_spec(self, cmd: FileTransmissionCommand) -> None:
        if len(self.file_specs) > 8192 or self.spec_complete:
            raise TransmissionError(ErrorCode.EINVAL, 'Too many file specs')
        self.file_specs.append((cmd.file_id, cmd.name))

    @property
    def is_expired(self) -> bool:
        return monotonic() - self.last_activity_at > (60 * EXPIRE_TIME)

    def close(self) -> None:
        pass  # TODO: Implement this


class FileTransmission:

    def __init__(self, window_id: int):
        self.window_id = window_id
        self.active_receives: Dict[str, ActiveReceive] = {}
        self.active_sends: Dict[str, ActiveSend] = {}
        self.pending_receive_responses: Deque[FileTransmissionCommand] = deque()
        self.pending_timer: Optional[int] = None

    def callback_after(self, callback: Callable[[Optional[int]], None], timeout: float = 0) -> Optional[int]:
        return add_timer(callback, timeout, False)

    def start_pending_timer(self) -> None:
        if self.pending_timer is None:
            self.pending_timer = self.callback_after(self.try_pending, 0.2)

    def try_pending(self, timer_id: Optional[int]) -> None:
        self.pending_timer = None
        while self.pending_receive_responses:
            payload = self.pending_receive_responses.popleft()
            ar = self.active_receives.get(payload.id)
            if ar is None:
                continue
            if not self.write_ftc_to_child(payload, appendleft=True):
                break
            ar.last_activity_at = monotonic()
        self.prune_expired()

    def __del__(self) -> None:
        for ar in self.active_receives.values():
            ar.close()
        self.active_receives = {}
        for a in self.active_sends.values():
            a.close()
        self.active_receives = {}
        self.active_sends = {}

    def drop_receive(self, receive_id: str) -> None:
        ar = self.active_receives.pop(receive_id, None)
        if ar is not None:
            ar.close()

    def drop_send(self, send_id: str) -> None:
        a = self.active_sends.pop(send_id, None)
        if a is not None:
            a.close()

    def prune_expired(self) -> None:
        for k in tuple(self.active_receives):
            if self.active_receives[k].is_expired:
                self.drop_receive(k)
        for a in tuple(self.active_sends):
            if self.active_sends[a].is_expired:
                self.drop_send(a)

    def handle_serialized_command(self, data: str) -> None:
        try:
            cmd = FileTransmissionCommand.deserialize(data)
        except Exception as e:
            log_error(f'Failed to parse file transmission command with error: {e}')
            return
        if not cmd.id:
            log_error('File transmission command without id received, ignoring')
            return
        if cmd.action is Action.cancel:
            if cmd.id in self.active_receives:
                self.handle_receive_cmd(cmd)
                return
            if cmd.id in self.active_sends:
                self.handle_send_cmd(cmd)
                return
        self.prune_expired()
        if cmd.id in self.active_receives or cmd.action is Action.send:
            self.handle_receive_cmd(cmd)
        if cmd.id in self.active_sends or cmd.action is Action.receive:
            self.handle_send_cmd(cmd)

    def handle_send_cmd(self, cmd: FileTransmissionCommand) -> None:
        if cmd.id in self.active_sends:
            asd = self.active_sends[cmd.id]
            if cmd.action is Action.receive:
                log_error('File transmission receive received for already active id, aborting')
                self.drop_send(cmd.id)
                return
            if cmd.action is Action.file:
                try:
                    asd.add_file_spec(cmd)
                except TransmissionError as err:
                    self.drop_send(asd.id)
                    if asd.send_errors:
                        self.send_transmission_error(asd.id, err)
                    return
                if asd.spec_complete and asd.accepted:
                    self.send_metadata_for_send_transfer(asd)
                return
            if not asd.accepted:
                log_error(f'File transmission command {cmd.action} received for pending id: {cmd.id}, aborting')
                self.drop_send(cmd.id)
                return
            asd.last_activity_at = monotonic()
        else:
            if cmd.action is not Action.receive:
                log_error(f'File transmission command {cmd.action} received for unknown or rejected id: {cmd.id}, ignoring')
                return
            if len(self.active_sends) >= MAX_ACTIVE_SENDS:
                log_error('New File transmission send with too many active receives, ignoring')
                return
            asd = self.active_sends[cmd.id] = ActiveSend(cmd.id, cmd.quiet, cmd.bypass, cmd.size)
            self.start_send(asd.id)
            return
        if cmd.action is Action.cancel:
            self.drop_send(asd.id)
            if asd.send_acknowledgements:
                self.send_status_response(ErrorCode.CANCELED, request_id=asd.id)

    def send_metadata_for_send_transfer(self, asd: ActiveSend) -> None:
        sent = False
        for ftc in iter_file_metadata(asd.file_specs):
            if isinstance(ftc, TransmissionError):
                sent = True
                if asd.send_errors:
                    self.send_transmission_error(asd.id, ftc)
            else:
                ftc.id = asd.id
                self.write_ftc_to_child(ftc)
                sent = True
        if sent:
            self.send_status_response(code=ErrorCode.OK, request_id=asd.id, name=home_path())
        else:
            self.send_status_response(code=ErrorCode.ENOENT, request_id=asd.id, msg='No files found')
            self.drop_send(asd.id)

    def handle_receive_cmd(self, cmd: FileTransmissionCommand) -> None:
        if cmd.id in self.active_receives:
            ar = self.active_receives[cmd.id]
            if cmd.action is Action.send:
                log_error('File transmission send received for already active id, aborting')
                self.drop_receive(cmd.id)
                return
            if not ar.accepted:
                log_error(f'File transmission command {cmd.action} received for pending id: {cmd.id}, aborting')
                self.drop_receive(cmd.id)
                return
            ar.last_activity_at = monotonic()
        else:
            if cmd.action is not Action.send:
                log_error(f'File transmission command {cmd.action} received for unknown or rejected id: {cmd.id}, ignoring')
                return
            if len(self.active_receives) >= MAX_ACTIVE_RECEIVES:
                log_error('New File transmission send with too many active receives, ignoring')
                return
            ar = self.active_receives[cmd.id] = ActiveReceive(cmd.id, cmd.quiet, cmd.bypass)
            self.start_receive(ar.id)
            return

        if cmd.action is Action.cancel:
            self.drop_receive(ar.id)
            if ar.send_acknowledgements:
                self.send_status_response(ErrorCode.CANCELED, request_id=ar.id)
        elif cmd.action is Action.file:
            try:
                df = ar.start_file(cmd)
            except TransmissionError as err:
                if ar.send_errors:
                    self.send_transmission_error(ar.id, err)
            except Exception as err:
                log_error(f'Transmission protocol failed to start file with error: {err}')
                if ar.send_errors:
                    te = TransmissionError(file_id=cmd.file_id, msg=str(err))
                    self.send_transmission_error(ar.id, te)
            else:
                if df.ftype is FileType.directory:
                    try:
                        os.makedirs(df.name, exist_ok=True)
                    except OSError as err:
                        self.send_fail_on_os_error(err, 'Failed to create directory', ar, df.file_id)
                    else:
                        self.send_status_response(ErrorCode.OK, ar.id, df.file_id, name=df.name)
                else:
                    if ar.send_acknowledgements:
                        sz = df.existing_stat.st_size if df.existing_stat is not None else -1
                        ttype = TransmissionType.rsync \
                            if sz > -1 and df.ttype is TransmissionType.rsync and df.ftype is FileType.regular else TransmissionType.simple
                        self.send_status_response(code=ErrorCode.STARTED, request_id=ar.id, file_id=df.file_id, name=df.name, size=sz, ttype=ttype)
                        df.ttype = ttype
                        if ttype is TransmissionType.rsync:
                            try:
                                fs = signature_of_file(df.name)
                            except OSError as err:
                                self.send_fail_on_os_error(err, 'Failed to open file to read signature', ar, df.file_id)
                            else:
                                self.callback_after(partial(self.transmit_rsync_signature, fs, ar.id, df.file_id, deque()))
        elif cmd.action in (Action.data, Action.end_data):
            try:
                before = 0
                bf = ar.files.get(cmd.file_id)
                if bf is not None:
                    before = bf.bytes_written
                df = ar.add_data(cmd)
                if df.failed:
                    return
                if ar.send_acknowledgements:
                    if df.closed:
                        self.send_status_response(
                            code=ErrorCode.OK, request_id=ar.id, file_id=df.file_id, name=df.name, size=df.bytes_written)
                    elif df.bytes_written > before:
                        self.send_status_response(
                            code=ErrorCode.PROGRESS, request_id=ar.id, file_id=df.file_id, size=df.bytes_written)
            except TransmissionError as err:
                if ar.send_errors:
                    self.send_transmission_error(ar.id, err)
            except Exception as err:
                log_error(f'Transmission protocol failed to write data to file with error: {err}')
                if ar.send_errors:
                    te = TransmissionError(file_id=cmd.file_id, msg=str(err))
                    self.send_transmission_error(ar.id, te)
        elif cmd.action is Action.finish:
            try:
                ar.commit(self.send_fail_on_os_error)
            except TransmissionError as err:
                if ar.send_errors:
                    self.send_transmission_error(ar.id, err)
            except Exception as err:
                log_error(f'Transmission protocol failed to commit receive with error: {err}')
                if ar.send_errors:
                    te = TransmissionError(msg=str(err))
                    self.send_transmission_error(ar.id, te)
            finally:
                self.drop_receive(ar.id)
        else:
            log_error('Transmission receive command with unknown action: {cmd.action}, ignoring')

    def transmit_rsync_signature(
        self, fs: Iterator[memoryview],
        receive_id: str, file_id: str,
        pending: Deque[FileTransmissionCommand],
        timer_id: Optional[int] = None
    ) -> None:
        ar = self.active_receives.get(receive_id)
        if ar is None:
            return
        func = partial(self.transmit_rsync_signature, fs, receive_id, file_id, pending)
        while pending:
            if self.write_ftc_to_child(pending[0], use_pending=False):
                pending.popleft()
            else:
                self.callback_after(func, timeout=0.1)
                return
        try:
            chunk = next(fs)
        except StopIteration:
            self.write_ftc_to_child(FileTransmissionCommand(id=receive_id, action=Action.end_data, file_id=file_id))
            return
        except OSError as err:
            if ar.send_errors:
                self.send_fail_on_os_error(err, 'Failed to read signature', ar, file_id)
            return
        if not len(chunk):
            self.write_ftc_to_child(FileTransmissionCommand(id=receive_id, action=Action.end_data, file_id=file_id))
            return
        has_capacity = True
        for data in split_for_transfer(chunk, session_id=receive_id, file_id=file_id):
            if has_capacity:
                if not self.write_ftc_to_child(data, use_pending=False):
                    has_capacity = False
                    pending.append(data)
            else:
                pending.append(data)
        self.callback_after(func)

    def send_status_response(
        self, code: Union[ErrorCode, str] = ErrorCode.EINVAL,
        request_id: str = '', file_id: str = '', msg: str = '',
        name: str = '', size: int = -1,
        ttype: TransmissionType = TransmissionType.simple,
    ) -> bool:
        err = TransmissionError(code=code, msg=msg, file_id=file_id, name=name, size=size, ttype=ttype)
        return self.write_ftc_to_child(err.as_ftc(request_id))

    def send_transmission_error(self, request_id: str, err: TransmissionError) -> bool:
        if err.transmit:
            return self.write_ftc_to_child(err.as_ftc(request_id))
        return True

    def write_ftc_to_child(self, payload: FileTransmissionCommand, appendleft: bool = False, use_pending: bool = True) -> bool:
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            data = tuple(payload.get_serialized_fields(prefix_with_osc_code=True))
            queued = window.screen.send_escape_code_to_child(OSC, data)
            if not queued:
                if use_pending:
                    if appendleft:
                        self.pending_receive_responses.appendleft(payload)
                    else:
                        self.pending_receive_responses.append(payload)
                    self.start_pending_timer()
            return queued
        return False

    def start_send(self, asd_id: str) -> None:
        asd = self.active_sends[asd_id]
        if asd.bypass_ok is not None:
            self.handle_receive_confirmation(asd_id, {'response': 'y' if asd.bypass_ok else 'n'})
            return
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            boss._run_kitten('ask', ['--type=yesno', '--message', _(
                'The remote machine wants to read some files from this computer. Do you want to allow the transfer?'
                )],
                window=window, custom_callback=partial(self.handle_receive_confirmation, asd_id),
            )

    def handle_receive_confirmation(self, cmd_id: str, data: Dict[str, str], *a: Any) -> None:
        asd = self.active_sends.get(cmd_id)
        if asd is None:
            return
        if data['response'] == 'y':
            asd.accepted = True
        else:
            self.drop_send(asd.id)
        if asd.accepted:
            if asd.send_acknowledgements:
                self.send_status_response(code=ErrorCode.OK, request_id=asd.id)
            if asd.spec_complete:
                self.send_metadata_for_send_transfer(asd)
        else:
            if asd.send_errors:
                self.send_status_response(code=ErrorCode.EPERM, request_id=asd.id, msg='User refused the transfer')

    def start_receive(self, ar_id: str) -> None:
        ar = self.active_receives[ar_id]
        if ar.bypass_ok is not None:
            self.handle_send_confirmation(ar_id, {'response': 'y' if ar.bypass_ok else 'n'})
            return
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
        if ar.accepted:
            if ar.send_acknowledgements:
                self.send_status_response(code=ErrorCode.OK, request_id=ar.id)
        else:
            if ar.send_errors:
                self.send_status_response(code=ErrorCode.EPERM, request_id=ar.id, msg='User refused the transfer')

    def send_fail_on_os_error(self, err: OSError, msg: str, ar: ActiveReceive, file_id: str = '') -> None:
        if not ar.send_errors:
            return
        errname = errno.errorcode.get(err.errno, 'EFAIL')
        self.send_status_response(code=errname, msg=msg, request_id=ar.id, file_id=file_id)

    def active_file(self, rid: str = '', file_id: str = '') -> DestFile:
        return self.active_receives[rid].files[file_id]


class TestFileTransmission(FileTransmission):

    def __init__(self, allow: bool = True) -> None:
        super().__init__(0)
        self.test_responses: List[Dict[str, Union[str, int, bytes]]] = []
        self.allow = allow

    def write_ftc_to_child(self, payload: FileTransmissionCommand, appendleft: bool = False, use_pending: bool = True) -> bool:
        self.test_responses.append(payload.asdict())
        return True

    def start_receive(self, aid: str) -> None:
        self.handle_send_confirmation(aid, {'response': 'y' if self.allow else 'n'})

    def start_send(self, aid: str) -> None:
        self.handle_receive_confirmation(aid, {'response': 'y' if self.allow else 'n'})

    def callback_after(self, callback: Callable[[Optional[int]], None], timeout: float = 0) -> Optional[int]:
        callback(None)
        return None
