#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import subprocess

from kitty.constants import kitten_exe

from .base import PTY, BaseTest


class TestNotify(BaseTest):
    def test_notify_close_escape_code(self):
        for title in ([], ['']):
            for wait in ([], ['--wait-till-closed']):
                with self.subTest(title=title, wait=wait):
                    p = subprocess.run(
                        [kitten_exe(), 'notify', '--only-print-escape-code', '--identifier=test', *wait, *title],
                        capture_output=True,
                        timeout=10,
                    )
                    self.ae(p.returncode, 0, p.stderr)
                    self.ae(p.stdout, b'\x1b]99;i=test:p=close;\x1b\\')

    def test_notify_close_requires_identifier(self):
        for args, error in (([], b'non-empty TITLE'), ([''], b'non-empty TITLE'), (['--identifier=invalid:id'], b'Invalid identifier')):
            with self.subTest(args=args):
                p = subprocess.run([kitten_exe(), 'notify', '--only-print-escape-code', *args], capture_output=True, timeout=10)
                self.ae(p.returncode, 1)
                self.ae(p.stdout, b'')
                self.assertIn(error, p.stderr)

    def test_notify_close_terminal(self):
        with PTY([kitten_exe(), 'notify', '--identifier=test']) as pty:
            pty.wait_till(lambda: bool(pty.callbacks.notifications))
            pty.wait_till_child_exits(require_exit_code=0)
            self.ae(pty.callbacks.notifications, [(99, 'i=test:p=close;')])

    def test_notify_close_wait(self):
        for title, response in (([], 'alive'), ([''], 'close')):
            with self.subTest(title=title), PTY([kitten_exe(), 'notify', '--identifier=test', '--wait-till-closed', *title]) as pty:
                messages = pty.callbacks.notifications
                pty.wait_till(lambda: bool(messages))
                self.ae(messages[0], (99, 'i=test:p=close;'))
                pty.wait_till(lambda: (99, 'i=test:p=alive;') in messages)
                self.ae(messages, [(99, 'i=test:p=close;'), (99, 'i=test:p=alive;')])
                messages.clear()
                pty.write_to_child('\x1b]99;i=test:p=alive;test\x1b\\')
                pty.wait_till(lambda: bool(messages))
                self.ae(messages, [(99, 'i=test:p=alive;')])
                pty.write_to_child(f'\x1b]99;i=test:p={response};\x1b\\')
                pty.wait_till_child_exits(require_exit_code=0)
                self.assertTrue(all(m == (99, 'i=test:p=alive;') for m in messages))
