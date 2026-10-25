#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import os
import subprocess
import textwrap
import unittest
import warnings

from kitty.constants import kitty_exe

from .base import BaseTest


class WarningWorker(unittest.TestCase):
    # Only the driver tests below should run these fixtures, not test discovery.
    def warn_user(self):
        warnings.warn('worker warning regression', UserWarning)

    def warn_deprecation(self):
        warnings.warn('worker deprecation regression', DeprecationWarning)

    def succeed(self):
        pass


class TestRunner(BaseTest):
    def check_warning_filters(self, route):
        env = os.environ.copy()
        env.pop('PYTHONWARNINGS', None)
        for method, warning in (('warn_user', 'UserWarning'), ('warn_deprecation', 'DeprecationWarning'), ('succeed', '')):
            with self.subTest(route=route, method=method):
                code = textwrap.dedent(f"""\
                    import sys
                    import warnings
                    from kitty_tests.main import (
                        collect_worker_results, fork_test_workers, run_serial_tests,
                        spawn_test_workers, terminate_workers,
                    )
                    from kitty_tests.test_runner import WarningWorker

                    # Match the policy set by the test launcher's main().
                    warnings.simplefilter('error')
                    tests = [WarningWorker({method!r})]
                    if {route!r} == 'serial':
                        ok = run_serial_tests(tests, 2)
                    else:
                        if sys.platform == 'darwin':
                            procs, fds = spawn_test_workers(tests)
                            pids = []
                        else:
                            pids, fds = fork_test_workers(tests)
                            procs = []
                        try:
                            ok, _ = collect_worker_results(pids, procs, fds, len(tests))
                        finally:
                            terminate_workers(pids, procs, None)
                    raise SystemExit(0 if ok else 1)
                """)
                result = subprocess.run(
                    [kitty_exe(), '+runpy', f'exec({code!r}, {{}})'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=30,
                    env=env,
                )
                self.assertEqual(result.returncode, 1 if warning else 0, result.stdout)
                if warning:
                    self.assertIn(warning + ': worker ', result.stdout)

    def test_serial_worker_warning_filters(self):
        self.check_warning_filters('serial')

    def test_parallel_worker_warning_filters(self):
        self.check_warning_filters('parallel')
