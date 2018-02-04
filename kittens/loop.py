#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import os
import selectors
import sys
import termios
import tty

from contextlib import closing, contextmanager


@contextmanager
def non_block(fd):
    oldfl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, oldfl | os.O_NONBLOCK)
    yield
    fcntl.fcntl(fd, fcntl.F_SETFL, oldfl)


@contextmanager
def raw_terminal(fd):
    isatty = os.isatty(fd)
    if isatty:
        old = termios.tcgetattr(fd)
        tty.setraw(fd)
    yield
    if isatty:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class Loop:

    def __init__(self, input_fd=None, output_fd=None):
        self.input_fd = input_fd or sys.stdin.fileno()
        self.output_fd = output_fd or sys.stdout.fileno()
        self.wakeup_read_fd, self.wakeup_write_fd = os.pipe()
        self.sel = s = selectors.DefaultSelector()
        s.register(self.input_fd, selectors.EVENT_READ, self._read_ready)
        s.register(self.wakeup_read_fd, selectors.EVENT_READ, self._wakeup_ready)
        s.register(self.output_fd, selectors.EVENT_WRITE, self._write_ready)
        self.keep_going = True
        self.return_code = 0

    def _read_ready(self, handler):
        pass

    def _write_ready(self, handler):
        pass

    def _on_unhandled_exception(self, tb):
        pass

    def _wakeup_ready(self, handler):
        os.read(self.wakeup_read_fd)

    def wakeup(self):
        os.write(self.wakeup_write_fd, b'1')

    def _loop(self, handler):
        select = self.sel.select
        tb = None
        waiting_for_write = True
        with closing(self.sel), non_block(self.input_fd), non_block(self.output_fd), raw_terminal(self.input_fd):
            handler.write_buf.insert(0, b'\033 F\033?1049h
            while self.keep_going:
                has_data_to_write = bool(handler.write_buf)
                if has_data_to_write != waiting_for_write:
                    waiting_for_write = has_data_to_write
                    self.sel.modify(self.output_fd, selectors.EVENT_WRITE if waiting_for_write else 0, self._write_ready)
                events = select()
                for key, mask in events:
                    try:
                        key.data(handler)
                    except Exception:
                        import traceback
                        tb = traceback.format_exc()
                        self.keep_going = False
                        self.return_code = 1
                        break
            if tb is not None:
                self._report_error_loop(tb)

    def _report_error_loop(self, tb):
        raise NotImplementedError('TODO: Implement')
