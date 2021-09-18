#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import IO, Generator, Iterator, Optional

from .rsync import (
    IO_BUFFER_SIZE, JobCapsule, RsyncError, SignatureCapsule,
    begin_create_delta, begin_create_signature, begin_load_signature, iter_job,
    make_hash_table
)


def drive_job_on_file(f: IO[bytes], job: JobCapsule) -> Iterator[bytes]:
    finished = False
    prev_unused_input = b''
    while not finished:
        input_data = f.read(IO_BUFFER_SIZE)
        no_more_data = not input_data
        if prev_unused_input:
            input_data = prev_unused_input + input_data
            prev_unused_input = b''
        output, finished, sz_of_unused_input = iter_job(job, input_data, no_more_data)
        if sz_of_unused_input > 0 and not finished:
            if no_more_data:
                raise RsyncError(f"{sz_of_unused_input} bytes of input data were not used")
            prev_unused_input = input_data[-sz_of_unused_input:]
        yield output


def signature_of_file(path: str) -> Iterator[bytes]:
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        fsz = f.tell()
        job = begin_create_signature(fsz)
        f.seek(0)
        yield from drive_job_on_file(f, job)


def load_signature() -> Generator[Optional[SignatureCapsule], bytes, None]:
    job, signature = begin_load_signature()
    finished = False
    prev_unused_input = b''
    while not finished:
        input_data = yield None
        no_more_data = not input_data
        if prev_unused_input:
            input_data = prev_unused_input + input_data
            prev_unused_input = b''
        output, finished, sz_of_unused_input = iter_job(job, input_data, no_more_data, False)
        if sz_of_unused_input > 0 and not finished:
            if no_more_data:
                raise RsyncError(f"{sz_of_unused_input} bytes of input data were not used")
            prev_unused_input = input_data[-sz_of_unused_input:]
    make_hash_table(signature)
    yield signature


def delta_for_file(path: str, sig: SignatureCapsule) -> Iterator[bytes]:
    job = begin_create_delta(sig)
    with open(path, 'rb') as f:
        yield from drive_job_on_file(f, job)
