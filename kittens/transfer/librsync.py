#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
from typing import Iterator

from .rsync import IO_BUFFER_SIZE, begin_signature, iter_job


def signature_of_file(path: str) -> Iterator[bytes]:
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        fsz = f.tell()
        job = begin_signature(fsz)
        f.seek(0)
        finished = False
        while not finished:
            input_data = f.read(IO_BUFFER_SIZE)
            output, finished = iter_job(job, input_data)
            yield output
