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

    def __init__(self, job: 'JobCapsule', expecting_output: bool = True):
        self.job = job
        self.finished = False
        self.prev_unused_input = b''
        self.calls_with_no_data = 0
        self.expecting_output = expecting_output

    def __call__(self, input_data: bytes = b'') -> bytes:
        if self.finished:
            if input_data:
                raise RsyncError('There was too much input data')
            return b''
        no_more_data = not input_data
        if no_more_data:
            self.calls_with_no_data += 1
        if self.prev_unused_input:
            input_data = self.prev_unused_input + input_data
            self.prev_unused_input = b''
        output, self.finished, sz_of_unused_input = iter_job(self.job, input_data, no_more_data, self.expecting_output)
        if sz_of_unused_input > 0 and not self.finished:
            if no_more_data:
                raise RsyncError(f"{sz_of_unused_input} bytes of input data were not used")
            self.prev_unused_input = bytes(input_data[-sz_of_unused_input:])
        if self.finished:
            self.commit()
        elif self.calls_with_no_data > 3:
            raise RsyncError('There was not enough input data')
        return output

    def commit(self) -> None:
        pass


def drive_job_on_file(f: IO[bytes], job: 'JobCapsule') -> Iterator[bytes]:
    sj = StreamingJob(job)
    input_buf = bytearray(IO_BUFFER_SIZE)
    while not sj.finished:
        sz = f.readinto(input_buf)  # type: ignore
        yield sj(memoryview(input_buf)[:sz])


def signature_of_file(path: str) -> Iterator[bytes]:
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        fsz = f.tell()
        job = begin_create_signature(fsz)
        f.seek(0)
        yield from drive_job_on_file(f, job)


class LoadSignature(StreamingJob):

    def __init__(self) -> None:
        job, self.signature = begin_load_signature()
        super().__init__(job, expecting_output=False)

    def commit(self) -> None:
        build_hash_table(self.signature)


def delta_for_file(path: str, sig: 'SignatureCapsule') -> Iterator[bytes]:
    job = begin_create_delta(sig)
    with open(path, 'rb') as f:
        yield from drive_job_on_file(f, job)


class PatchFile(StreamingJob):

    def __init__(self, src_path: str):
        self.src_file = open(src_path, 'rb')
        job = begin_patch(self.read_from_src)
        super().__init__(job)

    def read_from_src(self, b: memoryview, pos: int) -> int:
        self.src_file.seek(pos)
        return self.src_file.readinto(b)  # type: ignore

    def close(self) -> None:
        if not self.src_file.closed:
            self.src_file.close()
    commit = close
