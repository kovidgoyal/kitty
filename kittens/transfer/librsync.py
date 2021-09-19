#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import IO, TYPE_CHECKING, Iterator

from .rsync import (
    IO_BUFFER_SIZE, RsyncError, begin_create_delta, begin_create_signature,
    begin_load_signature, begin_patch, iter_job, build_hash_table
)

if TYPE_CHECKING:
    from .rsync import JobCapsule, SignatureCapsule


class StreamingJob:

    expected_input_size = IO_BUFFER_SIZE

    def __init__(self, job: 'JobCapsule', output_buf_size: int = IO_BUFFER_SIZE):
        self.job = job
        self.finished = False
        self.prev_unused_input = b''
        self.calls_with_no_data = 0
        self.output_buf = bytearray(output_buf_size)

    def __call__(self, input_data: bytes = b'') -> memoryview:
        if self.finished:
            if input_data:
                raise RsyncError('There was too much input data')
            return memoryview(self.output_buf)[:0]
        no_more_data = not input_data
        if no_more_data:
            self.calls_with_no_data += 1
        if self.prev_unused_input:
            input_data = self.prev_unused_input + input_data
            self.prev_unused_input = b''
        self.finished, sz_of_unused_input, output_size = iter_job(self.job, input_data, self.output_buf)
        if sz_of_unused_input > 0 and not self.finished:
            if no_more_data:
                raise RsyncError(f"{sz_of_unused_input} bytes of input data were not used")
            self.prev_unused_input = bytes(input_data[-sz_of_unused_input:])
        if self.finished:
            self.commit()
        elif self.calls_with_no_data > 3:
            raise RsyncError('There was not enough input data')
        return memoryview(self.output_buf)[:output_size]

    def commit(self) -> None:
        pass


def drive_job_on_file(f: IO[bytes], job: 'JobCapsule', input_buf_size: int = IO_BUFFER_SIZE, output_buf_size: int = IO_BUFFER_SIZE) -> Iterator[memoryview]:
    sj = StreamingJob(job, output_buf_size=output_buf_size)
    input_buf = bytearray(input_buf_size)
    while not sj.finished:
        sz = f.readinto(input_buf)  # type: ignore
        yield sj(memoryview(input_buf)[:sz])


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

    def __init__(self) -> None:
        job, self.signature = begin_load_signature()
        super().__init__(job, output_buf_size=0)

    def commit(self) -> None:
        build_hash_table(self.signature)


def delta_for_file(path: str, sig: 'SignatureCapsule') -> Iterator[memoryview]:
    job = begin_create_delta(sig)
    with open(path, 'rb') as f:
        # see whole.c in librsync source for size calculations
        yield from drive_job_on_file(f, job, input_buf_size=8 * IO_BUFFER_SIZE, output_buf_size=4 * IO_BUFFER_SIZE)


class PatchFile(StreamingJob):

    # see whole.c in librsync source for size calculations
    expected_input_size = IO_BUFFER_SIZE

    def __init__(self, src_path: str):
        self.src_file = open(src_path, 'rb')
        job = begin_patch(self.read_from_src)
        super().__init__(job, output_buf_size=4 * IO_BUFFER_SIZE)

    def read_from_src(self, b: memoryview, pos: int) -> int:
        self.src_file.seek(pos)
        return self.src_file.readinto(b)  # type: ignore

    def close(self) -> None:
        if not self.src_file.closed:
            self.src_file.close()
    commit = close
