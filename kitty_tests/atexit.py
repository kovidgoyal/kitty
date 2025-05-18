#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>


import os
import select
import shutil
import signal
import subprocess
import tempfile

from kitty.constants import kitten_exe, kitty_exe
from kitty.shm import SharedMemory

from . import BaseTest


class Atexit(BaseTest):

    def setUp(self):
        self.tdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tdir)

    def test_atexit(self):

        def r(action='close'):
            p = subprocess.Popen([kitty_exe(), '+runpy', f'''\
import subprocess
p = subprocess.Popen(['{kitten_exe()}', '__atexit__'])
print(p.pid, flush=True)
raise SystemExit(p.wait())
'''], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            readers = [p.stdout.fileno()]
            def read():
                r, _, _ = select.select(readers, [], [], 10)
                if not r:
                    raise TimeoutError('Timed out waiting for read from child')
                return p.stdout.readline().rstrip().decode()
            atexit_pid = int(read())
            for i in range(2):
                with open(os.path.join(self.tdir, str(i)), 'w') as f:
                    p.stdin.write(f'unlink {f.name}\n'.encode())
                    p.stdin.flush()
                select.select(readers, [], [], 10)
                self.ae(read(), str(i+1))
            sdir = os.path.join(self.tdir, 'd')
            os.mkdir(sdir)
            p.stdin.write(f'rmtree {sdir}\n'.encode())
            p.stdin.flush()
            open(os.path.join(sdir, 'f'), 'w').close()
            select.select(readers, [], [], 10)
            self.ae(read(), str(i+2))
            shm = SharedMemory(size=64)
            shm.write(b'1' * 64)
            shm.flush()
            p.stdin.write(f'shm_unlink {shm.name}\n'.encode())
            p.stdin.flush()
            self.ae(read(), str(i+3))

            self.assertTrue(os.listdir(self.tdir))
            shm2 = SharedMemory(shm.name)
            self.ae(shm2.read()[:64], b'1' * 64)

            # Ensure child is ignoring signals
            os.kill(atexit_pid, signal.SIGINT)
            os.kill(atexit_pid, signal.SIGTERM)
            if action == 'close':
                p.stdin.close()
            elif action == 'terminate':
                p.terminate()
            else:
                p.kill()
            p.wait(10)
            if action != 'close':
                p.stdin.close()
            select.select(readers, [], [], 10)
            self.assertFalse(read())
            p.stdout.close()
            self.assertFalse(os.listdir(self.tdir))
            try:
                os.waitpid(atexit_pid, 0)
            except ChildProcessError:
                pass
            self.assertRaises(FileNotFoundError, lambda: SharedMemory(shm.name))

        r('close')
        r('terminate')
        r('kill')
