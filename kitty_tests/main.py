#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import importlib
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from functools import lru_cache
from tempfile import TemporaryDirectory, mkdtemp
from threading import Thread
from typing import (
    Any,
    NoReturn,
    Optional,
)

from . import BaseTest


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
    for x in contents(package):
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


@lru_cache
def python_for_type_check() -> str:
    return shutil.which('python') or shutil.which('python3') or 'python'


def type_check() -> NoReturn:
    from kitty.cli_stub import generate_stub  # type:ignore

    generate_stub()
    from kittens.tui.operations_stub import generate_stub  # type: ignore

    generate_stub()
    py = python_for_type_check()
    os.execlp(py, py, '-m', 'mypy', '--pretty')


def run_cli(suite: unittest.TestSuite, verbosity: int = 4) -> bool:
    r = unittest.TextTestRunner
    r.resultclass = unittest.TextTestResult
    runner = r(verbosity=verbosity)
    runner.tb_locals = True  # type: ignore
    from . import forwardable_stdio
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
    for (dirpath, dirnames, filenames) in os.walk(base):
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


class GoProc(Thread):

    def __init__(self, cmd: list[str]):
        super().__init__(name='GoProc')
        from kitty.constants import kitty_exe
        env = os.environ.copy()
        env['KITTY_PATH_TO_KITTY_EXE'] = kitty_exe()
        self.stdout = b''
        self.start_time = time.monotonic()
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
        self.start()

    @property
    def runtime(self):
        return self.end_time - self.start_time

    @property
    def returncode(self):
        return self.proc.returncode

    def run(self) -> None:
        try:
            self.stdout, _ = self.proc.communicate()
            self.proc.stdout.close()
        finally:
            shutil.rmtree(self.tdir)

    def wait(self, timeout=None) -> None:
        try:
            self.join(timeout)
        except KeyboardInterrupt:
            self.proc.terminate()
            if self.proc.wait(0.1) is None:
                self.proc.kill()
        self.join()
        self.end_time = time.monotonic()
        return self.stdout.decode('utf-8', 'replace'), self.proc.returncode


def run_go(packages: set[str], names: str) -> GoProc:
    go = go_exe()
    go_pkg_args = [f'github.com/kovidgoyal/kitty/{x}' for x in packages]
    cmd = [go, 'test', '--tags', 'testing', '-v']
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


def run_python_tests(args: Any, go_proc: 'Optional[GoProc]' = None) -> None:
    tests = find_all_tests()

    def print_go() -> None:
        stdout, rc = go_proc.wait()
        if go_proc.returncode == 0 and tests._tests:
            print(f'All Go tests succeeded, ran in {go_proc.runtime:.1f} seconds', flush=True)
        else:
            print(stdout, end='', flush=True)
        return rc

    if args.module:
        tests = filter_tests_by_module(tests, args.module)
        if not tests._tests:
            if go_proc:
                raise SystemExit(print_go())
            raise SystemExit('No test module named %s found' % args.module)

    if args.name:
        tests = filter_tests_by_name(tests, *args.name)
        if not tests._tests and not go_proc:
            raise SystemExit('No test named %s found' % args.name)
    if tests._tests:
        python_tests_ok = run_cli(tests, args.verbosity)
    else:
        python_tests_ok = True
    exit_code = 0 if python_tests_ok else 1
    if go_proc:
        print_go()
        if exit_code == 0:
            exit_code = go_proc.returncode
    if exit_code != 0:
        print("\x1b[31mError\x1b[39m: Some tests failed!")
    raise SystemExit(exit_code)


def run_tests(report_env: bool = False) -> None:
    report_env = report_env or BaseTest.is_ci
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
        help='Name of a test module to restrict to. For example: ssh.' ' For Go tests this is the name of a package, for example: tools/cli',
    )
    args = parser.parse_args()
    if args.name and args.name[0] in ('type-check', 'type_check', 'mypy'):
        type_check()
    go_pkgs = reduce_go_pkgs(args.module, args.name)
    os.environ['ASAN_OPTIONS'] = 'detect_leaks=0'  # ensure subprocesses dont fail because of leak detection
    if go_pkgs:
        go_proc: 'Optional[GoProc]' = run_go(go_pkgs, args.name)
    else:
        go_proc = None
    with env_for_python_tests(report_env):
        if go_pkgs:
            if report_env:
                print('Go executable:', go_exe())
            print('Go packages being tested:', ' '.join(go_pkgs))
        sys.stdout.flush()
        run_python_tests(args, go_proc)


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
    current_home = os.path.expanduser('~') + os.sep
    paths = os.environ.get('PATH', '/usr/local/sbin:/usr/local/bin:/usr/bin').split(os.pathsep)
    path = os.pathsep.join(x for x in paths if not x.startswith(current_home))
    launcher_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kitty', 'launcher')
    path = f'{launcher_dir}{os.pathsep}{path}'
    python_for_type_check()
    print('Running under CI:', BaseTest.is_ci)
    if report_env:
        print('Using PATH in test environment:', path)
        print('Python:', python_for_type_check())
        from kitty.fast_data_types import has_avx2, has_sse4_2
        print(f'Intrinsics: {has_avx2=} {has_sse4_2=}')
    # we need fonts installed in the user home directory as well, so initialize
    # fontconfig before nuking $HOME and friends
    from kitty.fonts.common import all_fonts_map
    all_fonts_map(True)

    with TemporaryDirectory() as tdir, env_vars(
        HOME=tdir,
        KT_ORIGINAL_HOME=os.path.expanduser('~'),
        USERPROFILE=tdir,
        PATH=path,
        TERM='xterm-kitty',
        XDG_CONFIG_HOME=os.path.join(tdir, '.config'),
        XDG_CONFIG_DIRS=os.path.join(tdir, '.config'),
        XDG_DATA_DIRS=os.path.join(tdir, '.local', 'xdg'),
        XDG_CACHE_HOME=os.path.join(tdir, '.cache'),
        XDG_RUNTIME_DIR=os.path.join(tdir, '.cache', 'run'),
        PYTHONWARNINGS='error',
    ):
        if os.path.isdir(gohome):
            os.symlink(gohome, os.path.join(tdir, os.path.basename(gohome)))
        yield


def main() -> None:
    import warnings

    warnings.simplefilter('error')
    run_tests()
