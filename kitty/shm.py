#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

# This is present in the python stdlib (version 3.7) in
# multiprocessing.shared_memory. However, it is crippled in various ways, most
# notably using extremely small filenames.

import errno
import mmap
import os
import secrets
import stat
import struct

from kitty.fast_data_types import SHM_NAME_MAX, shm_open, shm_unlink


def make_filename(prefix: str) -> str:
    "Create a random filename for the shared memory object."
    # number of random bytes to use for name. Use a largeish value
    # to make double unlink safe.
    if not prefix.startswith('/'):
        # FreeBSD requires name to start with /
        prefix = '/' + prefix
    plen = len(prefix.encode('utf-8'))
    safe_length = min(plen + 64, SHM_NAME_MAX)
    if safe_length - plen < 2:
        raise OSError(errno.ENAMETOOLONG, f'SHM filename prefix {prefix} is too long')
    nbytes = (safe_length - plen) // 2
    name = prefix + secrets.token_hex(nbytes)
    return name


class SharedMemory:
    '''
    Create or access randomly named shared memory. To create call with empty name and specific size.
    To access call with name only.

    WARNING: The actual size of the shared memory may be larger than the requested size.
    '''
    _fd: int = -1
    _name: str = ''
    _mmap: mmap.mmap | None = None
    _size: int = 0
    size_fmt = '!I'
    num_bytes_for_size = struct.calcsize(size_fmt)

    def __init__(
        self, name: str = '', size: int = 0, readonly: bool = False,
        mode: int = stat.S_IREAD | stat.S_IWRITE,
        prefix: str = 'kitty-',
        unlink_on_exit: bool = False, ignore_close_failure: bool = False
    ):
        self.unlink_on_exit = unlink_on_exit
        self.ignore_close_failure = ignore_close_failure
        if size < 0:
            raise TypeError("'size' must be a non-negative integer")
        if size and name:
            raise TypeError('Cannot specify both name and size')
        if not name:
            flags = os.O_CREAT | os.O_EXCL
            if not size:
                raise TypeError("'size' must be > 0")
        else:
            flags = 0
        flags |= os.O_RDONLY if readonly else os.O_RDWR

        tries = 30
        while not name and tries > 0:
            tries -= 1
            q = make_filename(prefix)
            try:
                self._fd = shm_open(q, flags, mode)
                name = q
            except FileExistsError:
                continue
        if tries <= 0:
            raise OSError(f'Failed to create a uniquely named SHM file, try shortening the prefix from: {prefix}')
        if self._fd < 0:
            self._fd = shm_open(name, flags, mode)
        self._name = name
        try:
            if flags & os.O_CREAT and size:
                if hasattr(os, 'posix_fallocate'):
                    os.posix_fallocate(self._fd, 0, size)
                else:
                    os.ftruncate(self._fd, size)
            self.stats = os.fstat(self._fd)
            size = self.stats.st_size
            self._mmap = mmap.mmap(self._fd, size, access=mmap.ACCESS_READ if readonly else mmap.ACCESS_WRITE)
        except OSError:
            self.unlink()
            raise

        self._size = size

    def read(self, sz: int = 0) -> bytes:
        if sz <= 0:
            sz = self.size
        return self.mmap.read(sz)

    def write(self, data: bytes) -> None:
        self.mmap.write(data)

    def tell(self) -> int:
        return self.mmap.tell()

    def seek(self, pos: int, whence: int = os.SEEK_SET) -> None:
        self.mmap.seek(pos, whence)

    def flush(self) -> None:
        self.mmap.flush()

    def write_data_with_size(self, data: str | bytes) -> None:
        if isinstance(data, str):
            data = data.encode('utf-8')
        sz = struct.pack(self.size_fmt, len(data))
        self.write(sz)
        self.write(data)

    def read_data_with_size(self) -> bytes:
        sz = struct.unpack(self.size_fmt, self.read(self.num_bytes_for_size))[0]
        return self.read(sz)

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass

    def __enter__(self) -> 'SharedMemory':
        return self

    def __exit__(self, *a: object) -> None:
        self.close()
        if self.unlink_on_exit:
            self.unlink()

    @property
    def size(self) -> int:
        return self._size

    @property
    def name(self) -> str:
        return self._name

    @property
    def mmap(self) -> mmap.mmap:
        ans = self._mmap
        if ans is None:
            raise RuntimeError('Cannot access the mmap of a closed shared memory object')
        return ans

    def fileno(self) -> int:
        return self._fd

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.name!r}, size={self.size})'

    def close(self) -> None:
        """Closes access to the shared memory from this instance but does
        not destroy the shared memory block."""
        if self._mmap is not None:
            try:
                self._mmap.close()
            except BufferError:
                if not self.ignore_close_failure:
                    raise
            self._mmap = None
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
