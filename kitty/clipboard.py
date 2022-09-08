#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import io
from typing import IO, Callable, Dict, List, Tuple, Union

from .conf.utils import uniq
from .constants import supports_primary_selection
from .fast_data_types import (
    GLFW_CLIPBOARD, get_boss, get_clipboard_mime, set_clipboard_data_types
)

DataType = Union[bytes, 'IO[bytes]']


class Clipboard:

    def __init__(self, clipboard_type: int = GLFW_CLIPBOARD) -> None:
        self.data: Dict[str, DataType] = {}
        self.clipboard_type = clipboard_type
        self.enabled = self.clipboard_type == GLFW_CLIPBOARD or supports_primary_selection

    def set_text(self, x: Union[str, bytes]) -> None:
        if self.enabled:
            self.data.clear()
            if isinstance(x, str):
                x = x.encode('utf-8')
            self.data['text/plain'] = x
            set_clipboard_data_types(self.clipboard_type, tuple(self.data))

    def get_text(self) -> str:
        parts: List[bytes] = []
        self.get_mime("text/plain", parts.append)
        return b''.join(parts).decode('utf-8', 'replace')

    def get_mime(self, mime: str, output: Callable[[bytes], None]) -> None:
        if self.enabled:
            get_clipboard_mime(self.clipboard_type, mime, output)

    def get_available_mime_types_for_paste(self) -> Tuple[str, ...]:
        if self.enabled:
            parts: List[bytes] = []
            get_clipboard_mime(self.clipboard_type, None, parts.append)
            return tuple(x.decode('utf-8', 'replace') for x in uniq(parts))
        return ()

    def __call__(self, mime: str) -> Callable[[], bytes]:
        data = self.data.get(mime, b'')
        if isinstance(data, bytes):
            def chunker() -> bytes:
                nonlocal data
                assert isinstance(data, bytes)
                ans = data
                data = b''
                return ans
            return chunker

        data.seek(0, 0)

        def io_chunker() -> bytes:
            assert not isinstance(data, bytes)
            return data.read(io.DEFAULT_BUFFER_SIZE)
        return io_chunker


def set_clipboard_string(x: Union[str, bytes]) -> None:
    get_boss().clipboard.set_text(x)


def get_clipboard_string() -> str:
    return get_boss().clipboard.get_text()


def set_primary_selection(x: Union[str, bytes]) -> None:
    get_boss().primary_selection.set_text(x)


def get_primary_selection() -> str:
    return get_boss().primary_selection.get_text()
