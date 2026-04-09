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


def client_request_data(mime: str = '', client_id: int = 0, request_id: int = 0) -> bytes:
    """Escape code a client sends to request data (t=r) or finish the drop (t=r with no MIME)."""
    meta = f'{DND_CODE};t=r'
    if request_id:
        meta += f':r={request_id}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};{mime}')


def client_request_uri_data(idx: int, client_id: int = 0, request_id: int = 0) -> bytes:
    """Escape code a client sends to request a file from the URI list (t=s ; text/uri-list:idx)."""
    meta = f'{DND_CODE};t=s'
    if request_id:
        meta += f':r={request_id}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};text/uri-list:{idx}')


def client_dir_read(handle_id: int, entry_num: int | None = None, client_id: int = 0, request_id: int = 0) -> bytes:
    """Escape code for a directory request (t=d:x=handle_id[:y=entry_num]).

    * entry_num=None → close the directory handle.
    * entry_num>=0   → read that entry (0-based).
    """
    meta = f'{DND_CODE};t=d:x={handle_id}'
    if entry_num is not None:
        meta += f':y={entry_num}'
    if request_id:
        meta += f':r={request_id}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


# ---- drag source helpers ----------------------------------------------------

def client_drag_register(client_id: int = 0) -> bytes:
    """Escape code a client sends to start offering drags (t=o, no payload)."""
    meta = f'{DND_CODE};t=o'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_drag_unregister(client_id: int = 0) -> bytes:
    """Escape code a client sends to stop offering drags (t=O)."""
    meta = f'{DND_CODE};t=O'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_drag_offer_mimes(operations: int, mimes: str, client_id: int = 0, more: bool = False) -> bytes:
    """Escape code a client sends to offer MIME types for a drag (t=o:o=ops ; payload).

    *operations*: 1=copy, 2=move, 3=either.
    *more*: if True set m=1 for chunked transfer.
    """
    meta = f'{DND_CODE};t=o:o={operations}'
    if client_id:
        meta += f':i={client_id}'
    if more:
        meta += ':m=1'
    return _osc(f'{meta};{mimes}')


def client_drag_pre_send(idx: int, data_b64: str, client_id: int = 0, more: bool = False) -> bytes:
    """Escape code for pre-sending data for a MIME type (t=p:x=idx ; b64 payload).

    *idx*: zero-based index into the offered MIME list.
    *data_b64*: base64-encoded payload.
    *more*: if True set m=1 for chunked transfer.
    """
    meta = f'{DND_CODE};t=p:x={idx}'
    if client_id:
        meta += f':i={client_id}'
    if more:
        meta += ':m=1'
    return _osc(f'{meta};{data_b64}')


def client_drag_add_image(
    idx: int, fmt: int, width: int, height: int, data_b64: str,
    client_id: int = 0, more: bool = False,
) -> bytes:
    """Escape code for adding an image thumbnail (t=p:x=-idx:y=fmt:X=w:Y=h ; b64).

    *idx*: 1-based image number (will be negated, so idx=1 means x=-1).
    *fmt*: 24=RGB, 32=RGBA, 100=PNG.
    """
    meta = f'{DND_CODE};t=p:x=-{idx}:y={fmt}:X={width}:Y={height}'
    if client_id:
        meta += f':i={client_id}'
    if more:
        meta += ':m=1'
    return _osc(f'{meta};{data_b64}')


def client_drag_change_image(idx: int, client_id: int = 0) -> bytes:
    """Escape code to change the drag image (t=P:x=idx)."""
    meta = f'{DND_CODE};t=P:x={idx}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_drag_start(client_id: int = 0) -> bytes:
    """Escape code to start the drag operation (t=P:x=-1)."""
    meta = f'{DND_CODE};t=P:x=-1'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_drag_send_data(idx: int, data_b64: str, client_id: int = 0, more: bool = False) -> bytes:
    """Escape code a client sends to provide data for a drag request (t=e:y=idx:m=0/1 ; b64).

    *idx*: zero-based MIME index.
    """
    m = 1 if more else 0
    meta = f'{DND_CODE};t=e:y={idx}:m={m}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};{data_b64}')


def client_drag_send_error(idx: int, err_name: str = '', client_id: int = 0) -> bytes:
    """Escape code a client sends to report an error during a drag (t=E:y=idx ; errname)."""
    meta = f'{DND_CODE};t=E:y={idx}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(f'{meta};{err_name}')


def client_drag_cancel(client_id: int = 0) -> bytes:
    """Escape code a client sends to cancel the full drag (t=E:y=-1)."""
    meta = f'{DND_CODE};t=E:y=-1'
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

            def w(data, *a):
                with open(os.path.join(root, *a), 'wb') as f:
                    f.write(data)

            w(a_content, 'a.txt')
            os.makedirs(os.path.join(root, 'b', 'd'))
            w(bc_content, 'b', 'c.txt')
            w(bde_content, 'b', 'd', 'e.txt')

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

                # Decode null-separated entries (no unique identifier prefix)
                root_entries = [e for e in root_listing_payload.split(b'\x00') if e]
                entry_names = {e.decode() for e in root_entries}
                self.assertIn('a.txt', entry_names)
                self.assertIn('b', entry_names)

                # Find index of 'a.txt' in the entries list (0-based for t=d:y=)
                entries_list = [e.decode() for e in root_entries]
                a_idx = entries_list.index('a.txt')
                b_idx = entries_list.index('b')

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
                b_names = {e.decode() for e in b_entries}
                self.assertIn('c.txt', b_names)
                self.assertIn('d', b_names)

                b_entries_list = [e.decode() for e in b_entries]
                bc_idx = b_entries_list.index('c.txt')
                bd_idx = b_entries_list.index('d')

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
                bd_names = {e.decode() for e in bd_entries}
                self.assertIn('e.txt', bd_names)

                bd_entries_list = [e.decode() for e in bd_entries]
                bde_idx = bd_entries_list.index('e.txt')

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
                parse_bytes(screen, client_dir_read(hid, 0))
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

    def test_dir_no_unique_identifier(self) -> None:
        """Directory listings should not contain a unique identifier prefix."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'hello.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                # All entries should be actual file/dir names, no dev:inode prefix
                self.assertEqual(entries, ['hello.txt'])

    def test_dir_symlink_to_file(self) -> None:
        """Symlinks to files inside directories are reported with t=r:X=1 and the symlink target."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            real_file = os.path.join(root, 'real.txt')
            with open(real_file, 'w') as f:
                f.write('real content')
            os.symlink('real.txt', os.path.join(root, 'link.txt'))
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = int(d_ev[0]['meta']['x'])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                self.assertIn('link.txt', entries)
                self.assertIn('real.txt', entries)
                link_idx = entries.index('link.txt')

                # Read the symlink entry → should get t=r with X=1 and target path
                parse_bytes(screen, client_dir_read(hid, link_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'expected t=r response for symlink')
                # Check X=1 flag indicating symlink
                self.assertEqual(r_events[0]['meta'].get('X'), '1',
                                 'symlink response must have X=1')
                # Payload should be the symlink target
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, b'real.txt')

    def test_dir_symlink_to_directory(self) -> None:
        """Symlinks to directories inside directories are reported with t=r:X=1."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, 'subdir'))
            os.symlink('subdir', os.path.join(root, 'link_to_dir'))
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = int(d_ev[0]['meta']['x'])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                self.assertIn('link_to_dir', entries)
                link_idx = entries.index('link_to_dir')

                # Read the symlink → should get t=r with X=1
                parse_bytes(screen, client_dir_read(hid, link_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'expected t=r response for dir symlink')
                self.assertEqual(r_events[0]['meta'].get('X'), '1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, b'subdir')

    def test_dir_symlink_absolute_target(self) -> None:
        """Symlinks with absolute targets report the full absolute path."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            real_file = os.path.join(root, 'abs_target.txt')
            with open(real_file, 'w') as f:
                f.write('content')
            os.symlink(real_file, os.path.join(root, 'abs_link.txt'))
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = int(d_ev[0]['meta']['x'])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                link_idx = entries.index('abs_link.txt')

                parse_bytes(screen, client_dir_read(hid, link_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events)
                self.assertEqual(r_events[0]['meta'].get('X'), '1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, real_file.encode())

    def test_dir_regular_file_no_symlink_flag(self) -> None:
        """Regular files in directories must NOT have the X=1 flag."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'regular.txt'), 'w') as f:
                f.write('hello')
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = int(d_ev[0]['meta']['x'])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                reg_idx = entries.index('regular.txt')

                parse_bytes(screen, client_dir_read(hid, reg_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events)
                # Regular files must not have X=1
                self.assertNotEqual(r_events[0]['meta'].get('X'), '1',
                                    'regular file must not have X=1 symlink flag')
                data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(data, b'hello')

    def test_dir_symlink_and_regular_mixed(self) -> None:
        """Directory with both regular files and symlinks handles each correctly."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'data.bin'), 'wb') as f:
                f.write(b'\x00\x01\x02\x03')
            os.symlink('data.bin', os.path.join(root, 'alias.bin'))
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = int(d_ev[0]['meta']['x'])
                entries = [e.decode() for e in payload.split(b'\x00') if e]

                # Read regular file
                data_idx = entries.index('data.bin')
                parse_bytes(screen, client_dir_read(hid, data_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertNotEqual(r_events[0]['meta'].get('X'), '1')
                self.ae(b''.join(e['payload'] for e in r_events if e['payload']),
                        b'\x00\x01\x02\x03')

                # Read symlink
                alias_idx = entries.index('alias.bin')
                parse_bytes(screen, client_dir_read(hid, alias_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertEqual(r_events[0]['meta'].get('X'), '1')
                self.ae(b''.join(e['payload'] for e in r_events if e['payload']),
                        b'data.bin')

    def test_dir_nested_symlink_in_subdir(self) -> None:
        """Symlinks inside nested subdirectories are handled correctly."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            sub = os.path.join(root, 'sub')
            os.mkdir(sub)
            with open(os.path.join(sub, 'target.txt'), 'w') as f:
                f.write('nested target')
            os.symlink('target.txt', os.path.join(sub, 'nested_link.txt'))
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                root_hid = int(d_ev[0]['meta']['x'])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                sub_idx = entries.index('sub')

                # Open subdirectory
                parse_bytes(screen, client_dir_read(root_hid, sub_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                sub_payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                sub_hid = int(d_ev[0]['meta']['x'])
                sub_entries = [e.decode() for e in sub_payload.split(b'\x00') if e]
                self.assertIn('nested_link.txt', sub_entries)

                link_idx = sub_entries.index('nested_link.txt')
                parse_bytes(screen, client_dir_read(sub_hid, link_idx))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertEqual(r_events[0]['meta'].get('X'), '1')
                self.ae(b''.join(e['payload'] for e in r_events if e['payload']),
                        b'target.txt')

    def test_dir_entry_zero_based_index(self) -> None:
        """Directory entry index 0 reads the first entry (0-based)."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'first.txt'), 'w') as f:
                f.write('first file')
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'd']
                hid = int(d_ev[0]['meta']['x'])

                # Index 0 should read the first entry
                parse_bytes(screen, client_dir_read(hid, 0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'entry index 0 should read the first entry')
                data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(data, b'first file')

    def test_top_level_symlink_to_file_resolved(self) -> None:
        """Top-level symlink in URI list resolves to file and sends file data."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            real = os.path.join(root, 'real.txt')
            with open(real, 'w') as f:
                f.write('resolved content')
            link = os.path.join(root, 'link.txt')
            os.symlink(real, link)
            uri_list = f'file://{link}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'top-level symlink should resolve and send file data')
                data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(data, b'resolved content')

    def test_top_level_symlink_to_dir_resolved(self) -> None:
        """Top-level symlink to directory in URI list resolves and returns directory listing."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            sub = os.path.join(root, 'realdir')
            os.mkdir(sub)
            with open(os.path.join(sub, 'inside.txt'), 'w') as f:
                f.write('inside')
            link = os.path.join(root, 'linkdir')
            os.symlink(sub, link)
            uri_list = f'file://{link}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'd']
                self.assertTrue(d_events, 'top-level symlink to dir should return directory listing')
                payload = b''.join(
                    chunk for e in d_events for chunk in e['chunks'] if chunk
                )
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                self.assertIn('inside.txt', entries)

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

    # ---- Drag source (t=o, t=O, t=p, t=P, t=e, t=E) tests ------------------

    def _setup_drag_offer(self, screen, wid, cap, mimes: str = 'text/plain', operations: int = 1, client_id: int = 0):
        """Send t=o with operations and payload to set up a drag offer being built."""
        parse_bytes(screen, client_drag_offer_mimes(operations, mimes, client_id=client_id))
        cap.consume(wid)  # discard any output

    def test_drag_register_and_unregister(self) -> None:
        """Client can register and unregister willingness to offer drags."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # Register for drag offers (t=o, no payload).
            parse_bytes(screen, client_drag_register())
            self._assert_no_output(cap, wid)

            # Unregister (t=O).
            parse_bytes(screen, client_drag_unregister())
            self._assert_no_output(cap, wid)

    def test_drag_offer_single_mime(self) -> None:
        """Client can offer a drag with a single MIME type."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            # No error expected – the offer is being built.
            self._assert_no_output(cap, wid)

    def test_drag_offer_multiple_mimes(self) -> None:
        """Client can offer a drag with multiple MIME types."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_offer_mimes(3, 'text/plain text/uri-list application/json'))
            self._assert_no_output(cap, wid)

    def test_drag_offer_no_operations_returns_einval(self) -> None:
        """Offering MIME types with operations=0 (no valid operations) returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # First need a valid offer to set allowed_operations, but if we pass o=0
            # directly and there's no prior offer, drag_add_mimes should abort with EINVAL.
            parse_bytes(screen, client_drag_offer_mimes(0, 'text/plain'))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_offer_copy_only(self) -> None:
        """Offering with operations=1 (copy only) is accepted."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            self._assert_no_output(cap, wid)

    def test_drag_offer_move_only(self) -> None:
        """Offering with operations=2 (move only) is accepted."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_offer_mimes(2, 'text/plain'))
            self._assert_no_output(cap, wid)

    def test_drag_offer_copy_and_move(self) -> None:
        """Offering with operations=3 (copy+move) is accepted."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_offer_mimes(3, 'text/plain text/html'))
            self._assert_no_output(cap, wid)

    def test_drag_pre_send_data_valid(self) -> None:
        """Pre-sending data for a valid MIME index succeeds."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain text/html')
            data = standard_b64encode(b'hello pre-sent').decode()
            # Send data for index 0 (text/plain)
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap, wid)

    def test_drag_pre_send_data_out_of_range_returns_einval(self) -> None:
        """Pre-sending data for an out-of-range MIME index returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            data = standard_b64encode(b'some data').decode()
            # Index 5 is out of range (we only offered one MIME type)
            parse_bytes(screen, client_drag_pre_send(5, data))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_pre_send_data_moderate_chunk(self) -> None:
        """Pre-sending a moderate chunk of data succeeds without triggering size cap."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # The size cap is 64MB (PRESENT_DATA_CAP = 64 * 1024 * 1024).
            # We can't realistically send 64MB in a unit test, so we verify
            # that a moderate chunk is accepted without error.
            chunk_raw = b'X' * 3072  # 3072 bytes = 4096 base64
            chunk_b64 = standard_b64encode(chunk_raw).decode()
            parse_bytes(screen, client_drag_pre_send(0, chunk_b64))
            self._assert_no_output(cap, wid)

    def test_drag_pre_send_without_offer_returns_einval(self) -> None:
        """Pre-sending data without a prior offer returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            data = standard_b64encode(b'orphan data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_image_rgba_valid(self) -> None:
        """Adding a valid RGBA image succeeds without error."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # 2x2 RGBA image = 2*2*4 = 16 bytes
            pixel_data = b'\xff\x00\x00\xff' * 4  # 4 red pixels
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            self._assert_no_output(cap, wid)

    def test_drag_add_image_rgb_valid(self) -> None:
        """Adding a valid RGB image succeeds without error."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # 2x2 RGB image = 2*2*3 = 12 bytes
            pixel_data = b'\xff\x00\x00' * 4  # 4 red pixels (RGB)
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 24, 2, 2, data_b64))
            self._assert_no_output(cap, wid)

    def test_drag_add_image_invalid_format_returns_einval(self) -> None:
        """Adding an image with an invalid format (not 24/32/100) returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            pixel_data = b'\xff\x00\x00' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            # fmt=16 is invalid
            parse_bytes(screen, client_drag_add_image(1, 16, 2, 2, data_b64))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_image_invalid_dimensions_returns_einval(self) -> None:
        """Adding an image with zero or negative dimensions returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            pixel_data = b'\xff\x00\x00' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            # width=0 is invalid
            parse_bytes(screen, client_drag_add_image(1, 24, 0, 2, data_b64))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_image_without_offer_returns_einval(self) -> None:
        """Adding an image without a prior drag offer returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            pixel_data = b'\xff\x00\x00\xff' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_too_many_images_returns_error(self) -> None:
        """Adding more than the maximum number of images returns an error."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            pixel_data = b'\xff\x00\x00\xff' * 4  # 2x2 RGBA
            data_b64 = standard_b64encode(pixel_data).decode()
            # The images array has 16 slots (indices 0..15).
            # The check is idx + 1 >= arraysz (16), so valid indices are 0..14.
            # Client 1-based idx maps to C idx via x=-idx, so valid client indices
            # are 1..14 (14 images). First 14 images should succeed.
            for i in range(1, 15):
                parse_bytes(screen, client_drag_add_image(i, 32, 2, 2, data_b64))
            self._assert_no_output(cap, wid)

            # Image 15 (C idx=15) should fail with an error (EFBIG)
            parse_bytes(screen, client_drag_add_image(15, 32, 2, 2, data_b64))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')

    def test_drag_start_no_real_window_returns_einval_or_eperm(self) -> None:
        """Starting a drag with a fake window (no GLFW handle) returns EINVAL or EPERM."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Try to start the drag – the fake window has no osw->handle, so
            # start_window_drag returns EINVAL.
            parse_bytes(screen, client_drag_start())
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            # Error is EINVAL because osw->handle is NULL
            self.assertIn(events[0]['payload'].strip(), [b'EINVAL', b'EPERM'])

    def test_drag_start_without_offer_returns_einval(self) -> None:
        """Starting a drag without a prior offer returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_start())
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_free_offer_cleans_up(self) -> None:
        """Sending t=O cleans up a partially built drag offer."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain text/html')
            # Pre-send some data
            data = standard_b64encode(b'test data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap, wid)

            # Cancel the offer
            parse_bytes(screen, client_drag_unregister())
            self._assert_no_output(cap, wid)

            # Trying to pre-send data now should fail (state is NONE)
            parse_bytes(screen, client_drag_pre_send(0, data))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_cancel_from_client(self) -> None:
        """Client can cancel a drag via t=E:y=-1."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Cancel the drag
            parse_bytes(screen, client_drag_cancel())
            self._assert_no_output(cap, wid)

            # After cancel, state should be NONE – trying to start should fail.
            parse_bytes(screen, client_drag_start())
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_second_offer_replaces_first(self) -> None:
        """A second offer with operations replaces the first one."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # First offer
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            data = standard_b64encode(b'first data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap, wid)

            # Second offer replaces the first (drag_add_mimes cancels if state != NONE)
            self._setup_drag_offer(screen, wid, cap, 'text/html')
            # Pre-send data for the new MIME type at index 0
            data2 = standard_b64encode(b'second data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data2))
            self._assert_no_output(cap, wid)

    def test_drag_client_id_propagated(self) -> None:
        """The client_id (i=…) set during drag offer is echoed in error replies."""
        client_id = 99
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain', client_id=client_id))
            self._assert_no_output(cap, wid)
            # Starting the drag will fail (no real window), producing an error with client_id
            parse_bytes(screen, client_drag_start(client_id=client_id))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('i'), str(client_id))

    def test_drag_change_image_before_start(self) -> None:
        """Changing the drag image index before starting is accepted silently."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Add an image
            pixel_data = b'\xff\x00\x00\xff' * 4  # 2x2 RGBA
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            self._assert_no_output(cap, wid)
            # Change to image index 0 (the first image)
            parse_bytes(screen, client_drag_change_image(0))
            self._assert_no_output(cap, wid)

    def test_drag_chunked_mime_offer(self) -> None:
        """A large MIME list can be sent in chunks using m=1."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # First chunk with m=1 (more coming)
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain ', more=True))
            self._assert_no_output(cap, wid)

            # Second (final) chunk with m=0 (default) – use the raw _osc helper
            # since client_drag_offer_mimes always sets operations, but subsequent
            # chunks should not re-set operations. The parser handles this via the
            # more flag on drag_add_mimes.
            final_chunk = _osc(f'{DND_CODE};t=o;text/html')
            parse_bytes(screen, final_chunk)
            self._assert_no_output(cap, wid)

            # Now verify we can pre-send data for both indices
            data0 = standard_b64encode(b'data for text/plain').decode()
            data1 = standard_b64encode(b'data for text/html').decode()
            parse_bytes(screen, client_drag_pre_send(0, data0))
            self._assert_no_output(cap, wid)
            parse_bytes(screen, client_drag_pre_send(1, data1))
            self._assert_no_output(cap, wid)

    def test_drag_pre_send_chunked_data(self) -> None:
        """Pre-sent data can be chunked across multiple escape codes."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')

            # Split raw data at a 3-byte boundary so base64 encoding produces
            # no padding on intermediate chunks.
            raw = b'hello world data!'  # 17 bytes
            split_at = 12  # multiple of 3
            chunk1_b64 = standard_b64encode(raw[:split_at]).decode()
            chunk2_b64 = standard_b64encode(raw[split_at:]).decode()

            # Send first chunk (m=1)
            parse_bytes(screen, client_drag_pre_send(0, chunk1_b64, more=True))
            self._assert_no_output(cap, wid)

            # Send final chunk (m=0)
            parse_bytes(screen, client_drag_pre_send(0, chunk2_b64, more=False))
            self._assert_no_output(cap, wid)

    def test_drag_add_image_chunked(self) -> None:
        """Image data can be chunked across multiple escape codes."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # 2x2 RGBA = 16 bytes total, split at a 3-byte boundary
            pixel_data = b'\xff\x00\x00\xff' * 4  # 16 bytes
            split_at = 12  # multiple of 3
            chunk1_b64 = standard_b64encode(pixel_data[:split_at]).decode()
            chunk2_b64 = standard_b64encode(pixel_data[split_at:]).decode()

            # First chunk (m=1) with full image metadata
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, chunk1_b64, more=True))
            self._assert_no_output(cap, wid)

            # Second chunk (m=0) – only needs x= (format/size from first chunk)
            final_img = _osc(f'{DND_CODE};t=p:x=-1;{chunk2_b64}')
            parse_bytes(screen, final_img)
            self._assert_no_output(cap, wid)

    def test_drag_process_item_data_without_started_state_invalid(self) -> None:
        """Sending t=e data before the drag is started is silently ignored."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # State is BEING_BUILT, not STARTED – drag_process_item_data should return early
            data_b64 = standard_b64encode(b'premature data').decode()
            parse_bytes(screen, client_drag_send_data(0, data_b64))
            self.assert_error(cap, wid)

    def test_drag_error_from_client_without_started_state_invalid(self) -> None:
        """Sending t=E with a MIME index before the drag is started is silently ignored."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # State is BEING_BUILT – sending an error for index 0 should be ignored
            parse_bytes(screen, client_drag_send_error(0, 'EIO'))
            self.assert_error(cap, wid)

    def test_drag_offer_with_empty_mimes_after_cancel(self) -> None:
        """After cancelling, a new offer can be started from scratch."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # Build and cancel
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            parse_bytes(screen, client_drag_cancel())
            self._assert_no_output(cap, wid)

            # New offer from scratch
            self._setup_drag_offer(screen, wid, cap, 'application/octet-stream')
            data = standard_b64encode(b'binary data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap, wid)

    def test_drag_multiple_images_sequential(self) -> None:
        """Multiple images can be added sequentially with different indices."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Image 1: 1x1 RGBA
            img1 = standard_b64encode(b'\xff\x00\x00\xff').decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 1, 1, img1))
            self._assert_no_output(cap, wid)
            # Image 2: 1x1 RGBA
            img2 = standard_b64encode(b'\x00\xff\x00\xff').decode()
            parse_bytes(screen, client_drag_add_image(2, 32, 1, 1, img2))
            self._assert_no_output(cap, wid)
            # Image 3: 1x1 RGBA
            img3 = standard_b64encode(b'\x00\x00\xff\xff').decode()
            parse_bytes(screen, client_drag_add_image(3, 32, 1, 1, img3))
            self._assert_no_output(cap, wid)

    def test_drag_offer_then_unregister_then_start_fails(self) -> None:
        """After unregistering (t=O), starting a drag (t=P:x=-1) fails."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            parse_bytes(screen, client_drag_unregister())
            self._assert_no_output(cap, wid)

            # Attempting to start should fail since unregister called drag_free_offer
            parse_bytes(screen, client_drag_start())
            self.assert_error(cap, wid)

    def assert_error(self, cap, wid, code='EINVAL'):
        events = self._get_events(cap, wid)
        self.assertEqual(len(events), 1, events)
        self.ae(events[0]['type'], 'R')
        self.ae(events[0]['payload'].strip(), code.encode())

    def test_drag_pre_send_multiple_mimes(self) -> None:
        """Pre-sent data can be provided for multiple different MIME types."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain text/html image/png')
            # Pre-send for text/plain (index 0)
            d0 = standard_b64encode(b'plain text data').decode()
            parse_bytes(screen, client_drag_pre_send(0, d0))
            self._assert_no_output(cap, wid)
            # Pre-send for text/html (index 1)
            d1 = standard_b64encode(b'<h1>html</h1>').decode()
            parse_bytes(screen, client_drag_pre_send(1, d1))
            self._assert_no_output(cap, wid)
            # Pre-send for image/png (index 2)
            d2 = standard_b64encode(b'\x89PNG fake data').decode()
            parse_bytes(screen, client_drag_pre_send(2, d2))
            self._assert_no_output(cap, wid)

    def test_drag_window_close_during_build_no_crash(self) -> None:
        """Closing the window while a drag offer is being built frees resources (no crash)."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain text/html')
            # Add an image
            pixel_data = b'\xff\x00\x00\xff' * 4  # 2x2 RGBA
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            # Pre-send some data
            d = standard_b64encode(b'partial data').decode()
            parse_bytes(screen, client_drag_pre_send(0, d))
            # Intentionally leave the offer partially built – cleanup happens in __exit__

    def test_drag_change_image_out_of_bounds(self) -> None:
        """Changing to an out-of-bounds image index is accepted (means remove image)."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Add one image
            pixel_data = b'\xff\x00\x00\xff' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            self._assert_no_output(cap, wid)
            # Change to a large index (out of bounds) – protocol says image should be removed
            parse_bytes(screen, client_drag_change_image(999))
            self._assert_no_output(cap, wid)

    def test_drag_offer_then_cancel_then_new_offer(self) -> None:
        """After cancelling a drag, building a completely new offer works."""
        with dnd_test_window() as (osw, wid, screen, cap):
            # First offer
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            d1 = standard_b64encode(b'data1').decode()
            parse_bytes(screen, client_drag_pre_send(0, d1))
            img = standard_b64encode(b'\xff\x00\x00\xff').decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 1, 1, img))
            self._assert_no_output(cap, wid)

            # Cancel via t=E:y=-1
            parse_bytes(screen, client_drag_cancel())
            self._assert_no_output(cap, wid)

            # New offer with different MIMEs
            self._setup_drag_offer(screen, wid, cap, 'application/json', operations=2)
            d2 = standard_b64encode(b'{"key":"value"}').decode()
            parse_bytes(screen, client_drag_pre_send(0, d2))
            self._assert_no_output(cap, wid)

    def test_drag_pre_send_invalid_base64_returns_einval(self) -> None:
        """Pre-sending invalid base64 data returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Send completely invalid base64
            parse_bytes(screen, client_drag_pre_send(0, '!@#$%^&*()'))
            self.assert_error(cap, wid)

    def test_drag_add_image_invalid_base64_returns_einval(self) -> None:
        """Adding an image with invalid base64 data returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Invalid base64 as image data
            parse_bytes(screen, client_drag_add_image(1, 32, 1, 1, '!@#$%^&*()'))
            self.assert_error(cap, wid)

    def test_drag_start_with_image_size_mismatch(self) -> None:
        """Starting a drag when image data size doesn't match dimensions returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Claim 2x2 RGBA (16 bytes) but send only 8 bytes
            wrong_data = b'\xff\x00\x00\xff' * 2  # only 8 bytes
            data_b64 = standard_b64encode(wrong_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            # The image is accepted during add (size check is deferred to drag_start
            # for RGBA/RGB where expand happens). But for RGBA, the size check in
            # drag_start will fail since 8 != 2*2*4.
            # Actually no - for fmt=32, expand_rgb_data is not called, only for fmt=24.
            # The check img.sz != width*height*4 happens in drag_start.
            parse_bytes(screen, client_drag_start())
            self.assert_error(cap, wid)

    def test_drag_start_with_rgb_image_size_mismatch(self) -> None:
        """Starting a drag when RGB image data size doesn't match w*h*3 returns EINVAL."""
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_drag_offer(screen, wid, cap, 'text/plain')
            # Claim 2x2 RGB (12 bytes) but send 8 bytes
            wrong_data = b'\xff\x00\x00' * 2 + b'\x00\x00'  # 8 bytes, not 12
            data_b64 = standard_b64encode(wrong_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 24, 2, 2, data_b64))
            # drag_start calls expand_rgb_data which checks sz == w*h*3
            parse_bytes(screen, client_drag_start())
            self.assert_error(cap, wid)

    # ---- Request queue and request_id tests ----------------------------------

    def test_request_id_echoed_in_data_response(self) -> None:
        """request_id is echoed back as r=ID in data responses."""
        payload_data = b'hello request_id'
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain', request_id=42))
            dnd_test_fake_drop_data(wid, 'text/plain', payload_data)
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events')
            for ev in r_events:
                self.ae(ev['meta'].get('r'), '42', f'expected r=42, got {ev["meta"]}')
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, payload_data)

    def test_request_id_echoed_in_error_response(self) -> None:
        """request_id is echoed back as r=ID in error responses."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('image/png', request_id=99))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('r'), '99')
            self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_request_id_zero_not_included(self) -> None:
        """When request_id is 0 (default), r= is not included in responses."""
        payload_data = b'no request_id'
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # Request without request_id (defaults to 0)
            parse_bytes(screen, client_request_data('text/plain'))
            dnd_test_fake_drop_data(wid, 'text/plain', payload_data)
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events')
            for ev in r_events:
                self.assertNotIn('r', ev['meta'], f'r= should not be present when request_id=0, got {ev["meta"]}')

    def test_request_id_in_error_for_io_failure(self) -> None:
        """request_id is echoed in I/O error responses."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            parse_bytes(screen, client_request_data('text/plain', request_id=77))
            dnd_test_fake_drop_data(wid, 'text/plain', b'', errno.EIO)
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('r'), '77')
            self.ae(events[0]['payload'].strip(), b'EIO')

    def test_multiple_queued_requests_fifo(self) -> None:
        """Multiple requests with different request_ids are served in FIFO order."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain text/html'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain', 'text/html'])
            cap.consume(wid)

            # Queue two requests
            parse_bytes(screen, client_request_data('text/plain', request_id=1))
            parse_bytes(screen, client_request_data('text/html', request_id=2))

            # First request (text/plain) gets served first
            dnd_test_fake_drop_data(wid, 'text/plain', b'plain data')
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r' and e['meta'].get('r') == '1']
            self.assertTrue(r_events, 'no t=r events for first request')
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, b'plain data')

            # Second request (text/html) gets served next
            dnd_test_fake_drop_data(wid, 'text/html', b'<html>data</html>')
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r' and e['meta'].get('r') == '2']
            self.assertTrue(r_events, 'no t=r events for second request')
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, b'<html>data</html>')

    def test_request_after_error_proceeds(self) -> None:
        """After an error response, the next queued request is processed."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # Queue: request for unknown MIME (error) followed by valid request
            parse_bytes(screen, client_request_data('image/png', request_id=10))
            parse_bytes(screen, client_request_data('text/plain', request_id=11))

            # The error for request 10 should have been sent immediately
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            err_events = [e for e in events if e['type'] == 'R']
            self.assertEqual(len(err_events), 1, events)
            self.ae(err_events[0]['meta'].get('r'), '10')
            self.ae(err_events[0]['payload'].strip(), b'ENOENT')

            # Now serve request 11
            dnd_test_fake_drop_data(wid, 'text/plain', b'second request data')
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events for second request')
            for ev in r_events:
                self.ae(ev['meta'].get('r'), '11')

    def test_queue_overflow_returns_emfile(self) -> None:
        """Exceeding 128 queued requests returns EMFILE and ends the drop."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # First request starts async processing
            parse_bytes(screen, client_request_data('text/plain', request_id=1))

            # Queue 127 more requests (fill to capacity = 128)
            for i in range(2, 129):
                parse_bytes(screen, client_request_data('text/plain', request_id=i))

            # No error yet - queue is at capacity
            raw = cap.consume(wid)
            err_events = [e for e in parse_escape_codes(raw) if e['type'] == 'R']
            self.assertEqual(len(err_events), 0, f'unexpected errors: {err_events}')

            # 129th request should trigger EMFILE
            parse_bytes(screen, client_request_data('text/plain', request_id=999))
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            err_events = [e for e in events if e['type'] == 'R']
            self.assertTrue(err_events, 'expected EMFILE error')
            self.ae(err_events[0]['meta'].get('r'), '999')
            self.ae(err_events[0]['payload'].strip(), b'EMFILE')

    def test_request_id_in_uri_file_response(self) -> None:
        """request_id is echoed in t=s (URI file) data responses."""
        import os
        import tempfile
        content = b'URI file with request_id\n'
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0, request_id=55))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'no t=r events')
                for ev in r_events:
                    self.ae(ev['meta'].get('r'), '55')
                combined = b''.join(e['payload'] for e in r_events)
                self.ae(combined, content)
        finally:
            os.unlink(fpath)

    def test_request_id_in_uri_error_response(self) -> None:
        """request_id is echoed in t=s error responses."""
        uri_list = b'file:///tmp/no_such_file_dnd_test_xyz\r\n'
        with dnd_test_window() as (osw, wid, screen, cap):
            self._setup_uri_drop(screen, wid, cap, uri_list)
            parse_bytes(screen, client_request_uri_data(0, request_id=66))
            events = self._get_events(cap, wid)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('r'), '66')

    def test_request_id_in_dir_listing_response(self) -> None:
        """request_id is echoed in directory listing (t=d) responses."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'file.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(0, request_id=88))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'd']
                self.assertTrue(d_events, 'expected t=d listing')
                for ev in d_events:
                    self.ae(ev['meta'].get('r'), '88')

    def test_request_id_in_dir_entry_file_response(self) -> None:
        """request_id is echoed when reading a file via directory handle (t=d)."""
        import os
        import tempfile
        content = b'directory file content\n'
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'f.txt'), 'wb') as f:
                f.write(content)
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)
                # Get dir listing first (no request_id needed for setup)
                parse_bytes(screen, client_request_uri_data(0))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'd']
                self.assertTrue(d_events)
                handle_id = int(d_events[0]['meta']['x'])
                listing = b''.join(chunk for e in d_events for chunk in e['chunks'] if chunk)
                entries = [e.decode() for e in listing.split(b'\x00') if e]
                f_idx = entries.index('f.txt')

                # Read file with request_id
                parse_bytes(screen, client_dir_read(handle_id, f_idx, request_id=33))
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'no t=r events')
                for ev in r_events:
                    self.ae(ev['meta'].get('r'), '33')
                combined = b''.join(e['payload'] for e in r_events)
                self.ae(combined, content)

    def test_request_id_in_dir_entry_error_response(self) -> None:
        """request_id is echoed when a directory entry read fails."""
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
                d_events = [e for e in events if e['type'] == 'd']
                handle_id = int(d_events[0]['meta']['x'])

                # Out-of-range entry with request_id
                parse_bytes(screen, client_dir_read(handle_id, 999, request_id=44))
                events = self._get_events(cap, wid)
                self.assertEqual(len(events), 1)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['meta'].get('r'), '44')
                self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_mixed_request_types_with_ids(self) -> None:
        """Mixed r/s/d request types with request_ids are processed in order."""
        import os
        import tempfile
        file_content = b'mixed request file\n'
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(file_content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (osw, wid, screen, cap):
                self._setup_uri_drop(screen, wid, cap, uri_list)

                # Queue: MIME data request, then URI file request
                parse_bytes(screen, client_request_data('text/plain', request_id=100))
                parse_bytes(screen, client_request_uri_data(0, request_id=200))

                # Serve first request (MIME data); the URI file request
                # completes synchronously right after so all output is in one batch
                dnd_test_fake_drop_data(wid, 'text/plain', b'plain text')
                raw = cap.consume(wid)
                events = parse_escape_codes_b64(raw)
                r_events_100 = [e for e in events if e['type'] == 'r' and e['meta'].get('r') == '100']
                self.assertTrue(r_events_100, 'no events with r=100')

                r_events_200 = [e for e in events if e['type'] == 'r' and e['meta'].get('r') == '200']
                self.assertTrue(r_events_200, 'no events with r=200')
                combined = b''.join(e['payload'] for e in r_events_200)
                self.ae(combined, file_content)
        finally:
            os.unlink(fpath)

    def test_finish_after_queued_requests(self) -> None:
        """A finish (empty t=r) after queued requests processes remaining then finishes."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # Queue: data request then finish
            parse_bytes(screen, client_request_data('text/plain', request_id=5))
            parse_bytes(screen, client_request_data(''))  # finish

            # Serve the data request
            dnd_test_fake_drop_data(wid, 'text/plain', b'data before finish')
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events')
            for ev in r_events:
                self.ae(ev['meta'].get('r'), '5')

    def test_multiple_sync_errors_processed_immediately(self) -> None:
        """Multiple queued requests that all fail synchronously are processed immediately."""
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 0, 0, 0, 0)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # Queue three requests for unknown MIMEs
            parse_bytes(screen, client_request_data('image/png', request_id=1))
            parse_bytes(screen, client_request_data('image/gif', request_id=2))
            parse_bytes(screen, client_request_data('image/jpeg', request_id=3))

            # All three errors should be available immediately
            raw = cap.consume(wid)
            events = parse_escape_codes(raw)
            err_events = [e for e in events if e['type'] == 'R']
            self.assertEqual(len(err_events), 3, f'expected 3 errors, got {len(err_events)}: {err_events}')
            self.ae(err_events[0]['meta'].get('r'), '1')
            self.ae(err_events[1]['meta'].get('r'), '2')
            self.ae(err_events[2]['meta'].get('r'), '3')
            for ev in err_events:
                self.ae(ev['payload'].strip(), b'ENOENT')

    def test_request_id_backward_compat_full_flow(self) -> None:
        """Full drop flow without request_id (backward compatibility) still works."""
        payload_data = b'backward compat data'
        with dnd_test_window() as (osw, wid, screen, cap):
            parse_bytes(screen, client_register('text/plain'))
            dnd_test_set_mouse_pos(wid, 2, 3, 16, 24)
            dnd_test_fake_drop_event(wid, True, ['text/plain'])
            cap.consume(wid)

            # Request without request_id
            parse_bytes(screen, client_request_data('text/plain'))
            dnd_test_fake_drop_data(wid, 'text/plain', payload_data)
            raw = cap.consume(wid)
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events)
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, payload_data)
            # Verify no r= in metadata
            for ev in r_events:
                self.assertNotIn('r', ev['meta'])

            # Finish
            parse_bytes(screen, client_request_data(''))
            self._assert_no_output(cap, wid)
