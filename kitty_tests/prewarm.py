#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


import json
import os
import select
import signal
import tempfile

from kitty.constants import is_macos, kitty_exe
from kitty.fast_data_types import (
    get_options, install_signal_handlers, read_signals, remove_signal_handlers
)

from . import BaseTest


class Prewarm(BaseTest):

    maxDiff = None

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
        import subprocess
        expecting_code = 0
        found_signal = False

        def handle_signal(siginfo):
            nonlocal found_signal
            self.ae(siginfo.si_signo, signal.SIGCHLD)
            self.ae(siginfo.si_code, expecting_code)
            if expecting_code in (os.CLD_EXITED, os.CLD_KILLED):
                p.wait(1)
                p.stdin.close()
            found_signal = True

        def t(signal, q):
            nonlocal expecting_code, found_signal
            expecting_code = q
            found_signal = False
            if signal is not None:
                p.send_signal(signal)
            if q is not None:
                for (fd, event) in poll.poll(5000):
                    read_signals(signal_read_fd, handle_signal)
                self.assertTrue(found_signal, f'Failed to to get SIGCHLD for signal {signal}')

        poll = select.poll()
        p = subprocess.Popen([kitty_exe(), '+runpy', 'while True: x=2+2'], stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
        signal_read_fd = install_signal_handlers(signal.SIGCHLD)[0]
        try:
            poll.register(signal_read_fd, select.POLLIN)
            if hasattr(os, 'CLD_STOPPED'):
                t(signal.SIGTSTP, os.CLD_STOPPED)
                # macOS doesnt send SIGCHLD for SIGCONT. This is not required by POSIX sadly
                t(signal.SIGCONT, None if is_macos else os.CLD_CONTINUED)
            t(signal.SIGINT, os.CLD_KILLED)
            p = subprocess.Popen([kitty_exe(), '+runpy', 'input()'], stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
            p.stdin.close()
            t(None, os.CLD_EXITED)
        finally:
            remove_signal_handlers()
