#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import io
import os
import subprocess
import textwrap
from contextlib import redirect_stdout

from kitty.constants import kitty_exe

from .base import BaseTest
from .main import collect_worker_results


class TestRunner(BaseTest):
    def run_worker(self, behavior):
        read_fd, write_fd = os.pipe()
        code = textwrap.dedent(f"""\
            import os
            import unittest
            from contextlib import contextmanager
            from kitty_tests import main

            behavior = {behavior!r}

            class WorkerTest(unittest.TestCase):
                def test_first(self):
                    pass

                def test_second(self):
                    if behavior == 'during_test':
                        os._exit(0)
                    if behavior == 'nonzero_exit':
                        os._exit(7)
                    if behavior in ('failure', 'expected_failure'):
                        self.fail('expected failure')
                    if behavior == 'skip':
                        self.skipTest('expected skip')
                    if behavior == 'subtests':
                        for value in range(2):
                            with self.subTest(value=value):
                                self.assertGreaterEqual(value, 0)
                    if behavior == 'subtest_failure':
                        with self.subTest(value=0):
                            self.fail('expected subtest failure')

            if behavior == 'before_tests':
                os._exit(0)
            if behavior == 'class_skip':
                WorkerTest = unittest.skip('expected class skip')(WorkerTest)
            if behavior == 'expected_failure':
                WorkerTest.test_second = unittest.expectedFailure(WorkerTest.test_second)
            if behavior in ('after_results', 'worker_error'):
                original_env = main.env_for_python_tests

                @contextmanager
                def exiting_env():
                    with original_env():
                        if behavior == 'worker_error':
                            raise RuntimeError('expected worker error')
                        yield
                    os._exit(0)

                main.env_for_python_tests = exiting_env

            main.run_test_worker([WorkerTest('test_first'), WorkerTest('test_second')], {write_fd})
        """)
        try:
            proc = subprocess.Popen([kitty_exe(), '+runpy', f'exec({code!r}, {{}})'], pass_fds=(write_fd,))
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            os.close(write_fd)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                python_ok, go_ok = collect_worker_results([], [proc], [read_fd], 2)
        finally:
            proc.kill()
            proc.wait()
        self.assertTrue(go_ok)
        return python_ok, output.getvalue()

    def test_worker_exits_early(self):
        for behavior, progress in (('before_tests', 'Py 0/2'), ('during_test', 'Py 1/2'), ('after_results', 'Py 2/2')):
            with self.subTest(behavior=behavior):
                ok, output = self.run_worker(behavior)
                self.assertFalse(ok, output)
                self.assertIn('WORKER ERROR', output)
                self.assertIn('without reporting completion', output)
                self.assertIn(progress, output)

    def test_worker_completes(self):
        for behavior in ('success', 'skip', 'class_skip', 'expected_failure', 'subtests'):
            with self.subTest(behavior=behavior):
                ok, output = self.run_worker(behavior)
                self.assertTrue(ok, output)
                self.assertNotIn('WORKER ERROR', output)
                self.assertIn('Ran 2 tests', output)

    def test_worker_reports_failure(self):
        for behavior, message in (
            ('failure', 'expected failure'),
            ('subtest_failure', 'expected subtest failure'),
            ('nonzero_exit', 'status 7'),
            ('worker_error', 'expected worker error'),
        ):
            with self.subTest(behavior=behavior):
                ok, output = self.run_worker(behavior)
                self.assertFalse(ok, output)
                self.assertIn(message, output)
                self.assertNotIn('without reporting completion', output)
