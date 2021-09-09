#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import stat
import sys
from contextlib import contextmanager
from enum import auto
from itertools import count
from typing import (
    Callable, Dict, Generator, Iterable, Iterator, List, Sequence, Tuple,
    Union, cast
)

from kitty.cli import parse_args
from kitty.cli_stub import TransferCLIOptions
from kitty.fast_data_types import FILE_TRANSFER_CODE
from kitty.file_transmission import (
    Action, Compression, FileTransmissionCommand, FileType, NameReprEnum,
    TransmissionType
)
from kitty.types import run_once

from ..tui.handler import Handler

_cwd = _home = ''


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
        self.file_size = stat_result.st_size
        self.file_hash = stat_result.st_dev, stat_result.st_ino
        self.remote_path = get_remote_path(self.local_path, remote_base)
        self.remote_path = self.remote_path.replace(os.sep, '/')
        self.file_id = hex(file_id)[2:]
        self.hard_link_target = ''
        self.symbolic_link_target = ''
        self.stat_result = stat_result
        self.file_type = file_type
        self.compression = Compression.zlib if self.file_size > 2048 else Compression.none
        self.remote_final_path = ''
        self.remote_initial_size = -1
        self.err_msg = ''

    def metadata_command(self) -> FileTransmissionCommand:
        return FileTransmissionCommand(
            action=Action.file, compression=self.compression, ftype=self.file_type,
            name=self.remote_path, permissions=self.permissions, mtime=self.mtime,
            file_id=self.file_id,
        )

    def data_commands(self) -> Iterator[FileTransmissionCommand]:
        if self.file_type is FileType.symlink:
            yield FileTransmissionCommand(action=Action.end_data, data=self.symbolic_link_target.encode('utf-8'), file_id=self.file_id)
        elif self.file_type is FileType.link:
            yield FileTransmissionCommand(action=Action.end_data, data=f'fid:{self.hard_link_target}'.encode('utf-8'), file_id=self.file_id)
        elif self.file_type is FileType.regular:
            compressor: Union[IdentityCompressor, ZlibCompressor] = ZlibCompressor() if self.compression is Compression.zlib else IdentityCompressor()
            with open(self.local_path, 'rb') as f:
                keep_going = True
                while keep_going:
                    data = f.read(4096)
                    keep_going = bool(data)
                    data = compressor.compress(data) if data else compressor.flush()
                    if data or not keep_going:
                        yield FileTransmissionCommand(action=Action.data if keep_going else Action.end_data, data=data, file_id=self.file_id)


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
    finished = auto()


class SendManager:

    def __init__(self, request_id: str, files: Tuple[File, ...]):
        self.files = files
        self.fid_map = {str(f.file_id): f for f in self.files}
        self.request_id = request_id
        self.state = SendState.waiting_for_permission
        self.all_done = False
        self.all_started = False

    def update_collective_statuses(self) -> None:
        found_not_started = found_not_done = False
        for f in self.files:
            if f.state is not FileState.finished:
                found_not_done = True
            if f.state is FileState.waiting_for_start:
                found_not_started = True
            if found_not_started and found_not_done:
                break
        self.all_done = not found_not_done
        self.all_started = not found_not_started

    def start_transfer(self) -> str:
        return FileTransmissionCommand(action=Action.send).serialize()

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
            file.state = FileState.finished
            if ftc.status != 'OK':
                file.err_msg = ftc.status
        self.update_collective_statuses()

    def on_file_transfer_response(self, ftc: FileTransmissionCommand) -> None:
        if ftc.action is Action.status:
            if ftc.file_id:
                self.on_file_status_update(ftc)
            else:
                self.status = SendState.permission_granted if ftc.status == 'OK' else SendState.permission_denied


class Send(Handler):
    use_alternate_screen = False

    def __init__(self, manager: SendManager):
        Handler.__init__(self)
        self.manager = manager

    def send_payload(self, payload: str) -> None:
        self.write(f'\x1b]{FILE_TRANSFER_CODE};id={self.manager.request_id};')
        self.write(payload)
        self.write(b'\x1b\\')

    def on_file_transfer_response(self, ftc: FileTransmissionCommand) -> None:
        if ftc.id != self.manager.request_id:
            return
        before = self.manager.state
        self.manager.on_file_transfer_response(ftc)
        if before == SendState.waiting_for_permission:
            if self.manager.status == SendState.permission_denied:
                self.cmd.styled('Permission denied for this transfer', fg='red')
                self.quit_loop(1)
            return

    def initialize(self) -> None:
        self.send_payload(self.manager.start_transfer())
        for payload in self.manager.send_file_metadata():
            self.send_payload(payload)

    def on_interrupt(self) -> None:
        self.cmd.styled('Interrupt requested, cancelling transfer, transferred files are in undefined state', fg='red')
        self.abort_transfer()

    def abort_transfer(self) -> None:
        self.send_payload(FileTransmissionCommand(action=Action.cancel).serialize())
        self.quit_loop(1)


def send_main(cli_opts: TransferCLIOptions, args: List[str]) -> None:
    print('Scanning files…')
    files = files_for_send(cli_opts, args)
    print(f'Found {len(files)} files and directories, requesting transfer permission…')


def parse_transfer_args(args: List[str]) -> Tuple[TransferCLIOptions, List[str]]:
    return parse_args(
        args[1:], option_text, '', 'Transfer files over the TTY device',
        'kitty transfer', result_class=TransferCLIOptions
    )


def main(args: List[str]) -> None:
    cli_opts, items = parse_transfer_args(args)
    if not items:
        raise SystemExit('Usage: kitty +kitten transfer file_or_directory ...')
    if cli_opts.direction == 'send':
        send_main(cli_opts, items)
        return


if __name__ == '__main__':
    main(sys.argv)
