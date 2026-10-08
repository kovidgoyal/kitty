#!/usr/bin/env python
# License: GPLv3 Copyright: 2026 Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import tempfile
from unittest.mock import patch

from kitty.constants import kitty_exe
from kitty.rc.base import PayloadGetter, all_command_names, command_for_name

from .base import BaseTest


class Window:
    def __init__(self, id: int, os_window_id: int):
        self.id = id
        self.os_window_id = os_window_id


class Boss:
    def __init__(self, windows: list[Window]):
        self.active_window = windows[0]
        self.all_windows = windows

    def match_windows(self, expr: str, self_window: Window | None = None):
        if expr == 'all':
            yield from self.all_windows
            return
        for window in self.all_windows:
            if str(window.id) == expr:
                yield window


class TestRemoteControl(BaseTest):
    def test_set_os_window_title_command_is_registered(self):
        self.assertIn('set_os_window_title', all_command_names())
        self.ae(command_for_name('set-os-window-title').name, 'set-os-window-title')

    def test_set_os_window_title_dedupes_os_windows(self):
        windows = [Window(1, 11), Window(2, 11), Window(3, 22)]
        boss = Boss(windows)
        cmd = command_for_name('set-os-window-title')

        with patch('kitty.rc.set_os_window_title.set_os_window_title_impl') as setter:
            cmd.response_from_kitty(boss, windows[0], PayloadGetter(cmd, {'match': 'all', 'self': True, 'title': 'repo'}))

        self.ae({call.args for call in setter.call_args_list}, {(11, 'repo'), (22, 'repo')})

    def test_set_os_window_title_without_title_resets_override(self):
        windows = [Window(1, 11)]
        boss = Boss(windows)
        cmd = command_for_name('set-os-window-title')

        with patch('kitty.rc.set_os_window_title.set_os_window_title_impl') as setter:
            cmd.response_from_kitty(boss, windows[0], PayloadGetter(cmd, {'self': True}))

        setter.assert_called_once_with(11, '')


TALK_THREAD_SURVIVES_ACCEPT_ERROR = """
import os, socket, sys, time
from kitty.fast_data_types import ChildMonitor
ls = socket.socket(socket.AF_UNIX)
ls.bind(sys.argv[1])
ls.listen(8)
cm = ChildMonitor(lambda *a: None, None, -1, ls.fileno())
a, b = socket.socketpair()
cm.inject_peer(os.dup(a.fileno()))
cm.fail_next_accepts(2)
c = socket.socket(socket.AF_UNIX)
c.connect(sys.argv[1])
deadline = time.monotonic() + 10
while cm.fail_next_accepts(-1) and time.monotonic() < deadline:
    time.sleep(0.01)
assert cm.fail_next_accepts(-1) == 0, 'injected accept errors not consumed'
cm.inject_peer(os.dup(b.fileno()))
print('ok', flush=True)
os._exit(0)
"""


TALK_THREAD_STALLED_PEER = """
import os, socket
from kitty.fast_data_types import ChildMonitor, send_data_to_peer
cm = ChildMonitor(lambda *a: None, None)
a, a_remote = socket.socketpair()
b, b_remote = socket.socketpair()
big = os.urandom(8 * 1024 * 1024)
pa = cm.inject_peer(os.dup(a.fileno()))
send_data_to_peer(pa, big)
pb = cm.inject_peer(os.dup(b.fileno()))
send_data_to_peer(pb, b'hello')
b_remote.settimeout(10)
assert b_remote.recv(16) == b'hello'
a_remote.settimeout(10)
got = bytearray()
while len(got) < len(big):
    got += a_remote.recv(1024 * 1024)
assert got == big, 'stalled peer response corrupted'
print('ok', flush=True)
os._exit(0)
"""


class TestTalkThread(BaseTest):

    def test_talk_thread_not_blocked_by_stalled_peer(self):
        p = subprocess.run([kitty_exe(), '+runpy', TALK_THREAD_STALLED_PEER], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('ok', p.stdout, p.stderr)

    def test_talk_thread_survives_accept_errors(self):
        with tempfile.TemporaryDirectory() as tdir:
            p = subprocess.run(
                [kitty_exe(), '+runpy', TALK_THREAD_SURVIVES_ACCEPT_ERROR, os.path.join(tdir, 's')],
                capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('ok', p.stdout, p.stderr)
        self.assertEqual(p.stderr.count('accept() on talk socket failed'), 1, p.stderr)
