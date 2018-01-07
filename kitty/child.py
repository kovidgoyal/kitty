#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import os

import kitty.fast_data_types as fast_data_types

from .constants import terminfo_dir, is_macos


def cwd_of_process(pid):
    if is_macos:
        from kitty.fast_data_types import cwd_of_process
        ans = cwd_of_process(pid)
    else:
        ans = '/proc/{}/cwd'.format(pid)
    return os.path.realpath(ans)


def cmdline_of_process(pid):
    if is_macos:
        # TODO: macOS implementation, see DarwinProcess.c in htop for inspiration
        raise NotImplementedError()
    return open('/proc/{}/cmdline'.format(pid), 'rb').read().decode('utf-8').split('\0')


def remove_cloexec(fd):
    fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.fcntl(fd, fcntl.F_GETFD) & ~fcntl.FD_CLOEXEC)


class Child:

    child_fd = pid = None
    forked = False

    def __init__(self, argv, cwd, opts, stdin=None, env=None, cwd_from=None):
        self.argv = argv
        if cwd_from is not None:
            try:
                cwd = cwd_of_process(cwd_from)
            except Exception:
                import traceback
                traceback.print_exc()
        else:
            cwd = os.path.expandvars(os.path.expanduser(cwd or os.getcwd()))
        self.cwd = os.path.abspath(cwd)
        self.opts = opts
        self.stdin = stdin
        self.env = env or {}

    def fork(self):
        if self.forked:
            return
        self.forked = True
        master, slave = os.openpty()  # Note that master and slave are in blocking mode
        remove_cloexec(slave)
        fast_data_types.set_iutf8(master, True)
        stdin, self.stdin = self.stdin, None
        if stdin is not None:
            stdin_read_fd, stdin_write_fd = os.pipe()
            remove_cloexec(stdin_read_fd)
        else:
            stdin_read_fd = stdin_write_fd = -1
        env = os.environ.copy()
        env.update(self.env)
        env['TERM'] = self.opts.term
        env['COLORTERM'] = 'truecolor'
        if os.path.isdir(terminfo_dir):
            env['TERMINFO'] = terminfo_dir
        env = tuple('{}={}'.format(k, v) for k, v in env.items())
        pid = fast_data_types.spawn(self.cwd, tuple(self.argv), env, master, slave, stdin_read_fd, stdin_write_fd)
        os.close(slave)
        self.pid = pid
        self.child_fd = master
        if stdin is not None:
            os.close(stdin_read_fd)
            fast_data_types.thread_write(stdin_write_fd, stdin)
        return pid
