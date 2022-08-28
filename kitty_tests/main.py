#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import importlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import unittest
from importlib.resources import contents
from functools import lru_cache
from io import StringIO
from threading import Thread
from typing import (
    Any, Callable, Dict, Generator, List, NoReturn, Sequence, Set, Tuple
)


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
    added: Set[unittest.TestCase] = set()
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
    py = os.environ.get('PYTHON_FOR_TYPE_CHECK') or shutil.which('python') or shutil.which('python3')
    os.execlp(py, py, '-m', 'mypy', '--pretty')


def run_cli(suite: unittest.TestSuite, verbosity: int = 4) -> bool:
    r = unittest.TextTestRunner
    r.resultclass = unittest.TextTestResult
    runner = r(verbosity=verbosity)
    runner.tb_locals = True  # type: ignore
    result = runner.run(suite)
    return result.wasSuccessful()


def find_testable_go_packages() -> Tuple[Set[str], Dict[str, List[str]]]:
    test_functions: Dict[str, List[str]] = {}
    ans = set()
    base = os.getcwd()
    pat = re.compile(r'^func Test([A-Z]\w+)', re.MULTILINE)
    for (dirpath, dirnames, filenames) in os.walk(base):
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


def create_go_filter(packages: List[str], *names: str) -> str:
    go = go_exe()
    if not go:
        return ''
    all_tests = set()
    try:
        lines = subprocess.check_output(f'{go} test -list .'.split() + packages).decode().splitlines()
    except subprocess.CalledProcessError as e:
        raise SystemExit(e.returncode)
    for line in lines:
        if line.startswith('Test'):
            all_tests.add(line[4:])
    tests = set(names) & all_tests
    return '|'.join(tests)


def run_go(packages: Set[str], names: str) -> 'subprocess.Popen[bytes]':
    go = go_exe()
    go_pkg_args = [f'kitty/{x}' for x in packages]
    cmd = [go, 'test', '-v']
    for name in names:
        cmd.extend(('-run', name))
    cmd += go_pkg_args
    print(shlex.join(cmd), flush=True)
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def reduce_go_pkgs(module: str, names: Sequence[str]) -> Set[str]:
    if not go_exe():
        print('Skipping Go tests as go exe not found', file=sys.stderr)
        return
    go_packages, go_functions = find_testable_go_packages()
    if module:
        go_packages &= {module}
    if names:
        pkgs = set()
        for name in names:
            pkgs |= set(go_functions.get(name, []))
        go_packages &= pkgs
    return go_packages


def run_tests() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'name', nargs='*', default=[],
        help='The name of the test to run, for e.g. linebuf corresponds to test_linebuf. Can be specified multiple times. For go tests Something corresponds to TestSometing.')
    parser.add_argument('--verbosity', default=4, type=int, help='Test verbosity')
    parser.add_argument('--module', default='', help='Name of a test module to restrict to. For example: ssh.'
                        ' For Go tests this is the name of a package, for example: tools/cli')
    args = parser.parse_args()
    if args.name and args.name[0] in ('type-check', 'type_check', 'mypy'):
        type_check()
    go_pkgs = reduce_go_pkgs(args.module, args.name)
    if go_pkgs:
        go_proc = run_go(go_pkgs, args.name)
    tests = find_all_tests()

    def print_go() -> None:
        print(go_proc.stdout.read().decode(), end='', flush=True)
        go_proc.stdout.close()
        go_proc.wait()

    if args.module:
        tests = filter_tests_by_module(tests, args.module)
        if not tests._tests:
            if go_pkgs:
                print_go()
                raise SystemExit(go_proc.returncode)
            raise SystemExit('No test module named %s found' % args.module)

    if args.name:
        tests = filter_tests_by_name(tests, *args.name)
        if not tests._tests and not go_pkgs:
            raise SystemExit('No test named %s found' % args.name)
    python_tests_ok = run_cli(tests, args.verbosity)
    exit_code = 0 if python_tests_ok else 1
    if go_pkgs:
        print_go()
        if exit_code == 0:
            exit_code = go_proc.returncode
    raise SystemExit(exit_code)
