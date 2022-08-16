#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import importlib
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from importlib.resources import contents
from typing import Callable, Generator, List, NoReturn, Sequence, Set


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


def run_cli(suite: unittest.TestSuite, verbosity: int = 4) -> None:
    r = unittest.TextTestRunner
    r.resultclass = unittest.TextTestResult
    runner = r(verbosity=verbosity)
    runner.tb_locals = True  # type: ignore
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def find_testable_go_packages() -> Set[str]:
    ans = set()
    base = os.getcwd()
    for (dirpath, dirnames, filenames) in os.walk(base):
        for f in filenames:
            if f.endswith('_test.go'):
                q = os.path.relpath(dirpath, base)
                ans.add(q)
    return ans


def go_exe() -> str:
    return shutil.which('go') or ''


def create_go_filter(packages: List[str], *names: str) -> str:
    go = go_exe()
    if not go:
        return ''
    all_tests = set()
    for line in subprocess.check_output(f'{go} test -list .'.split() + packages).decode().splitlines():
        if line.startswith('Test'):
            all_tests.add(line[4:])
    tests = set(names) & all_tests
    return '|'.join(tests)


def run_go(packages: List[str], names: str) -> None:
    go = go_exe()
    if not go:
        print('Skipping Go tests as go exe not found', file=sys.stderr)
        return
    if not packages:
        print('Skipping Go tests as go source files not availabe', file=sys.stderr)
        return
    cmd = [go, 'test', '-v']
    if names:
        cmd.extend(('-run', names))
    cmd += packages
    print(shlex.join(cmd), flush=True)
    os.execl(go, *cmd)


def run_tests() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'name', nargs='*', default=[],
        help='The name of the test to run, for e.g. linebuf corresponds to test_linebuf. Can be specified multiple times.')
    parser.add_argument('--verbosity', default=4, type=int, help='Test verbosity')
    parser.add_argument('--module', default='', help='Name of a test module to restrict to. For example: ssh.'
                        ' For Go tests this is the name of a package, for example: tools/cli')
    args = parser.parse_args()
    if args.name and args.name[0] in ('type-check', 'type_check', 'mypy'):
        type_check()
    tests = find_all_tests()
    go_packages = find_testable_go_packages()
    go_filter_spec = ''
    if args.module:
        tests = filter_tests_by_module(tests, args.module)
        go_packages &= {args.module}
        if not tests._tests and not go_packages:
            raise SystemExit('No test module named %s found' % args.module)
    go_pkg_args = [f'kitty/{x}' for x in go_packages]

    skip_go = False
    if args.name:
        tests = filter_tests_by_name(tests, *args.name)
        go_filter_spec = create_go_filter(go_pkg_args, *args.name)
        skip_go = not go_filter_spec
        if not tests._tests and not go_filter_spec:
            raise SystemExit('No test named %s found' % args.name)
    run_cli(tests, args.verbosity)
    if not skip_go:
        run_go(go_pkg_args, go_filter_spec)
