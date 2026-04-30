#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import re
from base64 import standard_b64encode
from contextlib import contextmanager
from functools import partial

from kitty.fast_data_types import (
    DND_CODE,
    Screen,
    StreamingBase64Decoder,
    dnd_set_test_write_func,
    dnd_test_cleanup_fake_window,
    dnd_test_create_fake_window,
    dnd_test_drag_notify,
    dnd_test_fake_drop_data,
    dnd_test_fake_drop_event,
    dnd_test_force_drag_dropped,
    dnd_test_request_drag_data,
    dnd_test_set_mouse_pos,
)
from kitty.machine_id import machine_id

from . import BaseTest, parse_bytes

# ---- helpers ----------------------------------------------------------------

def _osc(payload: str) -> bytes:
    """Wrap *payload* in an OSC escape sequence (OSC payload ST)."""
    return f'\x1b]{payload}\x1b\\'.encode()


def client_register(mimes: str = '', client_id: int = 0) -> bytes:
    """Escape code a client sends to start accepting drops (t=a)."""


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


def client_request_data(idx: int = 0, client_id: int = 0) -> bytes:
    """Escape code a client sends to request data (t=r:x=idx) or finish the drop (t=r with no x).

    *idx*: 1-based index into the list of MIME types. 0 or omitted means finish.
    """
    meta = f'{DND_CODE};t=r'
    if idx > 0:
        meta += f':x={idx}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_request_uri_data(mime_idx: int, file_idx: int, client_id: int = 0) -> bytes:
    """Escape code a client sends to request a file from the URI list (t=r:x=mime_idx:y=file_idx).

    *mime_idx*: 1-based index of text/uri-list in the MIME list.
    *file_idx*: 1-based index into the URI list entries.
    """
    meta = f'{DND_CODE};t=r:x={mime_idx}:y={file_idx}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_dir_read(handle_id: int, entry_num: int | None = None, client_id: int = 0) -> bytes:
    """Escape code for a directory request (t=r:Y=handle[:x=entry_num]).

    * entry_num=None → close the directory handle.
    * entry_num>=1   → read that entry (1-based).
    """
    meta = f'{DND_CODE};t=r:Y={handle_id}'
    if entry_num is not None:
        meta += f':x={entry_num}'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


# ---- drag source helpers ----------------------------------------------------

def client_drag_register(client_id: int = 0) -> bytes:
    """Escape code a client sends to start offering drags (t=o, no payload)."""
    meta = f'{DND_CODE};t=o:x=1'
    if client_id:
        meta += f':i={client_id}'
    return _osc(meta)


def client_drag_unregister(client_id: int = 0) -> bytes:
    """Escape code a client sends to stop offering drags (t=O)."""
    meta = f'{DND_CODE};t=o:x=2'
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


def client_remote_file(
    uri_idx: int = 0, data_b64: str = '', *,
    item_type: int = 0, more: bool = False,
    parent_handle: int = 0, entry_num: int = 0,
    client_id: int = 0,
) -> bytes:
    """Escape code for remote file data (t=k).

    *uri_idx*: 1-based index into the URI list (x= key).
    *item_type*: 0=file, 1=symlink, >1=directory handle (X= key).
    *more*: whether more data follows (m= key).
    *parent_handle*: directory handle for subdirectory entries (Y= key), 0 for top-level.
    *entry_num*: 1-based entry number within the directory (y= key).
    """
    meta = f'{DND_CODE};t=k:x={uri_idx}:X={item_type}'
    if parent_handle:
        meta += f':Y={parent_handle}:y={entry_num}'
    if more:
        meta += ':m=1'
    if client_id:
        meta += f':i={client_id}'
    if data_b64:
        return _osc(f'{meta};{data_b64}')
    return _osc(meta)


def client_remote_file_finish(client_id: int = 0) -> bytes:
    """Escape code signaling completion of all remote file data (t=k with no keys)."""
    meta = f'{DND_CODE};t=k'
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
        d = StreamingBase64Decoder()
        decoded = b''
        decoded_chunks = []
        for c in entry['chunks']:
            dec = d.decode(c)
            decoded_chunks.append(dec)
            decoded += dec
        # if d.needs_more_data():
        #     raise AssertionError('Incomplete base64 data')
        entry['payload'] = decoded
        entry['chunks'] = decoded_chunks
    return result


def is_dir_event(e: dict) -> bool:
    """Return True if the event is a directory listing response (X > 1)."""
    try:
        return int(e['meta'].get('X', '0')) > 1
    except (ValueError, TypeError):
        return False


def dir_handle(e: dict) -> int:
    """Return the directory handle from a directory listing event (value of X)."""
    return int(e['meta']['X'])


# ---- test context manager ---------------------------------------------------

class WriteCapture:
    """Accumulates bytes delivered by the DnD write interceptor."""

    def __init__(self) -> None:
        self._buf: dict[int, bytearray] = {}
        self.window_id = 0

    def __call__(self, window_id: int, data: bytes) -> None:
        self._buf.setdefault(window_id, bytearray())
        self._buf[window_id] += data

    def consume(self, window_id: int = 0) -> bytes:
        """Return and clear all buffered data for *window_id*."""
        buf = self._buf.pop(window_id or self.window_id, bytearray())
        return bytes(buf)

    def peek(self, window_id: int = 0) -> bytes:
        return bytes(self._buf.get(window_id or self.window_id, bytearray()))


@contextmanager
def dnd_test_window(mime_list_cap=0, present_data_cap=0, remote_drag_limit=0):
    """Context manager that creates a fake window + write-capture harness.

    Yields (window_id, screen, capture) where:
    * ``screen``       – Screen object whose window_id matches the fake window
    * ``capture``      – WriteCapture accumulating bytes sent to the child
    """
    capture = WriteCapture()
    dnd_set_test_write_func(capture, mime_list_cap, present_data_cap, remote_drag_limit)
    os_window_id, window_id = dnd_test_create_fake_window()
    capture.window_id = window_id
    try:
        screen = Screen(None, 24, 80, 0, 0, 0, window_id)
        yield screen, capture
    finally:
        dnd_set_test_write_func(None)
        dnd_test_cleanup_fake_window(os_window_id)


machine_id = partial(machine_id, 'tty-dnd-protocol-machine-id')

# ---- test class -------------------------------------------------------------

class TestDnDProtocol(BaseTest):

    def _assert_no_output(self, capture: WriteCapture) -> None:
        self.ae(capture.peek(), b'', 'unexpected output to child')

    def _register_for_drops(
        self, screen, cap, mimes='text/plain text/uri-list', client_id=0, register_machine_id=True
    ) -> None:
        meta = f'{DND_CODE};t=a'
        if client_id:
            meta += f':i={client_id}'
        r = _osc(f'{meta};{mimes}')
        parse_bytes(screen, r)
        if register_machine_id:
            if not isinstance(register_machine_id, str):
                register_machine_id = machine_id()
            parse_bytes(screen, _osc(f'{DND_CODE};t=a:x=1;1:{register_machine_id}'))
        self._assert_no_output(cap)

    def _get_events(self, capture: WriteCapture) -> list[dict]:
        return parse_escape_codes(capture.consume())

    def test_register_and_unregister(self) -> None:
        """Client can register and unregister for drops."""
        with dnd_test_window() as (screen, cap):
            # Client registers – state is already wanted=True from fake-window creation,
            # but calling the escape code should not break things.
            self._register_for_drops(screen, cap)
            # Client unregisters.
            parse_bytes(screen, client_unregister())
            self._assert_no_output(cap)

    def test_drop_move_sends_move_event(self) -> None:
        """A drop entering and moving over the window generates t=m events."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 5, 3, 100, 60)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain', 'text/uri-list'])

            events = self._get_events(cap)
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
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            mimes = ['text/plain']
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, False, mimes)
            cap.consume()  # discard first event

            # Second move with same mimes – list is still included.
            dnd_test_set_mouse_pos(cap.window_id, 1, 0, 8, 0)
            dnd_test_fake_drop_event(cap.window_id, False, mimes)
            raw = cap.consume(cap.window_id)
            events = parse_escape_codes(raw)
            self.assertEqual(len(events), 1, raw)
            self.ae(events[0]['type'], 'm')
            self.assertIn(b'text/plain', events[0]['payload'])

    def test_drop_leave_sends_leave_event(self) -> None:
        """Drop leaving sends t=m with x=-1,y=-1."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain'])
            cap.consume()

            dnd_test_fake_drop_event(cap.window_id, False, None)  # None → leave
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            ev = events[0]
            self.ae(ev['type'], 'm')
            self.ae(ev['meta'].get('x'), '-1')
            self.ae(ev['meta'].get('y'), '-1')

    def test_client_accepts_drop(self) -> None:
        """Client sending t=m:o=1 is recorded and does not trigger extra output."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain'])
            cap.consume()

            # Client accepts with copy operation.
            parse_bytes(screen, client_accept(1, 'text/plain'))
            # No immediate output expected.
            self._assert_no_output(cap)

    def test_full_drop_flow(self) -> None:
        """Complete happy-path: move → accept → drop → request → data → finish."""
        payload_data = b'hello world'
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')

            # Move
            dnd_test_set_mouse_pos(cap.window_id, 2, 3, 16, 24)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain'])
            cap.consume()

            # Client accepts
            parse_bytes(screen, client_accept(1, 'text/plain'))

            # OS drops
            dnd_test_set_mouse_pos(cap.window_id, 2, 3, 16, 24)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'M')
            self.assertIn(b'text/plain', events[0]['payload'])

            # Client requests data (idx=1 for 'text/plain', first in the MIME list)
            parse_bytes(screen, client_request_data(1))

            # OS delivers data
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', payload_data)
            raw = cap.consume()
            data_events = parse_escape_codes_b64(raw)
            # Should have data chunks plus an empty terminator
            self.assertTrue(len(data_events) >= 1, data_events)
            combined = b''.join(e['payload'] for e in data_events if e['type'] == 'r')
            self.ae(combined, payload_data)

            # Client finishes
            parse_bytes(screen, client_request_data())
            self._assert_no_output(cap)

    def test_request_unknown_mime(self) -> None:
        """Requesting an out-of-range MIME index yields an error."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            # Client requests index 99 which is out of range.
            parse_bytes(screen, client_request_data(99))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_data_error_propagation(self) -> None:
        """When data retrieval fails the client receives a t=R error code."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))

            # Simulate I/O error (EIO = 5 on Linux)
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'', errno.EIO)
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EIO')

    def test_data_eperm_error(self) -> None:
        """EPERM error is correctly forwarded to the client."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'', errno.EPERM)
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EPERM')

    def test_large_data_chunking(self) -> None:
        """Data larger than the chunk limit is sent in multiple base64 chunks."""
        # Each chunk is ≤ 3072 bytes of raw data (base64-encoded to ≤ 4096 bytes).
        chunk_limit = 3072
        big_payload = b'X' * (chunk_limit * 3)  # 3 chunks expected
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', big_payload)
            raw = cap.consume()
            data_events = parse_escape_codes_b64(raw)
            combined = b''.join(e['payload'] for e in data_events if e['type'] == 'r')
            self.ae(combined, big_payload)
            # Verify that we got more than one escape code (chunking happened)
            self.assertGreater(len(data_events), 1, 'expected multiple chunks')

    def test_client_id_propagated(self) -> None:
        """The client_id (i=…) set during registration is echoed in all replies."""
        client_id = 42
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, mimes='text/plain', client_id=client_id)
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain'])
            raw = cap.consume()
            events = parse_escape_codes(raw)
            self.assertEqual(len(events), 1, raw)
            self.ae(events[0]['meta'].get('i'), str(client_id))

    def test_multiple_mimes_priority(self) -> None:
        """The client can request data from any offered MIME type by index."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain text/uri-list')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            # OS offers both types.
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain', 'text/uri-list'])
            cap.consume()

            # Request text/uri-list (idx=2, since it's the 2nd in the offered list).
            parse_bytes(screen, client_request_data(2))
            dnd_test_fake_drop_data(cap.window_id, 'text/uri-list', b'file:///tmp/test\n')
            raw = cap.consume()
            data_events = parse_escape_codes_b64(raw)
            combined = b''.join(e['payload'] for e in data_events if e['type'] == 'r')
            self.ae(combined, b'file:///tmp/test\n')

    def test_drop_without_register_no_output(self) -> None:
        """If the client has not registered, no escape codes are sent on drop."""
        with dnd_test_window() as (screen, cap):
            # Explicitly unregister (clears the wanted flag).
            parse_bytes(screen, client_unregister())
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            # Fake window is created with wanted=True; after unregister it should be False.
            # drop_move_on_child only sends if w->drop.wanted is true, which is handled
            # by the caller (on_drop in glfw.c checks w->drop.wanted before calling).
            # Here we call drop_left_child which checks w->drop.wanted.
            dnd_test_fake_drop_event(cap.window_id, False, None)
            self._assert_no_output(cap)

    def test_malformed_dnd_command_invalid_type(self) -> None:
        """A DnD command with an unknown type character is silently ignored."""
        with dnd_test_window() as (screen, cap):
            # 'z' is not a valid type; the parser should emit an error and return
            # without calling any handler – no crash, no output.
            bad_cmd = _osc(f'{DND_CODE};t=z;')
            parse_bytes(screen, bad_cmd)
            self._assert_no_output(cap)

    def test_move_event_after_mime_change(self) -> None:
        """When offered MIME list changes, the new list is included in the move event."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain'])
            cap.consume()

            # Second move with a different MIME list – list must be re-sent.
            dnd_test_set_mouse_pos(cap.window_id, 1, 0, 8, 0)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/html', 'text/plain'])
            raw = cap.consume()
            events = parse_escape_codes(raw)
            self.assertEqual(len(events), 1, raw)
            self.assertIn(b'text/html', events[0]['payload'])

    def test_drop_event_has_uppercase_M(self) -> None:
        """A drop (not just a move) sends t=M (uppercase)."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'M')

    def test_data_end_signal(self) -> None:
        """The end-of-data signal is an empty payload escape code."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'hello')
            raw = cap.consume()
            events = parse_escape_codes(raw)
            # Last event must be an empty (end-of-stream) t=r.
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events found')
            last = r_events[-1]
            self.ae(last['payload'], b'')

    def test_empty_data(self) -> None:
        """Zero-byte payload is handled gracefully – only end signal is sent."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'')
            raw = cap.consume()
            events = parse_escape_codes(raw)
            r_events = [e for e in events if e['type'] == 'r']
            # Only the end signal should be present.
            self.assertEqual(len(r_events), 1, raw)
            self.ae(r_events[0]['payload'], b'')

    # ---- remote file/directory transfer tests ----------------

    def _setup_uri_drop(self, screen, cap, uri_list_data: bytes, mimes=None):
        """Register, drop, deliver text/uri-list data, discard move/drop events."""
        if mimes is None:
            mimes = ['text/plain', 'text/uri-list']
        self._register_for_drops(screen, cap, 'text/plain text/uri-list', register_machine_id='remote')
        dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
        dnd_test_fake_drop_event(cap.window_id, True, mimes)
        cap.consume()
        # Client requests and receives the URI list (idx=2 for text/uri-list in the default MIME list)
        uri_idx = mimes.index('text/uri-list') + 1  # 1-based
        parse_bytes(screen, client_request_data(uri_idx))
        dnd_test_fake_drop_data(cap.window_id, 'text/uri-list', uri_list_data)
        events = parse_escape_codes_b64(cap.consume())
        self.assertEqual(events[0]['meta']['X'], '1')

    def test_uri_file_transfer_basic(self) -> None:
        """URI file request sends the content of a regular file as t=r chunks."""
        import os
        import tempfile
        content = b'Hello, remote DnD world!\n' * 100
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                # Exclude the empty end-of-data entry when concatenating
                combined = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(combined, content)
        finally:
            os.unlink(fpath)

    def test_uri_file_transfer_enoent(self) -> None:
        """URI file request with an out-of-range index returns ENOENT."""
        uri_list = b'file:///tmp/no_such_file_exists_dnd_test_xyz\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_uri_drop(screen, cap, uri_list)
            # File at index 1 does not exist
            parse_bytes(screen, client_request_uri_data(2, 1))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.assertIn(events[0]['payload'].strip(), [b'ENOENT', b'EPERM'])

    def test_uri_file_transfer_out_of_bounds(self) -> None:
        """URI file request with an index beyond the URI list returns ENOENT."""
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 100))  # out of range
                events = self._get_events(cap)
                self.assertEqual(len(events), 1, events)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['payload'].strip(), b'ENOENT')
        finally:
            os.unlink(fpath)

    def test_uri_request_without_uri_list_returns_einval(self) -> None:
        """URI file request without prior text/uri-list request returns EINVAL."""
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fpath = f.name
        try:
            with dnd_test_window() as (screen, cap):
                self._register_for_drops(screen, cap, 'text/plain')
                dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
                dnd_test_fake_drop_event(cap.window_id, True, ['text/plain', 'text/uri-list'])
                cap.consume()
                # Do NOT request text/uri-list first
                parse_bytes(screen, client_request_uri_data(2, 1))
                events = self._get_events(cap)
                self.assertEqual(len(events), 1, events)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['payload'].strip(), b'EINVAL')
        finally:
            os.unlink(fpath)

    def test_uri_non_regular_file_returns_einval(self) -> None:
        """URI file request for a non-regular file (e.g. /dev/null) returns EINVAL."""
        uri_list = b'file:///dev/null\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_uri_drop(screen, cap, uri_list)
            parse_bytes(screen, client_request_uri_data(2, 1))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_uri_broken_symlink_returns_symlink_target(self) -> None:
        """A broken symlink in the URI list is transmitted as a symlink (X=1) with the target."""
        import os
        import tempfile
        import uuid
        does_not_exist = '/' + str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as root:
            broken_link = os.path.join(root, 'broken.txt')
            os.symlink(does_not_exist, broken_link)
            uri_list = f'file://{broken_link}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'expected t=r response for broken symlink')
                self.assertEqual(r_events[0]['meta'].get('X'), '1',
                                 'broken symlink response must have X=1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, does_not_exist.encode())

    def test_uri_non_broken_symlink_to_file_transmitted_as_symlink(self) -> None:
        """A non-broken symlink to a regular file is transmitted as a symlink (X=1) with the target path."""
        import os
        import tempfile
        content = b'content of the real file\n' * 10
        with tempfile.TemporaryDirectory() as root:
            real_file = os.path.join(root, 'real.txt')
            with open(real_file, 'wb') as f:
                f.write(content)
            link_path = os.path.join(root, 'link.txt')
            os.symlink(real_file, link_path)
            uri_list = f'file://{link_path}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'expected t=r response for symlink to file')
                self.assertEqual(r_events[0]['meta'].get('X'), '1',
                                 'symlink to file must have X=1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, real_file.encode())

    def test_uri_non_broken_symlink_to_directory_transmitted_as_symlink(self) -> None:
        """A non-broken symlink to a directory is transmitted as a symlink (X=1) with the target path."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            real_dir = os.path.join(root, 'realdir')
            os.makedirs(real_dir)
            with open(os.path.join(real_dir, 'inside.txt'), 'w') as f:
                f.write('hello')
            link_path = os.path.join(root, 'linkdir')
            os.symlink(real_dir, link_path)
            uri_list = f'file://{link_path}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'expected t=r response for symlink to directory')
                self.assertEqual(r_events[0]['meta'].get('X'), '1',
                                 'symlink to directory must have X=1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, real_dir.encode())

    def test_uri_directory_transfer_tree(self) -> None:
        """Full directory tree (>= 3 levels deep) transfer: listing, sub-dirs, file integrity.

        Also verifies that every response from the terminal unambiguously
        identifies the filesystem object it refers to.  For sub-directory
        listing responses the echoed Y= (parent handle) and x= (1-based entry
        index within the parent) together with X= (new child handle) make the
        response unambiguous.  For file/error responses Y= and x= alone
        suffice.
        """
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)

                # Request the root directory (mime_idx=2, file_idx=1)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                self.assertTrue(d_events, 'expected directory listing for root')

                root_listing_payload = b''.join(
                    chunk for e in d_events for chunk in e['chunks'] if chunk
                )
                root_handle_id = dir_handle(d_events[0])
                self.assertGreater(root_handle_id, 1,
                                   'root directory handle (X=) must be > 1')
                # For a top-level URI request the response echoes x= and y= from the
                # request; Y= must be absent because the request had no Y.
                for ev in d_events:
                    self.ae(ev['meta'].get('x'), '2',
                            'mime index must be echoed in root dir response')
                    self.ae(ev['meta'].get('y'), '1',
                            'file index must be echoed in root dir response')
                    self.assertIsNone(ev['meta'].get('Y'),
                                      'Y= must not be present in top-level dir response')

                # Decode null-separated entries (no unique identifier prefix)
                root_entries = [e for e in root_listing_payload.split(b'\x00') if e]
                entry_names = {e.decode() for e in root_entries}
                self.assertIn('a.txt', entry_names)
                self.assertIn('b', entry_names)

                # Find index of 'a.txt' in the entries list (1-based)
                entries_list = [e.decode() for e in root_entries]
                a_idx = entries_list.index('a.txt') + 1
                b_idx = entries_list.index('b') + 1

                # Read a.txt — response must echo Y=root_handle_id, x=a_idx
                parse_bytes(screen, client_dir_read(root_handle_id, a_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                for ev in r_events:
                    self.ae(ev['meta'].get('Y'), str(root_handle_id),
                            'parent handle must be echoed in file response')
                    self.ae(ev['meta'].get('x'), str(a_idx),
                            'entry index must be echoed in file response')
                a_data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(a_data, a_content)

                # Read sub-directory b → should get a new directory listing
                # Response must echo Y=root_handle_id, x=b_idx; X= is new handle
                parse_bytes(screen, client_dir_read(root_handle_id, b_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                b_d_events = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                self.assertTrue(b_d_events, 'expected directory listing for b/')

                b_listing_payload = b''.join(
                    chunk for e in b_d_events for chunk in e['chunks'] if chunk
                )
                b_handle_id = dir_handle(b_d_events[0])
                self.assertNotEqual(b_handle_id, root_handle_id)
                # Unambiguous identification: the response must identify both the
                # parent dir (Y=) and the entry within it (x=).
                for ev in b_d_events:
                    self.ae(ev['meta'].get('Y'), str(root_handle_id),
                            'parent handle must be echoed in sub-dir listing response')
                    self.ae(ev['meta'].get('x'), str(b_idx),
                            'entry index must be echoed in sub-dir listing response')

                b_entries = [e for e in b_listing_payload.split(b'\x00') if e]
                b_names = {e.decode() for e in b_entries}
                self.assertIn('c.txt', b_names)
                self.assertIn('d', b_names)

                b_entries_list = [e.decode() for e in b_entries]
                bc_idx = b_entries_list.index('c.txt') + 1
                bd_idx = b_entries_list.index('d') + 1

                # Read b/c.txt (binary integrity); response echoes Y=b_handle_id, x=bc_idx
                parse_bytes(screen, client_dir_read(b_handle_id, bc_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                for ev in r_events:
                    self.ae(ev['meta'].get('Y'), str(b_handle_id),
                            'parent handle must be echoed in file response')
                    self.ae(ev['meta'].get('x'), str(bc_idx),
                            'entry index must be echoed in file response')
                bc_data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(bc_data, bc_content)
                # Check SHA-256 integrity
                self.ae(hashlib.sha256(bc_data).digest(),
                        hashlib.sha256(bc_content).digest())

                # Read sub-directory b/d → yet another directory listing (level 3)
                # Response must echo Y=b_handle_id, x=bd_idx; X= is new handle
                parse_bytes(screen, client_dir_read(b_handle_id, bd_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                bd_d_events = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                self.assertTrue(bd_d_events, 'expected directory listing for b/d/')

                bd_listing_payload = b''.join(
                    chunk for e in bd_d_events for chunk in e['chunks'] if chunk
                )
                bd_handle_id = dir_handle(bd_d_events[0])
                # Unambiguous identification for third-level directory.
                for ev in bd_d_events:
                    self.ae(ev['meta'].get('Y'), str(b_handle_id),
                            'parent handle must be echoed in level-3 sub-dir listing response')
                    self.ae(ev['meta'].get('x'), str(bd_idx),
                            'entry index must be echoed in level-3 sub-dir listing response')

                bd_entries = [e for e in bd_listing_payload.split(b'\x00') if e]
                bd_names = {e.decode() for e in bd_entries}
                self.assertIn('e.txt', bd_names)

                bd_entries_list = [e.decode() for e in bd_entries]
                bde_idx = bd_entries_list.index('e.txt') + 1

                # Read b/d/e.txt; response echoes Y=bd_handle_id, x=bde_idx
                parse_bytes(screen, client_dir_read(bd_handle_id, bde_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                for ev in r_events:
                    self.ae(ev['meta'].get('Y'), str(bd_handle_id),
                            'parent handle must be echoed in deep file response')
                    self.ae(ev['meta'].get('x'), str(bde_idx),
                            'entry index must be echoed in deep file response')
                bde_data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(bde_data, bde_content)

                # Close all directory handles
                parse_bytes(screen, client_dir_read(bd_handle_id))
                parse_bytes(screen, client_dir_read(b_handle_id))
                parse_bytes(screen, client_dir_read(root_handle_id))
                # No error output expected from close operations
                self._assert_no_output(cap)

    def test_dir_handle_close_and_reuse(self) -> None:
        """Closing a directory handle invalidates it; subsequent requests return EINVAL."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'f.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                self.assertTrue(d_ev)
                hid = dir_handle(d_ev[0])

                # Close the handle
                parse_bytes(screen, client_dir_read(hid))
                self._assert_no_output(cap)

                # Now try to read from the closed handle → EINVAL
                parse_bytes(screen, client_dir_read(hid, 1))
                events = self._get_events(cap)
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                hid = dir_handle(d_ev[0])

                # Entry 999 does not exist
                parse_bytes(screen, client_dir_read(hid, 999))
                events = self._get_events(cap)
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = dir_handle(d_ev[0])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                self.assertIn('link.txt', entries)
                self.assertIn('real.txt', entries)
                link_idx = entries.index('link.txt') + 1

                # Read the symlink entry → should get t=r with X=1 and target path
                parse_bytes(screen, client_dir_read(hid, link_idx))
                raw = cap.consume()
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = dir_handle(d_ev[0])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                self.assertIn('link_to_dir', entries)
                link_idx = entries.index('link_to_dir') + 1

                # Read the symlink → should get t=r with X=1
                parse_bytes(screen, client_dir_read(hid, link_idx))
                raw = cap.consume()
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = dir_handle(d_ev[0])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                link_idx = entries.index('abs_link.txt') + 1

                parse_bytes(screen, client_dir_read(hid, link_idx))
                raw = cap.consume()
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = dir_handle(d_ev[0])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                reg_idx = entries.index('regular.txt') + 1

                parse_bytes(screen, client_dir_read(hid, reg_idx))
                raw = cap.consume()
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                hid = dir_handle(d_ev[0])
                entries = [e.decode() for e in payload.split(b'\x00') if e]

                # Read regular file
                data_idx = entries.index('data.bin') + 1
                parse_bytes(screen, client_dir_read(hid, data_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertNotEqual(r_events[0]['meta'].get('X'), '1')
                self.ae(b''.join(e['payload'] for e in r_events if e['payload']),
                        b'\x00\x01\x02\x03')

                # Read symlink
                alias_idx = entries.index('alias.bin') + 1
                parse_bytes(screen, client_dir_read(hid, alias_idx))
                raw = cap.consume()
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                root_hid = dir_handle(d_ev[0])
                entries = [e.decode() for e in payload.split(b'\x00') if e]
                sub_idx = entries.index('sub') + 1

                # Open subdirectory
                parse_bytes(screen, client_dir_read(root_hid, sub_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                sub_payload = b''.join(
                    chunk for e in d_ev for chunk in e['chunks'] if chunk
                )
                sub_hid = dir_handle(d_ev[0])
                sub_entries = [e.decode() for e in sub_payload.split(b'\x00') if e]
                self.assertIn('nested_link.txt', sub_entries)

                link_idx = sub_entries.index('nested_link.txt') + 1
                parse_bytes(screen, client_dir_read(sub_hid, link_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertEqual(r_events[0]['meta'].get('X'), '1')
                self.ae(b''.join(e['payload'] for e in r_events if e['payload']),
                        b'target.txt')

    def test_dir_entry_one_based_index(self) -> None:
        """Directory entry index 1 reads the first entry (1-based)."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'first.txt'), 'w') as f:
                f.write('first file')
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_ev = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                hid = dir_handle(d_ev[0])

                # Index 1 should read the first entry
                parse_bytes(screen, client_dir_read(hid, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'entry index 1 should read the first entry')
                data = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(data, b'first file')

    def test_top_level_symlink_to_file_transmitted_as_symlink(self) -> None:
        """Top-level symlink in URI list is transmitted as a symlink (X=1) with the target path."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            real = os.path.join(root, 'real.txt')
            with open(real, 'w') as f:
                f.write('resolved content')
            link = os.path.join(root, 'link.txt')
            os.symlink(real, link)
            uri_list = f'file://{link}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'top-level symlink to file should be transmitted as symlink')
                self.assertEqual(r_events[0]['meta'].get('X'), '1',
                                 'top-level symlink to file must have X=1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, real.encode())

    def test_top_level_symlink_to_dir_transmitted_as_symlink(self) -> None:
        """Top-level symlink to directory in URI list is transmitted as a symlink (X=1) with the target path."""
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
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'top-level symlink to dir should be transmitted as symlink')
                self.assertEqual(r_events[0]['meta'].get('X'), '1',
                                 'top-level symlink to directory must have X=1')
                target = b''.join(e['payload'] for e in r_events if e['payload'])
                self.ae(target, sub.encode())

    def test_window_close_during_transfer_no_leak(self) -> None:
        """Closing the window while dir handles are open frees all resources (no crash)."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'f.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            # The context manager calls dnd_test_cleanup_fake_window on exit,
            # which calls drop_free_data → drop_free_dir_handles.
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                cap.consume()
                # Intentionally leave the handle open – cleanup happens in __exit__

    # ---- Drag source (t=o, t=O, t=p, t=P, t=e, t=E) tests ------------------

    def _setup_drag_offer(self, screen, cap, mimes: str = 'text/plain', operations: int = 1, client_id: int = 0):
        """Send t=o with operations and payload to set up a drag offer being built."""
        parse_bytes(screen, client_drag_register())
        parse_bytes(screen, client_drag_offer_mimes(operations, mimes, client_id=client_id))
        cap.consume()  # discard any output

    def test_drag_register_and_unregister(self) -> None:
        """Client can register and unregister willingness to offer drags."""
        with dnd_test_window() as (screen, cap):
            # Register for drag offers (t=o, no payload).
            parse_bytes(screen, client_drag_register())
            self._assert_no_output(cap)

            # Unregister (t=O).
            parse_bytes(screen, client_drag_unregister())
            self._assert_no_output(cap)

    def test_drag_offer_single_mime(self) -> None:
        """Client can offer a drag with a single MIME type."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            # No error expected – the offer is being built.
            self._assert_no_output(cap)

    def test_drag_offer_multiple_mimes(self) -> None:
        """Client can offer a drag with multiple MIME types."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(3, 'text/plain text/uri-list application/json'))
            self._assert_no_output(cap)

    def test_drag_offer_no_operations_returns_einval(self) -> None:
        """Offering MIME types with operations=0 (no valid operations) returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            # First need a valid offer to set allowed_operations, but if we pass o=0
            # directly and there's no prior offer, drag_add_mimes should abort with EINVAL.
            parse_bytes(screen, client_drag_offer_mimes(0, 'text/plain'))
            self.assert_error(cap)

    def test_drag_offer_copy_only(self) -> None:
        """Offering with operations=1 (copy only) is accepted."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            self._assert_no_output(cap)

    def test_drag_offer_move_only(self) -> None:
        """Offering with operations=2 (move only) is accepted."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(2, 'text/plain'))
            self._assert_no_output(cap)

    def test_drag_offer_copy_and_move(self) -> None:
        """Offering with operations=3 (copy+move) is accepted."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(3, 'text/plain text/html'))
            self._assert_no_output(cap)

    def test_drag_pre_send_data_valid(self) -> None:
        """Pre-sending data for a valid MIME index succeeds."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain text/html')
            data = standard_b64encode(b'hello pre-sent').decode()
            # Send data for index 0 (text/plain)
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap)

    def test_drag_pre_send_data_out_of_range_returns_einval(self) -> None:
        """Pre-sending data for an out-of-range MIME index returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            data = standard_b64encode(b'some data').decode()
            # Index 5 is out of range (we only offered one MIME type)
            parse_bytes(screen, client_drag_pre_send(5, data))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_pre_send_data_moderate_chunk(self) -> None:
        """Pre-sending a moderate chunk of data succeeds without triggering size cap."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # The size cap is 64MB (PRESENT_DATA_CAP = 64 * 1024 * 1024).
            # We can't realistically send 64MB in a unit test, so we verify
            # that a moderate chunk is accepted without error.
            chunk_raw = b'X' * 3072  # 3072 bytes = 4096 base64
            chunk_b64 = standard_b64encode(chunk_raw).decode()
            parse_bytes(screen, client_drag_pre_send(0, chunk_b64))
            self._assert_no_output(cap)

    def test_drag_pre_send_without_offer_returns_einval(self) -> None:
        """Pre-sending data without a prior offer returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            data = standard_b64encode(b'orphan data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_image_rgba_valid(self) -> None:
        """Adding a valid RGBA image succeeds without error."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # 2x2 RGBA image = 2*2*4 = 16 bytes
            pixel_data = b'\xff\x00\x00\xff' * 4  # 4 red pixels
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            self._assert_no_output(cap)

    def test_drag_add_image_rgb_valid(self) -> None:
        """Adding a valid RGB image succeeds without error."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # 2x2 RGB image = 2*2*3 = 12 bytes
            pixel_data = b'\xff\x00\x00' * 4  # 4 red pixels (RGB)
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 24, 2, 2, data_b64))
            self._assert_no_output(cap)

    def test_drag_add_image_invalid_format_returns_einval(self) -> None:
        """Adding an image with an invalid format (not 24/32/100) returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            pixel_data = b'\xff\x00\x00' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            # fmt=16 is invalid
            parse_bytes(screen, client_drag_add_image(1, 16, 2, 2, data_b64))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_image_invalid_dimensions_returns_einval(self) -> None:
        """Adding an image with zero or negative dimensions returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            pixel_data = b'\xff\x00\x00' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            # width=0 is invalid
            parse_bytes(screen, client_drag_add_image(1, 24, 0, 2, data_b64))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_image_without_offer_returns_einval(self) -> None:
        """Adding an image without a prior drag offer returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            pixel_data = b'\xff\x00\x00\xff' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_add_too_many_images_returns_error(self) -> None:
        """Adding more than the maximum number of images returns an error."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            pixel_data = b'\xff\x00\x00\xff' * 4  # 2x2 RGBA
            data_b64 = standard_b64encode(pixel_data).decode()
            # The images array has 16 slots (indices 0..15).
            # The check is idx + 1 >= arraysz (16), so valid indices are 0..14.
            # Client 1-based idx maps to C idx via x=-idx, so valid client indices
            # are 1..14 (14 images). First 14 images should succeed.
            for i in range(1, 15):
                parse_bytes(screen, client_drag_add_image(i, 32, 2, 2, data_b64))
            self._assert_no_output(cap)

            # Image 15 (C idx=15) should fail with an error (EFBIG)
            parse_bytes(screen, client_drag_add_image(15, 32, 2, 2, data_b64))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')

    def test_drag_start_no_real_window_returns_einval_or_eperm(self) -> None:
        """Starting a drag with a fake window (no GLFW handle) returns EINVAL or EPERM."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Try to start the drag – the fake window has no osw->handle, so
            # start_window_drag returns EINVAL.
            parse_bytes(screen, client_drag_start())
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            # Error is EINVAL because osw->handle is NULL
            self.assertIn(events[0]['payload'].strip(), [b'EINVAL', b'EPERM'])

    def test_drag_start_without_offer_returns_einval(self) -> None:
        """Starting a drag without a prior offer returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_start())
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_free_offer_cleans_up(self) -> None:
        """Sending t=O cleans up a partially built drag offer."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain text/html')
            # Pre-send some data
            data = standard_b64encode(b'test data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap)

            # Cancel the offer
            parse_bytes(screen, client_drag_unregister())
            self._assert_no_output(cap)

            # Trying to pre-send data now should fail (state is NONE)
            parse_bytes(screen, client_drag_pre_send(0, data))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_cancel_from_client(self) -> None:
        """Client can cancel a drag via t=E:y=-1."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Cancel the drag
            parse_bytes(screen, client_drag_cancel())
            self._assert_no_output(cap)

            # After cancel, state should be NONE – trying to start should fail.
            parse_bytes(screen, client_drag_start())
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['payload'].strip(), b'EINVAL')

    def test_drag_second_offer_replaces_first(self) -> None:
        """A second offer with operations replaces the first one."""
        with dnd_test_window() as (screen, cap):
            # First offer
            self._setup_drag_offer(screen, cap, 'text/plain')
            data = standard_b64encode(b'first data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap)

            # Second offer replaces the first (drag_add_mimes cancels if state != NONE)
            self._setup_drag_offer(screen, cap, 'text/html')
            # Pre-send data for the new MIME type at index 0
            data2 = standard_b64encode(b'second data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data2))
            self._assert_no_output(cap)

    def test_drag_client_id_propagated(self) -> None:
        """The client_id (i=…) set during drag offer is echoed in error replies."""
        client_id = 99
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain', client_id=client_id))
            self._assert_no_output(cap)
            # Starting the drag will fail (no real window), producing an error with client_id
            parse_bytes(screen, client_drag_start(client_id=client_id))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'E')
            self.ae(events[0]['meta'].get('i'), str(client_id))

    def test_drag_change_image_before_start(self) -> None:
        """Changing the drag image index before starting is accepted silently."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Add an image
            pixel_data = b'\xff\x00\x00\xff' * 4  # 2x2 RGBA
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            self._assert_no_output(cap)
            # Change to image index 0 (the first image)
            parse_bytes(screen, client_drag_change_image(0))
            self._assert_no_output(cap)

    def test_drag_chunked_mime_offer(self) -> None:
        """A large MIME list can be sent in chunks using m=1."""
        with dnd_test_window() as (screen, cap):
            # First chunk with m=1 (more coming)
            parse_bytes(screen, client_drag_register())
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain ', more=True))
            self._assert_no_output(cap)

            # Second (final) chunk with m=0 (default) – use the raw _osc helper
            # since client_drag_offer_mimes always sets operations, but subsequent
            # chunks should not re-set operations. The parser handles this via the
            # more flag on drag_add_mimes.
            final_chunk = _osc(f'{DND_CODE};t=o;text/html')
            parse_bytes(screen, final_chunk)
            self._assert_no_output(cap)

            # Now verify we can pre-send data for both indices
            data0 = standard_b64encode(b'data for text/plain').decode()
            data1 = standard_b64encode(b'data for text/html').decode()
            parse_bytes(screen, client_drag_pre_send(0, data0))
            self._assert_no_output(cap)
            parse_bytes(screen, client_drag_pre_send(1, data1))
            self._assert_no_output(cap)

    def test_drag_pre_send_chunked_data(self) -> None:
        """Pre-sent data can be chunked across multiple escape codes."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')

            # Split raw data at a 3-byte boundary so base64 encoding produces
            # no padding on intermediate chunks.
            raw = b'hello world data!'  # 17 bytes
            split_at = 12  # multiple of 3
            chunk1_b64 = standard_b64encode(raw[:split_at]).decode()
            chunk2_b64 = standard_b64encode(raw[split_at:]).decode()

            # Send first chunk (m=1)
            parse_bytes(screen, client_drag_pre_send(0, chunk1_b64, more=True))
            self._assert_no_output(cap)

            # Send final chunk (m=0)
            parse_bytes(screen, client_drag_pre_send(0, chunk2_b64, more=False))
            self._assert_no_output(cap)

    def test_drag_add_image_chunked(self) -> None:
        """Image data can be chunked across multiple escape codes."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # 2x2 RGBA = 16 bytes total, split at a 3-byte boundary
            pixel_data = b'\xff\x00\x00\xff' * 4  # 16 bytes
            split_at = 12  # multiple of 3
            chunk1_b64 = standard_b64encode(pixel_data[:split_at]).decode()
            chunk2_b64 = standard_b64encode(pixel_data[split_at:]).decode()

            # First chunk (m=1) with full image metadata
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, chunk1_b64, more=True))
            self._assert_no_output(cap)

            # Second chunk (m=0) – only needs x= (format/size from first chunk)
            final_img = _osc(f'{DND_CODE};t=p:x=-1;{chunk2_b64}')
            parse_bytes(screen, final_img)
            self._assert_no_output(cap)

    def test_drag_process_item_data_without_started_state_invalid(self) -> None:
        """Sending t=e data before the drag is started is silently ignored."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # State is BEING_BUILT, not STARTED – drag_process_item_data should return early
            data_b64 = standard_b64encode(b'premature data').decode()
            parse_bytes(screen, client_drag_send_data(0, data_b64))
            self.assert_error(cap)

    def test_drag_error_from_client_without_started_state_invalid(self) -> None:
        """Sending t=E with a MIME index before the drag is started is silently ignored."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # State is BEING_BUILT – sending an error for index 0 should be ignored
            parse_bytes(screen, client_drag_send_error(0, 'EIO'))
            self.assert_error(cap)

    def test_drag_offer_with_empty_mimes_after_cancel(self) -> None:
        """After cancelling, a new offer can be started from scratch."""
        with dnd_test_window() as (screen, cap):
            # Build and cancel
            self._setup_drag_offer(screen, cap, 'text/plain')
            parse_bytes(screen, client_drag_cancel())
            self._assert_no_output(cap)

            # New offer from scratch
            self._setup_drag_offer(screen, cap, 'application/octet-stream')
            data = standard_b64encode(b'binary data').decode()
            parse_bytes(screen, client_drag_pre_send(0, data))
            self._assert_no_output(cap)

    def test_drag_multiple_images_sequential(self) -> None:
        """Multiple images can be added sequentially with different indices."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Image 1: 1x1 RGBA
            img1 = standard_b64encode(b'\xff\x00\x00\xff').decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 1, 1, img1))
            self._assert_no_output(cap)
            # Image 2: 1x1 RGBA
            img2 = standard_b64encode(b'\x00\xff\x00\xff').decode()
            parse_bytes(screen, client_drag_add_image(2, 32, 1, 1, img2))
            self._assert_no_output(cap)
            # Image 3: 1x1 RGBA
            img3 = standard_b64encode(b'\x00\x00\xff\xff').decode()
            parse_bytes(screen, client_drag_add_image(3, 32, 1, 1, img3))
            self._assert_no_output(cap)

    def test_drag_offer_then_unregister_then_start_fails(self) -> None:
        """After unregistering (t=O), starting a drag (t=P:x=-1) fails."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            parse_bytes(screen, client_drag_unregister())
            self._assert_no_output(cap)

            # Attempting to start should fail since unregister called drag_free_offer
            parse_bytes(screen, client_drag_start())
            self.assert_error(cap)

    def assert_error(self, cap, code='EINVAL'):
        events = self._get_events(cap)
        self.assertEqual(len(events), 1, events)
        self.ae(events[0]['type'], 'E')
        self.ae(events[0]['payload'].strip(), code.encode())

    def test_drag_pre_send_multiple_mimes(self) -> None:
        """Pre-sent data can be provided for multiple different MIME types."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain text/html image/png')
            # Pre-send for text/plain (index 0)
            d0 = standard_b64encode(b'plain text data').decode()
            parse_bytes(screen, client_drag_pre_send(0, d0))
            self._assert_no_output(cap)
            # Pre-send for text/html (index 1)
            d1 = standard_b64encode(b'<h1>html</h1>').decode()
            parse_bytes(screen, client_drag_pre_send(1, d1))
            self._assert_no_output(cap)
            # Pre-send for image/png (index 2)
            d2 = standard_b64encode(b'\x89PNG fake data').decode()
            parse_bytes(screen, client_drag_pre_send(2, d2))
            self._assert_no_output(cap)

    def test_drag_window_close_during_build_no_crash(self) -> None:
        """Closing the window while a drag offer is being built frees resources (no crash)."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain text/html')
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
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Add one image
            pixel_data = b'\xff\x00\x00\xff' * 4
            data_b64 = standard_b64encode(pixel_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 2, 2, data_b64))
            self._assert_no_output(cap)
            # Change to a large index (out of bounds) – protocol says image should be removed
            parse_bytes(screen, client_drag_change_image(999))
            self._assert_no_output(cap)

    def test_drag_offer_then_cancel_then_new_offer(self) -> None:
        """After cancelling a drag, building a completely new offer works."""
        with dnd_test_window() as (screen, cap):
            # First offer
            self._setup_drag_offer(screen, cap, 'text/plain')
            d1 = standard_b64encode(b'data1').decode()
            parse_bytes(screen, client_drag_pre_send(0, d1))
            img = standard_b64encode(b'\xff\x00\x00\xff').decode()
            parse_bytes(screen, client_drag_add_image(1, 32, 1, 1, img))
            self._assert_no_output(cap)

            # Cancel via t=E:y=-1
            parse_bytes(screen, client_drag_cancel())
            self._assert_no_output(cap)

            # New offer with different MIMEs
            self._setup_drag_offer(screen, cap, 'application/json', operations=2)
            d2 = standard_b64encode(b'{"key":"value"}').decode()
            parse_bytes(screen, client_drag_pre_send(0, d2))
            self._assert_no_output(cap)

    def test_drag_pre_send_invalid_base64_returns_einval(self) -> None:
        """Pre-sending invalid base64 data returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Send completely invalid base64
            parse_bytes(screen, client_drag_pre_send(0, '!@#$%^&*()'))
            self.assert_error(cap)

    def test_drag_add_image_invalid_base64_returns_einval(self) -> None:
        """Adding an image with invalid base64 data returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Invalid base64 as image data
            parse_bytes(screen, client_drag_add_image(1, 32, 1, 1, '!@#$%^&*()'))
            self.assert_error(cap)

    def test_drag_start_with_image_size_mismatch(self) -> None:
        """Starting a drag when image data size doesn't match dimensions returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
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
            self.assert_error(cap)

    def test_drag_start_with_rgb_image_size_mismatch(self) -> None:
        """Starting a drag when RGB image data size doesn't match w*h*3 returns EINVAL."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Claim 2x2 RGB (12 bytes) but send 8 bytes
            wrong_data = b'\xff\x00\x00' * 2 + b'\x00\x00'  # 8 bytes, not 12
            data_b64 = standard_b64encode(wrong_data).decode()
            parse_bytes(screen, client_drag_add_image(1, 24, 2, 2, data_b64))
            # drag_start calls expand_rgb_data which checks sz == w*h*3
            parse_bytes(screen, client_drag_start())
            self.assert_error(cap)


    # ---- Request queue and disambiguation tests --------------------------------

    def test_x_key_echoed_in_data_response(self) -> None:
        """x= key is echoed in data responses to identify which request is being answered."""
        payload_data = b'hello disambiguation'
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', payload_data)
            raw = cap.consume()
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events')
            for ev in r_events:
                self.ae(ev['meta'].get('x'), '1')

    def test_x_key_echoed_in_error_response(self) -> None:
        """x= key is echoed in error responses."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            # Request out-of-range index -> error
            parse_bytes(screen, client_request_data(99))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('x'), '99')
            self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_x_key_in_error_for_io_failure(self) -> None:
        """x= key is echoed in I/O error responses."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'', errno.EIO)
            events = self._get_events(cap)
            self.assertEqual(len(events), 1)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('x'), '1')
            self.ae(events[0]['payload'].strip(), b'EIO')

    def test_fifo_order_with_different_indices(self) -> None:
        """Multiple requests with different x= values are served in FIFO order."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain text/html')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain', 'text/html'])
            cap.consume()

            # Queue two requests: idx=1 (text/plain) then idx=2 (text/html)
            parse_bytes(screen, client_request_data(1))
            parse_bytes(screen, client_request_data(2))

            # First request (idx=1) gets served first
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'plain data')
            raw = cap.consume()
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r' and e['meta'].get('x') == '1']
            self.assertTrue(r_events, 'no t=r events for first request (x=1)')
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, b'plain data')

            # Second request (idx=2) gets served next
            dnd_test_fake_drop_data(cap.window_id, 'text/html', b'<html>data</html>')
            raw = cap.consume()
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r' and e['meta'].get('x') == '2']
            self.assertTrue(r_events, 'no t=r events for second request (x=2)')
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, b'<html>data</html>')

    def test_request_after_error_proceeds(self) -> None:
        """After an error response, the next queued request is processed."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            # Queue: request for out-of-range index (error) followed by valid request
            parse_bytes(screen, client_request_data(99))
            parse_bytes(screen, client_request_data(1))

            # The error for index 99 should have been sent immediately
            raw = cap.consume()
            events = parse_escape_codes(raw)
            err_events = [e for e in events if e['type'] == 'R']
            self.assertEqual(len(err_events), 1, events)
            self.ae(err_events[0]['meta'].get('x'), '99')
            self.ae(err_events[0]['payload'].strip(), b'ENOENT')

            # Now serve request for index 1
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'second request data')
            raw = cap.consume()
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events, 'no t=r events for second request')
            for ev in r_events:
                self.ae(ev['meta'].get('x'), '1')

    def test_queue_overflow_returns_emfile(self) -> None:
        """Exceeding 128 queued requests returns EMFILE and ends the drop."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            # First request starts async processing
            parse_bytes(screen, client_request_data(1))

            # Queue 127 more requests (fill to capacity = 128)
            for i in range(2, 129):
                parse_bytes(screen, client_request_data(1))

            # No error yet - queue is at capacity
            raw = cap.consume()
            err_events = [e for e in parse_escape_codes(raw) if e['type'] == 'R']
            self.assertEqual(len(err_events), 0, f'unexpected errors: {err_events}')

            # 129th request should trigger EMFILE
            parse_bytes(screen, client_request_data(1))
            raw = cap.consume()
            events = parse_escape_codes(raw)
            err_events = [e for e in events if e['type'] == 'R']
            self.assertTrue(err_events, 'expected EMFILE error')
            self.ae(err_events[0]['payload'].strip(), b'EMFILE')

    def test_xy_keys_in_uri_file_response(self) -> None:
        """x= and y= keys are echoed in URI file data responses."""
        import os
        import tempfile
        content = b'URI file with disambiguation\n'
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'no t=r events')
                for ev in r_events:
                    self.ae(ev['meta'].get('x'), '2')
                    self.ae(ev['meta'].get('y'), '1')
                combined = b''.join(e['payload'] for e in r_events)
                self.ae(combined, content)
        finally:
            os.unlink(fpath)

    def test_xy_keys_in_uri_error_response(self) -> None:
        """x= and y= keys are echoed in URI file error responses."""
        uri_list = b'file:///tmp/no_such_file_dnd_test_xyz\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_uri_drop(screen, cap, uri_list)
            parse_bytes(screen, client_request_uri_data(2, 1))
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'R')
            self.ae(events[0]['meta'].get('x'), '2')
            self.ae(events[0]['meta'].get('y'), '1')

    def test_X_key_is_handle_in_dir_listing_response(self) -> None:
        """X= key acts as directory handle (> 1) in directory listing responses.

        For top-level URI directory requests the request keys x= (mime index)
        and y= (file index) are echoed in the response.  X= holds the new
        directory handle; Y= is absent because the original request had no Y.
        """
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'file.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                self.assertTrue(d_events, 'expected directory listing')
                for ev in d_events:
                    self.ae(ev['meta'].get('x'), '2')
                    self.ae(ev['meta'].get('y'), '1')
                    handle = dir_handle(ev)
                    self.assertGreater(handle, 1, 'X= must be a directory handle (> 1)')
                    # In a fresh window the handle counter starts at 1, so the
                    # first allocated handle must be exactly 2.
                    self.ae(handle, 2, 'first allocated directory handle must be 2')
                    self.assertIsNone(ev['meta'].get('Y'),
                                     'Y= must not be present in top-level dir response')

    def test_Y_and_x_keys_in_dir_entry_file_response(self) -> None:
        """Y= and x= keys are echoed when reading a file via directory handle."""
        import os
        import tempfile
        content = b'directory file content\n'
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'f.txt'), 'wb') as f:
                f.write(content)
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                self.assertTrue(d_events)
                handle_id = dir_handle(d_events[0])
                listing = b''.join(chunk for e in d_events for chunk in e['chunks'] if chunk)
                entries = [e.decode() for e in listing.split(b'\x00') if e]
                f_idx = entries.index('f.txt') + 1

                # Read file from directory
                parse_bytes(screen, client_dir_read(handle_id, f_idx))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events = [e for e in events if e['type'] == 'r']
                self.assertTrue(r_events, 'no t=r events')
                for ev in r_events:
                    self.ae(ev['meta'].get('x'), str(f_idx))
                    self.ae(ev['meta'].get('Y'), str(handle_id))
                combined = b''.join(e['payload'] for e in r_events)
                self.ae(combined, content)

    def test_Y_and_x_keys_in_dir_entry_error_response(self) -> None:
        """Y= and x= keys are echoed when a directory entry read fails."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, 'only.txt'), 'w').close()
            uri_list = f'file://{root}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)
                parse_bytes(screen, client_request_uri_data(2, 1))
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                d_events = [e for e in events if e['type'] == 'r' and is_dir_event(e)]
                handle_id = dir_handle(d_events[0])

                # Out-of-range entry
                parse_bytes(screen, client_dir_read(handle_id, 999))
                events = self._get_events(cap)
                self.assertEqual(len(events), 1)
                self.ae(events[0]['type'], 'R')
                self.ae(events[0]['meta'].get('x'), '999')
                self.ae(events[0]['meta'].get('Y'), str(handle_id))
                self.ae(events[0]['payload'].strip(), b'ENOENT')

    def test_mixed_request_types_processed_in_order(self) -> None:
        """Mixed MIME data and URI file requests are processed in FIFO order."""
        import os
        import tempfile
        file_content = b'mixed request file\n'
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(file_content)
            fpath = f.name
        try:
            uri_list = f'file://{fpath}\r\n'.encode()
            with dnd_test_window() as (screen, cap):
                self._setup_uri_drop(screen, cap, uri_list)

                # Queue: MIME data request (x=1), then URI file request (x=2,y=1)
                parse_bytes(screen, client_request_data(1))
                parse_bytes(screen, client_request_uri_data(2, 1))

                # Serve first request (MIME data); the URI file request
                # completes synchronously right after so all output is in one batch
                dnd_test_fake_drop_data(cap.window_id, 'text/plain', b'plain text')
                raw = cap.consume()
                events = parse_escape_codes_b64(raw)
                r_events_x1 = [e for e in events if e['type'] == 'r' and e['meta'].get('x') == '1' and 'y' not in e['meta']]
                self.assertTrue(r_events_x1, 'no events with x=1 (MIME data)')

                r_events_x2y1 = [e for e in events if e['type'] == 'r' and e['meta'].get('x') == '2' and e['meta'].get('y') == '1']
                self.assertTrue(r_events_x2y1, 'no events with x=2,y=1 (URI file)')
                combined = b''.join(e['payload'] for e in r_events_x2y1)
                self.ae(combined, file_content)
        finally:
            os.unlink(fpath)

    def test_multiple_sync_errors_processed_immediately(self) -> None:
        """Multiple queued requests that all fail synchronously are processed immediately."""
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 0, 0, 0, 0)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            # Queue three requests for out-of-range indices
            parse_bytes(screen, client_request_data(10))
            parse_bytes(screen, client_request_data(20))
            parse_bytes(screen, client_request_data(30))

            # All three errors should be available immediately
            raw = cap.consume()
            events = parse_escape_codes(raw)
            err_events = [e for e in events if e['type'] == 'R']
            self.assertEqual(len(err_events), 3, f'expected 3 errors, got {len(err_events)}: {err_events}')
            self.ae(err_events[0]['meta'].get('x'), '10')
            self.ae(err_events[1]['meta'].get('x'), '20')
            self.ae(err_events[2]['meta'].get('x'), '30')
            for ev in err_events:
                self.ae(ev['payload'].strip(), b'ENOENT')

    def test_no_r_key_in_responses(self) -> None:
        """Responses must not contain the old r= key."""
        payload_data = b'no r= key test'
        with dnd_test_window() as (screen, cap):
            self._register_for_drops(screen, cap, 'text/plain')
            dnd_test_set_mouse_pos(cap.window_id, 2, 3, 16, 24)
            dnd_test_fake_drop_event(cap.window_id, True, ['text/plain'])
            cap.consume()

            parse_bytes(screen, client_request_data(1))
            dnd_test_fake_drop_data(cap.window_id, 'text/plain', payload_data)
            raw = cap.consume()
            events = parse_escape_codes_b64(raw)
            r_events = [e for e in events if e['type'] == 'r']
            self.assertTrue(r_events)
            combined = b''.join(e['payload'] for e in r_events)
            self.ae(combined, payload_data)
            # Verify no r= key in metadata
            for ev in r_events:
                self.assertNotIn('r', ev['meta'], f'r= should not be present, got {ev["meta"]}')

            # Finish
            parse_bytes(screen, client_request_data())
            self._assert_no_output(cap)

    # ---- Remote drag (t=k) tests --------------------------------------------

    def _setup_remote_drag(self, screen, cap, uri_list_data: bytes,
                           mimes: str = 'text/plain text/uri-list',
                           operations: int = 1, client_id: int = 0):
        """Set up a remote drag offer in DROPPED state with uri-list data delivered.

        1. Register for drag offers with a *different* machine id (so is_remote_client=True).
        2. Offer MIME types including text/uri-list.
        3. Force state to DROPPED.
        4. Mark the text/uri-list item as requesting remote files.
        5. Send the text/uri-list data via t=e escape codes.
        """
        # Register with a different machine_id to make is_remote_client=True
        parse_bytes(screen, _osc(f'{DND_CODE};t=o:x=1;different-machine-id'))
        parse_bytes(screen, client_drag_offer_mimes(operations, mimes, client_id=client_id))
        cap.consume()
        dnd_test_force_drag_dropped(cap.window_id)
        # Find the index of text/uri-list
        mime_list = mimes.split()
        uri_idx = mime_list.index('text/uri-list')
        dnd_test_request_drag_data(cap.window_id, uri_idx)
        # Send the uri-list data
        b64 = standard_b64encode(uri_list_data).decode()
        parse_bytes(screen, client_drag_send_data(uri_idx, b64, client_id=client_id))
        # End of data
        parse_bytes(screen, client_drag_send_data(uri_idx, '', client_id=client_id))
        cap.consume()

    def test_remote_drag_single_file(self) -> None:
        """Transfer a single regular file via t=k."""
        uri_list = b'file:///home/user/hello.txt\r\n'
        file_content = b'Hello, World!'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            b64 = standard_b64encode(file_content).decode()
            # Send file data for URI index 1 (1-based), type=0 (file)
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            self._assert_no_output(cap)
            # End of data for this file
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            self._assert_no_output(cap)
            # Completion signal
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_single_symlink(self) -> None:
        """Transfer a symlink via t=k with X=1."""
        uri_list = b'file:///home/user/link\r\n'
        target = b'/usr/share/target'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            b64 = standard_b64encode(target).decode()
            # Send symlink data (X=1)
            parse_bytes(screen, client_remote_file(1, b64, item_type=1))
            self._assert_no_output(cap)
            # End of data
            parse_bytes(screen, client_remote_file(1, '', item_type=1))
            self._assert_no_output(cap)
            # Completion signal
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_single_directory(self) -> None:
        """Transfer a directory with entries via t=k with X=handle (>1)."""
        uri_list = b'file:///home/user/mydir\r\n'
        # Directory listing: two entries separated by null bytes
        dir_entries = b'file1.txt\x00file2.txt'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            b64 = standard_b64encode(dir_entries).decode()
            # Send directory listing (X=2, handle for this directory)
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            self._assert_no_output(cap)
            # End of listing data
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            self._assert_no_output(cap)

            # Now send data for each child entry
            # Entry 1: file1.txt (y=1 is 1-based)
            content1 = b'content of file1'
            b64 = standard_b64encode(content1).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=1))
            self._assert_no_output(cap)
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=1))
            self._assert_no_output(cap)

            # Entry 2: file2.txt
            content2 = b'content of file2'
            b64 = standard_b64encode(content2).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=2))
            self._assert_no_output(cap)
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=2))
            self._assert_no_output(cap)

            # Completion signal
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_multiple_uris(self) -> None:
        """Transfer multiple files from a URI list."""
        uri_list = b'file:///home/user/a.txt\r\nfile:///home/user/b.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # File 1 (URI index 1)
            b64 = standard_b64encode(b'aaa').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            self._assert_no_output(cap)
            # File 2 (URI index 2)
            b64 = standard_b64encode(b'bbb').decode()
            parse_bytes(screen, client_remote_file(2, b64, item_type=0))
            parse_bytes(screen, client_remote_file(2, '', item_type=0))
            self._assert_no_output(cap)
            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_chunked_file(self) -> None:
        """File data can be sent in multiple chunks with m=1."""
        uri_list = b'file:///home/user/big.bin\r\n'
        file_data = b'A' * 100 + b'B' * 200
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Split the base64 stream across two chunks
            full_b64 = standard_b64encode(file_data).decode()
            mid = len(full_b64) // 2
            # Ensure split point is at a 4-byte boundary for valid base64 chunks
            mid = (mid // 4) * 4
            chunk1_b64 = full_b64[:mid]
            chunk2_b64 = full_b64[mid:]
            # First chunk with more=True
            parse_bytes(screen, client_remote_file(1, chunk1_b64, item_type=0, more=True))
            self._assert_no_output(cap)
            # Second chunk with more=False (last chunk before end-of-data)
            parse_bytes(screen, client_remote_file(1, chunk2_b64, item_type=0))
            self._assert_no_output(cap)
            # End of data
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            self._assert_no_output(cap)
            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_directory_with_symlink(self) -> None:
        """Directory can contain symlinks (X=1 type for children)."""
        uri_list = b'file:///home/user/proj\r\n'
        dir_entries = b'readme.txt\x00link'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Top-level directory (handle=2)
            b64 = standard_b64encode(dir_entries).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            self._assert_no_output(cap)

            # Child 1: regular file
            b64 = standard_b64encode(b'readme content').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=1))
            self._assert_no_output(cap)

            # Child 2: symlink (X=1)
            b64 = standard_b64encode(b'/target/path').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=1, parent_handle=2, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=1, parent_handle=2, entry_num=2))
            self._assert_no_output(cap)

            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_deep_directory_tree_breadth_first(self) -> None:
        """Transfer a 3-level deep directory tree in breadth-first order.

        Structure:
            root/
                file_a.txt
                sub1/
                    file_b.txt
                    subsub/
                        file_c.txt
                        link -> /target
        """
        uri_list = b'file:///home/user/root\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)

            # Level 0: root directory (handle=2)
            root_entries = b'file_a.txt\x00sub1'
            b64 = standard_b64encode(root_entries).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            parse_bytes(screen, client_remote_file(1, '', item_type=2))

            # Level 1: children of root (handle=2)
            # Entry 1: file_a.txt (regular file)
            b64 = standard_b64encode(b'content_a').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=1))

            # Entry 2: sub1 (subdirectory, handle=3)
            sub1_entries = b'file_b.txt\x00subsub'
            b64 = standard_b64encode(sub1_entries).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=3, parent_handle=2, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=3, parent_handle=2, entry_num=2))

            # Level 2: children of sub1 (handle=3)
            # Entry 1: file_b.txt
            b64 = standard_b64encode(b'content_b').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=3, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=3, entry_num=1))

            # Entry 2: subsub (subdirectory, handle=4)
            subsub_entries = b'file_c.txt\x00link'
            b64 = standard_b64encode(subsub_entries).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=4, parent_handle=3, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=4, parent_handle=3, entry_num=2))

            # Level 3: children of subsub (handle=4)
            # Entry 1: file_c.txt
            b64 = standard_b64encode(b'content_c').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=4, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=4, entry_num=1))

            # Entry 2: link (symlink, type=1)
            b64 = standard_b64encode(b'/target').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=1, parent_handle=4, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=1, parent_handle=4, entry_num=2))

            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_deep_directory_tree_depth_first(self) -> None:
        """Transfer a 3-level deep directory tree in depth-first order.

        Same structure as breadth-first test but entries are sent depth-first:
            root/
                file_a.txt
                sub1/
                    file_b.txt
                    subsub/
                        file_c.txt
                        link -> /target
        """
        uri_list = b'file:///home/user/root\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)

            # Root directory (handle=2)
            root_entries = b'file_a.txt\x00sub1'
            b64 = standard_b64encode(root_entries).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            parse_bytes(screen, client_remote_file(1, '', item_type=2))

            # Entry 1 of root: file_a.txt (file)
            b64 = standard_b64encode(b'content_a').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=1))

            # Entry 2 of root: sub1 (directory, handle=3)
            sub1_entries = b'file_b.txt\x00subsub'
            b64 = standard_b64encode(sub1_entries).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=3, parent_handle=2, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=3, parent_handle=2, entry_num=2))

            # Depth first: immediately descend into sub1
            # Entry 1 of sub1: file_b.txt
            b64 = standard_b64encode(b'content_b').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=3, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=3, entry_num=1))

            # Entry 2 of sub1: subsub (directory, handle=4)
            subsub_entries = b'file_c.txt\x00link'
            b64 = standard_b64encode(subsub_entries).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=4, parent_handle=3, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=4, parent_handle=3, entry_num=2))

            # Depth first: immediately descend into subsub
            # Entry 1 of subsub: file_c.txt
            b64 = standard_b64encode(b'content_c').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=4, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=4, entry_num=1))

            # Entry 2 of subsub: link (symlink)
            b64 = standard_b64encode(b'/target').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=1, parent_handle=4, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=1, parent_handle=4, entry_num=2))

            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_completion_signal(self) -> None:
        """The completion signal t=k with no keys works correctly."""
        uri_list = b'file:///home/user/f.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_invalid_uri_index(self) -> None:
        """Sending t=k with an out-of-bounds URI index returns an error."""
        uri_list = b'file:///home/user/a.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # URI index 2 is out of bounds (only 1 URI)
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(2, b64, item_type=0))
            self.assert_error(cap)

    def test_remote_drag_invalid_entry_num(self) -> None:
        """Sending t=k with an out-of-bounds entry number in a directory returns error."""
        uri_list = b'file:///home/user/dir\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Create directory with 1 entry
            dir_entries = b'file1.txt'
            b64 = standard_b64encode(dir_entries).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            cap.consume()

            # Entry number 2 is out of bounds (only 1 entry)
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=2))
            self.assert_error(cap)

    def test_remote_drag_invalid_handle(self) -> None:
        """Sending t=k with a non-existent directory handle returns error."""
        uri_list = b'file:///home/user/dir\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Create directory (handle=2)
            dir_entries = b'file1.txt'
            b64 = standard_b64encode(dir_entries).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            cap.consume()

            # Use non-existent handle 99
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=99, entry_num=1))
            self.assert_error(cap)

    def test_remote_drag_invalid_base64(self) -> None:
        """Sending invalid base64 data in t=k returns an error."""
        uri_list = b'file:///home/user/f.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Send garbage that's not valid base64
            parse_bytes(screen, client_remote_file(1, '!@#$%^&*()', item_type=0))
            self.assert_error(cap)

    def test_remote_drag_too_large_chunk(self) -> None:
        """Chunks larger than 4096 bytes are rejected."""
        uri_list = b'file:///home/user/f.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Send a chunk > 4096 bytes (the b64 payload is checked before decoding)
            big_b64 = standard_b64encode(b'x' * 4097).decode()
            parse_bytes(screen, client_remote_file(1, big_b64, item_type=0))
            self.assert_error(cap)

    def test_remote_drag_negative_X_rejected(self) -> None:
        """Sending t=k with X < 0 is rejected."""
        uri_list = b'file:///home/user/f.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Directly construct escape code with negative X
            parse_bytes(screen, _osc(f'{DND_CODE};t=k:x=1:X=-1'))
            self.assert_error(cap)

    def test_remote_drag_without_remote_flag_fails(self) -> None:
        """t=k fails if the drag is not from a remote client."""
        with dnd_test_window() as (screen, cap):
            # Register with local machine_id (is_remote_client=False)
            parse_bytes(screen, _osc(f'{DND_CODE};t=o:x=1;{machine_id()}'))
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain text/uri-list'))
            cap.consume()
            dnd_test_force_drag_dropped(cap.window_id)
            # Mark the uri-list item - but since is_remote_client is False,
            # requested_remote_files will be False
            dnd_test_request_drag_data(cap.window_id, 1)
            # Try to send remote file data directly - should fail since no item has requested_remote_files
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            self.assert_error(cap)

    def test_remote_drag_without_dropped_state_fails(self) -> None:
        """t=k fails if the drag state is not DROPPED (data not yet delivered)."""
        with dnd_test_window() as (screen, cap):
            # Only register, don't progress to DROPPED state
            parse_bytes(screen, _osc(f'{DND_CODE};t=o:x=1;different-machine-id'))
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/uri-list'))
            cap.consume()
            # State is BEING_BUILT, not DROPPED, so t=k should fail
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            self.assert_error(cap)

    def test_remote_drag_dos_remote_drag_limit(self) -> None:
        """Total remote data size exceeding REMOTE_DRAG_LIMIT triggers EMFILE error."""
        uri_list = b'file:///home/user/big.bin\r\n'
        with dnd_test_window(remote_drag_limit=50) as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # First chunk within limit
            b64 = standard_b64encode(b'x' * 30).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0, more=True))
            self._assert_no_output(cap)
            # Second chunk pushes over the limit
            b64 = standard_b64encode(b'y' * 30).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            self.assert_error(cap, 'EMFILE')

    def test_remote_drag_dos_present_data_cap_on_directory(self) -> None:
        """Directory listing data exceeding PRESENT_DATA_CAP triggers EMFILE error."""
        uri_list = b'file:///home/user/dir\r\n'
        with dnd_test_window(present_data_cap=20) as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Send a directory listing that will exceed the cap
            big_listing = b'\x00'.join([f'file{i}.txt'.encode() for i in range(100)])
            b64 = standard_b64encode(big_listing).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            self.assert_error(cap, 'EMFILE')

    def test_remote_drag_error_from_client(self) -> None:
        """Client error (t=E) during remote drag aborts correctly."""
        uri_list = b'file:///home/user/f.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Client reports an error
            parse_bytes(screen, client_drag_cancel())
            # The drag should have been canceled - t=k should now fail
            cap.consume()  # discard any error output from cancel
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            self.assert_error(cap)

    def test_remote_drag_three_level_tree_with_verification(self) -> None:
        """Transfer a 3-level directory tree and verify no errors occur.

        root/
            alpha.txt        (file)
            beta/             (dir)
                gamma.txt     (file)
                delta/        (dir)
                    epsilon   (file)
                    zeta      (symlink -> /zeta-target)
            eta -> /link-tgt  (symlink)
        """
        uri_list = b'file:///home/user/root\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)

            # Root directory (handle=10)
            root_entries = b'alpha.txt\x00beta\x00eta'
            b64 = standard_b64encode(root_entries).decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=10))
            parse_bytes(screen, client_remote_file(1, '', item_type=10))

            # alpha.txt (child 1 of root)
            b64 = standard_b64encode(b'alpha content').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=10, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=10, entry_num=1))

            # beta (child 2 of root, handle=20)
            beta_entries = b'gamma.txt\x00delta'
            b64 = standard_b64encode(beta_entries).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=20, parent_handle=10, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=20, parent_handle=10, entry_num=2))

            # eta (child 3 of root, symlink)
            b64 = standard_b64encode(b'/link-tgt').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=1, parent_handle=10, entry_num=3))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=1, parent_handle=10, entry_num=3))

            # gamma.txt (child 1 of beta)
            b64 = standard_b64encode(b'gamma content').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=20, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=20, entry_num=1))

            # delta (child 2 of beta, handle=30)
            delta_entries = b'epsilon\x00zeta'
            b64 = standard_b64encode(delta_entries).decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=30, parent_handle=20, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=30, parent_handle=20, entry_num=2))

            # epsilon (child 1 of delta)
            b64 = standard_b64encode(b'epsilon content').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=30, entry_num=1))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=30, entry_num=1))

            # zeta (child 2 of delta, symlink)
            b64 = standard_b64encode(b'/zeta-target').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=1, parent_handle=30, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=1, parent_handle=30, entry_num=2))

            self._assert_no_output(cap)
            # Completion
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_process_item_data_basic(self) -> None:
        """Basic drag_process_item_data: send data for a MIME type after DROPPED state."""
        with dnd_test_window() as (screen, cap):
            # Set up a non-remote drag with text/plain
            parse_bytes(screen, _osc(f'{DND_CODE};t=o:x=1;{machine_id()}'))
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            cap.consume()
            dnd_test_force_drag_dropped(cap.window_id)
            dnd_test_request_drag_data(cap.window_id, 0)
            # Send data for text/plain (index 0)
            b64 = standard_b64encode(b'test data').decode()
            parse_bytes(screen, client_drag_send_data(0, b64))
            self._assert_no_output(cap)
            # End of data
            parse_bytes(screen, client_drag_send_data(0, ''))
            # Should get a notification (but no error)
            events = self._get_events(cap)
            for ev in events:
                self.assertNotEqual(ev['type'], 'E', f'unexpected error: {ev}')

    def test_remote_drag_process_item_data_error(self) -> None:
        """Client can report an error via t=E for a MIME data delivery."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, _osc(f'{DND_CODE};t=o:x=1;{machine_id()}'))
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            cap.consume()
            dnd_test_force_drag_dropped(cap.window_id)
            dnd_test_request_drag_data(cap.window_id, 0)
            # Client reports EPERM error
            parse_bytes(screen, client_drag_send_error(0, 'EPERM'))
            # The error should propagate but not crash
            cap.consume()

    def test_remote_drag_process_item_data_invalid_index(self) -> None:
        """Sending data for a non-existent MIME index is rejected."""
        with dnd_test_window() as (screen, cap):
            parse_bytes(screen, _osc(f'{DND_CODE};t=o:x=1;{machine_id()}'))
            parse_bytes(screen, client_drag_offer_mimes(1, 'text/plain'))
            cap.consume()
            dnd_test_force_drag_dropped(cap.window_id)
            # Index 5 is way out of bounds
            b64 = standard_b64encode(b'data').decode()
            parse_bytes(screen, client_drag_send_data(5, b64))
            self.assert_error(cap)

    def test_remote_drag_mixed_file_dir_symlink(self) -> None:
        """Transfer mixed content: file, directory and symlink as separate URIs."""
        uri_list = b'file:///tmp/a.txt\r\nfile:///tmp/mydir\r\nfile:///tmp/mylink\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)

            # URI 1: regular file
            b64 = standard_b64encode(b'file a content').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            parse_bytes(screen, client_remote_file(1, '', item_type=0))

            # URI 2: directory (handle=5)
            dir_entries = b'child.txt'
            b64 = standard_b64encode(dir_entries).decode()
            parse_bytes(screen, client_remote_file(2, b64, item_type=5))
            parse_bytes(screen, client_remote_file(2, '', item_type=5))

            # Child of directory (entry 1)
            b64 = standard_b64encode(b'child content').decode()
            parse_bytes(screen, client_remote_file(
                2, b64, item_type=0, parent_handle=5, entry_num=1))
            parse_bytes(screen, client_remote_file(
                2, '', item_type=0, parent_handle=5, entry_num=1))

            # URI 3: symlink
            b64 = standard_b64encode(b'/symlink/target').decode()
            parse_bytes(screen, client_remote_file(3, b64, item_type=1))
            parse_bytes(screen, client_remote_file(3, '', item_type=1))

            self._assert_no_output(cap)
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_empty_file(self) -> None:
        """Transfer an empty file (end-of-data immediately after start)."""
        uri_list = b'file:///home/user/empty.txt\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Start file transfer, then immediately end (no data chunks)
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            self._assert_no_output(cap)
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_empty_directory(self) -> None:
        """Transfer a directory with no entries."""
        uri_list = b'file:///home/user/emptydir\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Empty directory listing (single entry name)
            b64 = standard_b64encode(b'').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=2))
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    def test_remote_drag_uri_list_with_comments(self) -> None:
        """URI list with comment lines (starting with #) should filter them out."""
        uri_list = b'# this is a comment\r\nfile:///home/user/f.txt\r\n# another comment\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Only 1 real URI (f.txt), so URI index 1 should work
            b64 = standard_b64encode(b'content').decode()
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            # URI index 2 should fail (no such entry)
            cap.consume()
            b64 = standard_b64encode(b'bad').decode()
            parse_bytes(screen, client_remote_file(2, b64, item_type=0))
            self.assert_error(cap)

    def test_remote_drag_multiple_chunks_directory_listing(self) -> None:
        """Directory listing data can be sent in multiple chunks."""
        uri_list = b'file:///home/user/dir\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Send directory listing in two chunks
            chunk1 = b'file1.txt\x00fi'
            chunk2 = b'le2.txt'
            b64_1 = standard_b64encode(chunk1).decode()
            b64_2 = standard_b64encode(chunk2).decode()
            parse_bytes(screen, client_remote_file(1, b64_1, item_type=2, more=True))
            self._assert_no_output(cap)
            parse_bytes(screen, client_remote_file(data_b64=b64_2))
            self._assert_no_output(cap)
            # End of listing
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            self._assert_no_output(cap)

            # Verify children are accessible: entry 1 and entry 2
            b64 = standard_b64encode(b'c1').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=1))
            self._assert_no_output(cap)
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=1))
            self._assert_no_output(cap)
            b64 = standard_b64encode(b'c2').decode()
            parse_bytes(screen, client_remote_file(
                1, b64, item_type=0, parent_handle=2, entry_num=2))
            parse_bytes(screen, client_remote_file(
                1, '', item_type=0, parent_handle=2, entry_num=2))
            self._assert_no_output(cap)

            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)

    # ---- DoS limits tests ---------------------------------------------------

    def test_dos_mime_list_size_cap(self) -> None:
        """Exceeding MIME_LIST_SIZE_CAP when offering MIME types returns EFBIG."""
        with dnd_test_window(mime_list_cap=20) as (screen, cap):
            parse_bytes(screen, client_drag_register())
            # Offer MIME types that exceed the cap
            long_mime = 'x' * 30
            parse_bytes(screen, client_drag_offer_mimes(1, long_mime))
            self.assert_error(cap, 'EFBIG')

    def test_dos_present_data_cap_pre_send(self) -> None:
        """Exceeding PRESENT_DATA_CAP with pre-sent data returns EFBIG."""
        with dnd_test_window(present_data_cap=50) as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            # Pre-send data exceeding the cap
            big_data = standard_b64encode(b'x' * 60).decode()
            parse_bytes(screen, client_drag_pre_send(0, big_data))
            self.assert_error(cap, 'EFBIG')

    def test_dos_mime_list_size_cap_drop_target(self) -> None:
        """Exceeding MIME_LIST_SIZE_CAP when registering for drops silently ignores the excess."""
        with dnd_test_window(mime_list_cap=10) as (screen, cap):
            # Register with MIME types exceeding the cap
            long_mimes = 'text/plain text/html application/json'
            self._register_for_drops(screen, cap, long_mimes)
            # The drop should still enter (excess mimes are silently dropped)
            dnd_test_set_mouse_pos(cap.window_id, 1, 1, 1, 1)
            dnd_test_fake_drop_event(cap.window_id, False, ['text/plain'])
            events = self._get_events(cap)
            # Should get a move event
            self.assertTrue(len(events) >= 1, events)

    def test_drag_notify_colon_separators(self) -> None:
        """drag_notify output has proper colon separators between metadata keys."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain text/html')
            dnd_test_force_drag_dropped(cap.window_id)
            # DRAG_NOTIFY_ACCEPTED (type=0) should produce t=e:x=1:y=<idx>
            dnd_test_drag_notify(cap.window_id, 0, 'text/html')
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'e')
            # Verify proper key formatting with colons
            self.ae(events[0]['meta'].get('x'), '1')
            self.ae(events[0]['meta'].get('y'), '1')  # text/html is index 1

    def test_drag_notify_action_changed_colon_separator(self) -> None:
        """drag_notify ACTION_CHANGED output has proper colon separators."""
        from kitty.fast_data_types import GLFW_DRAG_OPERATION_MOVE
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            dnd_test_force_drag_dropped(cap.window_id)
            # DRAG_NOTIFY_ACTION_CHANGED (type=1) with MOVE action
            dnd_test_drag_notify(cap.window_id, 1, '', GLFW_DRAG_OPERATION_MOVE)
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'e')
            self.ae(events[0]['meta'].get('x'), '2')  # ACTION_CHANGED = type+1 = 2
            self.ae(events[0]['meta'].get('o'), '2')   # MOVE = o=2

    def test_drag_notify_finished_colon_separator(self) -> None:
        """drag_notify FINISHED output has proper colon separators."""
        with dnd_test_window() as (screen, cap):
            self._setup_drag_offer(screen, cap, 'text/plain')
            dnd_test_force_drag_dropped(cap.window_id)
            # DRAG_NOTIFY_FINISHED (type=3) with was_canceled=0
            dnd_test_drag_notify(cap.window_id, 3, '', 0, 0)
            events = self._get_events(cap)
            self.assertEqual(len(events), 1, events)
            self.ae(events[0]['type'], 'e')
            self.ae(events[0]['meta'].get('x'), '4')  # FINISHED = type+1 = 4
            self.ae(events[0]['meta'].get('y'), '0')   # was_canceled = 0

    def test_remote_drag_children_freed_on_cleanup(self) -> None:
        """Remote drag with directories properly frees the children array on cleanup."""
        uri_list = b'file:///home/user/mydir\r\n'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            # Create a directory entry (X=2 means directory handle=2)
            dir_listing = standard_b64encode(b'file1.txt\x00subdir').decode()
            parse_bytes(screen, client_remote_file(1, dir_listing, item_type=2))
            self._assert_no_output(cap)
            # Finish the directory entry
            parse_bytes(screen, client_remote_file(1, '', item_type=2))
            self._assert_no_output(cap)
            # Now send file data for the first child (entry_num=1, Y=handle)
            file_data = standard_b64encode(b'hello').decode()
            parse_bytes(screen, client_remote_file(1, file_data, item_type=0, parent_handle=2, entry_num=1))
            parse_bytes(screen, client_remote_file(1, '', item_type=0, parent_handle=2, entry_num=1))
            self._assert_no_output(cap)
            # Cleanup happens when context manager exits - no crash means children are freed

    def test_remote_drag_uri_replaced_without_leak(self) -> None:
        """Remote drag replaces URI string without leaking the original."""
        uri_list = b'file:///home/user/hello.txt\r\n'
        file_content = b'test content'
        with dnd_test_window() as (screen, cap):
            self._setup_remote_drag(screen, cap, uri_list)
            b64 = standard_b64encode(file_content).decode()
            # Send file data - this replaces the URI string in the uri_list
            parse_bytes(screen, client_remote_file(1, b64, item_type=0))
            self._assert_no_output(cap)
            # End of data for this file
            parse_bytes(screen, client_remote_file(1, '', item_type=0))
            self._assert_no_output(cap)
            # Completion signal
            parse_bytes(screen, client_remote_file_finish())
            self._assert_no_output(cap)
            # No crash or leak - cleanup happens in context manager exit
