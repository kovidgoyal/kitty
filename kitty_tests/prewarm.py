#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import select
import signal
import subprocess
import tempfile
import time
from contextlib import suppress

from kitty.constants import kitty_exe, terminfo_dir
from kitty.fast_data_types import (
    CLD_EXITED, CLD_KILLED, CLD_STOPPED, get_options, has_sigqueue, install_signal_handlers,
    read_signals, sigqueue
)

from . import BaseTest


class Prewarm(BaseTest):

    maxDiff = None

    def test_socket_prewarming(self):
        from kitty.prewarm import fork_prewarm_process, wait_for_child_death
        exit_code = 17
        src = '''\
def socket_child_main(exit_code=0, initial_print=''):
    import os, sys, json, signal
    from kitty.fast_data_types import get_options
    from kitty.utils import read_screen_size

    def report_screen_size_change(*a):
        print("Screen size changed:", read_screen_size(fd=sys.stderr.fileno()).cols, file=sys.stderr, flush=True)

    def report_tstp(*a):
        print("SIGTSTP received", file=sys.stderr, flush=True)
        raise SystemExit(19)

    signal.signal(signal.SIGWINCH, report_screen_size_change)
    signal.signal(signal.SIGTSTP, report_tstp)

    if initial_print:
        print(initial_print, flush=True, file=sys.stderr)

    output = {
        'test_env': os.environ.get('TEST_ENV_PASS', ''),
        'cwd': os.path.realpath(os.getcwd()),
        'font_family': get_options().font_family,
        'cols': read_screen_size(fd=sys.stderr.fileno()).cols,
        'stdin_data': sys.stdin.read(),
        'done': 'hello',
    }
    print(json.dumps(output, indent=2), file=sys.stderr, flush=True)
    print('testing stdout', end='')
    raise SystemExit(exit_code)
    ''' + '\n\n'
        cwd = os.path.realpath(tempfile.gettempdir())
        opts = self.set_options()
        opts.config_overrides = 'font_family prewarm',
        p = fork_prewarm_process(opts, use_exec=True)
        if p is None:
            return
        env = os.environ.copy()
        env.update({
            'TEST_ENV_PASS': 'xyz',
            'KITTY_PREWARM_SOCKET': p.socket_env_var(),
            'KITTY_PREWARM_SOCKET_REAL_TTY': ' ' * 32,
            'TERM': 'xterm-kitty',
            'TERMINFO': terminfo_dir
        })
        cols = 117

        def wait_for_death(exit_code, timeout=5):
            status = wait_for_child_death(pty.child_pid, timeout=timeout)
            if status is None:
                os.kill(pty.child_pid, signal.SIGKILL)
            if status is None:
                pty.process_input_from_child(0)
            self.assertIsNotNone(status, f'prewarm wrapper process did not exit. Screen contents: {pty.screen_contents()}')
            if isinstance(exit_code, signal.Signals):
                self.assertTrue(os.WIFSIGNALED(status), 'prewarm wrapper did not die with a signal')
                self.assertEqual(os.WTERMSIG(status), exit_code.value)
            else:
                with suppress(AttributeError):
                    self.assertEqual(os.waitstatus_to_exitcode(status), exit_code, pty.screen_contents())

        if not self.is_ci:  # signal delivery tests are pretty flakey on CI so give up on them
            with self.subTest(msg='test SIGINT via signal to wrapper'):
                pty = self.create_pty(
                    argv=[kitty_exe(), '+runpy', src + 'socket_child_main(initial_print="child ready:")'], cols=cols, env=env, cwd=cwd)
                pty.wait_till(lambda: 'child ready:' in pty.screen_contents())
                os.kill(pty.child_pid, signal.SIGINT)
                pty.wait_till(lambda: 'KeyboardInterrupt' in pty.screen_contents())
                wait_for_death(signal.SIGINT)

            with self.subTest(msg='test SIGINT via Ctrl-c'):
                pty = self.create_pty(
                    argv=[kitty_exe(), '+runpy', src + 'socket_child_main(initial_print="child ready:")'], cols=cols, env=env, cwd=cwd)
                pty.wait_till(lambda: 'child ready:' in pty.screen_contents())
                pty.write_to_child('\x03', flush=True)
                pty.wait_till(lambda: 'KeyboardInterrupt' in pty.screen_contents())
                wait_for_death(signal.SIGINT)

            with self.subTest(msg='test SIGTSTP via Ctrl-z'):
                pty = self.create_pty(
                    argv=[kitty_exe(), '+runpy', src + 'socket_child_main(initial_print="child ready:")'], cols=cols, env=env, cwd=cwd)
                pty.wait_till(lambda: 'child ready:' in pty.screen_contents())
                pty.write_to_child('\x1a', flush=True)
                pty.wait_till(lambda: 'SIGTSTP received' in pty.screen_contents())
                wait_for_death(19)

            with self.subTest(msg='test SIGWINCH handling'):
                pty = self.create_pty(
                    argv=[kitty_exe(), '+runpy', src + 'socket_child_main(initial_print="child ready:")'], cols=cols, env=env, cwd=cwd)
                pty.wait_till(lambda: 'child ready:' in pty.screen_contents())
                pty.set_window_size(columns=cols + 3)
                pty.wait_till(lambda: f'Screen size changed: {cols + 3}' in pty.screen_contents())
                os.close(pty.master_fd)

        with self.subTest(msg='test env rewrite'):
            pty = self.create_pty(
                argv=[kitty_exe(), '+runpy', src + 'socket_child_main(initial_print="child ready:")'], cols=cols, env=env, cwd=cwd)
            pty.wait_till(lambda: 'child ready:' in pty.screen_contents())
            from kitty.child import environ_of_process
            self.assertIn('/', environ_of_process(pty.child_pid).get('KITTY_PREWARM_SOCKET_REAL_TTY', ''))
            os.close(pty.master_fd)

        with self.subTest(msg='test passing of data via cwd, env vars and stdin/stdout redirection'):
            stdin_r, stdin_w = os.pipe()
            os.set_inheritable(stdin_w, False)
            stdout_r, stdout_w = os.pipe()
            os.set_inheritable(stdout_r, False)
            pty = self.create_pty(
                argv=[kitty_exe(), '+runpy', src + f'socket_child_main({exit_code})'], cols=cols, env=env, cwd=cwd,
                stdin_fd=stdin_r, stdout_fd=stdout_w)
            stdin_data = 'testing--stdin-read'
            with open(stdin_w, 'w') as f:
                f.write(stdin_data)

            def has_json():
                s = pty.screen_contents().strip()
                return 'hello' in s and s.endswith('}')

            pty.wait_till(has_json)
            wait_for_death(exit_code)
            output = json.loads(pty.screen_contents().strip())
            self.assertEqual(output['test_env'], env['TEST_ENV_PASS'])
            self.assertEqual(output['cwd'], cwd)
            self.assertEqual(output['font_family'], 'prewarm')
            self.assertEqual(output['cols'], cols)
            self.assertEqual(output['stdin_data'], stdin_data)
            with open(stdout_r) as f:
                stdout_data = f.read()
            self.assertEqual(stdout_data, 'testing stdout')

    def test_prewarming(self):
        from kitty.prewarm import fork_prewarm_process

        cwd = tempfile.gettempdir()
        env = {'TEST_ENV_PASS': 'xyz'}
        cols = 117
        stdin_data = 'from_stdin'
        pty = self.create_pty(cols=cols)
        ttyname = os.ttyname(pty.slave_fd)
        opts = get_options()
        opts.config_overrides = 'font_family prewarm',
        p = fork_prewarm_process(opts, use_exec=True)
        if p is None:
            return
        p.take_from_worker_fd(create_file=True)
        child = p(pty.slave_fd, [kitty_exe(), '+runpy', """\
import os, json; from kitty.utils import *; from kitty.fast_data_types import get_options; print(json.dumps({
        'cterm': os.ctermid(),
        'ttyname': os.ttyname(sys.stdout.fileno()),
        'cols': read_screen_size().cols,
        'cwd': os.getcwd(),
        'env': os.environ.get('TEST_ENV_PASS'),
        'pid': os.getpid(),
        'font_family': get_options().font_family,
        'stdin': sys.stdin.read(),

        'done': 'hello',
        }, indent=2))"""], cwd=cwd, env=env, stdin_data=stdin_data)
        self.assertFalse(pty.screen_contents().strip())
        p.mark_child_as_ready(child.child_id)
        pty.wait_till(lambda: 'hello' in pty.screen_contents())
        data = json.loads(pty.screen_contents())
        self.ae(data['cols'], cols)
        self.assertTrue(data['cterm'])
        self.ae(data['ttyname'], ttyname)
        self.ae(os.path.realpath(data['cwd']), os.path.realpath(cwd))
        self.ae(data['env'], env['TEST_ENV_PASS'])
        self.ae(data['font_family'], 'prewarm')
        self.ae(int(p.from_worker.readline()), data['pid'])

    def test_signal_handling(self):
        from kitty.prewarm import restore_python_signal_handlers, wait_for_child_death
        expecting_code = 0
        expecting_signal = signal.SIGCHLD
        expecting_value = 0
        found_signal = False

        def handle_signals(signals):
            nonlocal found_signal
            for siginfo in signals:
                if siginfo.si_signo != expecting_signal.value:
                    continue
                if expecting_code is not None:
                    self.ae(siginfo.si_code, expecting_code)
                self.ae(siginfo.sival_int, expecting_value)
                if expecting_code in (CLD_EXITED, CLD_KILLED):
                    p.wait(1)
                    p.stdin.close()
                found_signal = True

        def assert_signal():
            nonlocal found_signal
            found_signal = False
            st = time.monotonic()
            while time.monotonic() - st < 30:
                for (fd, event) in poll.poll(10):
                    if fd == signal_read_fd:
                        signals = []
                        read_signals(signal_read_fd, signals.append)
                        handle_signals(signals)
                if found_signal:
                    break
            self.assertTrue(found_signal, f'Failed to get signal: {expecting_signal!r}')

        def t(signal, q, expecting_sig=signal.SIGCHLD):
            nonlocal expecting_code, found_signal, expecting_signal
            expecting_code = q
            expecting_signal = expecting_sig
            if signal is not None:
                p.send_signal(signal)
            assert_signal()

        poll = select.poll()

        def run():
            return subprocess.Popen([kitty_exe(), '+runpy', 'import sys; sys.stdin.read()'], stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
        p = run()
        orig_mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())
        signal_read_fd = install_signal_handlers(signal.SIGCHLD, signal.SIGUSR1)[0]
        try:
            poll.register(signal_read_fd, select.POLLIN)
            t(signal.SIGINT, CLD_KILLED)
            p = run()
            p.stdin.close()
            t(None, CLD_EXITED)
            expecting_code = None
            expecting_signal = signal.SIGUSR1
            os.kill(os.getpid(), signal.SIGUSR1)
            assert_signal()
            expecting_value = 17 if has_sigqueue else 0
            sigqueue(os.getpid(), signal.SIGUSR1.value, expecting_value)
            assert_signal()

            expecting_code = None
            expecting_value = 0
            p = run()
            p.send_signal(signal.SIGSTOP)
            s = wait_for_child_death(p.pid, options=os.WUNTRACED, timeout=5)
            self.assertTrue(os.WIFSTOPPED(s))
            t(None, CLD_STOPPED)
            p.send_signal(signal.SIGCONT)
            s = wait_for_child_death(p.pid, options=os.WCONTINUED, timeout=5)
            self.assertTrue(os.WIFCONTINUED(s))
            # macOS does not send SIGCHLD when child is continued
            # https://stackoverflow.com/questions/48487935/sigchld-is-sent-on-sigcont-on-linux-but-not-on-macos
            p.stdin.close()
            p.wait(1)
            for fd, event in poll.poll(0):
                read_signals(signal_read_fd, lambda si: None)
        finally:
            restore_python_signal_handlers()
            signal.pthread_sigmask(signal.SIG_SETMASK, orig_mask)
