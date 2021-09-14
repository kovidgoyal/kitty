#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import stat
import sys
from contextlib import contextmanager
from enum import auto
from itertools import count
from mimetypes import guess_type
from typing import (
    IO, Callable, Dict, Generator, Iterable, Iterator, List, Optional,
    Sequence, Tuple, Union, cast
)

from kitty.cli import parse_args
from kitty.cli_stub import TransferCLIOptions
from kitty.fast_data_types import FILE_TRANSFER_CODE
from kitty.file_transmission import (
    Action, Compression, FileTransmissionCommand, FileType, NameReprEnum,
    TransmissionType, encode_password
)
from kitty.types import run_once
from kitty.typing import KeyEventType

from ..tui.handler import Handler
from ..tui.loop import Loop, debug
from ..tui.operations import styled
from ..tui.utils import human_size

_cwd = _home = ''
debug


def should_be_compressed(path: str) -> bool:
    ext = path.rpartition(os.extsep)[-1].lower()
    if ext in ('zip', 'odt', 'odp', 'pptx', 'docx', 'gz', 'bz2', 'xz', 'svgz'):
        return False
    mt = guess_type(path)[0] or ''
    if mt:
        if mt.endswith('+zip'):
            return False
        if mt.startswith('image/') and mt not in ('image/svg+xml',):
            return False
        if mt.startswith('video/'):
            return False
    return True


def abspath(path: str) -> str:
    return os.path.normpath(os.path.join(_cwd or os.getcwd(), path))


def home_path() -> str:
    return _home or os.path.expanduser('~')


def expand_home(path: str) -> str:
    if path.startswith('~' + os.sep) or (os.altsep and path.startswith('~' + os.altsep)):
        return os.path.join(home_path(), path[2:].lstrip(os.sep + (os.altsep or '')))
    return path


@run_once
def short_uuid_func() -> Callable[[], str]:
    from kitty.short_uuid import ShortUUID, escape_code_safe_alphabet
    return ShortUUID(alphabet=''.join(set(escape_code_safe_alphabet) - {';'})).uuid4


def random_id() -> str:
    f = short_uuid_func()
    return cast(str, f())


@contextmanager
def set_paths(cwd: str = '', home: str = '') -> Generator[None, None, None]:
    global _cwd, _home
    orig = _cwd, _home
    try:
        _cwd, _home = cwd, home
        yield
    finally:
        _cwd, _home = orig


def option_text() -> str:
    return '''\
--direction -d
default=send
choices=send,receive
Whether to send or receive files.


--mode -m
default=normal
choices=mirror
How to interpret command line arguments. In :code:`mirror` mode all arguments
are assumed to be files on the sending computer and they are mirrored onto the
receiving computer. In :code:`normal` mode the last argument is assumed to be a
destination path on the receiving computer.


--permissions-password -p
The password to use to skip the transfer confirmation popup in kitty. Must match the
password set for the :opt:`file_transfer_password` option in kitty.conf. Note that
leading and trailing whitespace is removed from the password. A password starting with
., / or ~ characters is assumed to be a file name to read the password from. A value
of - means read the password from STDIN. A password that is purely a number less than 256
is assumed to be the number of a file descriptor from which to read the actual password.


--confirm-paths -c
type=bool-set
Before actually transferring files, show a mapping of local file names to remote file names
and ask for confirmation.
'''


class IdentityCompressor:

    def compress(self, data: bytes) -> bytes:
        return data

    def flush(self) -> bytes:
        return b''


class ZlibCompressor:

    def __init__(self) -> None:
        import zlib
        self.c = zlib.compressobj()

    def compress(self, data: bytes) -> bytes:
        return self.c.compress(data)

    def flush(self) -> bytes:
        return self.c.flush()


def get_remote_path(local_path: str, remote_base: str) -> str:
    if not remote_base:
        return local_path.replace(os.sep, '/')
    if remote_base.endswith('/'):
        return os.path.join(remote_base, os.path.basename(local_path))
    return remote_base


class FileState(NameReprEnum):
    waiting_for_start = auto()
    waiting_for_data = auto()
    transmitting = auto()
    finished = auto()
    acknowledged = auto()


class File:

    def __init__(
        self, local_path: str, expanded_local_path: str, file_id: int, stat_result: os.stat_result,
        remote_base: str, file_type: FileType, ttype: TransmissionType = TransmissionType.simple
    ) -> None:
        self.ttype = ttype
        self.state = FileState.waiting_for_start
        self.local_path = local_path
        self.expanded_local_path = expanded_local_path
        self.permissions = stat.S_IMODE(stat_result.st_mode)
        self.mtime = stat_result.st_mtime_ns
        self.file_size = self.bytes_to_transmit = stat_result.st_size
        self.file_hash = stat_result.st_dev, stat_result.st_ino
        self.remote_path = get_remote_path(self.local_path, remote_base)
        self.remote_path = self.remote_path.replace(os.sep, '/')
        self.file_id = hex(file_id)[2:]
        self.hard_link_target = ''
        self.symbolic_link_target = ''
        self.stat_result = stat_result
        self.file_type = file_type
        self.compression = Compression.zlib if (
            self.file_type is FileType.regular and self.file_size > 4096 and should_be_compressed(self.expanded_local_path)
        ) else Compression.none
        self.compression = Compression.zlib
        self.compressor: Union[ZlibCompressor, IdentityCompressor] = ZlibCompressor() if self.compression is Compression.zlib else IdentityCompressor()
        self.remote_final_path = ''
        self.remote_initial_size = -1
        self.err_msg = ''
        self.actual_file: Optional[IO[bytes]] = None
        self.transmitted_bytes = 0

    def next_chunk(self, sz: int = 1024 * 1024) -> Tuple[bytes, int]:
        if self.file_type is FileType.symlink:
            self.state = FileState.finished
            ans = self.symbolic_link_target.encode('utf-8')
            return ans, len(ans)
        if self.file_type is FileType.link:
            self.state = FileState.finished
            ans = self.hard_link_target.encode('utf-8')
            return ans, len(ans)
        if self.actual_file is None:
            self.actual_file = open(self.expanded_local_path, 'rb')
        chunk = self.actual_file.read(sz)
        uncompressed_sz = len(chunk)
        is_last = not chunk or self.actual_file.tell() >= self.file_size
        cchunk = self.compressor.compress(chunk)
        if is_last and not isinstance(self.compressor, IdentityCompressor):
            cchunk += self.compressor.flush()
        if is_last:
            self.state = FileState.finished
            self.actual_file.close()
            self.actual_file = None
        return cchunk, uncompressed_sz

    def metadata_command(self) -> FileTransmissionCommand:
        return FileTransmissionCommand(
            action=Action.file, compression=self.compression, ftype=self.file_type,
            name=self.remote_path, permissions=self.permissions, mtime=self.mtime,
            file_id=self.file_id,
        )


def process(cli_opts: TransferCLIOptions, paths: Iterable[str], remote_base: str) -> Iterator[File]:
    counter = count(1)
    for x in paths:
        expanded = expand_home(x)
        try:
            s = os.stat(expanded, follow_symlinks=False)
        except OSError as err:
            raise SystemExit(f'Failed to stat {x} with error: {err}') from err
        if stat.S_ISDIR(s.st_mode):
            yield File(x, expanded, next(counter), s, remote_base, FileType.directory)
            new_remote_base = remote_base
            if new_remote_base:
                new_remote_base = new_remote_base.rstrip('/') + '/' + os.path.basename(x) + '/'
            else:
                new_remote_base = x.replace(os.sep, '/').rstrip('/') + '/'
            yield from process(cli_opts, [os.path.join(x, y) for y in os.listdir(expanded)], new_remote_base)
        elif stat.S_ISLNK(s.st_mode):
            yield File(x, expanded, next(counter), s, remote_base, FileType.symlink)
        elif stat.S_ISREG(s.st_mode):
            yield File(x, expanded, next(counter), s, remote_base, FileType.regular)


def process_mirrored_files(cli_opts: TransferCLIOptions, args: Sequence[str]) -> Iterator[File]:
    paths = [abspath(x) for x in args]
    try:
        common_path = os.path.commonpath(paths)
    except ValueError:
        common_path = ''
    home = home_path().rstrip(os.sep)
    if common_path and common_path.startswith(home + os.sep):
        paths = [os.path.join('~', os.path.relpath(x, home)) for x in paths]
    yield from process(cli_opts, paths, '')


def process_normal_files(cli_opts: TransferCLIOptions, args: Sequence[str]) -> Iterator[File]:
    if len(args) < 2:
        raise SystemExit('Must specify at least one local path and one remote path')
    args = list(args)
    remote_base = args.pop().replace(os.sep, '/')
    if len(args) > 1 and not remote_base.endswith('/'):
        remote_base += '/'
    paths = [abspath(x) for x in args]
    yield from process(cli_opts, paths, remote_base)


def files_for_send(cli_opts: TransferCLIOptions, args: List[str]) -> Tuple[File, ...]:
    if cli_opts.mode == 'mirror':
        files = list(process_mirrored_files(cli_opts, args))
    else:
        files = list(process_normal_files(cli_opts, args))
    groups: Dict[Tuple[int, int], List[File]] = {}

    # detect hard links
    for f in files:
        groups.setdefault(f.file_hash, []).append(f)
    for group in groups.values():
        if len(group) > 1:
            for lf in group[1:]:
                lf.file_type = FileType.link
                lf.hard_link_target = group[0].file_id

    # detect symlinks to other transferred files
    for f in tuple(files):
        if f.file_type is FileType.symlink:
            try:
                link_dest = os.readlink(f.local_path)
            except OSError:
                files.remove(f)
                continue
            f.symbolic_link_target = f'path:{link_dest}'
            q = link_dest if os.path.isabs(link_dest) else os.path.join(os.path.dirname(f.local_path), link_dest)
            try:
                st = os.stat(q)
            except OSError:
                pass
            else:
                fh = st.st_dev, st.st_ino
                if fh in groups:
                    g = tuple(x for x in groups[fh] if os.path.samestat(st, x.stat_result))
                    if g:
                        t = g[0]
                        f.symbolic_link_target = f'fid:{t.file_id}'
    return tuple(files)


class SendState(NameReprEnum):
    waiting_for_permission = auto()
    permission_granted = auto()
    permission_denied = auto()
    canceled = auto()


class SendManager:

    def __init__(self, request_id: str, files: Tuple[File, ...], pw: Optional[str] = None):
        self.files = files
        self.password = encode_password(request_id, pw) if pw else ''
        self.fid_map = {f.file_id: f for f in self.files}
        self.request_id = request_id
        self.state = SendState.waiting_for_permission
        self.all_acknowledged = False
        self.all_started = False
        self.active_idx: Optional[int] = None
        self.current_chunk_uncompressed_sz: Optional[int] = None
        self.prefix = f'\x1b]{FILE_TRANSFER_CODE};id={self.request_id};'
        self.suffix = '\x1b\\'
        self.total_size_of_all_files = sum(df.file_size for df in self.files if df.file_size >= 0)

    @property
    def active_file(self) -> Optional[File]:
        if self.active_idx is not None:
            ans = self.files[self.active_idx]
            if ans.state is FileState.transmitting:
                return ans

    def activate_next_ready_file(self) -> Optional[File]:
        for i, f in enumerate(self.files):
            if f.state is FileState.transmitting:
                self.active_idx = i
                self.update_collective_statuses()
                return f
        self.active_idx = None
        self.update_collective_statuses()

    def update_collective_statuses(self) -> None:
        found_not_started = found_not_done = False
        for f in self.files:
            if f.state is not FileState.acknowledged:
                found_not_done = True
            if f.state is FileState.waiting_for_start:
                found_not_started = True
            if found_not_started and found_not_done:
                break
        self.all_acknowledged = not found_not_done
        self.all_started = not found_not_started

    def start_transfer(self) -> str:
        return FileTransmissionCommand(action=Action.send, password=self.password).serialize()

    def next_chunks(self) -> Iterator[str]:
        if self.active_file is None:
            self.activate_next_ready_file()
        af = self.active_file
        if af is None:
            return
        chunk = b''
        self.current_chunk_uncompressed_sz = 0
        while af.state is not FileState.finished and not chunk:
            chunk, usz = af.next_chunk()
            self.current_chunk_uncompressed_sz += usz
        is_last = af.state is FileState.finished
        if is_last:
            self.activate_next_ready_file()
        mv = memoryview(chunk)
        pos = 0
        limit = len(chunk)
        while pos < limit:
            cc = mv[pos:pos + 4096]
            pos += 4096
            final = is_last and pos >= limit
            yield FileTransmissionCommand(action=Action.end_data if final else Action.data, file_id=af.file_id, data=cc).serialize()

    def send_file_metadata(self) -> Iterator[str]:
        for f in self.files:
            yield f.metadata_command().serialize()

    def on_file_status_update(self, ftc: FileTransmissionCommand) -> None:
        file = self.fid_map.get(ftc.file_id)
        if file is None:
            return
        if ftc.status == 'STARTED':
            file.state = FileState.waiting_for_data if file.ttype is TransmissionType.rsync else FileState.transmitting
            file.remote_final_path = ftc.name
            file.remote_initial_size = ftc.size
        else:
            if ftc.name and not file.remote_final_path:
                file.remote_final_path = ftc.name
            file.state = FileState.acknowledged
            if ftc.status != 'OK':
                file.err_msg = ftc.status
            if file is self.active_file:
                self.active_idx = None
        self.update_collective_statuses()

    def on_file_transfer_response(self, ftc: FileTransmissionCommand) -> None:
        if ftc.action is Action.status:
            if ftc.file_id:
                self.on_file_status_update(ftc)
            else:
                self.state = SendState.permission_granted if ftc.status == 'OK' else SendState.permission_denied


class Send(Handler):
    use_alternate_screen = False

    def __init__(self, cli_opts: TransferCLIOptions, manager: SendManager):
        Handler.__init__(self)
        self.manager = manager
        self.cli_opts = cli_opts
        self.transmit_started = False
        self.file_metadata_sent = False
        self.quit_after_write_code: Optional[int] = None
        self.check_paths_printed = False

    def send_payload(self, payload: str) -> None:
        self.write(self.manager.prefix)
        self.write(payload)
        self.write(self.manager.suffix)

    def on_file_transfer_response(self, ftc: FileTransmissionCommand) -> None:
        if self.quit_after_write_code is not None:
            return
        if ftc.id != self.manager.request_id:
            return
        if ftc.status == 'CANCELED':
            self.quit_loop(1)
            return
        if self.manager.state is SendState.canceled:
            return
        before = self.manager.state
        self.manager.on_file_transfer_response(ftc)
        if before == SendState.waiting_for_permission:
            if self.manager.state == SendState.permission_denied:
                self.cmd.styled('Permission denied for this transfer', fg='red')
                self.print()
                self.quit_loop(1)
                return
            if self.manager.state == SendState.permission_granted:
                self.cmd.styled('Permission granted for this transfer', fg='green')
                self.print()
                self.send_file_metadata()
        self.loop_tick()

    def start_transfer(self) -> None:
        if self.manager.active_file is None:
            self.manager.activate_next_ready_file()
        if self.manager.active_file is not None:
            self.transmit_started = True
            self.transmit_next_chunk()

    def print_check_paths(self) -> None:
        if self.check_paths_printed:
            return
        self.check_paths_printed = True
        self.print('The following file transfers will be performed. A red destination means an existing file will be overwritten.')
        for df in self.manager.files:
            self.cmd.styled(df.file_type.short_text, fg=df.file_type.color)
            self.print(end=' ')
            self.print(df.local_path, '→', end=' ')
            self.cmd.styled(df.remote_final_path, fg='red' if df.remote_initial_size > -1 else None)
            self.print()
        self.print(f'Transferring {len(self.manager.files)} files of total size: {human_size(self.manager.total_size_of_all_files)}')
        self.print()
        self.print_continue_msg()

    def print_continue_msg(self) -> None:
        self.print(
            'Press', styled('y', fg='green', bold=True, fg_intense=True), 'to continue or',
            styled('n', fg='red', bold=True, fg_intense=True), 'to abort')

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        if self.quit_after_write_code is not None:
            return
        if self.check_paths_printed and not self.transmit_started:
            if text.lower() == 'y':
                self.start_transfer()
                return
            if text.lower() == 'n':
                self.abort_transfer()
                self.print('Sending cancel request to terminal')
                return
            self.print_continue_msg()

    def on_key(self, key_event: KeyEventType) -> None:
        if self.quit_after_write_code is not None:
            return
        if key_event.matches('esc'):
            if self.check_paths_printed and not self.transmit_started:
                self.abort_transfer()
                self.print('Sending cancel request to terminal')
            else:
                self.on_interrupt()

    def check_for_transmit_ok(self) -> None:
        if self.manager.state is not SendState.permission_granted:
            return
        if self.cli_opts.confirm_paths:
            if self.manager.all_started:
                self.print_check_paths()
            return
        self.start_transfer()

    def transmit_next_chunk(self) -> None:
        for chunk in self.manager.next_chunks():
            self.send_payload(chunk)
        else:
            if self.manager.all_acknowledged:
                self.transfer_finished()

    def transfer_finished(self) -> None:
        self.send_payload(FileTransmissionCommand(action=Action.finish).serialize())
        self.quit_after_write_code = 0

    def on_writing_finished(self) -> None:
        if self.manager.current_chunk_uncompressed_sz is not None:
            self.manager.current_chunk_uncompressed_sz = None
        if self.quit_after_write_code is not None:
            self.quit_loop(self.quit_after_write_code)
            return
        if self.manager.state is SendState.permission_granted:
            self.loop_tick()

    def loop_tick(self) -> None:
        if self.manager.state == SendState.waiting_for_permission:
            return
        if self.transmit_started:
            self.transmit_next_chunk()
        else:
            self.check_for_transmit_ok()

    def initialize(self) -> None:
        self.send_payload(self.manager.start_transfer())
        if self.cli_opts.permissions_password:
            # dont wait for permission, not needed with a password and
            # avoids a roundtrip
            self.send_file_metadata()
        self.cmd.set_cursor_visible(False)

    def finalize(self) -> None:
        self.cmd.set_cursor_visible(True)

    def send_file_metadata(self) -> None:
        if not self.file_metadata_sent:
            for payload in self.manager.send_file_metadata():
                self.send_payload(payload)
            self.file_metadata_sent = True

    def on_term(self) -> None:
        if self.quit_after_write_code is not None:
            return
        self.cmd.styled('Terminate requested, cancelling transfer, transferred files are in undefined state', fg='red')
        self.print()
        self.abort_transfer(delay=2)

    def on_interrupt(self) -> None:
        if self.quit_after_write_code is not None:
            return
        if self.manager.state is SendState.canceled:
            self.print('Waiting for canceled acknowledgement from terminal, will abort in a few seconds if no response received')
            return
        self.cmd.styled('Interrupt requested, cancelling transfer, transferred files are in undefined state', fg='red')
        self.print()
        self.abort_transfer()

    def abort_transfer(self, delay: float = 5) -> None:
        self.send_payload(FileTransmissionCommand(action=Action.cancel).serialize())
        self.manager.state = SendState.canceled
        self.asyncio_loop.call_later(delay, self.quit_loop, 1)


def send_main(cli_opts: TransferCLIOptions, args: List[str]) -> None:
    print('Scanning files…')
    files = files_for_send(cli_opts, args)
    print(f'Found {len(files)} files and directories, requesting transfer permission…')
    loop = Loop()
    handler = Send(cli_opts, SendManager(random_id(), files, cli_opts.permissions_password))
    loop.loop(handler)
    raise SystemExit(loop.return_code)


def parse_transfer_args(args: List[str]) -> Tuple[TransferCLIOptions, List[str]]:
    return parse_args(
        args[1:], option_text, '', 'Transfer files over the TTY device',
        'kitty transfer', result_class=TransferCLIOptions
    )


def read_password(loc: str) -> str:
    if not loc:
        return ''
    if loc.isdigit() and int(loc) >= 0 and int(loc) < 256:
        with open(int(loc), 'rb') as f:
            return f.read().decode('utf-8')
    if loc[0] in ('.', '~', '/'):
        if loc[0] == '~':
            loc = os.path.expanduser(loc)
        with open(loc, 'rb') as f:
            return f.read().decode('utf-8')
    if loc == '-':
        return sys.stdin.read()
    return loc


def main(args: List[str]) -> None:
    cli_opts, items = parse_transfer_args(args)
    if cli_opts.permissions_password:
        cli_opts.permissions_password = read_password(cli_opts.permissions_password).strip()

    if not items:
        raise SystemExit('Usage: kitty +kitten transfer file_or_directory ...')
    if cli_opts.direction == 'send':
        send_main(cli_opts, items)
        return


if __name__ == '__main__':
    main(sys.argv)
