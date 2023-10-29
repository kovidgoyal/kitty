#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import io
import os
from enum import Enum, IntEnum
from gettext import gettext as _
from tempfile import TemporaryFile
from typing import IO, Callable, Dict, List, Mapping, NamedTuple, Optional, Tuple, Union

from .conf.utils import uniq
from .constants import supports_primary_selection
from .fast_data_types import (
    ESC_OSC,
    GLFW_CLIPBOARD,
    GLFW_PRIMARY_SELECTION,
    find_in_memoryview,
    get_boss,
    get_clipboard_mime,
    get_options,
    set_clipboard_data_types,
)
from .utils import log_error


class Tempfile:

    def __init__(self, max_size: int) -> None:
        self.file: Union[io.BytesIO, IO[bytes]] = io.BytesIO()
        self.max_size = max_size

    def rollover_if_needed(self, sz: int) -> None:
        if isinstance(self.file, io.BytesIO) and self.file.tell() + sz > self.max_size:
            before = self.file.getvalue()
            self.file = TemporaryFile()
            self.file.write(before)

    def write(self, data: bytes) -> None:
        self.rollover_if_needed(len(data))
        self.file.write(data)

    def tell(self) -> int:
        return self.file.tell()

    def seek(self, pos: int) -> None:
        self.file.seek(pos, os.SEEK_SET)

    def read(self, offset: int, size: int) -> bytes:
        self.file.seek(offset)
        return self.file.read(size)

    def create_chunker(self, offset: int, size: int) -> Callable[[], Callable[[], bytes]]:
        def chunk_creator() -> Callable[[], bytes]:
            pos = offset
            limit = offset + size

            def chunker() -> bytes:
                nonlocal pos, limit
                if pos >= limit:
                    return b''
                ans = self.read(pos, min(io.DEFAULT_BUFFER_SIZE, limit - pos))
                pos = self.file.tell()
                return ans
            return chunker
        return chunk_creator


DataType = Union[bytes, Callable[[], Callable[[], bytes]]]
TARGETS_MIME = '.'


class ClipboardType(IntEnum):
    clipboard = GLFW_CLIPBOARD
    primary_selection = GLFW_PRIMARY_SELECTION

    @staticmethod
    def from_osc52_where_field(where: str) -> 'ClipboardType':
        where = where or 's0'
        return ClipboardType.clipboard if 'c' in where or 's' in where else ClipboardType.primary_selection


class Clipboard:

    def __init__(self, clipboard_type: ClipboardType = ClipboardType.clipboard) -> None:
        self.data: Dict[str, DataType] = {}
        self.clipboard_type = clipboard_type
        self.enabled = self.clipboard_type is ClipboardType.clipboard or supports_primary_selection

    def set_text(self, x: Union[str, bytes]) -> None:
        if isinstance(x, str):
            x = x.encode('utf-8')
        self.set_mime({'text/plain': x})

    def set_mime(self, data: Mapping[str, DataType]) -> None:
        if self.enabled and isinstance(data, dict):
            self.data = data
            set_clipboard_data_types(self.clipboard_type, tuple(self.data))

    def get_text(self) -> str:
        parts: List[bytes] = []
        self.get_mime("text/plain", parts.append)
        return b''.join(parts).decode('utf-8', 'replace')

    def get_mime(self, mime: str, output: Callable[[bytes], None]) -> None:
        if self.enabled:
            try:
                get_clipboard_mime(self.clipboard_type, mime, output)
            except RuntimeError as err:
                if str(err) != 'is_self_offer':
                    raise
                data = self.data.get(mime, b'')
                if isinstance(data, bytes):
                    output(data)
                else:
                    chunker = data()
                    q = b' '
                    while q:
                        q = chunker()
                        output(q)

    def get_mime_data(self, mime: str) -> bytes:
        ans: List[bytes] = []
        self.get_mime(mime, ans.append)
        return b''.join(ans)

    def get_available_mime_types_for_paste(self) -> Tuple[str, ...]:
        if self.enabled:
            parts: List[bytes] = []
            try:
                get_clipboard_mime(self.clipboard_type, None, parts.append)
            except RuntimeError as err:
                if str(err) != 'is_self_offer':
                    raise
                return tuple(self.data)
            return tuple(x.decode('utf-8', 'replace') for x in uniq(parts))
        return ()

    def __call__(self, mime: str) -> Callable[[], bytes]:
        data = self.data.get(mime, b'')
        if isinstance(data, str):
            data = data.encode('utf-8')  # type: ignore
        if isinstance(data, bytes):
            def chunker() -> bytes:
                nonlocal data
                assert isinstance(data, bytes)
                ans = data
                data = b''
                return ans
            return chunker

        return data()


def set_clipboard_string(x: Union[str, bytes]) -> None:
    get_boss().clipboard.set_text(x)


def get_clipboard_string() -> str:
    return get_boss().clipboard.get_text()


def set_primary_selection(x: Union[str, bytes]) -> None:
    get_boss().primary_selection.set_text(x)


def get_primary_selection() -> str:
    return get_boss().primary_selection.get_text()


def develop() -> Tuple[Clipboard, Clipboard]:
    from .constants import detect_if_wayland_ok, is_macos
    from .fast_data_types import set_boss
    from .main import init_glfw_module
    glfw_module = 'cocoa' if is_macos else ('wayland' if detect_if_wayland_ok() else 'x11')

    class Boss:
        clipboard = Clipboard()
        primary_selection = Clipboard(ClipboardType.primary_selection)
    init_glfw_module(glfw_module)
    set_boss(Boss())  # type: ignore
    return Boss.clipboard, Boss.primary_selection


class ProtocolType(Enum):
    osc_52 = 52
    osc_5522 = 5522


def encode_mime(x: str) -> str:
    import base64
    return base64.standard_b64encode(x.encode('utf-8')).decode('ascii')


def decode_metadata_value(k: str, x: str) -> str:
    if k == 'mime':
        import base64
        x = base64.standard_b64decode(x).decode('utf-8')
    return x


class ReadRequest(NamedTuple):
    is_primary_selection: bool = False
    mime_types: Tuple[str, ...] = ('text/plain',)
    id: str = ''
    protocol_type: ProtocolType = ProtocolType.osc_52

    def encode_response(self, status: str = 'DATA', mime: str = '', payload: bytes = b'') -> bytes:
        ans = f'{self.protocol_type.value};type=read:status={status}'
        if status == 'OK' and self.is_primary_selection:
            ans += ':loc=primary'
        if self.id:
            ans += f':id={self.id}'
        if mime:
            ans += f':mime={encode_mime(mime)}'
        a = ans.encode('ascii')
        if payload:
            import base64
            a += b';' + base64.standard_b64encode(payload)
        return a


def encode_osc52(loc: str, response: str) -> str:
    from base64 import standard_b64encode
    return '52;{};{}'.format(
        loc, standard_b64encode(response.encode('utf-8')).decode('ascii'))


class MimePos(NamedTuple):
    start: int
    size: int


class WriteRequest:

    def __init__(
        self, is_primary_selection: bool = False, protocol_type: ProtocolType = ProtocolType.osc_52, id: str = '',
        rollover_size: int = 16 * 1024 * 1024, max_size: int = -1,
    ) -> None:
        self.id = id
        self.is_primary_selection = is_primary_selection
        self.protocol_type = protocol_type
        self.max_size_exceeded = False
        self.tempfile = Tempfile(max_size=rollover_size)
        self.mime_map: Dict[str, MimePos] = {}
        self.currently_writing_mime = ''
        self.current_leftover_bytes = memoryview(b'')
        self.max_size = (get_options().clipboard_max_size * 1024 * 1024) if max_size < 0 else max_size
        self.aliases: Dict[str, str] = {}
        self.committed = False

    def encode_response(self, status: str = 'OK') -> bytes:
        ans = f'{self.protocol_type.value};type=write:status={status}'
        if self.id:
            ans += f':id={self.id}'
        a = ans.encode('ascii')
        return a

    def commit(self) -> None:
        if self.committed:
            return
        self.committed = True
        cp = get_boss().primary_selection if self.is_primary_selection else get_boss().clipboard
        if cp.enabled:
            for alias, src in self.aliases.items():
                pos = self.mime_map.get(src)
                if pos is not None:
                    self.mime_map[alias] = pos
            x = {mime: self.tempfile.create_chunker(pos.start, pos.size) for mime, pos in self.mime_map.items()}
            cp.set_mime(x)

    def add_base64_data(self, data: Union[str, bytes], mime: str = 'text/plain') -> None:
        if isinstance(data, str):
            data = data.encode('ascii')
        if self.currently_writing_mime and self.currently_writing_mime != mime:
            self.flush_base64_data()
        if not self.currently_writing_mime:
            self.mime_map[mime] = MimePos(self.tempfile.tell(), -1)
            self.currently_writing_mime = mime

        def write_saving_leftover_bytes(data: bytes) -> None:
            if len(data) == 0:
                return
            extra = len(data) % 4
            if extra > 0:
                mv = memoryview(data)
                self.current_leftover_bytes = mv[-extra:]
                mv = mv[:-extra]
                if len(mv) > 0:
                    self.write_base64_data(mv)
            else:
                self.write_base64_data(data)

        if len(self.current_leftover_bytes) > 0:
            extra = 4 - len(self.current_leftover_bytes)
            if len(data) >= extra:
                self.write_base64_data(memoryview(bytes(self.current_leftover_bytes) + data[:extra]))
                self.current_leftover_bytes = memoryview(b'')
                data = memoryview(data)[extra:]
                write_saving_leftover_bytes(data)
            else:
                self.current_leftover_bytes = memoryview(bytes(self.current_leftover_bytes) + data)
        else:
            write_saving_leftover_bytes(data)

    def flush_base64_data(self) -> None:
        if self.currently_writing_mime:
            b = self.current_leftover_bytes
            padding = 4 - len(b)
            if padding in (1, 2):
                self.write_base64_data(memoryview(bytes(b) + b'=' * padding))
            start = self.mime_map[self.currently_writing_mime][0]
            self.mime_map[self.currently_writing_mime] = MimePos(start, self.tempfile.tell() - start)
            self.currently_writing_mime = ''
            self.current_leftover_bytes = memoryview(b'')

    def write_base64_data(self, b: bytes) -> None:
        from base64 import standard_b64decode
        if not self.max_size_exceeded:
            d = standard_b64decode(b)
            self.tempfile.write(d)
            if self.max_size > 0 and self.tempfile.tell() > (self.max_size * 1024 * 1024):
                log_error(f'Clipboard write request has more data than allowed by clipboard_max_size ({self.max_size}), truncating')
                self.max_size_exceeded = True

    def data_for(self, mime: str = 'text/plain', offset: int = 0, size: int = -1) -> bytes:
        start, full_size = self.mime_map[mime]
        if size == -1:
            size = full_size
        return self.tempfile.read(start+offset, size)


class ClipboardRequestManager:

    def __init__(self, window_id: int) -> None:
        self.window_id = window_id
        self.currently_asking_permission_for: Optional[ReadRequest] = None
        self.in_flight_write_request: Optional[WriteRequest] = None

    def parse_osc_5522(self, data: memoryview) -> None:
        import base64

        from .notify import sanitize_id
        idx = find_in_memoryview(data, ord(b';'))
        if idx > -1:
            metadata = str(data[:idx], "utf-8", "replace")
            epayload = data[idx+1:]
        else:
            metadata = str(data, "utf-8", "replace")
            epayload = data[len(data):]
        m: Dict[str, str] = {}
        for record in metadata.split(':'):
            try:
                k, v = record.split('=', 1)
            except Exception:
                log_error('Malformed OSC 5522: metadata is not key=value pairs')
                return
            m[k] = decode_metadata_value(k, v)
        typ = m.get('type', '')
        if typ == 'read':
            payload = base64.standard_b64decode(epayload)
            rr = ReadRequest(
                is_primary_selection=m.get('loc', '') == 'primary',
                mime_types=tuple(payload.decode('utf-8').split()),
                protocol_type=ProtocolType.osc_5522, id=sanitize_id(m.get('id', ''))
            )
            self.handle_read_request(rr)
        elif typ == 'write':
            self.in_flight_write_request = WriteRequest(
                is_primary_selection=m.get('loc', '') == 'primary',
                protocol_type=ProtocolType.osc_5522, id=sanitize_id(m.get('id', ''))
            )
            self.handle_write_request(self.in_flight_write_request)
        elif typ == 'walias':
            wr = self.in_flight_write_request
            mime = m.get('mime', '')
            if mime and wr is not None:
                aliases = base64.standard_b64decode(epayload).decode('utf-8').split()
                for alias in aliases:
                    wr.aliases[alias] = mime
        elif typ == 'wdata':
            wr = self.in_flight_write_request
            w = get_boss().window_id_map.get(self.window_id)
            if wr is None:
                return
            mime = m.get('mime', '')
            if mime:
                try:
                    wr.add_base64_data(epayload, mime)
                except OSError:
                    if w is not None:
                        w.screen.send_escape_code_to_child(ESC_OSC, wr.encode_response(status='EIO'))
                    self.in_flight_write_request = None
                    raise
                except Exception:
                    if w is not None:
                        w.screen.send_escape_code_to_child(ESC_OSC, wr.encode_response(status='EINVAL'))
                    self.in_flight_write_request = None
                    raise
            else:
                wr.flush_base64_data()
                wr.commit()
                self.in_flight_write_request = None
                if w is not None:
                    w.screen.send_escape_code_to_child(ESC_OSC, wr.encode_response(status='DONE'))

    def parse_osc_52(self, data: memoryview, is_partial: bool = False) -> None:
        idx = find_in_memoryview(data, ord(b';'))
        if idx > -1:
            where = str(data[idx:], "utf-8", 'replace')
            data = data[idx+1:]
        else:
            where = str(data, "utf-8", 'replace')
            data = data[len(data):]
        if len(data) == 1 and data.tobytes() == b'?':
            rr = ReadRequest(is_primary_selection=ClipboardType.from_osc52_where_field(where) is ClipboardType.primary_selection)
            self.handle_read_request(rr)
        else:
            wr = self.in_flight_write_request
            if wr is None:
                wr = self.in_flight_write_request = WriteRequest(ClipboardType.from_osc52_where_field(where) is ClipboardType.primary_selection)
            wr.add_base64_data(data)
            if is_partial:
                return
            self.in_flight_write_request = None
            self.handle_write_request(wr)

    def handle_write_request(self, wr: WriteRequest) -> None:
        wr.flush_base64_data()
        q = 'write-primary' if wr.is_primary_selection else 'write-clipboard'
        allowed = q in get_options().clipboard_control
        self.fulfill_write_request(wr, allowed)

    def fulfill_write_request(self, wr: WriteRequest, allowed: bool = True) -> None:
        if wr.protocol_type is ProtocolType.osc_52:
            self.fulfill_legacy_write_request(wr, allowed)
            return
        w = get_boss().window_id_map.get(self.window_id)
        cp = get_boss().primary_selection if wr.is_primary_selection else get_boss().clipboard
        if not allowed or not cp.enabled:
            self.in_flight_write_request = None
            if w is not None:
                w.screen.send_escape_code_to_child(ESC_OSC, wr.encode_response(status='EPERM' if not allowed else 'ENOSYS'))

    def fulfill_legacy_write_request(self, wr: WriteRequest, allowed: bool = True) -> None:
        cp = get_boss().primary_selection if wr.is_primary_selection else get_boss().clipboard
        w = get_boss().window_id_map.get(self.window_id)
        if w is not None and cp.enabled and allowed:
            wr.commit()

    def handle_read_request(self, rr: ReadRequest) -> None:
        cc = get_options().clipboard_control
        if rr.is_primary_selection:
            ask_for_permission = 'read-primary-ask' in cc
            allowed = 'read-primary' in cc
        else:
            ask_for_permission = 'read-clipboard-ask' in cc
            allowed = 'read-clipboard' in cc
        if ask_for_permission:
            self.ask_to_read_clipboard(rr)
        else:
            self.fulfill_read_request(rr, allowed=allowed)

    def fulfill_read_request(self, rr: ReadRequest, allowed: bool = True) -> None:
        if rr.protocol_type is ProtocolType.osc_52:
            return self.fulfill_legacy_read_request(rr, allowed)
        w = get_boss().window_id_map.get(self.window_id)
        if w is None:
            return
        cp = get_boss().primary_selection if rr.is_primary_selection else get_boss().clipboard
        if not cp.enabled:
            w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(status='ENOSYS'))
            return
        if not allowed:
            w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(status='EPERM'))
            return
        w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(status='OK'))

        current_mime = ''

        def write_chunks(data: bytes) -> None:
            assert w is not None
            mv = memoryview(data)
            while mv:
                w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(payload=mv[:4096], mime=current_mime))
                mv = mv[4096:]

        for mime in rr.mime_types:
            current_mime = mime
            if mime == TARGETS_MIME:
                payload = ' '.join(cp.get_available_mime_types_for_paste()).encode('utf-8')
                if payload:
                    payload += b'\n'
                w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(payload=payload, mime=current_mime))
                continue
            try:
                cp.get_mime(mime, write_chunks)
            except Exception as e:
                log_error(f'Failed to read requested mime type {mime} with error: {e}')
        w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(status='DONE'))

    def reject_read_request(self, rr: ReadRequest) -> None:
        if rr.protocol_type is ProtocolType.osc_52:
            return self.fulfill_legacy_read_request(rr, False)
        w = get_boss().window_id_map.get(self.window_id)
        if w is not None:
            w.screen.send_escape_code_to_child(ESC_OSC, rr.encode_response(status='EPERM'))

    def fulfill_legacy_read_request(self, rr: ReadRequest, allowed: bool = True) -> None:
        cp = get_boss().primary_selection if rr.is_primary_selection else get_boss().clipboard
        w = get_boss().window_id_map.get(self.window_id)
        if w is not None:
            text = ''
            if cp.enabled and allowed:
                text = cp.get_text()
            loc = 'p' if rr.is_primary_selection else 'c'
            w.screen.send_escape_code_to_child(ESC_OSC, encode_osc52(loc, text))

    def ask_to_read_clipboard(self, rr: ReadRequest) -> None:
        if rr.mime_types == (TARGETS_MIME,):
            self.fulfill_read_request(rr, True)
            return
        if self.currently_asking_permission_for is not None:
            self.reject_read_request(rr)
            return
        w = get_boss().window_id_map.get(self.window_id)
        if w is not None:
            self.currently_asking_permission_for = rr
            get_boss().confirm(_(
                'A program running in this window wants to read from the system clipboard.'
                ' Allow it to do so, once?'),
                self.handle_clipboard_confirmation, window=w,
            )

    def handle_clipboard_confirmation(self, confirmed: bool) -> None:
        rr = self.currently_asking_permission_for
        self.currently_asking_permission_for = None
        if rr is not None:
            self.fulfill_read_request(rr, confirmed)

    def close(self) -> None:
        if self.in_flight_write_request is not None:
            self.in_flight_write_request = None
