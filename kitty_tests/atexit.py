#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>


import os
import select
import shutil
import signal
import subprocess
import tempfile

from kitty.constants import kitten_exe, kitty_exe

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
            self.assertTrue(os.listdir(self.tdir))

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

        r('close')
        r('terminate')
        r('kill')
