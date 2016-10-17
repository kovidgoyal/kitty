#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import termios
import struct
import shlex
import fcntl
import signal
import ctypes
from functools import lru_cache

from PyQt5.QtGui import QFontMetrics

current_font_metrics = cell_width = None
libc = ctypes.CDLL(None)
wcwidth_native = libc.wcwidth
del libc
wcwidth_native.argtypes = [ctypes.c_wchar]
wcwidth_native.restype = ctypes.c_int


@lru_cache(maxsize=2**13)
def wcwidth(c: str) -> int:
    if current_font_metrics is None:
        return min(2, wcwidth_native(c))
    w = current_font_metrics.widthChar(c)
    cells, extra = divmod(w, cell_width)
    if extra > 0.1 * cell_width:
        cells += 1
    return min(2, cells)


def set_current_font_metrics(fm: QFontMetrics, cw: int) -> None:
    global current_font_metrics, cell_width
    current_font_metrics, cell_width = fm, cw
    wcwidth.cache_clear()


def create_pty():
    if not hasattr(create_pty, 'master'):
        create_pty.master, create_pty.slave = os.openpty()
        fcntl.fcntl(create_pty.slave, fcntl.F_SETFD, fcntl.fcntl(create_pty.slave, fcntl.F_GETFD) & ~fcntl.FD_CLOEXEC)
        # Note that master and slave are in blocking mode
    return create_pty.master, create_pty.slave


def fork_child(cmd, cwd, opts):
    argv = shlex.split(cmd)
    master, slave = create_pty()
    pid = os.fork()
    if pid == 0:
        try:
            os.chdir(cwd)
        except EnvironmentError:
            os.chdir('/')
        os.setsid()
        for i in range(3):
            os.dup2(slave, i)
        os.close(slave), os.close(master)
        # Establish the controlling terminal (see man 7 credentials)
        os.close(os.open(os.ttyname(1), os.O_RDWR))
        os.environ['TERM'] = opts.term
        os.environ['COLORTERM'] = 'truecolor'
        os.execvp(argv[0], argv)
    else:
        os.close(slave)
        fork_child.pid = pid
        return pid


def resize_pty(w, h):
    master = create_pty()[0]
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('4H', w, h, 0, 0))


def hangup():
    if hasattr(fork_child, 'pid'):
        pid = fork_child.pid
        del fork_child.pid
        pgrp = os.getpgid(pid)
        os.killpg(pgrp, signal.SIGHUP)
        os.close(create_pty()[0])
