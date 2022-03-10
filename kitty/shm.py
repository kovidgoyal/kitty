#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

# This is present in the python stdlib (version 3.7) in
# multiprocessing.shared_memory. However, it is crippled in various ways, most
# notably using extremely small filenames.

import mmap
import os
import secrets
import stat
from typing import Optional

from kitty.fast_data_types import SHM_NAME_MAX, shm_open, shm_unlink


def make_filename(prefix: str) -> str:
    "Create a random filename for the shared memory object."
    # number of random bytes to use for name. Use a largeish value
    # to make double unlink safe.
    safe_length = min(128, SHM_NAME_MAX)
    if not prefix.startswith('/'):
        # FreeBSD requires name to start with /
        prefix = '/' + prefix
    nbytes = (safe_length - len(prefix)) // 2
    name = prefix + secrets.token_hex(nbytes)
    return name


class SharedMemory:
    _buf: Optional[memoryview] = None
    _fd: int = -1

    def __init__(
            self, name: Optional[str] = None, create: bool = False, size: int = 0, readonly: bool = False,
            mode: int = stat.S_IREAD | stat.S_IWRITE,
            prefix: str = 'kitty-'
    ):
        if not size >= 0:
            raise ValueError("'size' must be a positive integer")
        if create:
            flags = os.O_CREAT | os.O_EXCL
            if size <= 0:
                raise ValueError("'size' must be > 0")
        else:
            flags = 0
        flags |= os.O_RDONLY if readonly else os.O_RDWR
        if name is None and not flags & os.O_EXCL:
            raise ValueError("'name' can only be None if create=True")

        if name is None:
            while True:
                name = make_filename(prefix)
                try:
                    self._fd = shm_open(name, flags, mode)
                except FileExistsError:
                    continue
                self._name = name
                break
        else:
            self._fd = shm_open(name, flags)
        self._name = name
        try:
            if create and size:
                os.ftruncate(self._fd, size)
            stats = os.fstat(self._fd)
            size = stats.st_size
            self._mmap = mmap.mmap(self._fd, size, access=mmap.ACCESS_READ if readonly else mmap.ACCESS_WRITE)
        except OSError:
            self.unlink()
            raise

        self.size = size
        self._buf = memoryview(self._mmap)

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass

    def __enter__(self) -> 'SharedMemory':
        return self

    def __exit__(self, *a: object) -> None:
        self.close()

    @property
    def name(self) -> str:
        return self._name

    def fileno(self) -> int:
        return self._fd

    @property
    def buf(self) -> memoryview:
        ans = self._buf
        if ans is None:
            raise RuntimeError('Cannot access the buffer of a closed shared memory object')
        return ans

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.name!r}, size={self.size})'

    def close(self) -> None:
        """Closes access to the shared memory from this instance but does
        not destroy the shared memory block."""
        if self._buf is not None:
            self._buf.release()
            self._buf = None
        if getattr(self, '_mmap', None) is not None:
            self._mmap.close()
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def unlink(self) -> None:
        """Requests that the underlying shared memory block be destroyed.

        In order to ensure proper cleanup of resources, unlink should be
        called once (and only once) across all processes which have access
        to the shared memory block."""
        if self._name:
            try:
                shm_unlink(self._name)
            except FileNotFoundError:
                pass
            self._name = ''
