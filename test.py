#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import unittest
import os
import sys
import importlib

base = os.path.dirname(os.path.abspath(__file__))


def init_env():
    sys.path.insert(0, base)


def itertests(suite):
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


def find_tests_in_dir(path, excludes=('main.py',)):
    package = os.path.relpath(path, base).replace(os.sep, '/').replace('/', '.')
    items = os.listdir(path)
    suits = []
    for x in items:
        if x.endswith('.py') and x not in excludes:
            m = importlib.import_module(package + '.' + x.partition('.')[0])
            suits.append(unittest.defaultTestLoader.loadTestsFromModule(m))
    return unittest.TestSuite(suits)


def filter_tests(suite, test_ok):
    ans = unittest.TestSuite()
    added = set()
    for test in itertests(suite):
        if test_ok(test) and test not in added:
            ans.addTest(test)
            added.add(test)
    return ans


def filter_tests_by_name(suite, *names):
    names = {x if x.startswith('test_') else 'test_' + x for x in names}

    def q(test):
        return test._testMethodName in names
    return filter_tests(suite, q)


def filter_tests_by_module(suite, *names):
    names = frozenset(names)

    def q(test):
        m = test.__class__.__module__.rpartition('.')[-1]
        return m in names
    return filter_tests(suite, q)


def run_tests(find_tests, verbosity=4):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('name', nargs='?', default=None,
                        help='The name of the test to run, for e.g. writing.WritingTest.many_many_basic or .many_many_basic for a shortcut')
    args = parser.parse_args()
    tests = find_tests()
    if args.name:
        if args.name.startswith('.'):
            tests = filter_tests_by_name(tests, args.name[1:])
        else:
            tests = filter_tests_by_module(tests, args.name)
        if not tests._tests:
            raise SystemExit('No test named %s found' % args.name)
    run_cli(tests, verbosity)


def run_cli(suite, verbosity=4):
    r = unittest.TextTestRunner
    r.resultclass = unittest.TextTestResult
    init_env()
    runner = r(verbosity=verbosity)
    runner.tb_locals = True
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)

if __name__ == '__main__':
    run_cli(find_tests_in_dir(os.path.join(base, 'kitty_tests')))
