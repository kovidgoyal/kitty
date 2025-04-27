#!/usr/bin/env python
# License: GPL v3 Copyright: 2018, Kovid Goyal <kovid at kovidgoyal.net>

import asyncio
import codecs
import io
import os
import re
import selectors
import signal
import sys
import termios
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from enum import Enum, IntFlag, auto
from functools import partial
from typing import Any, NamedTuple

from kitty.constants import is_macos
from kitty.fast_data_types import FILE_TRANSFER_CODE, close_tty, normal_tty, open_tty, parse_input_from_terminal, raw_tty
from kitty.key_encoding import ALT, CTRL, SHIFT, backspace_key, decode_key_event, enter_key
from kitty.typing_compat import ImageManagerType, KeyEventType, Protocol
from kitty.utils import ScreenSize, ScreenSizeGetter, screen_size_function, write_all

from .handler import Handler
from .operations import MouseTracking, init_state, reset_state


class BinaryWrite(Protocol):

    def write(self, data: bytes) -> None:
        pass

    def flush(self) -> None:
        pass


def debug_write(*a: Any, **kw: Any) -> None:
    from base64 import standard_b64encode
    fobj = kw.pop('file', sys.stderr.buffer)
    buf = io.StringIO()
    kw['file'] = buf
    print(*a, **kw)
    stext = buf.getvalue()
    for i in range(0, len(stext), 256):
        chunk = stext[i:i + 256]
        text = b'\x1bP@kitty-print|' + standard_b64encode(chunk.encode('utf-8')) + b'\x1b\\'
        fobj.write(text)
    fobj.flush()


class Debug:

    fobj: BinaryWrite | None = None

    def __call__(self, *a: Any, **kw: Any) -> None:
        kw['file'] = self.fobj or sys.stdout.buffer
        debug_write(*a, **kw)


debug = Debug()
ftc_code = str(FILE_TRANSFER_CODE)


class TermManager:

    def __init__(
        self, optional_actions: int = termios.TCSANOW, use_alternate_screen: bool = True,
        mouse_tracking: MouseTracking = MouseTracking.none
    ) -> None:
        self.extra_finalize: str | None = None
        self.optional_actions = optional_actions
        self.use_alternate_screen = use_alternate_screen
        self.mouse_tracking = mouse_tracking

    def set_state_for_loop(self, set_raw: bool = True) -> None:
        if set_raw:
            raw_tty(self.tty_fd, self.original_termios)
        write_all(self.tty_fd, init_state(self.use_alternate_screen, self.mouse_tracking))

    def reset_state_to_original(self) -> None:
        normal_tty(self.tty_fd, self.original_termios)
        if self.extra_finalize:
            write_all(self.tty_fd, self.extra_finalize)
        write_all(self.tty_fd, reset_state(self.use_alternate_screen))

    @contextmanager
    def suspend(self) -> Generator['TermManager', None, None]:
        self.reset_state_to_original()
        yield self
        self.set_state_for_loop()

    def __enter__(self) -> 'TermManager':
        self.tty_fd, self.original_termios = open_tty(False, self.optional_actions)
        self.set_state_for_loop(set_raw=False)
        return self

    def __exit__(self, *a: object) -> None:
        with suppress(Exception):
            self.reset_state_to_original()
            close_tty(self.tty_fd, self.original_termios)
            del self.tty_fd, self.original_termios


class MouseButton(IntFlag):
    NONE, LEFT, MIDDLE, RIGHT, FOURTH, FIFTH, SIXTH, SEVENTH = 0, 1, 2, 4, 8, 16, 32, 64
    WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT = -1, -2, -4, -8


bmap = MouseButton.LEFT, MouseButton.MIDDLE, MouseButton.RIGHT
ebmap = MouseButton.FOURTH, MouseButton.FIFTH, MouseButton.SIXTH, MouseButton.SEVENTH
wbmap = MouseButton.WHEEL_UP, MouseButton.WHEEL_DOWN, MouseButton.WHEEL_LEFT, MouseButton.WHEEL_RIGHT
SHIFT_INDICATOR = 1 << 2
ALT_INDICATOR = 1 << 3
CTRL_INDICATOR = 1 << 4
MOTION_INDICATOR = 1 << 5


class EventType(Enum):
    PRESS = auto()
    RELEASE = auto()
    MOVE = auto()


class MouseEvent(NamedTuple):
    cell_x: int
    cell_y: int
    pixel_x: int
    pixel_y: int
    type: EventType
    buttons: MouseButton
    mods: int


def pixel_to_cell(px: int, length: int, cell_length: int) -> int:
    px = max(0, min(px, length - 1))
    return px // cell_length


def decode_sgr_mouse(text: str, screen_size: ScreenSize) -> MouseEvent:
    cb_, x_, y_ = text.split(';')
    m, y_ = y_[-1], y_[:-1]
    cb, x, y = map(int, (cb_, x_, y_))
    typ = EventType.RELEASE if m == 'm' else (EventType.MOVE if cb & MOTION_INDICATOR else EventType.PRESS)
    buttons: MouseButton = MouseButton.NONE
    cb3 = cb & 3
    if cb >= 128:
        buttons |= ebmap[cb3]
    elif cb >= 64:
        buttons |= wbmap[cb3]
    elif cb3 < 3:
        buttons |= bmap[cb3]
    mods = 0
    if cb & SHIFT_INDICATOR:
        mods |= SHIFT
    if cb & ALT_INDICATOR:
        mods |= ALT
    if cb & CTRL_INDICATOR:
        mods |= CTRL
    return MouseEvent(
        pixel_to_cell(x, screen_size.width, screen_size.cell_width), pixel_to_cell(y, screen_size.height, screen_size.cell_height),
        x, y, typ, buttons, mods
    )


class UnhandledException(Handler):

    def __init__(self, tb: str) -> None:
        self.tb = tb

    def initialize(self) -> None:
        self.cmd.clear_screen()
        self.cmd.set_scrolling_region()
        self.cmd.set_cursor_visible(True)
        self.cmd.set_default_colors()
        self.write(self.tb.replace('\n', '\r\n'))
        self.write('\r\n')
        self.write('Press Enter to quit')

    def on_key(self, key_event: KeyEventType) -> None:
        if key_event.key == 'ENTER':
            self.quit_loop(1)

    def on_interrupt(self) -> None:
        self.quit_loop(1)
    on_eot = on_term = on_interrupt


class SignalManager:

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_winch: Callable[[], None],
        on_interrupt: Callable[[], None],
        on_term: Callable[[], None],
        on_hup: Callable[[], None],
    ) -> None:
        self.asyncio_loop = loop
        self.on_winch, self.on_interrupt, self.on_term = on_winch, on_interrupt, on_term
        self.on_hup = on_hup

    def __enter__(self) -> None:
        self.asyncio_loop.add_signal_handler(signal.SIGWINCH, self.on_winch)
        self.asyncio_loop.add_signal_handler(signal.SIGINT, self.on_interrupt)
        self.asyncio_loop.add_signal_handler(signal.SIGTERM, self.on_term)
        self.asyncio_loop.add_signal_handler(signal.SIGHUP, self.on_hup)

    def __exit__(self, *a: Any) -> None:
        tuple(map(self.asyncio_loop.remove_signal_handler, (
            signal.SIGWINCH, signal.SIGINT, signal.SIGTERM, signal.SIGHUP)))


sanitize_bracketed_paste: str = '[\x03\x04\x0e\x0f\r\x07\x7f\x8d\x8e\x8f\x90\x9b\x9d\x9e\x9f]'


class Loop:

    def __init__(
        self,
        sanitize_bracketed_paste: str = sanitize_bracketed_paste,
        optional_actions: int = termios.TCSADRAIN
    ):
        if is_macos:
            # On macOS PTY devices are not supported by the KqueueSelector and
            # the PollSelector is broken, causes 100% CPU usage
            self.asyncio_loop: asyncio.AbstractEventLoop = asyncio.SelectorEventLoop(selectors.SelectSelector())
            asyncio.set_event_loop(self.asyncio_loop)
        else:
            self.asyncio_loop = asyncio.get_event_loop()
        self.return_code = 0
        self.overlay_ready_reported = False
        self.optional_actions = optional_actions
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

    def _read_ready(self, handler: Handler, fd: int) -> None:
        try:
            bdata = os.read(fd, io.DEFAULT_BUFFER_SIZE)
        except BlockingIOError:
            return
        if not bdata:
            handler.terminal_io_ended = True
            self.quit(1)
            return
        data = self.decoder.decode(bdata)
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

    # terminal input callbacks {{{
    def _on_text(self, text: str) -> None:
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

    def _on_dcs(self, dcs: str) -> None:
        if dcs.startswith('@kitty-cmd'):
            import json
            self.handler.on_kitty_cmd_response(json.loads(dcs[len('@kitty-cmd'):]))
        elif dcs.startswith('1+r'):
            from binascii import unhexlify
            vals = dcs[3:].split(';')
            for q in vals:
                parts = q.split('=', 1)
                try:
                    name, val = parts[0], unhexlify(parts[1]).decode('utf-8', 'replace')
                except Exception:
                    continue
                self.handler.on_capability_response(name, val)

    def _on_csi(self, csi: str) -> None:
        q = csi[-1]
        if q in 'mM':
            if csi.startswith('<'):
                # SGR mouse event
                try:
                    ev = decode_sgr_mouse(csi[1:], self.handler.screen_size)
                except Exception:
                    pass
                else:
                    self.handler.on_mouse_event(ev)
        elif q in 'u~ABCDEHFPQRS':
            if csi == '200~':
                self.in_bracketed_paste = True
                return
            elif csi == '201~':
                self.in_bracketed_paste = False
                return
            try:
                k = decode_key_event(csi[:-1], q)
            except Exception:
                pass
            else:
                if not self.handler.perform_default_key_action(k):
                    self.handler.on_key_event(k)

    def _on_pm(self, pm: str) -> None:
        pass

    def _on_osc(self, osc: str) -> None:
        idx = osc.find(';')
        if idx <= 0:
            return
        q = osc[:idx]
        if q == '52':
            widx = osc.find(';', idx + 1)
            if widx < idx:
                from_primary = osc.find('p', idx + 1) > -1
                payload = ''
            else:
                from base64 import standard_b64decode
                from_primary = osc.find('p', idx+1, widx) > -1
                data = memoryview(osc.encode('ascii'))
                payload = standard_b64decode(data[widx+1:]).decode('utf-8')
            self.handler.on_clipboard_response(payload, from_primary)
        elif q == ftc_code:
            from kitty.file_transmission import FileTransmissionCommand
            data = memoryview(osc.encode('ascii'))
            self.handler.on_file_transfer_response(FileTransmissionCommand.deserialize(data[idx+1:]))

    def _on_apc(self, apc: str) -> None:
        if apc.startswith('G'):
            if self.handler.image_manager is not None:
                self.handler.image_manager.handle_response(apc)
    # }}}

    @property
    def total_pending_bytes_to_write(self) -> int:
        return sum(map(len, self.write_buf))

    def _write_ready(self, handler: Handler, fd: int) -> None:
        if len(self.write_buf) > self.iov_limit:
            self.write_buf[self.iov_limit - 1] = b''.join(self.write_buf[self.iov_limit - 1:])
            del self.write_buf[self.iov_limit:]
        total_size = self.total_pending_bytes_to_write
        if total_size:
            try:
                written = os.writev(fd, self.write_buf)
            except BlockingIOError:
                return
            if not written:
                handler.terminal_io_ended = True
                self.quit(1)
                return
        else:
            written = 0
        if written >= total_size:
            self.write_buf: list[bytes] = []
            self.asyncio_loop.remove_writer(fd)
            self.waiting_for_writes = False
            handler.on_writing_finished()
        else:
            consumed = 0
            for i, buf in enumerate(self.write_buf):
                if not written:
                    break
                if len(buf) <= written:
                    written -= len(buf)
                    consumed += 1
                    continue
                self.write_buf[i] = buf[written:]
                break
            del self.write_buf[:consumed]

    def quit(self, return_code: int | None = None) -> None:
        if return_code is not None:
            self.return_code = return_code
        self.asyncio_loop.stop()

    def loop_impl(self, handler: Handler, term_manager: TermManager, image_manager: ImageManagerType | None = None) -> str | None:
        self.write_buf = []
        tty_fd = term_manager.tty_fd
        tb = None
        self.waiting_for_writes = True

        def schedule_write(data: bytes) -> None:
            self.write_buf.append(data)
            if not self.waiting_for_writes:
                self.asyncio_loop.add_writer(tty_fd, self._write_ready, handler, tty_fd)
                self.waiting_for_writes = True

        def handle_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            nonlocal tb
            loop.stop()
            tb = context['message']
            exc = context.get('exception')
            if exc is not None:
                import traceback
                tb += '\n' + ''.join(traceback.format_exception(exc.__class__, exc, exc.__traceback__))

        self.asyncio_loop.set_exception_handler(handle_exception)
        handler._initialize(self._get_screen_size(), term_manager, schedule_write, self, debug, image_manager)
        with handler:
            if handler.overlay_ready_report_needed:
                handler.cmd.overlay_ready()
            self.asyncio_loop.add_reader(
                    tty_fd, self._read_ready, handler, tty_fd)
            self.asyncio_loop.add_writer(
                    tty_fd, self._write_ready, handler, tty_fd)
            self.asyncio_loop.run_forever()
            self.asyncio_loop.remove_reader(tty_fd)
            if self.waiting_for_writes:
                self.asyncio_loop.remove_writer(tty_fd)
        return tb

    def loop(self, handler: Handler) -> None:
        tb: str | None = None

        def _on_sigwinch() -> None:
            self._get_screen_size.changed = True
            handler.screen_size = self._get_screen_size()
            handler.on_resize(handler.screen_size)

        signal_manager = SignalManager(self.asyncio_loop, _on_sigwinch, handler.on_interrupt, handler.on_term, handler.on_hup)
        with TermManager(self.optional_actions, handler.use_alternate_screen, handler.mouse_tracking) as term_manager, signal_manager:
            self._get_screen_size: ScreenSizeGetter = screen_size_function(term_manager.tty_fd)
            image_manager = None
            if handler.image_manager_class is not None:
                image_manager = handler.image_manager_class(handler)
            try:
                tb = self.loop_impl(handler, term_manager, image_manager)
            except Exception:
                import traceback
                tb = traceback.format_exc()

            term_manager.extra_finalize = b''.join(self.write_buf).decode('utf-8')
            if tb is not None:
                report_overlay_ready = handler.overlay_ready_report_needed and not self.overlay_ready_reported
                self.return_code = 1
                if not handler.terminal_io_ended:
                    self._report_error_loop(tb, term_manager, report_overlay_ready)

    def _report_error_loop(self, tb: str, term_manager: TermManager, overlay_ready_report_needed: bool) -> None:
        handler = UnhandledException(tb)
        handler.overlay_ready_report_needed = overlay_ready_report_needed
        self.loop_impl(handler, term_manager)
