#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import termios
import struct
import fcntl
import signal
from threading import Thread

from .constants import terminfo_dir
import kitty.fast_data_types as fast_data_types


def remove_cloexec(fd):
    fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.fcntl(fd, fcntl.F_GETFD) & ~fcntl.FD_CLOEXEC)


class Child:

    child_fd = pid = None
    forked = False

    def __init__(self, argv, cwd, opts, stdin=None):
        self.argv = argv
        self.cwd = os.path.abspath(os.path.expandvars(os.path.expanduser(cwd or os.getcwd())))
        self.opts = opts
        self.stdin = stdin

    def fork(self):
        if self.forked:
            return
        self.forked = True
        master, slave = os.openpty()  # Note that master and slave are in blocking mode
        remove_cloexec(slave)
        self.set_iutf8(fd=master)
        stdin, self.stdin = self.stdin, None
        if stdin is not None:
            stdin_read_fd, stdin_write_fd = os.pipe()
            remove_cloexec(stdin_read_fd)
            stdin_file = os.fdopen(stdin_write_fd, 'wb')
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
            os.environ['TERM'] = self.opts.term
            os.environ['COLORTERM'] = 'truecolor'
            if os.path.isdir(terminfo_dir):
                os.environ['TERMINFO'] = terminfo_dir
            try:
                os.execvp(self.argv[0], self.argv)
            except Exception as err:
                print('Could not launch:', self.argv[0])
                print('\t', err)
                input('\nPress Enter to exit:')
        else:  # master
            os.close(slave)
            self.pid = pid
            self.child_fd = master
            if stdin is not None:
                t = Thread(name='WriteStdin', target=stdin_file.write, args=(stdin,))
                t.daemon = True
                t.start()
            return pid

    def resize_pty(self, w, h, ww, wh):
        if self.child_fd is not None:
            fcntl.ioctl(self.child_fd, termios.TIOCSWINSZ, struct.pack('4H', h, w, ww, wh))

    def set_iutf8(self, on=True, fd=None):
        fd = fd or self.child_fd
        if fd is not None and hasattr(fast_data_types, 'IUTF8'):
            attrs = termios.tcgetattr(fd)
            if on:
                attrs[0] |= fast_data_types.IUTF8
            else:
                attrs[0] &= ~fast_data_types.IUTF8
            termios.tcsetattr(fd, termios.TCSANOW, attrs)

    def hangup(self):
        if self.pid is not None:
            pid, self.pid = self.pid, None
            try:
                pgrp = os.getpgid(pid)
            except ProcessLookupError:
                return
            os.killpg(pgrp, signal.SIGHUP)
            os.close(self.child_fd)
            self.child_fd = None

    def __del__(self):
        self.hangup()

    def get_child_status(self):
        if self.pid is not None:
            try:
                return os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG)
            except ChildProcessError:
                self.pid = None
