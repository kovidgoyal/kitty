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
import time
from pty import CHILD, fork
from unittest import TestCase

from kitty.config import finalize_keys, finalize_mouse_mappings
from kitty.fast_data_types import (
    Cursor, HistoryBuf, LineBuf, Screen, get_options, parse_bytes, set_options
)
from kitty.options.parse import merge_result_dicts
from kitty.options.types import Options, defaults
from kitty.types import MouseEvent
from kitty.utils import read_screen_size
from kitty.window import process_remote_print, process_title_from_child


class Callbacks:

    def __init__(self, pty=None) -> None:
        self.clear()
        self.pty = pty

    def write(self, data) -> None:
        self.wtcbuf += data

    def title_changed(self, data, is_base64=False) -> None:
        self.titlebuf.append(process_title_from_child(data, is_base64))

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
        self.iconbuf = self.colorbuf = self.ctbuf = ''
        self.titlebuf = []
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

    def handle_remote_print(self, msg):
        text = process_remote_print(msg)
        print(text, file=sys.__stderr__)

    def handle_remote_ssh(self, msg):
        from kittens.ssh.main import get_ssh_data
        if self.pty:
            for line in get_ssh_data(msg):
                self.pty.write_to_child(line)

    def handle_remote_echo(self, msg):
        from base64 import standard_b64decode
        if self.pty:
            data = standard_b64decode(msg)
            self.pty.write_to_child(data)


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

    def create_pty(self, argv, cols=80, lines=25, scrollback=100, cell_width=10, cell_height=20, options=None, cwd=None, env=None):
        self.set_options(options)
        return PTY(argv, lines, cols, scrollback, cell_width, cell_height, cwd, env)

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2


class PTY:

    def __init__(self, argv, rows=25, columns=80, scrollback=100, cell_width=10, cell_height=20, cwd=None, env=None):
        if isinstance(argv, str):
            argv = shlex.split(argv)
        pid, self.master_fd = fork()
        self.is_child = pid == CHILD
        self.write_buf = b''
        if self.is_child:
            while read_screen_size().width != columns * cell_width:
                time.sleep(0.01)
            if cwd:
                os.chdir(cwd)
            os.execvpe(argv[0], argv, env or os.environ)
        os.set_blocking(self.master_fd, False)
        self.cell_width = cell_width
        self.cell_height = cell_height
        self.set_window_size(rows=rows, columns=columns)
        self.callbacks = Callbacks(self)
        self.screen = Screen(self.callbacks, rows, columns, scrollback, cell_width, cell_height, 0, self.callbacks)
        self.received_bytes = b''

    def __del__(self):
        if not self.is_child:
            fd = self.master_fd
            del self.master_fd
            os.close(fd)

    def write_to_child(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.write_buf += data

    def send_cmd_to_child(self, cmd):
        self.write_to_child(cmd + '\r')

    def process_input_from_child(self, timeout=10):
        rd, wd, err = select.select([self.master_fd], [self.master_fd] if self.write_buf else [], [self.master_fd], timeout)
        if err:
            raise OSError('master_fd is in error condition')
        while wd:
            try:
                n = os.write(self.master_fd, self.write_buf)
            except (BlockingIOError, OSError):
                n = 0
            if not n:
                break
            self.write_buf = self.write_buf[n:]

        bytes_read = 0
        while rd:
            try:
                data = os.read(self.master_fd, io.DEFAULT_BUFFER_SIZE)
            except (BlockingIOError, OSError):
                data = b''
            if not data:
                break
            bytes_read += len(data)
            self.received_bytes += data
            parse_bytes(self.screen, data)
        return bytes_read

    def wait_till(self, q, timeout=10):
        end_time = time.monotonic() + timeout
        while not q() and time.monotonic() <= end_time:
            self.process_input_from_child(timeout=max(0, end_time - time.monotonic()))
        if not q():
            raise TimeoutError(f'The condition was not met. Screen contents: \n {repr(self.screen_contents())}')

    def set_window_size(self, rows=25, columns=80):
        if hasattr(self, 'screen'):
            self.screen.resize(rows, columns)
        x_pixels = columns * self.cell_width
        y_pixels = rows * self.cell_height
        s = struct.pack('HHHH', rows, columns, x_pixels, y_pixels)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, s)

    def screen_contents(self):
        lines = []
        for i in range(self.screen.lines):
            x = str(self.screen.line(i))
            if x:
                lines.append(x)
        return '\n'.join(lines)

    def last_cmd_output(self, as_ansi=False, add_wrap_markers=False):
        from kitty.window import cmd_output
        return cmd_output(self.screen, as_ansi=as_ansi, add_wrap_markers=add_wrap_markers)
