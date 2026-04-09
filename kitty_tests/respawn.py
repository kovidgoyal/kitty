#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import signal
import tempfile
import time
from contextlib import suppress

from . import BaseTest


class FakeBoss:
    encryption_public_key = 'test_key'
    listening_on = ''


class TestRespawn(BaseTest):

    def setUp(self):
        super().setUp()
        from kitty.fast_data_types import get_boss, set_boss
        self.set_options()
        self._old_boss = get_boss()
        set_boss(FakeBoss())
        self._pids: list[int] = []
        self._fds: set[int] = set()
        self._tmpdirs: list[str] = []

    def tearDown(self):
        from kitty.fast_data_types import set_boss
        for pid in self._pids:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
        for fd in self._fds:
            with suppress(OSError):
                os.close(fd)
        for d in self._tmpdirs:
            with suppress(OSError):
                os.rmdir(d)
        set_boss(self._old_boss)
        super().tearDown()

    def _tmpdir(self) -> str:
        d = tempfile.mkdtemp()
        self._tmpdirs.append(d)
        return d

    def _make_child(self, code: str = 'import time; time.sleep(100)', cwd: str | None = None):
        from kitty.child import Child
        if cwd is None:
            cwd = self._tmpdir()
        child = Child(self.cmd_to_run_python_code(code), cwd)
        child.fork()
        child.mark_terminal_ready()
        self._pids.append(child.pid)
        self._fds.add(child.child_fd)
        return child

    def _respawn(self, child, **kwargs):
        result = child.respawn(**kwargs)
        self.assertIsNotNone(result)
        child.mark_terminal_ready()
        old_pid, old_fd = result
        self._pids.append(child.pid)
        self._fds.add(child.child_fd)
        return old_pid, old_fd

    def _read_child_output(self, fd: int, timeout: float = 0.3) -> bytes:
        os.set_blocking(fd, False)
        time.sleep(timeout)
        with suppress(BlockingIOError):
            return os.read(fd, 4096)
        return b''

    def test_child_respawn_basic(self):
        """Test that Child.respawn() creates a new process and returns old pid/fd."""
        child = self._make_child()
        old_pid, old_fd = child.pid, child.child_fd

        new_cwd = self._tmpdir()
        returned_old_pid, returned_old_fd = self._respawn(
            child, cwd=new_cwd,
            argv=self.cmd_to_run_python_code('print("respawned", flush=True); import time; time.sleep(100)'),
        )

        self.assertEqual(returned_old_pid, old_pid)
        self.assertEqual(returned_old_fd, old_fd)
        self.assertNotEqual(child.pid, old_pid)
        self.assertIn(b'respawned', self._read_child_output(child.child_fd))

        proc_cwd = os.readlink(f'/proc/{child.pid}/cwd')
        self.assertEqual(os.path.realpath(proc_cwd), os.path.realpath(new_cwd))

    def test_child_respawn_env(self):
        """Test that respawn merges new env vars."""
        child = self._make_child()
        self._respawn(
            child,
            env={'KITTY_TEST_RESPAWN_VAR': 'test_value'},
            argv=self.cmd_to_run_python_code(
                'import os; print(os.environ["KITTY_TEST_RESPAWN_VAR"], flush=True); import time; time.sleep(100)'
            ),
        )
        self.assertIn(b'test_value', self._read_child_output(child.child_fd))

    def test_child_respawn_hold(self):
        """Test that respawn with hold=True sets the hold flag."""
        child = self._make_child()
        self.assertFalse(child.hold)
        old_pid = child.pid

        self._respawn(child, hold=True)

        self.assertTrue(child.hold)
        self.assertNotEqual(child.pid, old_pid)
        os.kill(child.pid, 0)  # verify process is alive

    def test_child_respawn_repeated(self):
        """Test that respawning multiple times doesn't corrupt argv."""
        child = self._make_child()
        original_argv = list(child.argv)

        for i in range(2):
            self._respawn(child)
            self.assertEqual(child.argv_before_cwd_rewrite, original_argv,
                             f'argv corrupted after respawn #{i+1}')

    def test_child_respawn_not_forked(self):
        """Test that respawn returns None if child was never forked."""
        from kitty.child import Child
        child = Child(self.cmd_to_run_python_code('pass'), '/tmp')
        self.assertIsNone(child.respawn())

    def test_dup2_fd_reuse(self):
        """Test the dup2 trick: after dup2(new_fd, old_fd), reading old_fd gives new child's output."""
        import pty
        old_master, old_slave = pty.openpty()
        new_master, new_slave = pty.openpty()

        pid = os.fork()
        if pid == 0:
            os.close(old_master)
            os.close(old_slave)
            os.close(new_master)
            os.dup2(new_slave, 1)
            os.close(new_slave)
            os.write(1, b'from_new_child\n')
            os._exit(0)

        os.close(old_slave)
        os.close(new_slave)
        os.dup2(new_master, old_master)
        os.close(new_master)

        self.assertIn(b'from_new_child', self._read_child_output(old_master, timeout=0.2))
        os.close(old_master)
        os.waitpid(pid, 0)
