#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import fcntl
import io
import os
import re
import selectors
import signal
import sys
import termios
import tty
from collections import namedtuple
from contextlib import closing, contextmanager
from functools import partial

from kitty.fast_data_types import parse_input_from_terminal
from kitty.icat import screen_size
from kitty.key_encoding import (
    ALT, CTRL, PRESS, RELEASE, REPEAT, SHIFT, C, D, backspace_key,
    decode_key_event, enter_key
)

from .handler import Handler
from .operations import init_state, reset_state, clear_screen


def log(*a, **kw):
    fd = getattr(log, 'fd', None)
    if fd is None:
        fd = log.fd = open('/tmp/kitten-debug', 'w')
    kw['file'] = fd
    print(*a, **kw)
    fd.flush()


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
    if isinstance(data, str):
        data = data.encode('utf-8')
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


LEFT, MIDDLE, RIGHT, FOURTH, FIFTH = 1, 2, 4, 8, 16
DRAG = REPEAT
MouseEvent = namedtuple('MouseEvent', 'x y type buttons mods')
bmap = {0: LEFT, 1: MIDDLE, 2: RIGHT}
MOTION_INDICATOR = 1 << 5
EXTRA_BUTTON_INDICATOR = 1 << 6
SHIFT_INDICATOR = 1 << 2
ALT_INDICATOR = 1 << 3
CTRL_INDICATOR = 1 << 4


def decode_sgr_mouse(text):
    cb, x, y = text.split(';')
    m, y = y[-1], y[:-1]
    cb, x, y = map(int, (cb, x, y))
    typ = RELEASE if m == 'm' else (DRAG if cb & MOTION_INDICATOR else PRESS)
    buttons = 0
    cb3 = cb & 3
    if cb3 != 3:
        if cb & EXTRA_BUTTON_INDICATOR:
            buttons |= FIFTH if cb3 & 1 else FOURTH
        else:
            buttons |= bmap[cb3]
    mods = 0
    if cb & SHIFT_INDICATOR:
        mods |= SHIFT
    if cb & ALT_INDICATOR:
        mods |= ALT
    if cb & CTRL_INDICATOR:
        mods |= CTRL
    return MouseEvent(x, y, typ, buttons, mods)


class UnhandledException(Handler):

    def __init__(self, tb):
        self.tb = tb

    def initialize(self, screen_size, quit_loop, wakeup):
        Handler.initialize(self, screen_size, quit_loop, wakeup)
        self.write(clear_screen())
        self.write(self.tb.replace('\n', '\r\n'))
        self.write('\r\n')
        self.write('Press the Enter key to quit')

    def on_key(self, key_event):
        if key_event is enter_key:
            self.quit_loop(1)

    def on_interrupt(self):
        self.quit_loop(1)

    def on_eot(self):
        self.quit_loop(1)


class Loop:

    def __init__(self, input_fd=None, output_fd=None,
                 sanitize_bracketed_paste='[\x03\x04\x0e\x0f\r\x07\x7f\x8d\x8e\x8f\x90\x9b\x9d\x9e\x9f]'):
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
        self.decoder = codecs.getincrementaldecoder('utf-8')('ignore')
        try:
            self.iov_limit = os.sysconf('SC_IOV_MAX') - 1
        except Exception:
            self.iov_limit = 255
        self.parse_input_from_terminal = partial(parse_input_from_terminal, self._on_text, self._on_dcs, self._on_csi, self._on_osc, self._on_pm, self._on_apc)
        self.ebs_pat = re.compile('([\177\r\x03\x04])')
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
        except Exception:
            self.read_buf = ''
            raise
        finally:
            del self.handler

    def _on_text(self, text):
        if self.in_bracketed_paste and self.sanitize_bracketed_paste:
            text = self.sanitize_ibp_pat.sub('', text)

        for chunk in self.ebs_pat.split(text):
            if len(chunk) == 1:
                if chunk == '\r':
                    self.handler.on_key(enter_key)
                elif chunk == '\177':
                    self.handler.on_key(backspace_key)
                elif chunk == '\x03':
                    self.handler.on_interrupt()
                elif chunk == '\x04':
                    self.handler.on_eot()
                else:
                    self.handler.on_text(chunk, self.in_bracketed_paste)
            else:
                self.handler.on_text(chunk, self.in_bracketed_paste)

    def _on_dcs(self, dcs):
        pass

    def _on_csi(self, csi):
        q = csi[-1]
        if q in 'mM':
            if csi.startswith('<'):
                # SGR mouse event
                try:
                    ev = decode_sgr_mouse(csi[1:])
                except Exception:
                    pass
                else:
                    self.handler.on_mouse(ev)
        elif q == '~':
            if csi == '200~':
                self.in_bracketed_paste = True
            elif csi == '201~':
                self.in_bracketed_paste = False

    def _on_pm(self, pm):
        pass

    def _on_osc(self, osc):
        pass

    def _on_apc(self, apc):
        if apc.startswith('K'):
            try:
                k = decode_key_event(apc)
            except Exception:
                pass
            else:
                if k.mods is CTRL and k.type is not RELEASE:
                    if k.key is C:
                        self.handler.on_interrupt()
                        return
                    if k.key is D:
                        self.handler.on_eot()
                        return
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

    def _wakeup_ready(self, handler):
        data = os.read(self.wakeup_read_fd, 1024)
        if b'r' in data:
            screen_size.changed = True
            handler.on_resize(screen_size())
        if b't' in data:
            handler.on_term()
        if b'i' in data:
            handler.on_interrupt()

    def _wakeup_write(self, val):
        while not os.write(self.wakeup_write_fd, val):
            pass

    def _on_sigwinch(self, signum, frame):
        self._wakeup_write(b'r')

    def _on_sigterm(self, signum, frame):
        self._wakeup_write(b't')

    def _on_sigint(self, signum, frame):
        self._wakeup_write(b'i')

    def quit(self, return_code=None):
        self.read_allowed = False
        if return_code is not None:
            self.return_code = return_code

    def wakeup(self):
        self._wakeup_write(b'1')

    def _modify_output_selector(self, waiting_for_write):
        if waiting_for_write:
            try:
                self.sel.register(self.output_fd, selectors.EVENT_WRITE, self._write_ready)
            except KeyError:
                pass
        else:
            try:
                self.sel.unregister(self.output_fd)
            except KeyError:
                pass

    def loop(self, handler):
        select = self.sel.select
        tb = None
        waiting_for_write = True
        with closing(self.sel), sanitize_term(self.output_fd), non_block(self.input_fd), non_block(self.output_fd), raw_terminal(self.input_fd):
            signal.signal(signal.SIGWINCH, self._on_sigwinch)
            signal.signal(signal.SIGTERM, self._on_sigterm)
            signal.signal(signal.SIGINT, self._on_sigint)
            handler.write_buf = []
            keep_going = True
            try:
                handler.initialize(screen_size(), self.quit, self.wakeup)
            except Exception:
                import traceback
                tb = traceback.format_exc()
                self.return_code = 1
                keep_going = False
            while keep_going:
                has_data_to_write = bool(handler.write_buf)
                if not has_data_to_write and not self.read_allowed:
                    break
                if has_data_to_write != waiting_for_write:
                    waiting_for_write = has_data_to_write
                    self._modify_output_selector(waiting_for_write)
                events = select()
                for key, mask in events:
                    try:
                        key.data(handler)
                    except Exception:
                        import traceback
                        tb = traceback.format_exc()
                        self.return_code = 1
                        keep_going = False
                        break
            if tb is not None:
                self._report_error_loop(tb)

    def _report_error_loop(self, tb):
        select = self.sel.select
        waiting_for_write = False
        handler = UnhandledException(tb)
        handler.write_buf = []
        handler.initialize(screen_size(), self.quit, self.wakeup)
        while True:
            has_data_to_write = bool(handler.write_buf)
            if not has_data_to_write and not self.read_allowed:
                break
            if has_data_to_write != waiting_for_write:
                waiting_for_write = has_data_to_write
                self._modify_output_selector(waiting_for_write)
            events = select()
            for key, mask in events:
                key.data(handler)
