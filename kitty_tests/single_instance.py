#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import json
import os
import socket
import subprocess
import sys
from contextlib import closing

from kitty.constants import kitty_exe

from .base import BaseTest


class TestSingleInstance(BaseTest):
    def test_single_instance_client(self):
        # Test that a client can talk to a single instance socket belonging to
        # the same user. The abstract socket namespace used below exists only
        # on Linux.
        if not sys.platform.startswith('linux'):
            self.skipTest('Abstract UNIX sockets are only available on Linux')
        group = f'test-{os.getpid()}'
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as server:
            server.bind('\0' + f'kitty-ipc-{os.geteuid()}-{group}')
            server.listen()
            env = os.environ.copy()
            env['KITTY_SINGLE_INSTANCE_TEST'] = 'xyz'
            p = subprocess.Popen(
                [kitty_exe(), '--single-instance', f'--instance-group={group}', '--title', 'si-test-title'],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                with closing(server.accept()[0]) as peer:
                    data = b''
                    while True:
                        d = peer.recv(8192)
                        if not d:
                            break
                        data += d
                output = p.communicate(timeout=30)[0].decode()
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()
            self.assertEqual(p.returncode, 0, f'kitty --single-instance failed with output: {output}')
            msg = json.loads(data.decode('utf-8'))
            self.assertEqual(msg['cmd'], 'new_instance')
            self.assertIn('si-test-title', msg['args'])
            self.assertEqual(msg['cwd'], os.getcwd())
            self.assertEqual(msg['environ'].get('KITTY_SINGLE_INSTANCE_TEST'), 'xyz')
