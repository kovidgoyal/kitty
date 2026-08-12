#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import io
import json
import os
import unittest
from contextlib import redirect_stdout

from .main import PipeTestResult, collect_worker_results


class TestParallelTestRunner(unittest.TestCase):
    def test_subtest_failures_are_reported(self) -> None:
        class FailingSubTest(unittest.TestCase):
            def runTest(self) -> None:
                with self.subTest(value='bad'):
                    self.fail('subtest failure')

        read_fd, write_fd = os.pipe()
        try:
            result = PipeTestResult(write_fd)
            unittest.TestSuite((FailingSubTest(),)).run(result)
        finally:
            os.close(write_fd)
        try:
            records = [json.loads(line) for line in os.read(read_fd, 64 * 1024).splitlines()]
        finally:
            os.close(read_fd)

        self.assertFalse(result.wasSuccessful())
        failure = next(record for record in records if record['t'] == 'fail')
        self.assertIn("value='bad'", failure['id'])
        self.assertIn('subtest failure', failure['msg'])

    def test_worker_exit_failure_is_not_ignored(self) -> None:
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            os.close(write_fd)
            os._exit(3)

        os.close(write_fd)
        output = io.StringIO()
        with redirect_stdout(output):
            python_ok, go_ok = collect_worker_results([pid], [read_fd], 0)

        self.assertFalse(python_ok)
        self.assertTrue(go_ok)
        self.assertIn('exited with status 3', output.getvalue())
