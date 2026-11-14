#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from kitty.child import Child, KittyWrapper, children_of_process, cmdline_of_pid, cwd_of_process, memory_used_by_process_tree_rooted_at
from kitty.constants import is_macos, kitty_exe

from .base import BaseTest


def spawn_and_wait_for_ready(code: str, what: str) -> subprocess.Popen:
    # Run code via kitty +runpy and wait for it to print ready. stderr is
    # captured, as in test workers it is /dev/null, so that the reason the
    # child failed is reported.
    p = subprocess.Popen([kitty_exe(), '+runpy', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    line = p.stdout.readline().strip()
    p.stdout.close()
    if line != b'ready':
        p.kill()
        err = p.stderr.read().decode('utf-8', 'replace')
        p.stderr.close()
        raise AssertionError(f'Unexpected output from {what}: {line!r} exit code: {p.wait()} stderr:\n{err}')
    p.stderr.close()
    return p


class ChildMemoryTest(BaseTest):
    def _spawn_allocating_child(self, alloc_bytes: int) -> subprocess.Popen:
        return spawn_and_wait_for_ready(
            f"""\
import sys, time
buf = bytearray({alloc_bytes})
for i in range(0, {alloc_bytes}, 4096):
    buf[i] = 1
sys.stdout.write("ready\\n")
sys.stdout.flush()
time.sleep(300)
""",
            'allocating child',
        )

    def _terminate(self, p: subprocess.Popen) -> None:
        p.terminate()
        p.wait()

    def test_memory_returns_positive_for_live_process(self):
        mem = memory_used_by_process_tree_rooted_at(os.getpid())
        self.assertGreater(mem, 0)

    def test_memory_returns_minus_one_for_nonexistent_pid(self):
        self.ae(memory_used_by_process_tree_rooted_at(99999999), -1)

    def test_memory_accounts_for_child_allocation(self):
        # Verify that a child's known resident allocation shows up in the
        # measurement.  check_if_cgroup_root=True falls back to per-process
        # tree walk when pid is not the cgroup root (the common case when
        # running under a shared session cgroup), so this exercises the tree
        # walk path on Linux and the always-tree-walk path on macOS.
        alloc = 20 * 1024 * 1024  # 20 MiB
        child = self._spawn_allocating_child(alloc)
        try:
            mem = memory_used_by_process_tree_rooted_at(child.pid, check_if_cgroup_root=True)
            self.assertGreater(
                mem,
                alloc // 2,
                f'Expected at least {alloc // 2} bytes for a {alloc}-byte allocation, got {mem}',
            )
        finally:
            self._terminate(child)

    def test_memory_of_parent_tree_includes_child(self):
        # Measuring the current process tree must yield more than measuring
        # the child alone, because the test runner itself occupies memory.
        alloc = 20 * 1024 * 1024  # 20 MiB
        child = self._spawn_allocating_child(alloc)
        try:
            mem_child = memory_used_by_process_tree_rooted_at(child.pid, check_if_cgroup_root=True)
            mem_tree = memory_used_by_process_tree_rooted_at(os.getpid(), check_if_cgroup_root=True)
            self.assertGreater(
                mem_tree,
                mem_child,
                'Parent tree memory should exceed child-only memory',
            )
        finally:
            self._terminate(child)

    def test_memory_cgroup_path_returns_positive(self):
        # The fast cgroup path (check_if_cgroup_root=False, the default) must
        # return a usable value on Linux.
        if is_macos:
            self.skipTest('cgroup not available on macOS')
        mem = memory_used_by_process_tree_rooted_at(os.getpid())
        self.assertGreater(mem, 0)

    def test_memory_cgroup_and_tree_walk_both_positive(self):
        # Both the cgroup path and the tree-walk path should give positive
        # results for a process that is alive.
        if is_macos:
            self.skipTest('cgroup path not applicable on macOS')
        alloc = 10 * 1024 * 1024  # 10 MiB
        child = self._spawn_allocating_child(alloc)
        try:
            mem_cgroup = memory_used_by_process_tree_rooted_at(child.pid, check_if_cgroup_root=False)
            mem_walk = memory_used_by_process_tree_rooted_at(child.pid, check_if_cgroup_root=True)
            self.assertGreater(mem_cgroup, 0)
            self.assertGreater(mem_walk, 0)
        finally:
            self._terminate(child)


class ChildRootTest(BaseTest):
    def _spawn_wrapper(self, child_cwd: str, start_child: bool = True) -> subprocess.Popen:
        # A process that, like /usr/bin/login, runs a child and waits for it.
        # The child is started from a non-main thread, as kitten does.
        code = f"""\
import sys, threading, time
def run_child(started):
    import subprocess, sys, time
    subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(300)'], cwd={child_cwd!r},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started.set()
    time.sleep(300)  # keep the thread alive so the child stays its child
if {start_child!r}:
    started = threading.Event()
    threading.Thread(target=run_child, args=(started,), daemon=True).start()
    if not started.wait(10):
        raise SystemExit('Failed to start child')
sys.stdout.write("ready\\n")
sys.stdout.flush()
time.sleep(300)
"""
        return spawn_and_wait_for_ready(code, 'wrapper')

    def _terminate_tree(self, p: subprocess.Popen) -> None:
        children = children_of_process(p.pid)
        p.terminate()
        p.wait()
        for c in children:
            try:
                os.kill(c, 15)
            except ProcessLookupError:
                pass

    def _child_for(self, pid: int, *wrappers: KittyWrapper) -> Child:
        c = Child(['unused'], '/')
        c.pid = pid
        c.kitty_wrappers = wrappers
        return c

    def test_root_pid(self):
        with tempfile.TemporaryDirectory() as tdir:
            tdir = os.path.realpath(tdir)
            p = self._spawn_wrapper(tdir)
            try:
                children = children_of_process(p.pid)
                self.ae(len(children), 1)
                inner = children[0]
                self.ae(cwd_of_process(inner), tdir)
                self.assertNotEqual(cwd_of_process(p.pid), tdir)
                # Not launched via a wrapper, the original process is root
                c = self._child_for(p.pid)
                self.ae(c.root_pid, p.pid)
                self.ae(c.current_cwd, cwd_of_process(p.pid))
                # A wrapper that never replaces itself is always skipped
                c = self._child_for(p.pid, KittyWrapper(('/usr/bin/login', '-f'), False))
                self.ae(c.root_pid, inner)
                self.ae(c.current_cwd, tdir)
                # A wrapper that replaces itself is skipped only while it is
                # still running as the wrapper
                argv = tuple(cmdline_of_pid(p.pid))
                c = self._child_for(p.pid, KittyWrapper(argv[:2], True))
                self.ae(c.root_pid, inner)
                c = self._child_for(p.pid, KittyWrapper(('/some/other/wrapper',), True))
                self.ae(c.root_pid, p.pid)
                # Skipping stops at the first process that is not a wrapper
                c = self._child_for(p.pid, KittyWrapper(argv[:2], True), KittyWrapper(('/some/other/wrapper',), True))
                self.ae(c.root_pid, inner)
            finally:
                self._terminate_tree(p)

    def test_root_pid_caching(self):
        with tempfile.TemporaryDirectory() as tdir:
            p = self._spawn_wrapper(tdir)
            try:
                inner = children_of_process(p.pid)[0]
                argv = tuple(cmdline_of_pid(p.pid))
                # No wrappers, nothing to resolve
                c = self._child_for(p.pid)
                self.ae(c.root_pid, p.pid)
                self.assertIsNone(c.resolved_root_pid)
                # A wrapper that never replaces itself has a fixed child
                c = self._child_for(p.pid, KittyWrapper(('/usr/bin/login',), False))
                self.ae(c.root_pid, inner)
                self.ae(c.resolved_root_pid, inner)
                # A wrapper that will replace itself, its child is cached but
                # not the result
                wrapping = KittyWrapper(argv[:2], True)
                c = self._child_for(p.pid, wrapping)
                self.ae(c.root_pid, inner)
                self.assertIsNone(c.resolved_root_pid)
                self.ae(c.wrapper_children, {p.pid: inner})
                # Once it has replaced itself, the result is final
                replaced = KittyWrapper(('/not/the/wrapper/anymore',), True)
                c.kitty_wrappers = (replaced,)
                self.ae(c.root_pid, p.pid)
                self.ae(c.resolved_root_pid, p.pid)
                self.ae(c.wrapper_children, {})
                # Not looking like the wrapper without ever having looked like
                # it, means it might not have been exec-ed yet, so dont cache
                c = self._child_for(p.pid, replaced)
                self.ae(c.root_pid, p.pid)
                self.assertIsNone(c.resolved_root_pid)
                # The original process properties use the root process
                c = self._child_for(p.pid, KittyWrapper(('/usr/bin/login',), False))
                self.ae(c.current_cwd, os.path.realpath(tdir))
                self.ae(c.cmdline, cmdline_of_pid(inner))
            finally:
                self._terminate_tree(p)

    def test_descendants_from_threads(self):
        if is_macos:
            self.skipTest('Per thread children lists are Linux only')
        from kitty import child

        with tempfile.TemporaryDirectory() as tdir:
            p = self._spawn_wrapper(tdir)
            try:
                inner = children_of_process(p.pid)
                self.ae(len(inner), 1)
                self.ae(child._get_descendants_of(p.pid), set(inner))
                # Kernels without /proc/<pid>/task/<tid>/children
                orig = child.proc_children_supported
                child.proc_children_supported = lambda: False  # type: ignore
                try:
                    self.ae(children_of_process(p.pid), inner)
                    self.ae(child._get_descendants_of(p.pid), set(inner))
                finally:
                    child.proc_children_supported = orig
            finally:
                self._terminate_tree(p)

    def test_root_pid_wrapper_without_child(self):
        p = self._spawn_wrapper('/', start_child=False)
        try:
            self.ae(children_of_process(p.pid), [])
            c = self._child_for(p.pid, KittyWrapper(('/usr/bin/login',), False))
            self.ae(c.root_pid, p.pid)
        finally:
            self._terminate_tree(p)


class LaunchWrapperTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.set_options({'shell_integration': frozenset({'disabled'})})
        self.contexts = []

    def tearDown(self):
        from kitty.launch_wrapper import load_prefix_func

        load_prefix_func.clear_override()
        super().tearDown()

    def _fork(self, argv=('/bin/prog', 'arg'), launch_request=None, hold=False, user_func=None):
        # Fork a Child with spawning faked, returning the Child and the
        # exe and argv that would have been spawned
        from kitty import child as child_module
        from kitty.launch_wrapper import load_prefix_func

        load_prefix_func.set_override(user_func)
        spawned = {}

        def spawn(exe, cwd, argv, *a):
            spawned['exe'], spawned['argv'] = exe, argv
            return 1234567

        boss = SimpleNamespace(encryption_public_key='key', listening_on='', window_id_map={})
        c = Child(list(argv), '/', env={'KITTY_WINDOW_ID': '7'}, hold=hold, launch_request=launch_request)
        with (
            patch.object(child_module.fast_data_types, 'spawn', spawn),
            patch.object(child_module.fast_data_types, 'get_boss', return_value=boss),
            patch.object(child_module.fast_data_types, 'systemd_move_pid_into_new_scope', side_effect=NotImplementedError, create=True),
        ):
            c.fork()
        os.close(c.child_fd)
        c.child_fd = None
        return c, spawned['exe'], spawned['argv']

    def _recording(self, ans):
        def func(ctx):
            self.contexts.append(ctx)
            if isinstance(ans, Exception):
                raise ans
            return ans

        return func

    def test_launch_wrapper(self):
        from kitty.launch_wrapper import LaunchRequest

        req = LaunchRequest('tab', None, (('a', 'b'),))
        # Not a user launch, the wrapper is not called
        c, exe, argv = self._fork(user_func=self._recording(['wrapper', '-x']))
        self.ae(argv, ('/bin/prog', 'arg'))
        self.ae(self.contexts, [])
        self.ae(c.kitty_wrappers, ())
        # No launch_wrapper.py
        c, exe, argv = self._fork(launch_request=req)
        self.ae(argv, ('/bin/prog', 'arg'))
        # A prefix is applied, with the actual command still known to kitty
        c, exe, argv = self._fork(launch_request=req, user_func=self._recording(['/bin/wrapper', '-x']))
        self.ae(argv, ('/bin/wrapper', '-x', '/bin/prog', 'arg'))
        self.ae(exe, '/bin/wrapper')
        self.ae(c.argv, ['/bin/prog', 'arg'])
        self.ae(c.final_exe, '/bin/prog')
        self.ae(c.kitty_wrappers, (KittyWrapper(('/bin/wrapper', '-x'), True),))
        ctx = self.contexts[-1]
        self.ae(ctx.argv, ('/bin/prog', 'arg'))
        self.ae(ctx.cwd, '/')
        self.ae(ctx.window_id, 7)
        self.ae(ctx.launch_type, 'tab')
        self.ae(ctx.source_window_id, None)
        self.ae(ctx.source_pid, None)
        self.ae(dict(ctx.user_vars), {'a': 'b'})
        self.ae(ctx.env['KITTY_WINDOW_ID'], '7')
        self.assertFalse(ctx.is_default_shell)
        with self.assertRaises(TypeError):
            ctx.env['x'] = 'y'
        # The hold wrapper runs outside the user's wrapper
        c, exe, argv = self._fork(launch_request=req, hold=True, user_func=self._recording(['/bin/wrapper']))
        self.ae(argv[-2:], ('/bin/prog', 'arg'))
        self.ae(argv[-3], '/bin/wrapper')
        self.ae(c.kitty_wrappers[-1], KittyWrapper(('/bin/wrapper',), True))
        self.ae(len(c.kitty_wrappers), 2)
        self.ae(c.kitty_wrappers[0].argv, argv[: len(c.kitty_wrappers[0].argv)])
        # Failures and invalid return values result in no prefix
        from kitty import launch_wrapper

        errors = []
        with patch.object(launch_wrapper, 'log_error', lambda *a: errors.append(a)):
            for bad in (ValueError('oops'), 'a string', ['ok', 1], 3):
                c, exe, argv = self._fork(launch_request=req, user_func=self._recording(bad))
                self.ae(argv, ('/bin/prog', 'arg'))
                self.ae(c.kitty_wrappers, ())
            for empty in (None, [], ()):
                c, exe, argv = self._fork(launch_request=req, user_func=self._recording(empty))
                self.ae(argv, ('/bin/prog', 'arg'))
        self.ae(len(errors), 4)
