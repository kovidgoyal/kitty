#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import codecs
import io
import os
import re
import selectors
import signal
import sys
from collections import namedtuple
from contextlib import closing, contextmanager
from functools import partial
from queue import Empty, Queue

from kitty.fast_data_types import (
    close_tty, normal_tty, open_tty, parse_input_from_terminal, raw_tty,
    safe_pipe
)
from kitty.key_encoding import (
    ALT, CTRL, PRESS, RELEASE, REPEAT, SHIFT, C, D, backspace_key,
    decode_key_event, enter_key
)
from kitty.utils import screen_size_function, write_all

from .handler import Handler
from .operations import init_state, reset_state


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


class TermManager:

    def __init__(self):
        self.extra_finalize = None

    def set_state_for_loop(self, set_raw=True):
        if set_raw:
            raw_tty(self.tty_fd, self.original_termios)
        write_all(self.tty_fd, init_state())

    def reset_state_to_original(self):
        normal_tty(self.tty_fd, self.original_termios)
        if self.extra_finalize:
            write_all(self.tty_fd, self.extra_finalize)
        write_all(self.tty_fd, reset_state())

    @contextmanager
    def suspend(self):
        self.reset_state_to_original()
        yield self
        self.set_state_for_loop()

    def __enter__(self):
        self.tty_fd, self.original_termios = open_tty()
        self.set_state_for_loop(set_raw=False)
        return self

    def __exit__(self, *a):
        self.reset_state_to_original()
        close_tty(self.tty_fd, self.original_termios)
        del self.tty_fd, self.original_termios


class SignalManager:

    def __init__(self, on_sigwinch, on_sigterm, on_sigint):
        self.on_sigwinch = on_sigwinch
        self.on_sigterm = on_sigterm
        self.on_sigint = on_sigint

    def __enter__(self):
        for x in ('winch', 'term', 'int'):
            attr = 'on_sig' + x
            handler = getattr(self, attr)
            old_handler = signal.signal(getattr(signal, 'SIG' + x.upper()), handler)
            setattr(self, attr, old_handler)

    def __exit__(self, *a):
        for x in ('winch', 'term', 'int'):
            attr = 'on_sig' + x
            val = getattr(self, attr)
            if val is None:
                val = signal.SIG_DFL
            signal.signal(getattr(signal, 'SIG' + x.upper()), val)


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

    def __init__(self,
                 sanitize_bracketed_paste='[\x03\x04\x0e\x0f\r\x07\x7f\x8d\x8e\x8f\x90\x9b\x9d\x9e\x9f]'):
        self.wakeup_read_fd, self.wakeup_write_fd = safe_pipe()
        # For some reason on macOS the DefaultSelector fails when tty_fd is
        # open('/dev/tty')
        self.sel = s = selectors.PollSelector()
        s.register(self.wakeup_read_fd, selectors.EVENT_READ)
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

    def _read_ready(self, handler, fd):
        if not self.read_allowed:
            return
        try:
            data = os.read(fd, io.DEFAULT_BUFFER_SIZE)
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
            elif chunk:
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

    def _write_ready(self, handler, fd):
        if len(handler.write_buf) > self.iov_limit:
            handler.write_buf[self.iov_limit - 1] = b''.join(handler.write_buf[self.iov_limit - 1:])
            del handler.write_buf[self.iov_limit:]
        sizes = tuple(map(len, handler.write_buf))
        try:
            written = os.writev(fd, handler.write_buf)
        except BlockingIOError:
            return
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

    def _wakeup_ready(self, handler, fd):
        data = os.read(fd, 1024)
        if b'r' in data:
            self._get_screen_size.changed = True
            handler.on_resize(self._get_screen_size())
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

    def _modify_output_selector(self, tty_fd, waiting_for_write):
        events = selectors.EVENT_READ
        if waiting_for_write:
            events |= selectors.EVENT_WRITE
        self.sel.modify(tty_fd, events)

    def loop_impl(self, handler, tty_fd, image_manager=None, waiting_for_write=True):
        read_ready, write_ready, wakeup_ready = self._read_ready, self._write_ready, self._wakeup_ready
        select = self.sel.select
        handler._initialize(self._get_screen_size(), self.quit, self.wakeup, self.start_job, debug, image_manager)
        with handler:
            while True:
                has_data_to_write = bool(handler.write_buf)
                if not has_data_to_write and not self.read_allowed:
                    break
                if has_data_to_write != waiting_for_write:
                    waiting_for_write = has_data_to_write
                    self._modify_output_selector(tty_fd, waiting_for_write)
                for key, mask in select():
                    fd = key.fd
                    if fd == tty_fd:
                        if mask & selectors.EVENT_READ:
                            read_ready(handler, fd)
                        if mask & selectors.EVENT_WRITE:
                            write_ready(handler, fd)
                    else:
                        wakeup_ready(handler, fd)

    def loop(self, handler):
        tb = None
        signal_manager = SignalManager(self._on_sigwinch, self._on_sigterm, self._on_sigint)
        with closing(self.sel), TermManager() as term_manager, signal_manager:
            self.sel.register(term_manager.tty_fd, selectors.EVENT_READ | selectors.EVENT_WRITE)
            self._get_screen_size = screen_size_function(term_manager.tty_fd)
            handler.write_buf = []
            handler._term_manager = term_manager
            image_manager = None
            if handler.image_manager_class is not None:
                image_manager = handler.image_manager_class(handler)
            try:
                self.loop_impl(handler, term_manager.tty_fd, image_manager)
            except Exception:
                import traceback
                tb = traceback.format_exc()
                self.return_code = 1

            term_manager.extra_finalize = b''.join(handler.write_buf).decode('utf-8')
            if tb is not None:
                self._report_error_loop(tb, term_manager)

    def _report_error_loop(self, tb, term_manager):
        handler = UnhandledException(tb)
        handler.write_buf = []
        handler._term_manager = term_manager
        self.loop_impl(handler, term_manager.tty_fd, waiting_for_write=False)
