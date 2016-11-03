#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import subprocess
import sys
import termios
import struct
import fcntl
import signal
import ctypes
import unicodedata
from contextlib import contextmanager
from functools import lru_cache
from time import monotonic

import glfw

from .constants import terminfo_dir

libc = ctypes.CDLL(None)
wcwidth_native = libc.wcwidth
del libc
wcwidth_native.argtypes = [ctypes.c_wchar]
wcwidth_native.restype = ctypes.c_int


@lru_cache(maxsize=2**13)
def wcwidth(c: str) -> int:
    if unicodedata.combining(c):
        return 0
    if wcwidth.current_font is None:
        return min(2, wcwidth_native(c))
    return wcwidth.current_font(c)
wcwidth.current_font = None


def set_current_font_metrics(current_font) -> None:
    wcwidth.cache_clear()
    wcwidth.current_font = current_font


def create_pty():
    if not hasattr(create_pty, 'master'):
        create_pty.master, create_pty.slave = os.openpty()
        fcntl.fcntl(create_pty.slave, fcntl.F_SETFD, fcntl.fcntl(create_pty.slave, fcntl.F_GETFD) & ~fcntl.FD_CLOEXEC)
        # Note that master and slave are in blocking mode
    return create_pty.master, create_pty.slave


def fork_child(argv, cwd, opts):
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
        os.closerange(3, 200)
        # Establish the controlling terminal (see man 7 credentials)
        os.close(os.open(os.ttyname(1), os.O_RDWR))
        os.environ['TERM'] = opts.term
        os.environ['COLORTERM'] = 'truecolor'
        if os.path.isdir(terminfo_dir):
            os.environ['TERMINFO'] = terminfo_dir
        try:
            os.execvp(argv[0], argv)
        except Exception as err:
            print('Could not launch:', argv[0])
            print('\t', err)
            input('\nPress Enter to exit:')
    else:
        os.close(slave)
        fork_child.pid = pid
        return pid


def resize_pty(w, h):
    master = create_pty()[0]
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('4H', h, w, 0, 0))


def hangup():
    if hasattr(fork_child, 'pid'):
        pid = fork_child.pid
        del fork_child.pid
        try:
            pgrp = os.getpgid(pid)
        except ProcessLookupError:
            return
        os.killpg(pgrp, signal.SIGHUP)
        os.close(create_pty()[0])


def get_child_status():
    if hasattr(fork_child, 'pid'):
        try:
            return os.waitid(os.P_PID, fork_child.pid, os.WEXITED | os.WNOHANG)
        except ChildProcessError:
            del fork_child.pid

base_size = sys.getsizeof('')


def is_simple_string(x):
    ' We use the fact that python stores unicode strings with a 1-byte representation when possible '
    return sys.getsizeof(x) == base_size + len(x)


@contextmanager
def timeit(name, do_timing=False):
    if do_timing:
        st = monotonic()
    yield
    if do_timing:
        print('Time for {}: {}'.format(name, monotonic() - st))


def sanitize_title(x):
    return re.sub(r'\s+', ' ', re.sub(r'[\0-\x19]', '', x))


def get_logical_dpi():
    if not hasattr(get_logical_dpi, 'ans'):
        raw = subprocess.check_output(['xdpyinfo']).decode('utf-8')
        m = re.search(r'^\s*resolution:\s*(\d+)+x(\d+)', raw, flags=re.MULTILINE)
        get_logical_dpi.ans = int(m.group(1)), int(m.group(2))
    return get_logical_dpi.ans


def get_dpi():
    if not hasattr(get_dpi, 'ans'):
        m = glfw.glfwGetPrimaryMonitor()
        width, height = glfw.glfwGetMonitorPhysicalSize(m)
        vmode = glfw.glfwGetVideoMode(m)
        dpix = vmode.width / (width / 25.4)
        dpiy = vmode.height / (height / 25.4)
        get_dpi.ans = {'physical': (dpix, dpiy), 'logical': get_logical_dpi()}
    return get_dpi.ans
