#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
from collections.abc import Generator
from contextlib import contextmanager

_cwd = _home = ''


def abspath(path: str, use_home: bool = False) -> str:
    base = home_path() if use_home else (_cwd or os.getcwd())
    return os.path.normpath(os.path.join(base, path))


def home_path() -> str:
    return _home or os.path.expanduser('~')


def cwd_path() -> str:
    return _cwd or os.getcwd()


def expand_home(path: str) -> str:
    if path.startswith('~' + os.sep) or (os.altsep and path.startswith('~' + os.altsep)):
        return os.path.join(home_path(), path[2:].lstrip(os.sep + (os.altsep or '')))
    return path


@contextmanager
def set_paths(cwd: str = '', home: str = '') -> Generator[None, None, None]:
    global _cwd, _home
    orig = _cwd, _home
    try:
        _cwd, _home = cwd, home
        yield
    finally:
        _cwd, _home = orig


class IdentityCompressor:

    def compress(self, data: bytes | memoryview) -> bytes:
        return bytes(data)

    def flush(self) -> bytes:
        return b''


class ZlibCompressor:

    def __init__(self) -> None:
        import zlib
        self.c = zlib.compressobj()

    def compress(self, data: bytes | memoryview) -> bytes:
        return self.c.compress(data)

    def flush(self) -> bytes:
        return self.c.flush()
