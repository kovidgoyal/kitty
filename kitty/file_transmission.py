#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import inspect
import io
import json
import os
import re
import stat
import tempfile
from base64 import b85decode
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import suppress
from dataclasses import Field, dataclass, field, fields
from enum import Enum, auto
from functools import partial
from gettext import gettext as _
from itertools import count
from time import time_ns
from typing import IO, Any, DefaultDict, Deque, Union

from kittens.transfer.utils import IdentityCompressor, ZlibCompressor, abspath, expand_home, home_path
from kitty.fast_data_types import ESC_OSC, FILE_TRANSFER_CODE, AES256GCMDecrypt, add_timer, base64_decode, base64_encode, get_boss, get_options, monotonic
from kitty.types import run_once
from kitty.typing_compat import ReadableBuffer, WriteableBuffer

from .utils import log_error

EXPIRE_TIME = 10  # minutes
MAX_ACTIVE_RECEIVES = MAX_ACTIVE_SENDS = 10
ftc_prefix = str(FILE_TRANSFER_CODE)


@run_once
def safe_string_pat() -> 're.Pattern[str]':
    return re.compile(r'[^0-9a-zA-Z_:./@-]')


def safe_string(x: str) -> str:
    return safe_string_pat().sub('', x)


def as_unicode(x: str | bytes) -> str:
    if isinstance(x, bytes):
        x = x.decode('ascii')
    return x


def encode_bypass(request_id: str, bypass: str) -> str:
    import hashlib
    q = request_id + ';' + bypass
    return 'sha256:' + hashlib.sha256(q.encode('utf-8', 'replace')).hexdigest()


def split_for_transfer(
    data: bytes | bytearray | memoryview,
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


def iter_file_metadata(file_specs: Iterable[tuple[str, str]]) -> Iterator[Union['FileTransmissionCommand', 'TransmissionError']]:
    file_map: DefaultDict[tuple[int, int], list[FileTransmissionCommand]] = defaultdict(list)
    counter = count()

    def skey(sr: os.stat_result) -> tuple[int, int]:
        return sr.st_dev, sr.st_ino

    def make_ftc(path: str, spec_id: str, sr: os.stat_result | None = None, parent: str = '') -> FileTransmissionCommand:
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
        ans = FileTransmissionCommand(
            action=Action.file, file_id=spec_id, mtime=sr.st_mtime_ns, permissions=stat.S_IMODE(sr.st_mode),
            name=path, status=str(next(counter)), size=sr.st_size, ftype=ftype, parent=parent
        )
        file_map[skey(sr)].append(ans)
        return ans

    def add_dir(ftc: FileTransmissionCommand) -> None:
        try:
            lr = os.listdir(ftc.name)
        except OSError:
            return
        for entry in lr:
            try:
                child_ftc = make_ftc(os.path.join(ftc.name, entry), spec_id, parent=ftc.status)
            except (ValueError, OSError):
                continue
            if child_ftc.ftype is FileType.directory:
                add_dir(child_ftc)

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
            errname = errno.errorcode.get(err.errno, 'EFAIL') if err.errno is not None else 'EFAIL'
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
        if ftc.ftype is FileType.directory:
            add_dir(ftc)

    def resolve_symlink(ftc: FileTransmissionCommand) -> FileTransmissionCommand:
        if ftc.ftype is FileType.symlink:
            try:
                dest = os.path.realpath(ftc.name)
            except OSError:
                pass
            else:
                try:
                    s = os.stat(dest, follow_symlinks=False)
                except OSError:
                    pass
                else:
                    tgt = file_map.get(skey(s))
                    if tgt is not None:
                        ftc.data = tgt[0].status.encode('utf-8')
        return ftc

    for fkey, cmds in file_map.items():
        base = cmds[0]
        yield resolve_symlink(base)
        if len(cmds) > 1 and base.ftype is FileType.regular:
            for q in cmds:
                if q is not base and q.ftype is FileType.regular:
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
        self, code: ErrorCode | str = ErrorCode.EINVAL,
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


@run_once
def name_to_serialized_map() -> dict[str, str]:
    ans: dict[str, str] = {}
    for k in fields(FileTransmissionCommand):
        ans[k.name] = k.metadata.get('sname', k.name)
    return ans


@run_once
def serialized_to_field_map() -> dict[bytes | memoryview, 'Field[Any]']:
    ans: dict[bytes | memoryview, 'Field[Any]'] = {}
    for k in fields(FileTransmissionCommand):
        ans[k.metadata.get('sname', k.name).encode('ascii')] = k
    return ans


@dataclass
class FileTransmissionCommand:

    action: Action = field(default=Action.invalid, metadata={'sname': 'ac'})
    compression: Compression = field(default=Compression.none, metadata={'sname': 'zip'})
    ftype: FileType = field(default=FileType.regular, metadata={'sname': 'ft'})
    ttype: TransmissionType = field(default=TransmissionType.simple, metadata={'sname': 'tt'})
    id: str = ''
    file_id: str = field(default='', metadata={'sname': 'fid'})
    bypass: str = field(default='', metadata={'base64': True, 'sname': 'pw'})
    quiet: int = field(default=0, metadata={'sname': 'q'})
    mtime: int = field(default=-1, metadata={'sname': 'mod'})
    permissions: int = field(default=-1, metadata={'sname': 'prm'})
    size: int = field(default=-1, metadata={'sname': 'sz'})
    name: str = field(default='', metadata={'base64': True, 'sname': 'n'})
    status: str = field(default='', metadata={'base64': True, 'sname': 'st'})
    parent: str = field(default='', metadata={'sname': 'pr'})
    data: bytes | memoryview = field(default=b'', repr=False, metadata={'sname': 'd'})

    def __repr__(self) -> str:
        ans = []
        for k in fields(self):
            if not k.repr:
                continue
            val = getattr(self, k.name)
            if val != k.default:
                ans.append(f'{k.name}={val!r}')
        if self.data:
            ans.append(f'data={len(self.data)} bytes')
        return 'FTC(' + ', '.join(ans) + ')'

    def asdict(self, keep_defaults: bool = False) -> dict[str, str | int | bytes]:
        ans = {}
        for k in fields(self):
            val = getattr(self, k.name)
            if not keep_defaults and val == k.default:
                continue
            if inspect.isclass(k.type) and issubclass(k.type, Enum):
                val = val.name
            ans[k.name] = val
        return ans

    def get_serialized_fields(self, prefix_with_osc_code: bool = False) -> Iterator[str | bytes]:
        nts = name_to_serialized_map()
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
            yield nts[name]
            yield '='
            if inspect.isclass(k.type) and issubclass(k.type, Enum):
                yield val.name
            elif k.type == bytes | memoryview:
                yield base64_encode(val)
            elif k.type is str:
                if k.metadata.get('base64'):
                    yield base64_encode(val.encode('utf-8'))
                else:
                    yield safe_string(val)
            elif k.type is int:
                yield str(val)
            else:
                raise KeyError(f'Field of unknown type: {k.name}')

    def serialize(self, prefix_with_osc_code: bool = False) -> str:
        return ''.join(map(as_unicode, self.get_serialized_fields(prefix_with_osc_code)))

    @classmethod
    def deserialize(cls, data: str | bytes | memoryview) -> 'FileTransmissionCommand':
        ans = FileTransmissionCommand()
        fmap = serialized_to_field_map()
        from kittens.transfer.rsync import parse_ftc

        def handle_item(key: memoryview, val: memoryview) -> None:
            field = fmap.get(key)
            if field is None:
                return
            if inspect.isclass(field.type) and issubclass(field.type, Enum):
                setattr(ans, field.name, field.type[str(val, "utf-8")])
            elif field.type == bytes | memoryview:
                setattr(ans, field.name, base64_decode(val))
            elif field.type is int:
                setattr(ans, field.name, int(val))
            elif field.type is str:
                if field.metadata.get('base64'):
                    sval = base64_decode(val).decode('utf-8')
                else:
                    sval = safe_string(str(val, "utf-8"))
                setattr(ans, field.name, sval)

        parse_ftc(data, handle_item)
        if ans.action is Action.invalid:
            raise ValueError('No valid action specified in file transmission command')

        return ans


class IdentityDecompressor:

    def __call__(self, data: bytes | memoryview, is_last: bool = False) -> bytes:
        return bytes(data)


class ZlibDecompressor:

    def __init__(self) -> None:
        import zlib
        self.d = zlib.decompressobj(wbits=0)

    def __call__(self, data: bytes | memoryview, is_last: bool = False) -> bytes:
        ans = self.d.decompress(data)
        if is_last:
            ans += self.d.flush()
        return ans


class PatchFile:

    def __init__(self, path: str, expected_size: int):
        from kittens.transfer.rsync import Patcher
        self.patcher = Patcher(expected_size)
        self.block_buffer = memoryview(bytearray(self.patcher.block_size))
        self.path = path
        self.signature_done = False
        self.src_file: io.BufferedReader | None = None
        self._dest_file: IO[bytes] | None = None
        self.closed = False

    @property
    def dest_file(self) -> IO[bytes]:
        if self._dest_file is None:
            self._dest_file = tempfile.NamedTemporaryFile(mode='wb', dir=os.path.dirname(os.path.abspath(os.path.realpath(self.path))), delete=False)
        return self._dest_file

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        p = self.patcher
        del self.block_buffer, self.patcher
        if self._dest_file is not None and not self._dest_file.closed:
            self._dest_file.close()
            p.finish_delta_data()
            if self.src_file is not None:
                os.replace(self.dest_file.name, self.src_file.name)
        if self.src_file is not None and not self.src_file.closed:
            self.src_file.close()

    def tell(self) -> int:
        df = self.dest_file
        if df.closed:
            return os.path.getsize(self.path)
        return df.tell()

    def read_from_src(self, pos: int, b: WriteableBuffer) -> int:
        assert self.src_file is not None
        self.src_file.seek(pos, os.SEEK_SET)
        return self.src_file.readinto(b)

    def write_to_dest(self, b: ReadableBuffer) -> None:
        self.dest_file.write(b)

    def write(self, b: bytes) -> None:
        self.patcher.apply_delta_data(b, self.read_from_src, self.write_to_dest)

    def next_signature_block(self, buf: memoryview) -> int:
        if self.signature_done:
            return 0
        if self.src_file is None:
            self.src_file = open(self.path, 'rb')
            return self.patcher.signature_header(buf)
        n = self.src_file.readinto(self.block_buffer)
        if n > 0:
            n = self.patcher.sign_block(self.block_buffer[:n], buf)
        else:
            self.src_file.seek(0, os.SEEK_SET)
            self.signature_done = True
        return n


class DestFile:

    def __init__(self, ftc: FileTransmissionCommand) -> None:
        self.name = ftc.name
        if not os.path.isabs(self.name):
            self.name = expand_home(self.name)
            if not os.path.isabs(self.name):
                self.name = abspath(self.name, use_home=True)
        try:
            self.existing_stat: os.stat_result | None = os.stat(self.name, follow_symlinks=False)
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
        self.decompressor: ZlibDecompressor | IdentityDecompressor = ZlibDecompressor() if ftc.compression is Compression.zlib else IdentityDecompressor()
        self.closed = self.ftype is FileType.directory
        self.actual_file: PatchFile | IO[bytes] | None = None
        self.failed = False
        self.bytes_written = 0

    def signature_iterator(self) -> PatchFile:
        self.actual_file = PatchFile(self.name, self.existing_stat.st_size if self.existing_stat is not None else 0)
        return self.actual_file

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

    def write_data(self, all_files: dict[str, 'DestFile'], data: bytes | memoryview, is_last: bool) -> None:
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
                        lt = os.path.relpath(lt, os.path.dirname(self.name))
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
                self.unlink_existing_if_needed()
                flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_BINARY', 0)
                self.actual_file = open(os.open(self.name, flags, self.permissions), mode='r+b', closefd=True)
            af = self.actual_file
            if decompressed or is_last:
                af.write(decompressed)
                self.bytes_written = af.tell()
            if is_last:
                self.close()
                self.apply_metadata()


def check_bypass(password: str, request_id: str, bypass_data: str) -> bool:
    protocol, sep, bypass_data = bypass_data.partition(':')
    if protocol == 'kitty-1':
        try:
            pcmd = json.loads(bypass_data)
            pubkey = pcmd.get('pubkey', '')
            if not pubkey:
                return False
            ekey = get_boss().encryption_key
            d = AES256GCMDecrypt(ekey.derive_secret(b85decode(pubkey)), b85decode(pcmd['iv']), b85decode(pcmd['tag']))
            data = d.add_data_to_be_decrypted(b85decode(pcmd['encrypted']), True)
            timestamp, sep, payload = data.decode('utf-8').partition(':')
            delta = time_ns() - int(timestamp)
            if abs(delta) > 5 * 60 * 1e9:
                return False
            return payload == f'{request_id};{password}'
        except Exception as err:
            log_error(f'Invalid file transmission bypass data received: {err}')
            return False
    elif protocol == 'sha256':
        return (encode_bypass(request_id, password) == bypass_data) if password else False
    else:
        log_error(f'Invalid file transmission bypass data received with protocol: {protocol}')
    return False


class ActiveReceive:
    id: str
    files: dict[str, DestFile]
    accepted: bool = False

    def __init__(self, request_id: str, quiet: int, bypass: str) -> None:
        self.id = request_id
        self.bypass_ok: bool | None = None
        if bypass:
            byp = get_options().file_transfer_confirmation_bypass
            self.bypass_ok = check_bypass(byp, request_id, bypass)
        self.files = {}
        self.last_activity_at = monotonic()
        self.send_acknowledgements = quiet < 1
        self.send_errors = quiet < 2
        self.pending_files_to_transmit_signature_of: Deque[tuple[PatchFile, str]] = deque()
        self.signature_pending_chunks: Deque[FileTransmissionCommand] = deque()

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
            with suppress(Exception):
                df.close()
            raise
        return df

    def commit(self, send_os_error: Callable[[OSError, str, 'ActiveReceive', str], None]) -> None:
        directories = sorted((df for df in self.files.values() if df.ftype is FileType.directory), key=lambda x: len(x.name), reverse=True)
        for df in directories:
            with suppress(OSError):
                # we ignore failures to apply directory metadata as we have already sent an OK for the dir
                df.apply_metadata()


class SourceFile:

    def __init__(self, ftc: FileTransmissionCommand):
        self.file_id = ftc.file_id
        self.path = ftc.name
        self.ttype = ftc.ttype
        self.waiting_for_signature = True if self.ttype is TransmissionType.rsync else False
        self.transmitted = False
        self.stat = os.stat(self.path, follow_symlinks=False)
        if stat.S_ISDIR(self.stat.st_mode):
            raise TransmissionError(ErrorCode.EINVAL, msg='Cannot send a directory', file_id=self.file_id)
        self.compressor: ZlibCompressor | IdentityCompressor = IdentityCompressor()
        self.target = b''
        self.open_file: io.BufferedReader | None = None
        if stat.S_ISLNK(self.stat.st_mode):
            self.target = os.readlink(self.path).encode('utf-8')
        else:
            self.open_file = open(self.path, 'rb')
            if ftc.compression is Compression.zlib:
                self.compressor = ZlibCompressor()
        from kittens.transfer import rsync
        self.differ = rsync.Differ() if self.waiting_for_signature else None
        self.buf = bytearray()
        self.write_pos = 0

    def write(self, b: ReadableBuffer) -> None:
        self.buf[self.write_pos:self.write_pos+len(b)] = b
        self.write_pos += len(b)

    @property
    def ready_to_transmit(self) -> bool:
        return not self.transmitted and not self.waiting_for_signature

    def close(self) -> None:
        if self.open_file is not None:
            self.open_file.close()
            self.open_file = None
        self.differ = None

    def next_chunk(self, sz: int = 1024 * 1024) -> tuple[bytes, int]:
        data: bytes | memoryview = b''
        if self.target:
            self.transmitted = True
            data = self.target
        else:
            if self.open_file is None:
                self.transmitted = True
                data = b''
            else:
                if self.differ is None:
                    data = self.open_file.read(sz)
                    if not data or self.open_file.tell() >= self.stat.st_size:
                        self.transmitted = True
                else:
                    self.write_pos = 0
                    has_more = self.differ.next_op(self.open_file.readinto, self.write)
                    data = memoryview(self.buf)[:self.write_pos]
                    if not has_more:
                        self.transmitted = True
        uncompressed_sz = len(data)
        cchunk = self.compressor.compress(data)
        if self.transmitted and not isinstance(self.compressor, IdentityCompressor):
            cchunk += self.compressor.flush()
        if self.transmitted:
            self.close()
        return cchunk, uncompressed_sz


class ActiveSend:

    def __init__(self, request_id: str, quiet: int, bypass: str, num_of_args: int) -> None:
        self.id = request_id
        self.expected_num_of_args = num_of_args
        self.bypass_ok: bool | None = None
        if bypass:
            byp = get_options().file_transfer_confirmation_bypass
            self.bypass_ok = check_bypass(byp, request_id, bypass)
        self.accepted = False
        self.last_activity_at = monotonic()
        self.send_acknowledgements = quiet < 1
        self.send_errors = quiet < 2
        self.last_activity_at = monotonic()
        self.file_specs: list[tuple[str, str]] = []
        self.queued_files_map: dict[str, SourceFile] = {}
        self.active_file: SourceFile | None = None
        self.pending_chunks: Deque[FileTransmissionCommand] = deque()
        self.metadata_sent = False

    @property
    def spec_complete(self) -> bool:
        return self.expected_num_of_args <= len(self.file_specs)

    def add_file_spec(self, cmd: FileTransmissionCommand) -> None:
        self.last_activity_at = monotonic()
        if len(self.file_specs) > 8192 or self.spec_complete:
            raise TransmissionError(ErrorCode.EINVAL, 'Too many file specs')
        self.file_specs.append((cmd.file_id, cmd.name))

    def add_send_file(self, cmd: FileTransmissionCommand) -> None:
        self.last_activity_at = monotonic()
        if len(self.queued_files_map) > 32768:
            raise TransmissionError(ErrorCode.EINVAL, 'Too many queued files')
        self.queued_files_map[cmd.file_id] = SourceFile(cmd)

    def add_signature_data(self, cmd: FileTransmissionCommand) -> None:
        self.last_activity_at = monotonic()
        af = self.queued_files_map.get(cmd.file_id)
        if af is None:
            raise TransmissionError(ErrorCode.EINVAL, f'Signature data for unknown file_id: {cmd.file_id}')
        sl = af.differ
        if sl is None:
            raise TransmissionError(ErrorCode.EINVAL, f'Signature data for file that is not using rsync: {cmd.file_id}')
        sl.add_signature_data(cmd.data)
        if cmd.action is Action.end_data:
            sl.finish_signature_data()
            af.waiting_for_signature = False

    @property
    def is_expired(self) -> bool:
        return monotonic() - self.last_activity_at > (60 * EXPIRE_TIME)

    def close(self) -> None:
        if self.active_file is not None:
            self.active_file.close()
            self.active_file = None

    def next_chunk(self) -> FileTransmissionCommand | None:
        self.last_activity_at = monotonic()
        if self.pending_chunks:
            return self.pending_chunks.popleft()
        af = self.active_file
        if af is None:
            for f in self.queued_files_map.values():
                if f.ready_to_transmit:
                    self.active_file = af = f
                    break
            if af is None:
                return None
            self.queued_files_map.pop(af.file_id, None)
        while True:
            chunk, uncompressed_sz = af.next_chunk()
            if af.transmitted:
                self.active_file = None
                break
            if chunk:
                break
        if chunk:
            self.pending_chunks.extend(split_for_transfer(chunk, file_id=af.file_id, mark_last=af.transmitted))
            return self.pending_chunks.popleft()
        elif af.transmitted:
            return FileTransmissionCommand(action=Action.end_data, file_id=af.file_id)
        return None

    def return_chunk(self, ftc: FileTransmissionCommand) -> None:
        self.pending_chunks.insert(0, ftc)


class FileTransmission:

    def __init__(self, window_id: int):
        self.window_id = window_id
        self.active_receives: dict[str, ActiveReceive] = {}
        self.active_sends: dict[str, ActiveSend] = {}
        self.pending_receive_responses: Deque[FileTransmissionCommand] = deque()
        self.pending_timer: int | None = None

    def callback_after(self, callback: Callable[[int | None], None], timeout: float = 0) -> int | None:
        return add_timer(callback, timeout, False)

    def start_pending_timer(self) -> None:
        if self.pending_timer is None:
            self.pending_timer = self.callback_after(self.try_pending, 0.2)

    def try_pending(self, timer_id: int | None) -> None:
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

    def handle_serialized_command(self, data: memoryview) -> None:
        try:
            cmd = FileTransmissionCommand.deserialize(data)
        except Exception as e:
            log_error(f'Failed to parse file transmission command with error: {e}')
            return
        # print('from kitten:', cmd)
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
                    asd.add_send_file(cmd) if asd.metadata_sent else asd.add_file_spec(cmd)
                except OSError as err:
                    self.send_fail_on_os_error(err, 'Failed to add send file', asd, cmd.file_id)
                    self.drop_send(asd.id)
                    return
                except TransmissionError as err:
                    self.drop_send(asd.id)
                    if asd.send_errors:
                        self.send_transmission_error(asd.id, err)
                    return
                if asd.metadata_sent:
                    self.pump_send_chunks(asd)
                else:
                    if asd.spec_complete and asd.accepted:
                        self.send_metadata_for_send_transfer(asd)
                return
            if cmd.action in (Action.data, Action.end_data):
                try:
                    asd.add_signature_data(cmd)
                except TransmissionError as err:
                    self.drop_send(asd.id)
                    if asd.send_errors:
                        self.send_transmission_error(asd.id, err)
                else:
                    self.pump_send_chunks(asd)
            elif cmd.action in (Action.status, Action.finish):
                self.drop_send(asd.id)
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
            asd.metadata_sent = True
        else:
            self.send_status_response(code=ErrorCode.ENOENT, request_id=asd.id, msg='No files found')
            self.drop_send(asd.id)

    def pump_send_chunks(self, asd: ActiveSend) -> None:
        while True:
            try:
                ftc = asd.next_chunk()
            except OSError as err:
                fid = asd.active_file.file_id if asd.active_file else ''
                self.send_fail_on_os_error(err, 'Failed to read data from file', asd, file_id=fid)
                self.drop_send(asd.id)
                break
            if ftc is None:
                break
            ftc.id = asd.id
            if not self.write_ftc_to_child(ftc, use_pending=False):
                asd.return_chunk(ftc)
                self.callback_after(self.pump_sends, 0.05)
                break

    def pump_sends(self, timer_id: int | None) -> None:
        for asd in self.active_sends.values():
            if asd.metadata_sent:
                self.pump_send_chunks(asd)

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
                                fs = df.signature_iterator()
                            except OSError as err:
                                self.send_fail_on_os_error(err, 'Failed to open file to read signature', ar, df.file_id)
                            else:
                                ar.pending_files_to_transmit_signature_of.append((fs, df.file_id))
                                self.callback_after(partial(self.transmit_rsync_signature, ar.id))
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
                import traceback
                st = traceback.format_exc()
                log_error(f'Transmission protocol failed to write data to file with error: {st}')
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
            log_error(f'Transmission receive command with unknown action: {cmd.action}, ignoring')

    def transmit_rsync_signature(self, receive_id: str, timer_id: int | None = None) -> None:
        q = self.active_receives.get(receive_id)
        if q is None:
            return
        ar = q  # for mypy
        while ar.signature_pending_chunks:
            if self.write_ftc_to_child(ar.signature_pending_chunks[0], use_pending=False):
                ar.signature_pending_chunks.popleft()
            else:
                self.callback_after(partial(self.transmit_rsync_signature, receive_id), timeout=0.1)
                return
        if not ar.pending_files_to_transmit_signature_of:
            return
        fs, file_id = ar.pending_files_to_transmit_signature_of[0]
        pos = 0
        buf = memoryview(bytearray(4096))
        is_finished = False
        while len(buf) >= pos + 32:
            try:
                n = fs.next_signature_block(buf[pos:])
            except OSError as err:
                if ar.send_errors:
                    self.send_fail_on_os_error(err, 'Failed to read signature', ar, file_id)
                return
            if not n:
                is_finished = True
                ar.pending_files_to_transmit_signature_of.popleft()
                break
            pos += n

        chunk = buf[:pos]
        has_capacity = True

        def write_ftc(data: FileTransmissionCommand) -> None:
            nonlocal has_capacity
            if has_capacity:
                if not self.write_ftc_to_child(data, use_pending=False):
                    has_capacity = False
                    ar.signature_pending_chunks.append(data)
            else:
                ar.signature_pending_chunks.append(data)

        if len(chunk):
            for data in split_for_transfer(chunk, session_id=receive_id, file_id=file_id):
                write_ftc(data)
        if is_finished:
            endftc = FileTransmissionCommand(id=receive_id, action=Action.end_data, file_id=file_id)
            write_ftc(endftc)
        self.callback_after(partial(self.transmit_rsync_signature, receive_id))

    def send_status_response(
        self, code: ErrorCode | str = ErrorCode.EINVAL,
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
            queued = window.screen.send_escape_code_to_child(ESC_OSC, data)
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
            self.handle_receive_confirmation(asd.bypass_ok, asd_id)
            return
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            boss.confirm(_(
                'The remote machine wants to read some files from this computer. Do you want to allow the transfer?'),
                self.handle_receive_confirmation, asd_id, window=window,
            )

    def handle_receive_confirmation(self, confirmed: bool, cmd_id: str) -> None:
        asd = self.active_sends.get(cmd_id)
        if asd is None:
            return
        if confirmed:
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
            self.handle_send_confirmation(ar.bypass_ok, ar_id)
            return
        boss = get_boss()
        window = boss.window_id_map.get(self.window_id)
        if window is not None:
            boss.confirm(_(
                'The remote machine wants to send some files to this computer. Do you want to allow the transfer?'),
                self.handle_send_confirmation, ar_id, window=window,
            )

    def handle_send_confirmation(self, confirmed: bool, cmd_id: str) -> None:
        ar = self.active_receives.get(cmd_id)
        if ar is None:
            return
        if confirmed:
            ar.accepted = True
        else:
            self.drop_receive(ar.id)
        if ar.accepted:
            if ar.send_acknowledgements:
                self.send_status_response(code=ErrorCode.OK, request_id=ar.id)
        else:
            if ar.send_errors:
                self.send_status_response(code=ErrorCode.EPERM, request_id=ar.id, msg='User refused the transfer')

    def send_fail_on_os_error(self, err: OSError, msg: str, ar: ActiveSend | ActiveReceive, file_id: str = '') -> None:
        if not ar.send_errors:
            return
        errname = errno.errorcode.get(err.errno, 'EFAIL') if err.errno is not None else 'EFAIL'
        self.send_status_response(code=errname, msg=msg, request_id=ar.id, file_id=file_id)

    def active_file(self, rid: str = '', file_id: str = '') -> DestFile:
        return self.active_receives[rid].files[file_id]


class TestFileTransmission(FileTransmission):

    def __init__(self, allow: bool = True) -> None:
        super().__init__(0)
        self.test_responses: list[dict[str, str | int | bytes]] = []
        self.allow = allow

    def write_ftc_to_child(self, payload: FileTransmissionCommand, appendleft: bool = False, use_pending: bool = True) -> bool:
        self.test_responses.append(payload.asdict())
        return True

    def start_receive(self, aid: str) -> None:
        self.handle_send_confirmation(self.allow, aid)

    def start_send(self, aid: str) -> None:
        self.handle_receive_confirmation(self.allow, aid)

    def callback_after(self, callback: Callable[[int | None], None], timeout: float = 0) -> int | None:
        callback(None)
        return None
