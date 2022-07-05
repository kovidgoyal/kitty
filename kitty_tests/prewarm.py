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

from kitty.constants import kitty_exe
from kitty.fast_data_types import (
    CLD_EXITED, CLD_KILLED, get_options, has_sigqueue, install_signal_handlers,
    read_signals, remove_signal_handlers, sigqueue
)

from . import BaseTest


class Prewarm(BaseTest):

    maxDiff = None

    def test_socket_prewarming(self):
        from kitty.prewarm import fork_prewarm_process
        exit_code = 17
        src = '''\
def socket_child_main(exit_code=0):
    import json
    import os
    import sys

    from kitty.fast_data_types import get_options
    from kitty.utils import read_screen_size
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
        env = {'TEST_ENV_PASS': 'xyz', 'KITTY_PREWARM_SOCKET': p.socket_env_var()}
        cols = 117
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
        with open(stdout_r) as f:
            stdout_data = f.read()
        status = os.waitpid(pty.child_pid, 0)[1]
        with suppress(AttributeError):
            self.assertEqual(os.waitstatus_to_exitcode(status), exit_code)
        pty.wait_till(lambda: 'hello' in pty.screen_contents())
        output = json.loads(pty.screen_contents().strip())
        self.assertEqual(output['test_env'], env['TEST_ENV_PASS'])
        self.assertEqual(output['cwd'], cwd)
        self.assertEqual(output['font_family'], 'prewarm')
        self.assertEqual(output['cols'], cols)
        self.assertEqual(output['stdin_data'], stdin_data)
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
        expecting_code = 0
        expecting_signal = 0
        expecting_value = 0
        found_signal = False

        def handle_signal(siginfo):
            nonlocal found_signal
            if expecting_signal:
                self.ae(siginfo.si_signo, expecting_signal)
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
            while time.monotonic() - st < 5:
                for (fd, event) in poll.poll(10):
                    if fd == signal_read_fd:
                        read_signals(signal_read_fd, handle_signal)
                if found_signal:
                    break
            self.assertTrue(found_signal, f'Failed to to get SIGCHLD for signal {signal}')

        def t(signal, q, expecting_sig=signal.SIGCHLD):
            nonlocal expecting_code, found_signal, expecting_signal
            expecting_code = q
            expecting_signal = expecting_sig.value
            if signal is not None:
                p.send_signal(signal)
            assert_signal()

        poll = select.poll()
        p = subprocess.Popen([kitty_exe(), '+runpy', 'input()'], stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
        signal_read_fd = install_signal_handlers(signal.SIGCHLD, signal.SIGUSR1)[0]
        try:
            poll.register(signal_read_fd, select.POLLIN)
            t(signal.SIGINT, CLD_KILLED)
            p = subprocess.Popen([kitty_exe(), '+runpy', 'input()'], stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
            p.stdin.close()
            t(None, os.CLD_EXITED)
            expecting_code = None
            expecting_signal = signal.SIGUSR1.value
            os.kill(os.getpid(), signal.SIGUSR1)
            assert_signal()
            expecting_value = 17 if has_sigqueue else 0
            sigqueue(os.getpid(), signal.SIGUSR1.value, expecting_value)
            assert_signal()

        finally:
            remove_signal_handlers()
