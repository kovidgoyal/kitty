#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import re
from base64 import standard_b64decode, standard_b64encode
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
    from kitty.fast_data_types import get_options
    from kitty.options.types import defaults
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
