#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import re
from base64 import standard_b64decode
from contextlib import contextmanager

from kitty.fast_data_types import (
    DND_CODE,
    Screen,
    dnd_set_test_write_func,
    dnd_test_cleanup_fake_window,
    dnd_test_create_fake_window,
    dnd_test_fake_drop_data,
    dnd_test_fake_drop_event,
    dnd_test_set_mouse_pos,
)

from . import BaseTest, parse_bytes

# ---- helpers ----------------------------------------------------------------

def _osc(payload: str) -> bytes:
    """Wrap *payload* in an OSC escape sequence (OSC payload ST)."""
    return f'\x1b]{payload}\x1b\\'.encode()


def client_register(mimes: str = '', client_id: int = 0) -> bytes:
    """Escape code a client sends to start accepting drops (t=a)."""
    meta = f'{DND_CODE};t=a'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};{mimes}')


def client_unregister(client_id: int = 0) -> bytes:
    """Escape code a client sends to stop accepting drops (t=A)."""
    meta = f'{DND_CODE};t=A'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_accept(operation: int, mimes: str = '', client_id: int = 0) -> bytes:
    """Escape code a client sends to signal acceptance of the current drop (t=m:o=…)."""
    meta = f'{DND_CODE};t=m:o={operation}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};{mimes}')


def client_request_data(mime: str = '', client_id: int = 0) -> bytes:
    """Escape code a client sends to request data (t=r) or finish the drop (t=r with no MIME)."""
    meta = f'{DND_CODE};t=r'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};{mime}')


def client_request_uri_data(idx: int, client_id: int = 0) -> bytes:
    """Escape code a client sends to request a file from the URI list (t=s ; text/uri-list:idx)."""
    meta = f'{DND_CODE};t=s'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};text/uri-list:{idx}')


def client_dir_read(handle_id: int, entry_num: int | None = None, client_id: int = 0) -> bytes:
    """Escape code for a directory request (t=d:x=handle_id[:y=entry_num]).

    * entry_num=None → close the directory handle.
    * entry_num>=1   → read that entry (1-based).
    """
    meta = f'{DND_CODE};t=d:x={handle_id}'
    if entry_num is not None:
        meta += f':y={entry_num}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


# ---- escape-code decoder used by assertions ---------------------------------

_OSC_RE = re.compile(
    rb'\x1b\]' + re.escape(str(DND_CODE).encode()) + rb';([^;\x1b]*?)(?:;([^\x1b]*))?\x1b\\',
)


def _decode_meta(raw: bytes) -> dict:
    """Parse the colon-separated metadata portion of a DnD escape code."""
    ans: dict = {}
    for kv in raw.split(b':'):
        if b'=' in kv:
            k, _, v = kv.partition(b'=')
            ans[k.decode()] = v.decode()
        elif kv:
            ans[kv.decode()] = ''
    return ans


def parse_escape_codes(data: bytes) -> list[dict]:
    """Decode all DnD escape codes present in *data*.

    Each returned dict has keys:
      * ``type``    – the 't' value (single character string)
      * ``meta``    – full parsed metadata dict (from the first chunk)
      * ``payload`` – concatenated raw payload bytes from all chunks
      * ``chunks``  – list of individual raw chunk payloads (bytes)
    Chunked sequences (m=1 … m=0) are assembled into a single entry.
    """
    results: list[dict] = []
    pending: dict | None = None

    for m in _OSC_RE.finditer(data):
        meta_raw = m.group(1)
        payload_raw: bytes = m.group(2) if m.group(2) is not None else b''
        meta = _decode_meta(meta_raw)
        more = meta.get('m', '0') == '1'
        t = meta.get('t', 'a')

        if pending is None:
            pending = {'type': t, 'meta': meta, 'chunks': [], 'payload': b''}

        pending['chunks'].append(payload_raw)
        pending['payload'] += payload_raw

        if not more:
            results.append(pending)
            pending = None

    if pending is not None:
        results.append(pending)
    return results


def parse_escape_codes_b64(data: bytes) -> list[dict]:
    """Like *parse_escape_codes* but base64-decodes each chunk's payload."""
    result = parse_escape_codes(data)
    for entry in result:
        decoded_chunks = []
        full = b''
        for chunk in entry['chunks']:
            dec = standard_b64decode(chunk + b'==') if chunk else b''
            decoded_chunks.append(dec)
            full += dec
        entry['chunks'] = decoded_chunks
        entry['payload'] = full
    return result


# ---- test context manager ---------------------------------------------------

class _WriteCapture:
    """Accumulates bytes delivered by the DnD write interceptor."""

    def __init__(self) -> None:
        self._buf: dict[int, bytearray] = {}

    def __call__(self, window_id: int, data: bytes) -> None:
        self._buf.setdefault(window_id, bytearray())
        self._buf[window_id] += data

    def consume(self, window_id: int) -> bytes:
        """Return and clear all buffered data for *window_id*."""
        buf = self._buf.pop(window_id, bytearray())
        return bytes(buf)

    def peek(self, window_id: int) -> bytes:
        return bytes(self._buf.get(window_id, bytearray()))


@contextmanager
def dnd_test_window():
    """Context manager that creates a fake window + write-capture harness.

    Yields (os_window_id, window_id, screen, capture) where:
    * ``os_window_id`` – OS-level window ID
    * ``window_id``    – kitty window ID (pass to the fake-event helpers)
    * ``screen``       – Screen object whose window_id matches the fake window
    * ``capture``      – _WriteCapture accumulating bytes sent to the child
    """
    capture = _WriteCapture()
    dnd_set_test_write_func(capture)
    os_window_id, window_id = dnd_test_create_fake_window()
    try:
        screen = Screen(None, 24, 80, 0, 0, 0, window_id)
        yield os_window_id, window_id, screen, capture
    finally:
        dnd_set_test_write_func(None)
        dnd_test_cleanup_fake_window(os_window_id)


# ---- test class -------------------------------------------------------------

class TestDnDProtocol(BaseTest):

    def _assert_no_output(self, capture: _WriteCapture, window_id: int) -> None:
        self.ae(capture.peek(window_id), b'', 'unexpected output to child')

    def _get_events(self, capture: _WriteCapture, window_id: int) -> list[dict]:
        return parse_escape_codes(capture.consume(window_id))

    def test_register_and_unregister(self) -> None:
        """Client can register and unregister for drops."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # Client registers – state is already wanted=True from fake-window creation,
            # but calling the escape code should not break things.
            parse_bytes(screen, client_register('text/plain text/uri-list'))
            # No output expected at this point (no drop in progress).
            self._assert_no_output(cap, wid)

            # Client unregisters.
            parse_bytes(screen, client_unregister())
            self._assert_no_output(cap, wid)

    def test_drop_move_sends_move_event(self) -> None:
        """A drop entering and moving over the window generates t=m events."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 5, 3, 100, 60)
            dnd_test_fake_drop_event(wid, False, ['text/plain', 'text/uri-list'])

            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            ev = events[0]
            self.ae(ev['type'], 'm')
            self.ae(ev['meta'].get('x'), '5')
            self.ae(ev['meta'].get('y'), '3')
            self.ae(ev['meta'].get('X'), '100')
            self.ae(ev['meta'].get('Y'), '60')
            # MIME list should be present in the payload
            self.assertIn(b'text/plain', ev['payload'])
            self.assertIn(b'text/uri-list', ev['payload'])

    def test_drop_move_mime_always_sent(self) -> None:
        """The current implementation always includes the MIME list in move events."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            mimes = ['text/plain']
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, False, mimes)
            cap.consume(wid)  # discard first event

            # Second move with same mimes – list is still included.
            dnd_test_set_mouse_pos(wid, 1, 0, 8, 0)
            dnd_test_fake_drop_event(wid, False, mimes)
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            self.assertEqual(len(events), 1, raw)
            self.ae(events[0]['type'], 'm')
            self.assertIn(b'text/plain', events[0]['payload'])

    def test_drop_leave_sends_leave_event(self) -> None:
        """Drop leaving sends t=m with x=-1,y=-1."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, False, ['text/plain'])
            cap.consume(wid)

            dnd_test_fake_drop_event(wid, False, None)  # None → leave
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            ev = events[0]
            self.ae(ev['type'], 'm')
            self.ae(ev['meta'].get('x'), '-1')
            self.ae(ev['meta'].get('y'), '-1')

    def test_client_accepts_drop(self) -> None:
        """Client sending t=m:o=1 is recorded and does not trigger extra output."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, False, ['text/plain'])
            cap.consume(wid)

            # Client accepts with copy operation.
            parse_bytes(screen, client_accept(1, 'text/plain'))
            # No immediate output expected.
            self._assert_no_output(cap, wid)

    def test_full_drop_flow(self) -> None:
        """Complete happy-path: move → accept → drop → request → data → finish."""
        payload_data = b'hello world'
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))

            # Move
            dnd_test_set_mouse_pos(wid, 2, 3, 16, 24)
            dnd_test_fake_drop_event(wid, False, ['text/plain'])
            cap.consume(wid)

            # Client accepts
            parse_bytes(screen, client_accept(1, 'text/plain'))

            # OS drops
            dnd_test_set_mouse_pos(wid, 2, 3, 16, 24)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'M')
            self.assertIn(b'text/plain', events[0]['payload'])

            # Client requests data
            parse_bytes(screen, client_request_data('text/plain'))

            # OS delivers data
            dnd_test_fake_drop_data(wid, 'text/plain', payload_data)
            raw = cap.consume(wid)
            data_events = parse_escape_codes_b64(raw)
            # Should have data chunks plus an empty terminator
            self.assertTrue(len(data_events) >= 1, data_events)
            combined = b''.join(e['payload'] for e in data_events if e['type'] == 'r')
            self.ae(combined, payload_data)

            # Client finishes
            parse_bytes(screen, client_request_data(''))
            self._assert_no_output(cap, wid)

    def test_request_unknown_mime(self) -> None:
        """Requesting a MIME type not in the offered set yields an error."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # Client requests a MIME that was not offered.
            parse_bytes(screen, client_request_data('image/png'))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_data_error_propagation(self) -> None:
        """When data retrieval fails the client receives a t=R error code."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain'))

            # Simulate I/O error (EIO = 5 on Linux)
            dnd_test_fake_drop_data(wid, 'text/plain', b'', errno.EIO)
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EIO')

    def test_data_eperm_error(self) -> None:
        """EPERM error is correctly forwarded to the client."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain'))
            dnd_test_fake_drop_data(wid, 'text/plain', b'', errno.EPERM)
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EPERM')

    def test_large_data_chunking(self) -> None:
        """Data larger than the chunk limit is sent in multiple base64 chunks."""
        # Each chunk is ≤ 3072 bytes of raw data (base64-encoded to ≤ 4096 bytes).
        chunk_limit = 3072
        big_payload = b'X' * (chunk_limit * 3)  # 3 chunks expected
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain'))
            dnd_test_fake_drop_data(wid, 'text/plain', big_payload)
            raw = cap.consume(wid)
            data_events = parse_escape_codes_b64(raw)
            combined = b''.join(e['payload'] for e in data_events if e['type'] == 'r')
            self.ae(combined, big_payload)
            # Verify that we got more than one escape code (chunking happened)
            self.assertGreater(len(data_events), 1, 'expected multiple chunks')

    def test_client_id_propagated(self) -> None:
        """The client_id (i=…) set during registration is echoed in all replies."""
        client_id = 42
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain', client_id=client_id))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, False, ['text/plain'])
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            self.assertEqual(len(events), 1, raw)
            self.ae(events[0]['meta'].get('i'), str(client_id))

    def test_multiple_mimes_priority(self) -> None:
        """The client can specify a preferred MIME ordering."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain text/uri-list'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            # OS offers both types.
            dnd_test_fake_drop_event(wid, True, ['text/plain', 'text/uri-list'])
            cap.consume(wid)

            # Request text/uri-list first (different from registration order).
            parse_bytes(screen, client_request_data('text/uri-list'))
            dnd_test_fake_drop_data(wid, 'text/uri-list', b'file:///tmp/test\n')
            raw = cap.consume(wid)
            data_events = parse_escape_codes_b64(raw)
            combined = b''.join(e['payload'] for e in data_events if e['type'] == 'r')
            self.ae(combined, b'file:///tmp/test\n')

    def test_drop_without_register_no_output(self) -> None:
        """If the client has not registered, no escape codes are sent on drop."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # Explicitly unregister (clears the wanted flag).
            parse_bytes(screen, client_unregister())
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            # Fake window is created with wanted=True; after unregister it should be False.
            # drop_move_on_child only sends if w->drop.wanted is true, which is handled
            # by the caller (on_drop in glfw.c checks w->drop.wanted before calling).
            # Here we call drop_left_child which checks w->drop.wanted.
            dnd_test_fake_drop_event(wid, False, None)
            self._assert_no_output(cap, wid)

    def test_malformed_dnd_command_invalid_type(self) -> None:
        """A DnD command with an unknown type character is silently ignored."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # 'z' is not a valid type; the parser should emit an error and return
            # without calling any handler – no crash, no output.
            bad_cmd = _osc(f'{DND_CODE};t=z;')
            parse_bytes(screen, bad_cmd)
            self._assert_no_output(cap, wid)

    def test_move_event_after_mime_change(self) -> None:
        """When offered MIME list changes, the new list is included in the move event."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, False, ['text/plain'])
            cap.consume(wid)

            # Second move with a different MIME list – list must be re-sent.
            dnd_test_set_mouse_pos(wid, 1, 0, 8, 0)
            dnd_test_fake_drop_event(wid, False, ['text/html', 'text/plain'])
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            self.assertEqual(len(events), 1, raw)
            self.assertIn(b'text/html', events[0]['payload'])

    def test_drop_event_has_uppercase_M(self) -> None:
        """A drop (not just a move) sends t=M (uppercase)."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'M')

    def test_data_end_signal(self) -> None:
        """The end-of-data signal is an empty payload escape code."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain'))
            dnd_test_fake_drop_data(wid, 'text/plain', b'hello')
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            # Last event must be an empty (end-of-stream) t=r.
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events found')
            last = r_events[-1]
            self.ae(last['payload'], b'')

    def test_empty_data(self) -> None:
        """Zero-byte payload is handled gracefully – only end signal is sent."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain'))
            dnd_test_fake_drop_data(wid, 'text/plain', b'')
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            r_events = [e for e in events if e['type'] == 'r']
            # Only the end signal should be present.
            self.assertEqual(len(r_events), 1, raw)
            self.ae(r_events[0]['payload'], b'')

    # ---- t=s / t=d (remote file/directory transfer) tests ----------------

    def _setup_uri_drop(self, screen, wid, cap, uri_list_data: bytes, mimes=None):
        """Register, drop, deliver text/uri-list data, discard move/drop events."""
        if mimes is None:
            mimes = ['text/plain', 'text/uri-list']
        parse_bytes(screen, client_register('text/plain text/uri-list'))
        dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
        dnd_test_fake_drop_event(wid, True, mimes)
        cap.consume(wid)
        # Client requests and receives the URI list
        parse_bytes(screen, client_request_data('text/uri-list'))
        dnd_test_fake_drop_data(wid, 'text/uri-list', uri_list_data)
        cap.consume(wid)  # discard t=r data for text/uri-list

    def test_uri_file_transfer_basic(self) -> None:
        """t=s request sends the content of a regular file as t=r chunks."""
        import os
        import tempfile
        content = b'Hello, remote DnD world!\n' * 100
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'no t=r events')
                combined = b''.join(e['payload'] for e in r_events)
                self.ae(combined, content)
                # Last chunk must be the empty end-of-data signal
                self.ae(r_events[-1]['payload'], b'')
        finally:
            os.unlink(fpath)

    def test_uri_file_transfer_integrity(self) -> None:
        """File content is transferred byte-for-byte (binary integrity)."""
        import os
        import tempfile
        # Use binary content with all byte values to check integrity
        content = bytes(range(256)) * 512  # 128 KiB
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                # Exclude the empty end-of-data entry when concatenating
                combined = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(combined, content)
        finally:
            os.unlink(fpath)

    def test_uri_file_transfer_enoent(self) -> None:
        """t=s with an out-of-range index returns ENOENT."""
        uri_list = b'file:///tmp/no_such_file_exists_dnd_test_xyz\r\n'
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_uri_drop(screen, wid, cap, uri_list)
            # Index 0 refers to a non-existent file
            parse_bytes(screen, client_request_uri_data(0))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.assertIn(events[0]['payload'].strip(), [b'ENOENT', b'EPERM'])

    def test_uri_file_transfer_out_of_bounds(self) -> None:
        """t=s with an index beyond the URI list returns ENOENT."""
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(99))  # out of range
                events = self._get_events(cap, wid)
                self.assertEqual(len(events), 1, events)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['payload'].strip(), b'ENOENT')
        finally:
            os.unlink(fpath)

    def test_uri_request_without_uri_list_returns_einval(self) -> None:
        """t=s without prior text/uri-list request returns EINVAL."""
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fpath = f.name
        try:
            with dnd_test_window() as (osw, wid, screen, cap):
                parse_bytes(screen, client_register('text/plain'))
                dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
                dnd_test_fake_drop_event(wid, True, ['text/plain', 'text/uri-list'])
                cap.consume(wid)
                # Do NOT request text/uri-list first
                parse_bytes(screen, client_request_uri_data(0))
                events = self._get_events(cap, wid)
                self.assertEqual(len(events), 1, events)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['payload'].strip(), b'EINVAL')
        finally:
            os.unlink(fpath)

    def test_uri_non_regular_file_returns_einval(self) -> None:
        """t=s for a non-regular file (e.g. /dev/null) returns EINVAL."""
        uri_list = b'file:///dev/null\r\n'
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_uri_drop(screen, wid, cap, uri_list)
            parse_bytes(screen, client_request_uri_data(0))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_uri_directory_transfer_tree(self) -> None:
        """Full directory tree transfer: listing, sub-dirs, file integrity."""
        import hashlib
        import os
        import tempfile

        # Build a tree: root/ a.txt  b/  b/c.txt  b/d/  b/d/e.txt
        with tempfile.TemporaryDirectory() as root:
            a_content = b'file a content\n' * 50
            bc_content = bytes(range(256)) * 20  # binary data
            bde_content = b'deep nested file\n'

            (open(os.path.join(root, 'a.txt'), 'wb')).write(a_content)
            os.makedirs(os.path.join(root, 'b', 'd'))
            (open(os.path.join(root, 'b', 'c.txt'), 'wb')).write(bc_content)
            (open(os.path.join(root, 'b', 'd', 'e.txt'), 'wb')).write(bde_content)

            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)

                # Request the root directory (idx=0)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'd']
                self.assertTrue(d_events, 'expected t=d listing for root')

                root_listing_payload = b''.join(
                    chunk for e in d_events for chunk in e['chunks'] if chunk
                )
                root_handle_id = int(d_events[0]['meta']['x'])
                self.assertGreater(root_handle_id, 0)

                # Decode null-separated entries
                root_entries = [e for e in root_listing_payload.split(b'\x00') if e]
                # First entry is the unique identifier; remainder are file/dir names
                self.assertGreater(len(root_entries), 1,
                                   f'expected entries, got {root_entries}')
                entry_names = {e.decode() for e in root_entries[1:]}
                self.assertIn('a.txt', entry_names)
                self.assertIn('b', entry_names)

                # Find index of 'a.txt' in the entries list (1-based for t=d:y=)
                entries_list = [e.decode() for e in root_entries[1:]]
                a_idx = entries_list.index('a.txt') + 1
                b_idx = entries_list.index('b') + 1

                # Read a.txt
                parse_bytes(screen, client_dir_read(root_handle_id, a_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                a_data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(a_data, a_content)

                # Read sub-directory b → should get a new t=d listing
                parse_bytes(screen, client_dir_read(root_handle_id, b_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                b_d_events = [e for e in events if e['type'] == 'd']
                self.assertTrue(b_d_events, 'expected t=d listing for b/')

                b_listing_payload = b''.join(
                    chunk for e in b_d_events for chunk in e['chunks'] if chunk
                )
                b_handle_id = int(b_d_events[0]['meta']['x'])
                self.assertNotEqual(b_handle_id, root_handle_id)

                b_entries = [e for e in b_listing_payload.split(b'\x00') if e]
                b_names = {e.decode() for e in b_entries[1:]}
                self.assertIn('c.txt', b_names)
                self.assertIn('d', b_names)

                b_entries_list = [e.decode() for e in b_entries[1:]]
                bc_idx = b_entries_list.index('c.txt') + 1
                bd_idx = b_entries_list.index('d') + 1

                # Read b/c.txt (binary integrity)
                parse_bytes(screen, client_dir_read(b_handle_id, bc_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                bc_data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(bc_data, bc_content)
                # Check SHA-256 integrity
                self.ae(hashlib.sha256(bc_data).digest(),
                        hashlib.sha256(bc_content).digest())

                # Read sub-directory b/d → yet another t=d listing
                parse_bytes(screen, client_dir_read(b_handle_id, bd_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                bd_d_events = [e for e in events if e['type'] == 'd']
                self.assertTrue(bd_d_events, 'expected t=d listing for b/d/')

                bd_listing_payload = b''.join(
                    chunk for e in bd_d_events for chunk in e['chunks'] if chunk
                )
                bd_handle_id = int(bd_d_events[0]['meta']['x'])
                bd_entries = [e for e in bd_listing_payload.split(b'\x00') if e]
                bd_names = {e.decode() for e in bd_entries[1:]}
                self.assertIn('e.txt', bd_names)

                bd_entries_list = [e.decode() for e in bd_entries[1:]]
                bde_idx = bd_entries_list.index('e.txt') + 1

                # Read b/d/e.txt
                parse_bytes(screen, client_dir_read(bd_handle_id, bde_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                bde_data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(bde_data, bde_content)

                # Close all directory handles
                parse_bytes(screen, client_dir_read(bd_handle_id))
                parse_bytes(screen, client_dir_read(b_handle_id))
                parse_bytes(screen, client_dir_read(root_handle_id))
                # No error output expected from close operations
                self._assert_no_output(cap, wid)

    def test_dir_handle_close_and_reuse(self) -> None:
        """Closing a directory handle invalidates it; subsequent requests return EINVAL."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'f.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                self.assertTrue(d_ev)
                hid = int(d_ev[0]['meta']['x'])

                # Close the handle
                parse_bytes(screen, client_dir_read(hid))
                self._assert_no_output(cap, wid)

                # Now try to read from the closed handle → EINVAL
                parse_bytes(screen, client_dir_read(hid, 1))
                events = self._get_events(cap, wid)
                self.assertEqual(len(events), 1)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_dir_entry_out_of_bounds_returns_enoent(self) -> None:
        """Reading a directory entry with an out-of-range index returns ENOENT."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'only.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                hid = int(d_ev[0]['meta']['x'])

                # Entry 999 does not exist
                parse_bytes(screen, client_dir_read(hid, 999))
                events = self._get_events(cap, wid)
                self.assertEqual(len(events), 1)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_dir_unique_identifier_prevents_loops(self) -> None:
        """Each directory listing starts with a unique id (dev:inode format)."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            sub = os.path.join(root, 'sub')
            os.mkdir(sub)
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                root_payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                root_handle_id = int(d_ev[0]['meta']['x'])
                root_uid = root_payload.split(b'\x00')[0].decode()
                # uid must be non-empty and contain a colon (dev:inode)
                self.assertIn(':', root_uid, f'uid={root_uid!r}')

                # Get the sub directory listing to compare identifiers
                entries = [e.decode() for e in root_payload.split(b'\x00')[1:] if e]
                sub_idx = entries.index('sub') + 1
                parse_bytes(screen, client_dir_read(root_handle_id, sub_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev2 = [e for e in events if e['type'] == 'd']
                sub_payload = b''.join(
                    chunk for e in d_ev2 for chunk in e['chunks'] if chunk
                )
                sub_uid = sub_payload.split(b'\x00')[0].decode() if sub_payload else ''
                self.assertIn(':', sub_uid, f'sub uid={sub_uid!r}')
                # Root and sub must have different identifiers
                self.assertNotEqual(root_uid, sub_uid)

    def test_window_close_during_transfer_no_leak(self) -> None:
        """Closing the window while dir handles are open frees all resources (no crash)."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'f.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            # The context manager calls dnd_test_cleanup_fake_window on exit,
            # which calls drop_free_data → drop_free_dir_handles.
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                cap.consume(wid)
                # Intentionally leave the handle open – cleanup happens in __exit__

