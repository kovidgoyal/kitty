#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import os
import sys

import kitty.fast_data_types as fast_data_types

from .constants import terminfo_dir, is_macos


def cwd_of_process(pid):
    if is_macos:
        raise NotImplementedError('getting cwd of child processes not implemented')
    return os.readlink('/proc/{}/cwd'.format(pid))


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
        self.cwd = os.path.abspath(os.path.expandvars(os.path.expanduser(cwd or os.getcwd())))
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
        env = self.env
        pid = os.fork()
        if pid == 0:  # child
            try:
                os.chdir(self.cwd)
            except EnvironmentError:
                os.chdir('/')
            os.setsid()
            for i in range(3):
                if stdin is not None and i == 0:
                    os.dup2(stdin_read_fd, i)
                    os.close(stdin_read_fd), os.close(stdin_write_fd)
                else:
                    os.dup2(slave, i)
            os.close(slave), os.close(master)
            os.closerange(3, 200)
            # Establish the controlling terminal (see man 7 credentials)
            os.close(os.open(os.ttyname(1), os.O_RDWR))
            os.environ.update(env)
            os.environ['TERM'] = self.opts.term
            os.environ['COLORTERM'] = 'truecolor'
            if os.path.isdir(terminfo_dir):
                os.environ['TERMINFO'] = terminfo_dir
            try:
                os.execvp(self.argv[0], self.argv)
            except Exception as err:
                # Report he failure and exec a shell instead so that
                # we are not left with a forked but not execed process
                print('Could not launch:', self.argv[0])
                print('\t', err)
                print('\nPress Enter to exit:', end=' ')
                sys.stdout.flush()
                os.execvp('/bin/sh', ['/bin/sh', '-c', 'read w'])
        else:  # master
            os.close(slave)
            self.pid = pid
            self.child_fd = master
            if stdin is not None:
                os.close(stdin_read_fd)
                fast_data_types.thread_write(stdin_write_fd, stdin)
            return pid
