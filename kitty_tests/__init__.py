#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import io
import os
import select
import shlex
import struct
import sys
import termios
from pty import CHILD, fork
from unittest import TestCase

from kitty.config import finalize_keys, finalize_mouse_mappings
from kitty.fast_data_types import (
    Cursor, HistoryBuf, LineBuf, Screen, get_options, parse_bytes, set_options
)
from kitty.options.parse import merge_result_dicts
from kitty.options.types import Options, defaults
from kitty.types import MouseEvent
from kitty.utils import no_echo, write_all


class Callbacks:

    def __init__(self) -> None:
        self.clear()

    def write(self, data) -> None:
        self.wtcbuf += data

    def title_changed(self, data) -> None:
        self.titlebuf += data

    def icon_changed(self, data) -> None:
        self.iconbuf += data

    def set_dynamic_color(self, code, data) -> None:
        self.colorbuf += data or ''

    def set_color_table_color(self, code, data) -> None:
        self.ctbuf += ''

    def request_capabilities(self, q) -> None:
        from kitty.terminfo import get_capabilities
        for c in get_capabilities(q, None):
            self.write(c.encode('ascii'))

    def use_utf8(self, on) -> None:
        self.iutf8 = on

    def desktop_notify(self, osc_code: int, raw_data: str) -> None:
        self.notifications.append((osc_code, raw_data))

    def open_url(self, url: str, hyperlink_id: int) -> None:
        self.open_urls.append((url, hyperlink_id))

    def clipboard_control(self, data: str, is_partial: bool = False) -> None:
        self.cc_buf.append((data, is_partial))

    def clear(self) -> None:
        self.wtcbuf = b''
        self.iconbuf = self.titlebuf = self.colorbuf = self.ctbuf = ''
        self.iutf8 = True
        self.notifications = []
        self.open_urls = []
        self.cc_buf = []
        self.bell_count = 0

    def on_bell(self) -> None:
        self.bell_count += 1

    def on_activity_since_last_focus(self) -> None:
        pass

    def on_mouse_event(self, event):
        ev = MouseEvent(**event)
        opts = get_options()
        action_def = opts.mousemap.get(ev)
        if not action_def:
            return False
        self.current_mouse_button = ev.button
        for action in opts.alias_map.resolve_aliases(action_def, 'mouse_map'):
            getattr(self, action.func)(*action.args)
        self.current_mouse_button = 0
        return True


def filled_line_buf(ynum=5, xnum=5, cursor=Cursor()):
    ans = LineBuf(ynum, xnum)
    cursor.x = 0
    for i in range(ynum):
        t = (f'{i}') * xnum
        ans.line(i).set_text(t, 0, xnum, cursor)
    return ans


def filled_cursor():
    ans = Cursor()
    ans.bold = ans.italic = ans.reverse = ans.strikethrough = ans.dim = True
    ans.fg = 0x101
    ans.bg = 0x201
    ans.decoration_fg = 0x301
    return ans


def filled_history_buf(ynum=5, xnum=5, cursor=Cursor()):
    lb = filled_line_buf(ynum, xnum, cursor)
    ans = HistoryBuf(ynum, xnum)
    for i in range(ynum):
        ans.push(lb.line(i))
    return ans


class BaseTest(TestCase):

    ae = TestCase.assertEqual
    maxDiff = 2048
    is_ci = os.environ.get('CI') == 'true'

    def set_options(self, options=None):
        final_options = {'scrollback_pager_history_size': 1024, 'click_interval': 0.5}
        if options:
            final_options.update(options)
        options = Options(merge_result_dicts(defaults._asdict(), final_options))
        finalize_keys(options, {})
        finalize_mouse_mappings(options, {})
        set_options(options)
        return options

    def cmd_to_run_python_code(self, code):
        from kitty.constants import kitty_exe
        return [kitty_exe(), '+runpy', code]

    def create_screen(self, cols=5, lines=5, scrollback=5, cell_width=10, cell_height=20, options=None):
        self.set_options(options)
        c = Callbacks()
        s = Screen(c, lines, cols, scrollback, cell_width, cell_height, 0, c)
        return s

    def create_pty(self, argv, cols=80, lines=25, scrollback=100, cell_width=10, cell_height=20, options=None, cwd=None):
        self.set_options(options)
        return PTY(argv, lines, cols, scrollback, cell_width, cell_height, cwd)

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2


class PTY:

    def __init__(self, argv, rows=25, columns=80, scrollback=100, cell_width=10, cell_height=20, cwd=None):
        pid, self.master_fd = fork()
        self.is_child = pid == CHILD
        if self.is_child:
            if cwd:
                os.chdir(cwd)
            if isinstance(argv, str):
                argv = shlex.split(argv)
            with no_echo():
                sys.stdin.readline()
            os.execlp(argv[0], *argv)
        os.set_blocking(self.master_fd, False)
        self.set_window_size(rows=rows, columns=columns)
        new = termios.tcgetattr(self.master_fd)
        new[3] = new[3] & ~termios.ECHO
        termios.tcsetattr(self.master_fd, termios.TCSADRAIN, new)
        self.write_to_child('ready\r\n')
        self.callbacks = Callbacks()
        self.screen = Screen(self.callbacks, rows, columns, scrollback, cell_width, cell_height, 0, self.callbacks)

    def __del__(self):
        if not self.is_child:
            os.close(self.master_fd)
            del self.master_fd

    def write_to_child(self, data):
        write_all(self.master_fd, data)

    def wait_for_input_from_child(self, timeout=10):
        rd = select.select([self.master_fd], [], [], timeout)[0]
        return bool(rd)

    def process_input_from_child(self):
        bytes_read = 0
        while True:
            try:
                data = os.read(self.master_fd, io.DEFAULT_BUFFER_SIZE)
            except (BlockingIOError, OSError):
                data = b''
            if not data:
                break
            bytes_read += len(data)
            parse_bytes(self.screen, data)
        return bytes_read

    def set_window_size(self, rows=25, columns=80, x_pixels=0, y_pixels=0):
        s = struct.pack('HHHH', rows, columns, x_pixels, y_pixels)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, s)

    def screen_contents(self):
        lines = []
        for i in range(self.screen.lines):
            x = str(self.screen.line(i))
            if x:
                lines.append(x)
        return '\n'.join(lines)
