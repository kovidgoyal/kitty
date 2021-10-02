#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import tempfile
from typing import IO, TYPE_CHECKING, Iterator, Union

from .rsync import (
    IO_BUFFER_SIZE, RsyncError, begin_create_delta, begin_create_signature,
    begin_load_signature, begin_patch, build_hash_table, iter_job
)

if TYPE_CHECKING:
    from .rsync import JobCapsule, SignatureCapsule


class StreamingJob:

    expected_input_size = IO_BUFFER_SIZE

    def __init__(self, job: 'JobCapsule', output_buf_size: int = IO_BUFFER_SIZE):
        self.job = job
        self.finished = False
        self.calls_with_no_data = 0
        self.output_buf = bytearray(output_buf_size)
        self.uncomsumed_data = b''

    def __call__(self, input_data: Union[memoryview, bytes] = b'') -> Iterator[memoryview]:
        if self.finished:
            if input_data:
                raise RsyncError('There was too much input data')
            return memoryview(self.output_buf)[:0]
        if self.uncomsumed_data:
            input_data = self.uncomsumed_data + bytes(input_data)
            self.uncomsumed_data = b''
        while True:
            self.finished, sz_of_unused_input, output_size = iter_job(self.job, input_data, self.output_buf)
            if output_size:
                yield memoryview(self.output_buf)[:output_size]
            if self.finished:
                break
            if not sz_of_unused_input and len(input_data):
                break
            consumed_some_input = sz_of_unused_input < len(input_data)
            produced_some_output = output_size > 0
            if not consumed_some_input and not produced_some_output:
                break
            input_data = memoryview(input_data)[-sz_of_unused_input:]
        if sz_of_unused_input:
            self.uncomsumed_data = bytes(input_data[-sz_of_unused_input:])

    def get_remaining_output(self) -> Iterator[memoryview]:
        if not self.finished:
            yield from self()
        if not self.finished:
            raise RsyncError('Insufficient input data')
        if self.uncomsumed_data:
            raise RsyncError(f'{len(self.uncomsumed_data)} bytes if unconsumed input data')


def drive_job_on_file(f: IO[bytes], job: 'JobCapsule', input_buf_size: int = IO_BUFFER_SIZE, output_buf_size: int = IO_BUFFER_SIZE) -> Iterator[memoryview]:
    sj = StreamingJob(job, output_buf_size=output_buf_size)
    input_buf = bytearray(input_buf_size)
    while not sj.finished:
        sz = f.readinto(input_buf)  # type: ignore
        if not sz:
            del input_buf
            yield from sj.get_remaining_output()
            break
        yield from sj(memoryview(input_buf)[:sz])


def signature_of_file(path: str) -> Iterator[memoryview]:
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        fsz = f.tell()
        job, block_len, strong_len = begin_create_signature(fsz)
        strong_len = max(0, strong_len)
        f.seek(0)
        # see whole.c in librsync source for size calculations
        yield from drive_job_on_file(f, job, input_buf_size=4 * block_len, output_buf_size=12 + 4 * (4 + (strong_len or IO_BUFFER_SIZE)))


class LoadSignature(StreamingJob):

    # see whole.c in librsync source for size calculations
    expected_input_size = 16 * 1024
    autocommit = True

    def __init__(self) -> None:
        job, self.signature = begin_load_signature()
        super().__init__(job, output_buf_size=0)

    def add_chunk(self, chunk: bytes) -> None:
        for ignored in self(chunk):
            pass

    def commit(self) -> None:
        for ignored in self.get_remaining_output():
            pass
        build_hash_table(self.signature)


def delta_for_file(path: str, sig: 'SignatureCapsule') -> Iterator[memoryview]:
    job = begin_create_delta(sig)
    with open(path, 'rb') as f:
        # see whole.c in librsync source for size calculations
        yield from drive_job_on_file(f, job, input_buf_size=8 * IO_BUFFER_SIZE, output_buf_size=4 * IO_BUFFER_SIZE)


class PatchFile(StreamingJob):

    # see whole.c in librsync source for size calculations
    expected_input_size = IO_BUFFER_SIZE

    def __init__(self, src_path: str, output_path: str = ''):
        self.overwrite_src = not output_path
        self.src_file = open(src_path, 'rb')
        if self.overwrite_src:
            self.dest_file = tempfile.NamedTemporaryFile(mode='wb', dir=os.path.dirname(os.path.abspath(os.path.realpath(src_path))), delete=False)
        else:
            self.dest_file = open(output_path, 'wb')
        job = begin_patch(self.read_from_src)
        super().__init__(job, output_buf_size=4 * IO_BUFFER_SIZE)

    def read_from_src(self, b: memoryview, pos: int) -> int:
        self.src_file.seek(pos)
        return self.src_file.readinto(b)  # type: ignore

    def close(self) -> None:
        if not self.src_file.closed:
            self.get_remaining_output()
            self.src_file.close()
            count = 100
            while not self.finished:
                self()
                count -= 1
                if count == 0:
                    raise Exception('Patching file did not receive enough input')
            self.dest_file.close()
            if self.overwrite_src:
                os.replace(self.dest_file.name, self.src_file.name)

    def write(self, data: bytes) -> None:
        for output in self(data):
            self.dest_file.write(output)

    def __enter__(self) -> 'PatchFile':
        return self

    def __exit__(self, *a: object) -> None:
        self.close()


def develop() -> None:
    import sys
    src = sys.argv[-1]
    sig_loader = LoadSignature()
    with open(src + '.sig', 'wb') as f:
        for chunk in signature_of_file(src):
            sig_loader.add_chunk(chunk)
            f.write(chunk)
    sig_loader.commit()
    with open(src + '.delta', 'wb') as f, PatchFile(src, src + '.output') as patcher:
        for chunk in delta_for_file(src, sig_loader.signature):
            f.write(chunk)
            patcher.write(chunk)
