#!/usr/bin/env python
# License: GPLv3 Copyright: 2024, Kovid Goyal <kovid at kovidgoyal.net>

import os
import time
from collections.abc import Iterator
from contextlib import closing, suppress
from functools import partial

from .constants import cache_dir, kitten_exe
from .utils import lock_file, unlock_file


class ImageRenderCache:
    lock_file_name = '.lock'
    # Max time to wait for the image conversion process. This runs on the
    # main thread so it must not be allowed to block indefinitely.
    conversion_timeout: float = 30.0

    def __init__(self, subdirname: str = 'rgba', max_entries: int = 32, cache_path: str = ''):
        self.subdirname = subdirname
        self.cache_path = cache_path
        self.cache_dir = ''
        self.max_entries = max_entries

    def ensure_subdir(self) -> None:
        if not self.cache_dir:
            import stat

            x = os.path.abspath(os.path.join(self.cache_path or cache_dir(), self.subdirname))
            os.makedirs(x, mode=stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC, exist_ok=True)
            self.cache_dir = x

    def __enter__(self) -> None:
        self.ensure_subdir()
        self.lock_file = open(os.path.join(self.cache_dir, self.lock_file_name), 'wb')
        try:
            lock_file(self.lock_file)
        except Exception:
            self.lock_file.close()
            raise

    def __exit__(self, *a: object) -> None:
        with closing(self.lock_file):
            unlock_file(self.lock_file)

    def entries(self) -> 'Iterator[os.DirEntry[str]]':
        for x in os.scandir(self.cache_dir):
            if x.name != self.lock_file_name:
                yield x

    def prune_entries(self) -> None:
        entries = list(self.entries())
        if len(entries) <= self.max_entries:
            return

        def sort_key(e: 'os.DirEntry[str]') -> float:
            with suppress(OSError):
                st = e.stat()
                return st.st_mtime
            return 0.0

        entries.sort(key=sort_key, reverse=True)
        for e in entries[self.max_entries :]:
            with suppress(FileNotFoundError):
                os.remove(e.path)

    def touch(self, path: str) -> None:
        os.utime(path, follow_symlinks=False)

    def render_image(self, src_path: str, output_path: str) -> None:
        import stat
        import subprocess

        # Open with O_NONBLOCK so that opening a FIFO cannot block and then
        # ensure we are reading from a regular file, so that the converter
        # cannot be fed an infinite stream from things like /dev/zero
        src_fd = os.open(src_path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOCTTY', 0) | getattr(os, 'O_CLOEXEC', 0))
        try:
            if not stat.S_ISREG(os.fstat(src_fd).st_mode):
                raise ValueError(f'Cannot convert {src_path} to RGBA data as it is not a regular file')
            os.set_blocking(src_fd, True)
        except Exception:
            os.close(src_fd)
            raise
        try:
            with open(src_fd, 'rb') as src, open(output_path, 'wb', opener=partial(os.open, mode=stat.S_IREAD | stat.S_IWRITE)) as output:
                try:
                    cp = subprocess.run(
                        [kitten_exe(), '__convert_image__', 'RGBA'], stdin=src, stdout=output, stderr=subprocess.PIPE, timeout=self.conversion_timeout
                    )
                except subprocess.TimeoutExpired as e:
                    raise ValueError(f'Timed out converting {src_path} to RGBA data') from e
                if cp.returncode != 0:
                    raise ValueError(f'Failed to convert {src_path} to RGBA data with error: {cp.stderr.decode("utf-8", "replace")}')
                if output.seek(0, os.SEEK_END) < 8:
                    raise ValueError(f'Failed to convert {src_path} to RGBA data, no output written. stderr: {cp.stderr.decode("utf-8", "replace")}')
        except Exception:
            with suppress(Exception):
                os.unlink(output_path)
            raise

    def read_metadata(self, output_path: str) -> tuple[int, int, int]:
        with open(output_path, 'rb') as f:
            header = f.read(8)
            import struct

            width, height = struct.unpack('<II', header)
            f.seek(0)
            return width, height, os.dup(f.fileno())

    def render(self, src_path: str) -> str:
        import stat
        import struct
        from hashlib import sha256

        src_info = os.stat(src_path)
        if not stat.S_ISREG(src_info.st_mode):
            raise ValueError(f'Cannot render {src_path} as it is not a regular file')
        output_name = sha256(struct.pack('@qqqq', src_info.st_dev, src_info.st_ino, src_info.st_size, src_info.st_mtime_ns)).hexdigest()

        with self:
            output_path = os.path.join(self.cache_dir, output_name)
            with suppress(OSError):
                self.touch(output_path)
                return output_path
            self.render_image(src_path, output_path)
            self.prune_entries()
            return output_path

    def __call__(self, src: str) -> tuple[int, int, int]:
        return self.read_metadata(self.render(src))


class ImageRenderCacheForTesting(ImageRenderCache):
    def __init__(self, cache_path: str):
        super().__init__(max_entries=2, cache_path=cache_path)
        self.current_time = time.time_ns()
        self.num_of_renders = 0

    def render_image(self, src_path: str, output_path: str) -> None:
        super().render_image(src_path, output_path)
        self.touch(output_path)
        self.num_of_renders += 1

    def touch(self, path: str) -> None:
        self.current_time += 3 * int(1e9)
        os.utime(path, ns=(self.current_time, self.current_time))


default_image_render_cache = ImageRenderCache()
