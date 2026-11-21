#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from select import select
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kitty.child import Child, KittyWrapper, children_of_process, cmdline_of_pid, cwd_of_process, memory_used_by_process_tree_rooted_at
from kitty.constants import is_macos, kitten_exe, kitty_exe

from .base import BaseTest


def _descendants(pid: int) -> list[int]:
    ans = []
    for child in children_of_process(pid):
        ans.append(child)
        ans.extend(_descendants(child))
    return ans


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

    def _fork(self, argv=('/bin/prog', 'arg'), launch_request=None, hold=False, user_func=None, cwd='/', env=None):
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
        c = Child(list(argv), cwd, env={'KITTY_WINDOW_ID': '7', **(env or {})}, hold=hold, launch_request=launch_request)
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

    def test_wrapper_matches_cmdline(self):
        def cmdline(*args):
            # cmdline_of_pid() drops empty arguments on Linux
            return args if is_macos else tuple(filter(None, args))

        w = KittyWrapper(('wrapper', '-x'), True, ('-x', 'prog', 'arg'))
        for yes in (
            ('wrapper', '-x', 'prog', 'arg'),
            # Run via PATH lookup by the hold kitten
            ('/usr/bin/wrapper', '-x', 'prog', 'arg'),
            ('/bin/sh', '/usr/bin/wrapper', '-x', 'prog', 'arg'),
            ('/usr/bin/env', 'sh', '-e', 'wrapper', '-x', 'prog', 'arg'),
        ):
            self.assertTrue(w.matches_cmdline(yes), yes)
        for no in (
            (),
            ('prog', 'arg'),
            ('/usr/bin/other', '-x', 'prog', 'arg'),
            ('/usr/bin/wrapper', 'prog', 'arg'),
            ('/bin/sh', '/usr/bin/other', '-x', 'prog', 'arg'),
            ('/bin/sh', '/usr/bin/wrapper', '-x', 'prog'),
            ('/bin/sh', '/usr/bin/wrapper', 'prog', 'arg'),
            ('/bin/sh', 'wrapper', 'prog', 'arg'),
        ):
            self.assertFalse(w.matches_cmdline(no), no)
        self.assertFalse(KittyWrapper(('wrapper', '-x'), True).matches_cmdline(('/bin/sh', '/usr/bin/wrapper', '-x', 'prog', 'arg')))
        # Wrappers specified by path must be run from that path
        w = KittyWrapper(('/opt/wrapper',), True, ('prog',))
        self.assertTrue(w.matches_cmdline(('/opt/wrapper', 'prog')))
        self.assertTrue(w.matches_cmdline(('/bin/sh', '/opt/wrapper', 'prog')))
        self.assertFalse(w.matches_cmdline(('/usr/opt/wrapper', 'prog')))
        self.assertFalse(w.matches_cmdline(('/bin/sh', '/usr/opt/wrapper', 'prog')))
        # Empty arguments
        w = KittyWrapper(('wrapper', '', 'x'), True, ('', 'x', '', 'prog'))
        self.assertTrue(w.matches_cmdline(cmdline('wrapper', '', 'x', '', 'prog')))
        self.assertTrue(w.matches_cmdline(cmdline('/bin/sh', '/bin/wrapper', '', 'x', '', 'prog')))
        self.assertFalse(w.matches_cmdline(cmdline('', 'prog')))

    def test_wrapper_runs_command(self):
        w = KittyWrapper(('wrapper', '-x'), True, ('-x', 'prog', 'arg'))
        for yes in (
            ('prog', 'arg'),
            ('/usr/bin/prog', 'arg'),
            ('/bin/sh', '/usr/bin/prog', 'arg'),
        ):
            self.assertTrue(w.runs_command(yes), yes)
        for no in (
            (),
            ('prog',),
            ('prog', 'arg', 'x'),
            ('other', 'arg'),
            ('/bin/sh', '/usr/bin/other', 'arg'),
            ('/bin/sh', '/usr/bin/wrapper', '-x', 'prog', 'arg'),
        ):
            self.assertFalse(w.runs_command(no), no)
        self.assertFalse(KittyWrapper(('wrapper', '-x'), True).runs_command(('prog', 'arg')))

    def _read_line(self, p: subprocess.Popen) -> str:
        self.assertTrue(select([p.stdout], [], [], 5)[0], 'Timed out waiting for output')
        return p.stdout.readline().decode().strip()

    def _stop_tree(self, p: subprocess.Popen) -> None:
        # Closing stdin makes everything the tests run exit, kill whatever
        # does not, as leftover processes keep the output of the test runner
        # open
        descendants = _descendants(p.pid)
        p.stdin.close()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        for pid in descendants:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)

    def _assert_root_pid_settles(self, c: Child, expected: int, timeout: float = 5) -> None:
        # Reading the process tree from /proc is not atomic, so on a heavily
        # loaded machine root_pid can transiently fail to resolve all the way
        # down to the command. Such results are never cached, so wait for it
        # to settle, while a wrong result that is cached still fails.
        end_time = time.monotonic() + timeout
        while (actual := c.root_pid) != expected and time.monotonic() < end_time:
            time.sleep(0.01)
        if actual != expected:
            tree = {}
            for pid in [c.pid] + _descendants(c.pid):
                try:
                    tree[pid] = cmdline_of_pid(pid), children_of_process(pid)
                except Exception as err:
                    tree[pid] = err
            self.fail(f'root_pid: {actual} != {expected} wrappers: {c.kitty_wrappers} resolved: {c.resolved_root_pid} process tree: {tree}')

    def _send_line(self, p: subprocess.Popen) -> None:
        p.stdin.write(b'\n')
        p.stdin.flush()

    # The command reports its PID and waits for a line on stdin in a child, so
    # the process tree is ready when its PID is reported
    report_pid = r"""/bin/sh -c 'printf "%s\n" "$0"; read -r _' "$$"
exit $?"""

    def test_script_launch_wrapper_root_pid(self):
        from kitty.launch_wrapper import LaunchRequest

        req = LaunchRequest('tab')
        # Reports its own PID and waits for a line, before exec-ing the command
        exec_wrapper = 'printf "%s\\n" "$$"\nread -r _\nexec "$@"\n'
        child_wrapper = '"$@"\nexit $?\n'
        # Runs another command first, and keeps running after the command exits
        busy_wrapper = """shift 2
/bin/sh -c 'printf "%s\\n" "$$"; read -r _'
"$@"
echo done
read -r _
"""
        # Starts a background helper before the command and keeps it alive
        background_wrapper = """sleep 60 &
trap "kill $!" EXIT
printf "%s\\n" "$!"
read -r _
"$@"
"""

        with tempfile.TemporaryDirectory() as tdir, patch.dict(os.environ, {'PATH': tdir + os.pathsep + os.environ.get('PATH', '')}):
            name = 'launch-wrapper'
            script = os.path.join(tdir, name)
            # The command takes the path to the wrapper as an argument, to
            # check it is not mistaken for the wrapper after being exec-ed
            command = ('/bin/sh', '-c', self.report_pid, script, '')
            for kind, body, prefix in (
                ('exec', exec_wrapper, (name,)),
                ('child', child_wrapper, (name,)),
                ('busy', busy_wrapper, (name, '', 'x')),
                ('background', background_wrapper, (name,)),
            ):
                with self.subTest(wrapper=kind):
                    with open(script, 'w') as f:
                        f.write('#!/bin/sh -e\n' + body)
                    os.chmod(script, 0o700)
                    c, exe, argv = self._fork(argv=command, launch_request=req, user_func=lambda ctx, prefix=prefix: list(prefix))
                    with subprocess.Popen(argv, executable=exe, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0) as p:
                        c.pid = p.pid
                        try:
                            if kind == 'exec':
                                # Not exec-ed yet and has no child
                                self.ae(int(self._read_line(p)), p.pid)
                                self.ae(c.root_pid, p.pid)
                                self.assertIsNone(c.resolved_root_pid)
                                self._send_line(p)
                            elif kind in ('busy', 'background'):
                                # Query while the helper is the wrapper's only child
                                helper_pid = int(self._read_line(p))
                                self.ae(c.root_pid, helper_pid)
                                self._send_line(p)
                            command_pid = int(self._read_line(p))
                            self.ae(command_pid == p.pid, kind == 'exec')
                            if kind == 'background':
                                self.ae(set(children_of_process(p.pid)), {helper_pid, command_pid})
                            self.ae(c.root_pid, command_pid)
                            if kind == 'exec':
                                self.ae(c.resolved_root_pid, p.pid)
                            elif kind == 'busy':
                                self._send_line(p)
                                self.ae(self._read_line(p), 'done')
                                # The command has exited, leaving only the wrapper
                                self.ae(c.root_pid, p.pid)
                                self.assertIsNone(c.resolved_root_pid)
                        finally:
                            self._stop_tree(p)

    def test_launch_wrapper_root_pid_with_hold(self):
        # The hold kitten runs wrappers specified by name via their path
        from kitty.launch_wrapper import LaunchRequest

        if not shutil.which('timeout'):
            self.skipTest('No timeout program')
        from kitty.launch_wrapper import LaunchPrefix, hold_prefix

        command = ('/bin/sh', '-c', self.report_pid, 'arg')
        for kind, user_func in (
            ('kitty holds', lambda ctx: ['timeout', '100']),
            # The wrapper holds the window inside itself
            ('wrapper holds', lambda ctx: LaunchPrefix(argv=['timeout', '100'] + hold_prefix(), handles_hold=True)),
        ):
            with self.subTest(kind=kind):
                c, exe, argv = self._fork(argv=command, launch_request=LaunchRequest('tab'), hold=True, user_func=user_func)
                self.ae(argv[0] == 'timeout', kind == 'wrapper holds')
                with subprocess.Popen(argv, executable=exe, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0) as p:
                    c.pid = p.pid
                    try:
                        command_pid = int(self._read_line(p))
                        if cmdline_of_pid(command_pid)[0] != command[0]:
                            # Under emulation, such as qemu-user via binfmt_misc, the
                            # cmdline of processes starts with the emulator
                            self.skipTest('Running under emulation')
                        self._assert_root_pid_settles(c, command_pid)
                    finally:
                        self._stop_tree(p)

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
        self.ae(c.kitty_wrappers, (KittyWrapper(('/bin/wrapper', '-x'), True, ('-x', '/bin/prog', 'arg')),))
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
        self.assertFalse(ctx.hold)
        with self.assertRaises(TypeError):
            ctx.env['x'] = 'y'
        # The hold wrapper runs outside the user's wrapper
        c, exe, argv = self._fork(launch_request=req, hold=True, user_func=self._recording(['/bin/wrapper']))
        self.ae(argv[-2:], ('/bin/prog', 'arg'))
        self.ae(argv[-3], '/bin/wrapper')
        self.assertTrue(self.contexts[-1].hold)
        self.ae(c.kitty_wrappers[-1], KittyWrapper(('/bin/wrapper',), True, ('/bin/prog', 'arg')))
        self.ae(len(c.kitty_wrappers), 2)
        self.ae(c.kitty_wrappers[0].argv, argv[: len(c.kitty_wrappers[0].argv)])
        # The full form of the return value
        from kitty.launch_wrapper import LaunchPrefix, hold_prefix

        c, exe, argv = self._fork(launch_request=req, user_func=self._recording(LaunchPrefix(argv=['/bin/wrapper', '-x'])))
        self.ae(argv, ('/bin/wrapper', '-x', '/bin/prog', 'arg'))
        self.ae(c.kitty_wrappers, (KittyWrapper(('/bin/wrapper', '-x'), True, ('-x', '/bin/prog', 'arg')),))
        # The wrapper can hold the window itself
        c, exe, argv = self._fork(launch_request=req, hold=True, user_func=self._recording(LaunchPrefix(argv=['/bin/wrapper'], handles_hold=True)))
        self.ae(argv, ('/bin/wrapper', '/bin/prog', 'arg'))
        self.ae(c.kitty_wrappers, (KittyWrapper(('/bin/wrapper',), True, ('/bin/prog', 'arg')),))
        # using the same helper as kitty, which is then skipped over
        hp = tuple(hold_prefix())
        c, exe, argv = self._fork(launch_request=req, hold=True, user_func=self._recording(LaunchPrefix(argv=('/bin/wrapper',) + hp, handles_hold=True)))
        self.ae(argv, ('/bin/wrapper',) + hp + ('/bin/prog', 'arg'))
        self.ae(c.kitty_wrappers, (KittyWrapper(('/bin/wrapper',), True, hp + ('/bin/prog', 'arg')), KittyWrapper(hp, True)))
        # handles_hold is ignored with no prefix, as nothing could hold the window
        c, exe, argv = self._fork(launch_request=req, hold=True, user_func=self._recording(LaunchPrefix(handles_hold=True)))
        self.ae(argv, hp + ('/bin/prog', 'arg'))
        # and does nothing when the window is not held
        c, exe, argv = self._fork(launch_request=req, user_func=self._recording(LaunchPrefix(argv=['/bin/wrapper'], handles_hold=True)))
        self.ae(argv, ('/bin/wrapper', '/bin/prog', 'arg'))
        with self.assertRaises(TypeError):
            LaunchPrefix(['/bin/wrapper'])  # type: ignore
        # Failures and invalid return values result in no prefix
        from kitty import launch_wrapper

        errors = []
        with patch.object(launch_wrapper, 'log_error', lambda *a: errors.append(a)):
            for bad in (ValueError('oops'), 'a string', ['ok', 1], 3, LaunchPrefix(argv='a string'), LaunchPrefix(argv=['ok'], handles_hold=1)):
                c, exe, argv = self._fork(launch_request=req, user_func=self._recording(bad))
                self.ae(argv, ('/bin/prog', 'arg'))
                self.ae(c.kitty_wrappers, ())
            for empty in (None, [], ()):
                c, exe, argv = self._fork(launch_request=req, user_func=self._recording(empty))
                self.ae(argv, ('/bin/prog', 'arg'))
        self.ae(len(errors), 6)

    def test_launch_wrapper_unresolved_argv(self):
        # The program is run as requested, so that the wrapper looks it up in
        # PATH, unless PATH would not find what kitty found
        from kitty import child as child_module
        from kitty.launch_wrapper import LaunchRequest

        req = LaunchRequest('tab')
        with tempfile.TemporaryDirectory() as tdir:
            on_path, off_path, alt_path = os.path.join(tdir, 'on'), os.path.join(tdir, 'off'), os.path.join(tdir, 'alt')
            for d, name in ((on_path, 'kitty-test-prog'), (off_path, 'kitty-test-other'), (alt_path, 'kitty-test-prog')):
                os.makedirs(d, exist_ok=True)
                exe = os.path.join(d, name)
                with open(exe, 'w') as f:
                    f.write('#!/bin/sh\n')
                os.chmod(exe, 0o755)
            path = os.pathsep.join((on_path, os.environ.get('PATH', os.defpath)))
            self.set_options({'shell_integration': frozenset({'disabled'}), 'exe_search_path': {off_path: off_path}})
            prog, other = os.path.join(on_path, 'kitty-test-prog'), os.path.join(off_path, 'kitty-test-other')
            with patch.dict(os.environ, {'PATH': path}):
                wrapper = self._recording(['/bin/wrapper'])
                # Found in PATH, kept as requested
                c, exe, argv = self._fork(argv=('kitty-test-prog', 'arg'), launch_request=req, user_func=wrapper)
                self.ae(self.contexts[-1].argv, ('kitty-test-prog', 'arg'))
                self.ae(argv, ('/bin/wrapper', 'kitty-test-prog', 'arg'))
                self.ae(c.resolved_exe, prog)
                # and without a wrapper, the resolved executable is run
                c, exe, argv = self._fork(argv=('kitty-test-prog', 'arg'))
                self.ae(argv, ('kitty-test-prog', 'arg'))
                self.ae(exe, prog)
                # Found only via exe_search_path, not in the PATH the child
                # gets, so the full path is used
                c, exe, argv = self._fork(argv=('kitty-test-other', 'arg'), launch_request=req, user_func=wrapper)
                self.ae(self.contexts[-1].argv, (other, 'arg'))
                self.ae(argv, ('/bin/wrapper', other, 'arg'))
                # PATH in the child environment finds a different executable
                # than kitty does
                c, exe, argv = self._fork(argv=('kitty-test-prog',), launch_request=req, user_func=wrapper, env={'PATH': alt_path})
                self.ae(self.contexts[-1].argv, (prog,))
                # Relative entries in PATH are relative to the working
                # directory of the child
                c, exe, argv = self._fork(argv=('kitty-test-prog',), launch_request=req, user_func=wrapper, env={'PATH': '.'}, cwd=on_path)
                self.ae(self.contexts[-1].argv, ('kitty-test-prog',))
                c, exe, argv = self._fork(argv=('kitty-test-prog',), launch_request=req, user_func=wrapper, env={'PATH': '.'}, cwd=off_path)
                self.ae(self.contexts[-1].argv, (prog,))
                # Not found at all, left as is
                c, exe, argv = self._fork(argv=('kitty-test-missing',), launch_request=req, user_func=wrapper)
                self.ae(self.contexts[-1].argv, ('kitty-test-missing',))
                # Paths are never modified
                c, exe, argv = self._fork(argv=(prog,), launch_request=req, user_func=wrapper)
                self.ae(self.contexts[-1].argv, (prog,))
                # The default shell is recognized when requested by name
                self.set_options({'shell_integration': frozenset({'disabled'}), 'shell': prog})
                with patch.object(child_module, 'shell_path', prog):
                    c, exe, argv = self._fork(argv=('kitty-test-prog',), launch_request=req, user_func=wrapper)
                    self.assertTrue(c.is_default_shell)
                    self.assertTrue(self.contexts[-1].is_default_shell)
                    c, exe, argv = self._fork(argv=('kitty-test-prog', 'arg'), launch_request=req, user_func=wrapper)
                    self.assertFalse(self.contexts[-1].is_default_shell)
                # The shell is recognized when it is found via a different
                # path to the same file
                link = os.path.join(tdir, 'kitty-test-link')
                os.symlink(prog, link)
                self.set_options({'shell_integration': frozenset({'disabled'}), 'shell': link})
                with patch.object(child_module, 'shell_path', link):
                    c, exe, argv = self._fork(argv=('kitty-test-prog',), launch_request=req, user_func=wrapper)
                    self.assertTrue(c.is_default_shell)
                    self.assertTrue(self.contexts[-1].is_default_shell)

    def test_launch_wrapper_default_bash_with_shell_integration(self):
        from kitty.launch_wrapper import LaunchRequest

        self.set_options({'shell': '/bin/bash', 'shell_integration': frozenset({'enabled'})})
        req = LaunchRequest('tab')
        # Exercise in-process shell integration even when Bash is the macOS login shell.
        with patch('kitty.child.shell_path', '/bin/sh'):
            for argv, is_default_shell in ((('/bin/bash',), True), (('/bin/bash', '--posix'), False)):
                with self.subTest(argv=argv):
                    self._fork(argv=argv, launch_request=req, user_func=self._recording(None))
                    self.ae(self.contexts[-1].argv, ('/bin/bash', '--posix'))
                    self.ae(self.contexts[-1].is_default_shell, is_default_shell)

    def test_launch_wrapper_invalid_shell(self):
        # An invalid shell option falls back to the login shell, with the
        # wrapper still applied
        from kitty import utils
        from kitty.constants import shell_path
        from kitty.launch_wrapper import LaunchRequest

        opts = self.set_options({'shell': '"unterminated', 'shell_integration': frozenset({'disabled'})})
        req = LaunchRequest('tab')
        utils.report_invalid_shell.cache_clear()
        with patch.object(utils, 'log_error') as log_error:
            self.ae(utils.resolved_shell(opts), [shell_path])
            c, exe, argv = self._fork(launch_request=req, user_func=self._recording(['/bin/wrapper']))
            self.ae(argv, ('/bin/wrapper', '/bin/prog', 'arg'))
            self.ae(c.kitty_wrappers, (KittyWrapper(('/bin/wrapper',), True, ('/bin/prog', 'arg')),))
            self.assertFalse(self.contexts[-1].is_default_shell)
            c, exe, argv = self._fork(argv=(shell_path,), launch_request=req, user_func=self._recording(['/bin/wrapper']))
            if is_macos:
                # On macOS the default shell is run via /usr/bin/login and the
                # run-shell kitten, with the wrapper inside login
                login_argv = c.kitty_wrappers[0].argv
                self.ae(login_argv[0], '/usr/bin/login')
                self.ae(argv[: len(login_argv)], login_argv)
                rest = argv[len(login_argv) :]
                self.ae(rest[:3], ('/bin/wrapper', kitten_exe(), 'run-shell'))
                self.ae(rest[3:5], ('--shell', shell_path))
            else:
                self.ae(argv, ('/bin/wrapper', shell_path))
            self.assertTrue(self.contexts[-1].is_default_shell)
        utils.report_invalid_shell.cache_clear()
        # Reported only once
        log_error.assert_called_once()
        self.assertIn('Unterminated string', log_error.call_args.args[0])

    def test_launch_wrapper_for_panel_commands(self):
        # Commands sent to a running panel via single instance are user
        # launches, not run from any window in the panel
        from kittens.panel import main as panel
        from kitty.fast_data_types import get_options
        from kitty.utils import resolved_shell

        cmd = ['/bin/prog', 'arg']
        cwd = os.path.realpath(tempfile.gettempdir())
        cases = (
            # toggle-visibility, if-running, has active tab, hold, launch type
            (True, 'new-tab', True, False, 'tab'),
            (True, 'new-window', True, True, 'window'),
            (True, 'new-window', False, False, 'tab'),
            (False, 'new-tab', True, True, 'os-window'),
        )
        for toggle, mode, has_active_tab, hold, launch_type in cases:
            with self.subTest(toggle=toggle, mode=mode, has_active_tab=has_active_tab, hold=hold):
                # The panel has an active window, which must not be used as the source
                tab = SimpleNamespace(active_window_for_cwd=SimpleNamespace(id=2), new_special_window=Mock())
                tm = SimpleNamespace(os_window_id=1, active_tab=tab if has_active_tab else None, new_tab=Mock())
                boss = Mock(os_window_map={1: tm}, os_window_death_actions={}, window_id_map={})
                boss.add_os_panel.return_value = 1
                sys_args = ['panel', f'--if-running={mode}', *(['--toggle-visibility'] if toggle else []), *(['--hold'] if hold else []), *cmd]
                with (
                    patch.object(panel, 'args', panel.parse_panel_args([])[0]),
                    patch.object(panel, 'mtime_map', {}),
                    patch.object(panel, 'current_focused_os_window_id', return_value=0),
                    patch.object(panel, 'layer_shell_config_for_os_window', return_value=None),
                    patch.object(panel, 'set_layer_shell_config'),
                    patch.object(panel, 'toggle_os_window_visibility'),
                ):
                    panel.handle_single_instance_command(boss, sys_args, {'X': 'y', 'XDG_ACTIVATION_TOKEN': 't', 'VTE_VERSION': '1'}, cwd=cwd)
                launch = tab.new_special_window if launch_type == 'window' else tm.new_tab
                launch.assert_called_once()
                sw = launch.call_args.args[0]
                # Cleaned up as for other single instance commands
                self.ae(sw.env, {'X': 'y'})
                self.ae(sw.hold, hold)
                self.ae(sw.cwd, cwd)
                wrapper = self._recording(['/bin/wrapper'])
                _, _, argv = self._fork(argv=sw.cmd, launch_request=sw.launch_request, hold=sw.hold, cwd=sw.cwd or '/', user_func=wrapper)
                self.ae(argv[-3:], ('/bin/wrapper', *cmd))
                if hold:
                    self.assertNotEqual(argv[0], '/bin/wrapper')
                ctx = self.contexts[-1]
                self.ae(ctx.launch_type, launch_type)
                # The command does not come from the active window of the panel
                self.assertIsNone(ctx.source_window_id)
                self.assertIsNone(ctx.source_pid)
        # A new panel without a command runs the default shell, not kitty's
        # internal run-shell kitten, so the wrapper sees the actual shell
        boss = Mock(os_window_map={1: tm}, os_window_death_actions={}, window_id_map={})
        boss.add_os_panel.return_value = 1
        tm.new_tab.reset_mock()
        with patch.object(panel, 'args', panel.parse_panel_args([])[0]), patch.object(panel, 'mtime_map', {}):
            panel.handle_single_instance_command(boss, ['panel'], {})
        sw = tm.new_tab.call_args.args[0]
        shell = resolved_shell(get_options())
        self.ae(sw.cmd, shell)
        self.ae(sw.launch_request.launch_type, 'os-window')
        # No cwd sent by the client, so the default is used
        self.assertIsNone(sw.cwd)
        self._fork(argv=sw.cmd, launch_request=sw.launch_request, user_func=self._recording(None))
        self.ae(self.contexts[-1].argv, tuple(shell))
        self.assertTrue(self.contexts[-1].is_default_shell)
