#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import importlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import unittest
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from functools import lru_cache
from tempfile import TemporaryDirectory, mkdtemp
from typing import (
    Any,
    NoReturn,
    Optional,
)

from . import is_ci

PARALLEL_THRESHOLD = 20


def contents(package: str) -> Iterator[str]:
    try:
        if sys.version_info[:2] < (3, 10):
            raise ImportError("importlib.resources.files() doesn't work with frozen builds on python 3.9")
        from importlib.resources import files
    except ImportError:
        from importlib.resources import contents

        return iter(contents(package))
    return (path.name for path in files(package).iterdir())


def itertests(suite: unittest.TestSuite) -> Generator[unittest.TestCase, None, None]:
    stack = [suite]
    while stack:
        suite = stack.pop()
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                stack.append(test)
                continue
            if test.__class__.__name__ == 'ModuleImportFailure':
                raise Exception('Failed to import a test module: %s' % test)
            yield test


def find_all_tests(package: str = '', excludes: Sequence[str] = ('main', 'gr')) -> unittest.TestSuite:
    suits = []
    if not package:
        package = __name__.rpartition('.')[0] if '.' in __name__ else 'kitty_tests'
    for x in sorted(contents(package)):
        name, ext = os.path.splitext(x)
        if ext in ('.py', '.pyc') and name not in excludes:
            m = importlib.import_module(package + '.' + x.partition('.')[0])
            suits.append(unittest.defaultTestLoader.loadTestsFromModule(m))
    return unittest.TestSuite(suits)


def filter_tests(suite: unittest.TestSuite, test_ok: Callable[[unittest.TestCase], bool]) -> unittest.TestSuite:
    ans = unittest.TestSuite()
    added: set[unittest.TestCase] = set()
    for test in itertests(suite):
        if test_ok(test) and test not in added:
            ans.addTest(test)
            added.add(test)
    return ans


def filter_tests_by_name(suite: unittest.TestSuite, *names: str) -> unittest.TestSuite:
    names_ = {x if x.startswith('test_') else 'test_' + x for x in names}

    def q(test: unittest.TestCase) -> bool:
        return test._testMethodName in names_

    return filter_tests(suite, q)


def filter_tests_by_module(suite: unittest.TestSuite, *names: str) -> unittest.TestSuite:
    names_ = frozenset(names)

    def q(test: unittest.TestCase) -> bool:
        m = test.__class__.__module__.rpartition('.')[-1]
        return m in names_

    return filter_tests(suite, q)


def type_check() -> NoReturn:
    from kitty.cli_stub import generate_stub  # type:ignore

    generate_stub()
    from kittens.tui.operations_stub import generate_stub  # type: ignore

    generate_stub()
    os.execlp('ty', 'ty', 'check')


def run_cli(suite: unittest.TestSuite, verbosity: int = 4) -> bool:
    r = unittest.TextTestRunner
    r.resultclass = unittest.TextTestResult
    runner = r(verbosity=verbosity)
    runner.tb_locals = True  # type: ignore
    from .base import forwardable_stdio

    with forwardable_stdio():
        result = runner.run(suite)
    sys.stdout.flush()
    sys.stderr.flush()
    return result.wasSuccessful()


def find_testable_go_packages() -> tuple[set[str], dict[str, list[str]]]:
    test_functions: dict[str, list[str]] = {}
    ans = set()
    base = os.getcwd()
    pat = re.compile(r'^func Test([A-Z]\w+)', re.MULTILINE)
    for dirpath, dirnames, filenames in os.walk(base):
        if 'b' in dirnames and os.path.basename(dirpath) == 'bypy':
            dirnames.remove('b')
        for f in filenames:
            if f.endswith('_test.go'):
                q = os.path.relpath(dirpath, base)
                ans.add(q)
                with open(os.path.join(dirpath, f)) as s:
                    raw = s.read()
                for m in pat.finditer(raw):
                    test_functions.setdefault(m.group(1), []).append(q)
    return ans, test_functions


@lru_cache
def go_exe() -> str:
    return shutil.which('go') or ''


class GoProc:
    def __init__(self, cmd: list[str]):
        from kitty.constants import kitty_exe

        env = os.environ.copy()
        env['KITTY_PATH_TO_KITTY_EXE'] = kitty_exe()
        self.start_time = time.monotonic()
        self.end_time: float = 0.0
        self.tdir = mkdtemp(prefix='kitty-go-tests-')
        env['HOME'] = self.tdir
        if not env.get('GOCACHE') and (gop := os.path.expanduser('~/.cache/go-build')) and os.path.isdir(gop):
            env['GOCACHE'] = gop
        if not env.get('GOMODCACHE') and (gop := os.path.expanduser('~/go/pkg/mod')) and os.path.isdir(gop):
            env['GOMODCACHE'] = gop
        env['XDG_CONFIG_HOME'] = self.tdir + '/conf'
        os.mkdir(env['XDG_CONFIG_HOME'])
        env['XDG_CACHE_HOME'] = self.tdir + '/cache'
        os.mkdir(env['XDG_CACHE_HOME'])
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        self.stdout_fd = self.proc.stdout.fileno()

    @property
    def runtime(self) -> float:
        return self.end_time - self.start_time

    @property
    def returncode(self) -> int:
        return self.proc.returncode

    def finish(self) -> None:
        """Reap the process after its stdout has been fully drained."""
        assert self.proc.stdout is not None
        self.proc.stdout.close()
        self.proc.wait()
        self.end_time = time.monotonic()
        shutil.rmtree(self.tdir, ignore_errors=True)


def run_go(packages: set[str], names: Sequence[str]) -> GoProc:
    go = go_exe()
    go_pkg_args = [f'github.com/kovidgoyal/kitty/{x}' for x in packages]
    cmd = [go, 'test', '--tags', 'testing', '-v', '-json']
    for name in names:
        cmd.extend(('-run', name))
    cmd += go_pkg_args
    return GoProc(cmd)


def reduce_go_pkgs(module: str, names: Sequence[str]) -> set[str]:
    if not go_exe():
        raise SystemExit('go executable not found, current path: ' + repr(os.environ.get('PATH', '')))
    go_packages, go_functions = find_testable_go_packages()
    if module:
        go_packages &= {module}
    if names:
        pkgs = set()
        for name in names:
            pkgs |= set(go_functions.get(name, []))
        go_packages &= pkgs
    return go_packages


@contextmanager
def env_vars(**kw: str) -> Iterator[None]:
    originals = {k: os.environ.get(k) for k in kw}
    os.environ.update(kw)
    try:
        yield
    finally:
        for k, v in originals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def env_for_python_tests(report_env: bool = False) -> Iterator[None]:
    gohome = os.path.expanduser('~/go')
    slangc = os.environ.get('SLANGC') or shutil.which('slangc') or 'slangc'
    current_home = os.path.expanduser('~') + os.sep
    paths = os.environ.get('PATH', '/usr/local/sbin:/usr/local/bin:/usr/bin').split(os.pathsep)
    path = os.pathsep.join(x for x in paths if not x.startswith(current_home))
    launcher_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kitty', 'launcher')
    path = f'{launcher_dir}{os.pathsep}{path}'
    if report_env:
        print('Running under CI:', is_ci)
        print('Using PATH in test environment:', path)
        from kitty.fast_data_types import has_avx2, has_sse4_2

        print(f'Intrinsics: {has_avx2=} {has_sse4_2=}')
    with (
        TemporaryDirectory() as tdir,
        env_vars(
            HOME=tdir,
            KT_ORIGINAL_HOME=os.path.expanduser('~'),
            USERPROFILE=tdir,
            PATH=path,
            TERM='xterm-kitty',
            SLANGC=slangc,
            XDG_CONFIG_HOME=os.path.join(tdir, '.config'),
            XDG_CONFIG_DIRS=os.path.join(tdir, '.config'),
            XDG_DATA_DIRS=os.path.join(tdir, '.local', 'xdg'),
            XDG_CACHE_HOME=os.path.join(tdir, '.cache'),
            XDG_RUNTIME_DIR=os.path.join(tdir, '.cache', 'run'),
            PYTHONWARNINGS='error',
        ),
    ):
        if os.path.isdir(gohome):
            os.symlink(gohome, os.path.join(tdir, os.path.basename(gohome)))
        yield


class PipeTestResult(unittest.TestResult):
    """Writes test results as newline-delimited JSON records to a file descriptor."""

    def __init__(self, write_fd: int) -> None:
        super().__init__()
        self._wfd = write_fd
        self._test_start: float = 0.0

    def _send(self, record: dict[str, Any]) -> None:
        data = (json.dumps(record) + '\n').encode()
        while data:
            n = os.write(self._wfd, data)
            data = data[n:]

    def _elapsed(self) -> float:
        return time.monotonic() - self._test_start

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self._test_start = time.monotonic()
        self._send({'t': 'start', 'id': str(test)})

    def addSuccess(self, test: unittest.TestCase) -> None:
        self._send({'t': 'ok', 'id': str(test), 'e': self._elapsed()})

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        self._send({'t': 'error', 'id': str(test), 'e': self._elapsed(), 'msg': self._exc_info_to_string(err, test)})

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self._send({'t': 'fail', 'id': str(test), 'e': self._elapsed(), 'msg': self._exc_info_to_string(err, test)})

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self._send({'t': 'skip', 'id': str(test), 'e': self._elapsed(), 'msg': reason})

    def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addExpectedFailure(test, err)
        self._send({'t': 'xfail', 'id': str(test), 'e': self._elapsed(), 'msg': self._exc_info_to_string(err, test)})

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self._send({'t': 'xpass', 'id': str(test), 'e': self._elapsed()})

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase, err: Any) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None:
            record_type = 'fail' if issubclass(err[0], test.failureException) else 'error'
            self._send({'t': record_type, 'id': str(subtest), 'e': self._elapsed(), 'msg': self._exc_info_to_string(err, test)})


def run_test_worker(tests: list[unittest.TestCase], write_fd: int) -> None:
    """Execute in a forked child: run tests, send results over write_fd, then exit."""
    result: Optional[PipeTestResult] = None
    exit_code = 1
    try:
        with env_for_python_tests():
            from .base import forwardable_stdio

            with forwardable_stdio():
                result = PipeTestResult(write_fd)
                unittest.TestSuite(tests).run(result)
                exit_code = 0
    except Exception:
        import traceback

        try:
            rec: dict[str, Any] = {'t': 'worker_error', 'msg': traceback.format_exc()}
            os.write(write_fd, (json.dumps(rec) + '\n').encode())
        except OSError:
            pass
        exit_code = 1
    finally:
        try:
            os.close(write_fd)
        except OSError:
            pass
    os._exit(exit_code)


def fork_test_workers(tests: list[unittest.TestCase]) -> tuple[list[int], list[int]]:
    """Chunk tests and fork worker processes. Returns (pids, read_fds)."""
    n = min(os.cpu_count() or 4, 8, len(tests))
    # Round-robin assignment so slow and fast tests are spread across all workers
    chunks: list[list[unittest.TestCase]] = [[] for _ in range(n)]
    for i, test in enumerate(tests):
        chunks[i % n].append(test)
    pids: list[int] = []
    read_fds: list[int] = []
    for chunk in chunks:
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            os.close(devnull)
            run_test_worker(chunk, w)
            # run_test_worker calls os._exit() — never returns
        os.close(w)
        read_fds.append(r)
        pids.append(pid)
    return pids, read_fds


_RED = '\x1b[31m'
_GREEN = '\x1b[32m'
_YELLOW = '\x1b[33m'
_CYAN = '\x1b[36m'
_RESET = '\x1b[0m'
_BOLD = '\x1b[1m'
_DIM = '\x1b[2m'


def collect_worker_results(
    pids: list[int],
    read_fds: list[int],
    total_py_tests: int,
    go_proc: Optional[GoProc] = None,
) -> tuple[bool, bool]:
    """Read JSON from worker pipes and go proc stdout, show live progress, print failures."""
    use_tty = sys.stdout.isatty()
    py_buffers: dict[int, bytes] = {fd: b'' for fd in read_fds}
    active_py = list(read_fds)
    go_buffer = b''
    go_active = go_proc is not None
    start = time.monotonic()

    py_run = 0
    py_failures: list[tuple[str, str]] = []
    py_errors: list[tuple[str, str]] = []
    py_skipped = 0
    py_unexpected_successes: list[str] = []
    py_worker_errors: list[str] = []

    go_run = 0
    go_failures: list[tuple[str, str]] = []
    go_test_output: dict[str, list[str]] = {}
    go_pkg_output: dict[str, list[str]] = {}

    # (elapsed_seconds, label) for every completed test in both suites
    all_timings: list[tuple[float, str]] = []

    def c(code: str, text: str) -> str:
        return (code + text + _RESET) if use_tty else text

    def render_progress() -> str:
        elapsed = time.monotonic() - start
        parts: list[str] = []
        if total_py_tests > 0 or active_py:
            py_mark = c(_GREEN, ' ✓') if not active_py else ''
            parts.append(c(_CYAN + _BOLD, 'Py') + f' {py_run}/{total_py_tests}' + py_mark)
        if go_proc is not None:
            # Go total is omitted: t.Run() sub-tests inflate the count beyond
            # what static analysis of Test* functions can predict.
            go_mark = c(_GREEN, ' ✓') if not go_active else ''
            parts.append(c(_YELLOW + _BOLD, 'Go') + f' {go_run}' + go_mark)
        fail_count = len(py_failures) + len(py_errors) + len(go_failures)
        if fail_count:
            parts.append(c(_RED, f'{fail_count} failed'))
        return '  ' + '  '.join(parts) + '  ' + c(_DIM, f'[{elapsed:.1f}s]')

    def show_progress(force: bool = False) -> None:
        line = render_progress()
        if use_tty:
            print(f'\r{line}\x1b[K', end='', flush=True)
        elif force or (total_py_tests > 0 and py_run % max(1, total_py_tests // 10) == 0):
            print(line, flush=True)

    while active_py or go_active:
        watch = list(active_py)
        if go_active and go_proc is not None:
            watch.append(go_proc.stdout_fd)
        readable, _, _ = select.select(watch, [], [])

        for fd in readable:
            if go_proc is not None and fd == go_proc.stdout_fd:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b''
                if not chunk:
                    go_active = False
                    go_proc.finish()
                    show_progress(force=True)
                    continue
                go_buffer += chunk
                while b'\n' in go_buffer:
                    raw, go_buffer = go_buffer.split(b'\n', 1)
                    if not raw:
                        continue
                    try:
                        evt: dict[str, Any] = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    action = evt.get('Action', '')
                    test_name = evt.get('Test', '')
                    pkg = evt.get('Package', '')
                    if test_name:
                        full = f'{pkg}.{test_name}' if pkg else test_name
                        if action == 'run':
                            go_test_output[full] = []
                        elif action == 'output':
                            go_test_output.setdefault(full, []).append(evt.get('Output', ''))
                        elif action in ('pass', 'fail', 'skip'):
                            go_run += 1
                            elapsed_test = float(evt.get('Elapsed') or 0.0)
                            if action == 'fail':
                                output = ''.join(go_test_output.pop(full, []))
                                go_failures.append((full, output))
                            else:
                                go_test_output.pop(full, None)
                            all_timings.append((elapsed_test, f'[Go] {full}'))
                            show_progress()
                    else:
                        if action == 'output':
                            go_pkg_output.setdefault(pkg, []).append(evt.get('Output', ''))
                        elif action == 'fail':
                            # Package-level failure (e.g. build error): show if no test-level failures from it
                            pkg_had_test_failure = any(f.startswith(pkg + '.') for f, _ in go_failures)
                            if not pkg_had_test_failure:
                                output = ''.join(go_pkg_output.pop(pkg, []))
                                if output:
                                    go_failures.append((pkg, output))
                                    show_progress()
                            else:
                                go_pkg_output.pop(pkg, None)
                        else:
                            go_pkg_output.pop(pkg, None)
            else:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b''
                if not chunk:
                    active_py.remove(fd)
                    os.close(fd)
                    show_progress(force=True)
                    continue
                py_buffers[fd] += chunk
                while b'\n' in py_buffers[fd]:
                    raw_py, py_buffers[fd] = py_buffers[fd].split(b'\n', 1)
                    if not raw_py:
                        continue
                    rec: dict[str, Any] = json.loads(raw_py)
                    t = rec['t']
                    elapsed_test = float(rec.get('e') or 0.0)
                    if t == 'ok':
                        py_run += 1
                        all_timings.append((elapsed_test, f'[Py] {rec["id"]}'))
                        show_progress()
                    elif t == 'fail':
                        py_run += 1
                        py_failures.append((rec['id'], rec['msg']))
                        all_timings.append((elapsed_test, f'[Py] {rec["id"]}'))
                        show_progress()
                    elif t == 'error':
                        py_run += 1
                        py_errors.append((rec['id'], rec['msg']))
                        all_timings.append((elapsed_test, f'[Py] {rec["id"]}'))
                        show_progress()
                    elif t == 'skip':
                        py_run += 1
                        py_skipped += 1
                        all_timings.append((elapsed_test, f'[Py] {rec["id"]}'))
                        show_progress()
                    elif t == 'xfail':
                        py_run += 1
                        all_timings.append((elapsed_test, f'[Py] {rec["id"]}'))
                        show_progress()
                    elif t == 'xpass':
                        py_run += 1
                        py_unexpected_successes.append(rec['id'])
                        all_timings.append((elapsed_test, f'[Py] {rec["id"]}'))
                        show_progress()
                    elif t == 'worker_error':
                        py_worker_errors.append(rec['msg'])

    for pid in pids:
        _, status = os.waitpid(pid, 0)
        if status != 0:
            py_worker_errors.append(f'Python test worker {pid} exited with status {os.waitstatus_to_exitcode(status)}')

    elapsed = time.monotonic() - start

    if use_tty:
        print()  # move past the progress line

    sep1 = '=' * 70
    sep2 = '-' * 70

    for msg in py_worker_errors:
        print(sep1)
        print(c(_RED + _BOLD, 'WORKER ERROR'))
        print(sep2)
        print(msg)

    for label_text, items in (('FAIL', py_failures), ('ERROR', py_errors)):
        for tid, msg in items:
            print(sep1)
            print(f'{c(_RED + _BOLD, label_text)}: {tid}')
            print(sep2)
            print(msg)

    for go_tid, go_output in go_failures:
        print(sep1)
        print(f'{c(_RED + _BOLD, "FAIL")}: {go_tid}')
        print(sep2)
        if go_output:
            print(go_output, end='' if go_output.endswith('\n') else '\n')

    if py_unexpected_successes:
        print(sep1)
        print('Unexpected successes:')
        for tid in py_unexpected_successes:
            print(f'  {tid}')

    print(sep2)
    total_ran = py_run + go_run
    count_word = 'test' if total_ran == 1 else 'tests'
    print(f'Ran {total_ran} {count_word} in {elapsed:.3f}s')

    all_timings.sort(reverse=True)
    slowest = all_timings[:5]
    if slowest:
        print()
        print(c(_DIM, 'Slowest tests:'))
        for t_elapsed, t_name in slowest:
            print(f'  {c(_DIM, f"{t_elapsed:.3f}s")}  {t_name}')

    print()

    python_ok = not (py_failures or py_errors or py_unexpected_successes or py_worker_errors)
    go_ok = go_proc is None or (go_proc.returncode == 0 and not go_failures)

    if not python_ok or not go_ok:
        fail_parts: list[str] = []
        if py_failures:
            fail_parts.append(f'failures={len(py_failures)}')
        if py_errors:
            fail_parts.append(f'errors={len(py_errors)}')
        if py_unexpected_successes:
            fail_parts.append(f'unexpected successes={len(py_unexpected_successes)}')
        if py_worker_errors:
            fail_parts.append(f'worker errors={len(py_worker_errors)}')
        if go_failures:
            fail_parts.append(f'go failures={len(go_failures)}')
        elif go_proc is not None and go_proc.returncode != 0:
            fail_parts.append('go failed')
        result = f'FAILED ({", ".join(fail_parts)})'
        print(c(_RED + _BOLD, result))
        return False, go_ok

    ok_msg = 'OK'
    if py_skipped:
        ok_msg += f' (skipped={py_skipped})'
    print(c(_GREEN + _BOLD, ok_msg))
    return True, True


def run_tests(report_env: bool = False) -> None:
    report_env = report_env or is_ci
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        'name',
        nargs='*',
        default=[],
        help='The name of the test to run, for e.g. linebuf corresponds to test_linebuf. Can be specified multiple times.'
        ' For go tests Something corresponds to TestSometing.',
    )
    parser.add_argument('--verbosity', default=4, type=int, help='Test verbosity')
    parser.add_argument(
        '--module',
        default='',
        help='Name of a test module to restrict to. For example: ssh. For Go tests this is the name of a package, for example: tools/cli',
    )
    args = parser.parse_args()
    if args.name and args.name[0] in ('type-check', 'type_check', 'mypy'):
        type_check()

    # Collect and filter all python tests upfront before any forking
    all_tests = find_all_tests()
    if args.module:
        all_tests = filter_tests_by_module(all_tests, args.module)
    if args.name:
        all_tests = filter_tests_by_name(all_tests, *args.name)
    tests_list = list(itertests(all_tests))

    go_pkgs = reduce_go_pkgs(args.module, args.name)
    has_go = bool(go_pkgs)
    os.environ['ASAN_OPTIONS'] = 'detect_leaks=0'

    # Validate filters before doing any work
    if args.module and not tests_list and not has_go:
        raise SystemExit('No test module named %s found' % args.module)
    if args.name and not tests_list and not has_go:
        raise SystemExit('No test named %s found' % ' '.join(args.name))

    # Pre-initialize fonts once before forking so all worker processes inherit
    # the warm C-level fontconfig state and their own all_fonts_map() calls are fast.
    from kitty.fonts.common import all_fonts_map

    all_fonts_map(True)

    # Fork Python workers before modifying the main-process env; each worker
    # calls env_for_python_tests independently for full HOME/XDG isolation.
    use_parallel = len(tests_list) > PARALLEL_THRESHOLD
    if use_parallel:
        pids, read_fds = fork_test_workers(tests_list)

    # Launch Go immediately so it runs in parallel with Python env setup and tests.
    if has_go:
        if report_env:
            print('Go executable:', go_exe())
            print('Go packages being tested:', ' '.join(go_pkgs))
        go_proc: Optional[GoProc] = run_go(go_pkgs, args.name)
    else:
        go_proc = None
    sys.stdout.flush()
    # we need fonts installed in the user home directory as well, so initialize
    # fontconfig before nuking $HOME and friends
    from kitty.fonts.common import all_fonts_map

    all_fonts_map(True)

    with env_for_python_tests(report_env):
        # Module filter with no python tests but go tests present: run go only
        if args.module and not tests_list:
            _, go_ok = collect_worker_results([], [], 0, go_proc=go_proc)
            raise SystemExit(0 if go_ok else 1)

        if use_parallel:
            python_ok, go_ok = collect_worker_results(pids, read_fds, len(tests_list), go_proc=go_proc)
        elif tests_list:
            python_ok = run_cli(all_tests, args.verbosity)
            if go_proc is not None:
                _, go_ok = collect_worker_results([], [], 0, go_proc=go_proc)
            else:
                go_ok = True
        else:
            python_ok = True
            if go_proc is not None:
                _, go_ok = collect_worker_results([], [], 0, go_proc=go_proc)
            else:
                go_ok = True

        exit_code = 0 if (python_ok and go_ok) else 1

    if exit_code != 0:
        print('\x1b[31mError\x1b[39m: Some tests failed!')
    raise SystemExit(exit_code)


def main() -> None:
    import warnings

    warnings.simplefilter('error')
    run_tests()
