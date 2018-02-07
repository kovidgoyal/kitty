#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import fcntl
import io
import os
import re
import selectors
import sys
import termios
import tty
from contextlib import closing, contextmanager
from functools import partial

from kitty.fast_data_types import parse_input_from_terminal
from kitty.key_encoding import decode_key_event, enter_key, backspace_key

from .operations import init_state, reset_state


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


def write_all(fd, data):
    while data:
        n = os.write(fd, data)
        if not n:
            break
        data = data[n:]


@contextmanager
def sanitize_term(output_fd):
    write_all(output_fd, init_state())
    yield
    write_all(output_fd, reset_state())


class Loop:

    def __init__(self, input_fd=None, output_fd=None, sanitize_bracketed_paste='[\x0e\x0f\r\x07\x7f\x8d\x8e\x8f\x90\x9b\x9d\x9e\x9f]'):
        self.input_fd = input_fd or sys.stdin.fileno()
        self.output_fd = output_fd or sys.stdout.fileno()
        self.wakeup_read_fd, self.wakeup_write_fd = os.pipe()
        self.sel = s = selectors.DefaultSelector()
        s.register(self.input_fd, selectors.EVENT_READ, self._read_ready)
        s.register(
            self.wakeup_read_fd, selectors.EVENT_READ, self._wakeup_ready
        )
        s.register(self.output_fd, selectors.EVENT_WRITE, self._write_ready)
        self.return_code = 0
        self.read_allowed = True
        self.read_buf = ''
        self.decoder = codecs.IncrementalDecoder(errors='ignore')
        try:
            self.iov_limit = os.sysconf('SC_IOV_MAX') - 1
        except Exception:
            self.iov_limit = 255
        self.parse_input_from_terminal = partial(parse_input_from_terminal, self.on_text, self.on_dcs, self.on_csi, self.on_osc, self.on_pm, self.on_apc)
        self.ebs_pat = re.compile('([\177\r])')
        self.in_bracketed_paste = False
        self.sanitize_bracketed_paste = bool(sanitize_bracketed_paste)
        if self.sanitize_bracketed_paste:
            self.sanitize_ibp_pat = re.compile(sanitize_bracketed_paste)

    def _read_ready(self, handler):
        if not self.read_allowed:
            return
        data = os.read(self.input_fd, io.DEFAULT_BUFFER_SIZE)
        if not data:
            raise EOFError('The input stream is closed')
        data = self.decoder.decode(data)
        if self.read_buf:
            data = self.read_buf + data
        self.read_buf = data
        self.handler = handler
        try:
            self.read_buf = self.parse_input_from_terminal(self.read_buf, self.in_bracketed_paste)
        finally:
            del self.handler

    def on_text(self, text):
        if self.in_bracketed_paste and self.sanitize_bracketed_paste:
            text = self.sanitize_ibp_pat.sub('', text)

        for chunk in self.ebs_pat.split(text):
            if chunk == '\r':
                self.handler.on_key(enter_key)
            elif chunk == '\177':
                self.handler.on_key(backspace_key)
            else:
                self.handler.on_text(chunk, self.in_bracketed_paste)

    def on_dcs(self, dcs):
        pass

    def on_csi(self, csi):
        q = csi[-1]
        if q in 'mM':
            pass
        elif q == '~':
            if csi == '200~':
                self.in_bracketed_paste = True
            elif csi == '201~':
                self.in_bracketed_paste = False

    def on_pm(self, pm):
        pass

    def on_apc(self, apc):
        if apc.startswith('K'):
            try:
                k = decode_key_event(apc)
            except Exception:
                pass
            else:
                self.handler.on_key(k)

    def _write_ready(self, handler):
        if len(handler.write_buf) > self.iov_limit:
            handler.write_buf[self.iov_limit - 1] = b''.join(handler.write_buf[self.iov_limit - 1:])
            del handler.write_buf[self.iov_limit:]
        sizes = tuple(map(len, handler.write_buf))
        written = os.writev(self.output_fd, handler.write_buf)
        if not written:
            raise EOFError('The output stream is closed')
        if written >= sum(sizes):
            handler.write_buf = []
        else:
            consumed = 0
            for i, buf in enumerate(handler.write_buf):
                if not written:
                    break
                if len(buf) <= written:
                    written -= len(buf)
                    consumed += 1
                    continue
                handler.write_buf[i] = buf[written:]
                break
            del handler.write_buf[:consumed]

    def _on_unhandled_exception(self, tb):
        pass

    def _wakeup_ready(self, handler):
        os.read(self.wakeup_read_fd)

    def wakeup(self):
        os.write(self.wakeup_write_fd, b'1')

    def quit(self, return_code=None):
        self.read_allowed = False
        if return_code is not None:
            self.return_code = return_code

    def _loop(self, handler):
        select = self.sel.select
        tb = None
        waiting_for_write = True
        with closing(self.sel), sanitize_term(self.output_fd), non_block(self.input_fd), non_block(self.output_fd), raw_terminal(self.input_fd):
            while True:
                has_data_to_write = bool(handler.write_buf)
                if not has_data_to_write and not self.read_allowed:
                    break
                if has_data_to_write != waiting_for_write:
                    waiting_for_write = has_data_to_write
                    self.sel.modify(
                        self.output_fd, selectors.EVENT_WRITE
                        if waiting_for_write else 0, self._write_ready
                    )
                events = select()
                for key, mask in events:
                    try:
                        key.data(handler)
                    except Exception:
                        import traceback
                        tb = traceback.format_exc()
                        self.return_code = 1
                        break
            if tb is not None:
                self._report_error_loop(tb)

    def _report_error_loop(self, tb):
        raise NotImplementedError('TODO: Implement')
