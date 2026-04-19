#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import tempfile
from base64 import standard_b64encode

from kitty.constants import kitten_exe
from kitty.fast_data_types import DND_CODE, dnd_set_test_write_func, dnd_test_cleanup_fake_window, dnd_test_create_fake_window, dnd_test_probe_state

from . import PTY, BaseTest
from .dnd import WriteCapture


class Capture(WriteCapture):

    def __call__(self, window_id: int, data: bytes) -> None:
        self.pty.write(data)


class TestDnDKitten(BaseTest):

    def setUp(self):
        capture = Capture()
        dnd_set_test_write_func(capture)
        os_window_id, window_id = dnd_test_create_fake_window()
        capture.window_id = window_id
        capture.os_window_id = os_window_id
        self.capture = capture
        self.test_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.messages_from_kitten = ''

    def send_dnd_command_to_kitten(self, payload=b'', as_base64=False, flush=False, **metadata):
        header = f'\x1b]{DND_CODE};'
        for k, v in metadata.items():
            header = header + f'{k}={v}:'
        self.pty.write_to_child(header.encode())
        if not payload:
            self.pty.write_to_child(b'\x1b\\', flush=flush)
            return
        if isinstance(payload, str):
            payload = payload.encode()
        payload = memoryview(standard_b64encode(payload) if as_base64 else payload)
        for i in range(0, len(payload), 4096):
            end = i + 4096
            is_last = end >= len(payload)
            chunk = payload[i:min(i+4096, len(payload))]
            if i == 0:
                self.pty.write_to_child(f'm={0 if is_last else 1};'.encode())
            else:
                self.pty.write_to_child(f'\x1b]{DND_CODE};m={0 if is_last else 1};'.encode())
            self.pty.write_to_child(chunk)
            self.pty.write_to_child(b'\x1b\\', flush=is_last and flush)

    def finish_setup(self, remote_client: bool = False):
        cmd = [kitten_exe(), 'dnd']
        if remote_client:
            cmd.append('--machine-id=remote-client-for-test')
        self.pty = self.enterContext(PTY(argv=cmd, rows=25, columns=80, window_id=self.capture.window_id))
        self.pty.callbacks.printbuf = self
        self.screen = self.pty.screen
        self.pty.wait_till(lambda: bool(self.pty.callbacks.titlebuf))
        self.assertTrue(self.probe_state('drop_wanted'))
        self.assertEqual(remote_client, self.probe_state('drop_is_remote_client'))
        if self.probe_state('drag_can_offer'):
            self.assertEqual(remote_client, self.probe_state('drag_is_remote_client'))

    def append(self, text):
        self.messages_from_kitten += text

    def wait_for_responses(self, *responses, timeout=10):
        q = '\n'.join(responses)
        def wait_till():
            return q == self.messages_from_kitten.strip()
        self.pty.wait_till(wait_till, timeout, lambda: f'Responses so far: {self.messages_from_kitten!r}')
        self.messages_from_kitten = ''

    def probe_state(self, which: str):
        return dnd_test_probe_state(self.capture.window_id, which)

    def tearDown(self):
        dnd_set_test_write_func(None)
        dnd_test_cleanup_fake_window(self.capture.os_window_id)
        del self.capture
        del self.screen
        del self.pty

    def test_dnd_kitten_drop(self):
        for remote_client in (False, True):
            with self.subTest(remote_client=remote_client):
                self.finish_setup(remote_client=remote_client)
