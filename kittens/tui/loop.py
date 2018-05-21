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
from queue import Empty, Queue

from kitty.fast_data_types import parse_input_from_terminal, safe_pipe
from kitty.key_encoding import (
    ALT, CTRL, PRESS, RELEASE, REPEAT, SHIFT, C, D, backspace_key,
    decode_key_event, enter_key
)
from kitty.utils import screen_size_function

from .handler import Handler
from .operations import init_state, reset_state

screen_size = screen_size_function()


def debug(*a, **kw):
    from base64 import standard_b64encode
    buf = io.StringIO()
    kw['file'] = buf
    print(*a, **kw)
    text = buf.getvalue()
    text = b'\x1bP@kitty-print|' + standard_b64encode(text.encode('utf-8')) + b'\x1b\\'
    fobj = getattr(debug, 'fobj', sys.stdout.buffer)
    fobj.write(text)
    if hasattr(fobj, 'flush'):
        fobj.flush()


def write_all(fd, data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    while data:
        n = os.write(fd, data)
        if not n:
            break
        data = data[n:]


class TermManager:

    def __init__(self, input_fd, output_fd):
        self.input_fd = input_fd
        self.output_fd = output_fd
        self.original_fl = fcntl.fcntl(self.input_fd, fcntl.F_GETFL)
        self.extra_finalize = None
        self.isatty = os.isatty(self.input_fd)
        if self.isatty:
            self.original_termios = termios.tcgetattr(self.input_fd)

    def set_state_for_loop(self):
        write_all(self.output_fd, init_state())
        fcntl.fcntl(self.input_fd, fcntl.F_SETFL, self.original_fl | os.O_NONBLOCK)
        if self.isatty:
            tty.setraw(self.input_fd)

    def reset_state_to_original(self):
        if self.isatty:
            termios.tcsetattr(self.input_fd, termios.TCSADRAIN, self.original_termios)
        fcntl.fcntl(self.input_fd, fcntl.F_SETFL, self.original_fl)
        if self.extra_finalize:
            write_all(self.output_fd, self.extra_finalize)
        write_all(self.output_fd, reset_state())

    @contextmanager
    def suspend(self):
        self.reset_state_to_original()
        yield self
        self.set_state_for_loop()

    def __enter__(self):
        self.set_state_for_loop()
        return self

    def __exit__(self, *a):
        self.reset_state_to_original()


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

    def initialize(self):
        self.cmd.clear_screen()
        self.cmd.set_scrolling_region()
        self.cmd.set_cursor_visible(True)
        self.cmd.set_default_colors()
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
        self.input_fd = sys.stdin.fileno() if input_fd is None else input_fd
        self.output_fd = sys.stdout.fileno() if output_fd is None else output_fd
        self.wakeup_read_fd, self.wakeup_write_fd = safe_pipe()
        # For some reason on macOS the DefaultSelector fails when input_fd is
        # open('/dev/tty')
        self.sel = s = selectors.PollSelector()
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
            self.iov_limit = max(os.sysconf('SC_IOV_MAX') - 1, 255)
        except Exception:
            self.iov_limit = 255
        self.parse_input_from_terminal = partial(parse_input_from_terminal, self._on_text, self._on_dcs, self._on_csi, self._on_osc, self._on_pm, self._on_apc)
        self.ebs_pat = re.compile('([\177\r\x03\x04])')
        self.in_bracketed_paste = False
        self.sanitize_bracketed_paste = bool(sanitize_bracketed_paste)
        if self.sanitize_bracketed_paste:
            self.sanitize_ibp_pat = re.compile(sanitize_bracketed_paste)
        self.jobs_queue = Queue()

    def start_job(self, job_id, func, *args, **kw):
        from threading import Thread
        t = Thread(target=partial(self._run_job, job_id, func), args=args, kwargs=kw, name='LoopJob')
        t.daemon = True
        t.start()

    def _run_job(self, job_id, func, *args, **kw):
        try:
            result = func(*args, **kw)
        except Exception as err:
            import traceback
            entry = {'id': job_id, 'exception': err, 'tb': traceback.format_exc()}
        else:
            entry = {'id': job_id, 'result': result}
        self.jobs_queue.put(entry)
        self._wakeup_write(b'j')

    def _read_ready(self, handler):
        if not self.read_allowed:
            return
        try:
            data = os.read(self.input_fd, io.DEFAULT_BUFFER_SIZE)
        except BlockingIOError:
            return
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
        if dcs.startswith('@kitty-cmd'):
            import json
            self.handler.on_kitty_cmd_response(json.loads(dcs[len('@kitty-cmd'):]))

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
        m = re.match(r'(\d+);', osc)
        if m is not None:
            code = int(m.group(1))
            rest = osc[m.end():]
            if code == 52:
                where, rest = rest.partition(';')[::2]
                from_primary = 'p' in where
                from base64 import standard_b64decode
                self.handler.on_clipboard_response(standard_b64decode(rest).decode('utf-8'), from_primary)

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
        elif apc.startswith('G'):
            if self.handler.image_manager is not None:
                self.handler.image_manager.handle_response(apc)

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
        if b'j' in data:
            while True:
                try:
                    entry = self.jobs_queue.get_nowait()
                except Empty:
                    break
                else:
                    job_id = entry.pop('id')
                    handler.on_job_done(job_id, entry)
        if b'1' in data:
            handler.on_wakeup()

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
        with closing(self.sel), TermManager(self.input_fd, self.output_fd) as term_manager:
            signal.signal(signal.SIGWINCH, self._on_sigwinch)
            signal.signal(signal.SIGTERM, self._on_sigterm)
            signal.signal(signal.SIGINT, self._on_sigint)
            handler.write_buf = []
            handler._term_manager = term_manager
            image_manager = None
            if handler.image_manager_class is not None:
                image_manager = handler.image_manager_class(handler)
            keep_going = True
            try:
                handler._initialize(screen_size(), self.quit, self.wakeup, self.start_job, debug, image_manager)
                with handler:
                    while keep_going:
                        has_data_to_write = bool(handler.write_buf)
                        if not has_data_to_write and not self.read_allowed:
                            break
                        if has_data_to_write != waiting_for_write:
                            waiting_for_write = has_data_to_write
                            self._modify_output_selector(waiting_for_write)
                        events = select()
                        for key, mask in events:
                            key.data(handler)
            except Exception:
                import traceback
                tb = traceback.format_exc()
                self.return_code = 1
                keep_going = False

            term_manager.extra_finalize = b''.join(handler.write_buf).decode('utf-8')

            if tb is not None:
                self._report_error_loop(tb, term_manager)

    def _report_error_loop(self, tb, term_manager):
        select = self.sel.select
        waiting_for_write = False
        handler = UnhandledException(tb)
        handler.write_buf = []
        handler._term_manager = term_manager
        handler._initialize(screen_size(), self.quit, self.wakeup, self.start_job, debug)
        with handler:
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
