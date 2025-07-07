#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import io
import os
import select
import shlex
import shutil
import signal
import struct
import sys
import termios
import time
from contextlib import contextmanager, suppress
from functools import wraps
from pty import CHILD, STDIN_FILENO, STDOUT_FILENO, fork
from unittest import TestCase

from kitty.config import finalize_keys, finalize_mouse_mappings
from kitty.fast_data_types import TEXT_SIZE_CODE, Cursor, HistoryBuf, LineBuf, Screen, get_options, monotonic, set_options
from kitty.options.parse import merge_result_dicts
from kitty.options.types import Options, defaults
from kitty.rgb import to_color
from kitty.types import MouseEvent
from kitty.utils import read_screen_size
from kitty.window import da1, decode_cmdline, process_remote_print, process_title_from_child


def parse_bytes(screen, data, dump_callback=None):
    data = memoryview(data)
    while data:
        dest = screen.test_create_write_buffer()
        s = screen.test_commit_write_buffer(data, dest)
        data = data[s:]
        screen.test_parse_written_data(dump_callback)


def draw_multicell(
    screen: Screen, text: str, width: int = 0, scale: int = 1, subscale_n: int = 0, subscale_d: int = 0, vertical_align: int = 0, horizontal_align: int = 0
    ) -> None:
    cmd = f'\x1b]{TEXT_SIZE_CODE};w={width}:s={scale}:n={subscale_n}:d={subscale_d}:v={vertical_align}:h={horizontal_align};{text}\a'
    parse_bytes(screen, cmd.encode())


class Callbacks:

    def __init__(self, pty=None) -> None:
        self.clear()
        self.pty = pty
        self.ftc = None
        self.set_pointer_shape = lambda data: None
        self.last_cmd_at = 0
        self.last_cmd_cmdline = ''
        self.last_cmd_exit_status = sys.maxsize

    def write(self, data) -> None:
        self.wtcbuf += bytes(data)

    def notify_child_of_resize(self):
        self.num_of_resize_events += 1

    def color_control(self, code, data) -> None:
        from kitty.window import color_control
        response = color_control(self.color_profile, code, data)
        if response:
            def p(x):
                if '@' in x:
                    return (to_color(x.partition('@')[0]), int(255 * float(x.partition('@')[2])))
                ans = to_color(x)
                if ans is None:
                    ans = x
                return ans
            parts = {x.partition('=')[0]:p(x.partition('=')[2]) for x in response.split(';')[1:]}
            self.color_control_responses.append(parts)

    def title_changed(self, data, is_base64=False) -> None:
        self.titlebuf.append(process_title_from_child(data, is_base64, ''))

    def icon_changed(self, data) -> None:
        self.iconbuf += str(data, 'utf-8')

    def set_dynamic_color(self, code, data='') -> None:
        if code == 22:
            self.set_pointer_shape(data)
        else:
            self.colorbuf += str(data or b'', 'utf-8')

    def set_color_table_color(self, code, data='') -> None:
        self.ctbuf += ''

    def color_profile_popped(self, x) -> None:
        pass

    def cmd_output_marking(self, is_start: bool | None, data: str = '') -> None:
        if is_start:
            self.last_cmd_at = monotonic()
            self.last_cmd_cmdline = decode_cmdline(data) if data else data
        else:
            if self.last_cmd_at != 0:
                self.last_cmd_at = 0
                with suppress(Exception):
                    self.last_cmd_exit_status = int(data)

    def request_capabilities(self, q) -> None:
        from kitty.terminfo import get_capabilities
        for c in get_capabilities(q, None):
            self.write(c.encode('ascii'))

    def desktop_notify(self, osc_code: int, raw_data: memoryview) -> None:
        self.notifications.append((osc_code, str(raw_data, 'utf-8')))

    def open_url(self, url: str, hyperlink_id: int) -> None:
        self.open_urls.append((url, hyperlink_id))

    def clipboard_control(self, data: memoryview, is_partial: bool = False) -> None:
        self.cc_buf.append((str(data, 'utf-8'), is_partial))

    def clear(self) -> None:
        self.wtcbuf = b''
        self.iconbuf = self.colorbuf = self.ctbuf = ''
        self.titlebuf = []
        self.printbuf = []
        self.color_control_responses = []
        self.notifications = []
        self.open_urls = []
        self.cc_buf = []
        self.bell_count = 0
        self.clone_cmds = []
        self.current_clone_data = ''
        self.last_cmd_exit_status = sys.maxsize
        self.last_cmd_cmdline = ''
        self.last_cmd_at = 0
        self.num_of_resize_events = 0
        self.da1 = []

    def on_bell(self) -> None:
        self.bell_count += 1

    def on_da1(self) -> None:
        self.da1.append(da1(get_options()))

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
        self.printbuf.append(text)

    def handle_remote_cmd(self, msg):
        pass

    def handle_remote_clone(self, msg):
        msg = str(msg, 'utf-8')
        if not msg:
            if self.current_clone_data:
                cdata, self.current_clone_data = self.current_clone_data, ''
                from kitty.launch import CloneCmd
                self.clone_cmds.append(CloneCmd(cdata))
            self.current_clone_data = ''
            return
        num, rest = msg.split(':', 1)
        if num == '0' or len(self.current_clone_data) > 1024 * 1024:
            self.current_clone_data = ''
        self.current_clone_data += rest

    def handle_remote_ssh(self, msg):
        from kittens.ssh.utils import get_ssh_data
        if self.pty:
            for line in get_ssh_data(msg, "testing"):
                self.pty.write_to_child(line)

    def handle_remote_echo(self, msg):
        from base64 import standard_b64decode
        if self.pty:
            data = standard_b64decode(msg)
            self.pty.write_to_child(data)

    def file_transmission(self, data):
        if self.ftc:
            self.ftc.handle_serialized_command(data)


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


is_ci = os.environ.get('CI') == 'true'
max_attempts = 4 if is_ci else 2
sleep_duration = 4 if is_ci else 2


def retry_on_failure(max_attempts=max_attempts, sleep_duration=sleep_duration):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt < max_attempts - 1: # Don't sleep on the last attempt
                        time.sleep(sleep_duration)
                        print(f'{func.__name__} failed, retrying in {sleep_duration} seconds', file=sys.stderr)
                    else:
                        raise # Re-raise the last exception
        return wrapper
    return decorator


class BaseTest(TestCase):

    ae = TestCase.assertEqual
    maxDiff = 2048
    is_ci = is_ci

    def rmtree_ignoring_errors(self, tdir):
        try:
            shutil.rmtree(tdir)
        except FileNotFoundError as err:
            print('Failed to delete the directory:', tdir, 'with error:', err, file=sys.stderr)

    def tearDown(self):
        set_options(None)

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
        c.color_profile = s.color_profile
        return s

    def create_pty(
            self, argv=None, cols=80, lines=100, scrollback=100, cell_width=10, cell_height=20,
            options=None, cwd=None, env=None, stdin_fd=None, stdout_fd=None
    ):
        self.set_options(options)
        return PTY(argv, lines, cols, scrollback, cell_width, cell_height, cwd, env, stdin_fd=stdin_fd, stdout_fd=stdout_fd)

    def assertEqualAttributes(self, c1, c2):
        x1, y1, c1.x, c1.y = c1.x, c1.y, 0, 0
        x2, y2, c2.x, c2.y = c2.x, c2.y, 0, 0
        try:
            self.assertEqual(c1, c2)
        finally:
            c1.x, c1.y, c2.x, c2.y = x1, y1, x2, y2


debug_stdout = debug_stderr = -1


@contextmanager
def forwardable_stdio():
    global debug_stderr, debug_stdout
    debug_stdout = fd = os.dup(sys.stdout.fileno())
    os.set_inheritable(fd, True)
    debug_stderr = fd = os.dup(sys.stderr.fileno())
    os.set_inheritable(fd, True)
    try:
        yield
    finally:
        os.close(debug_stderr)
        os.close(debug_stdout)
        debug_stderr = debug_stdout = -1


class PTY:

    def __init__(
        self, argv=None, rows=25, columns=80, scrollback=100, cell_width=10, cell_height=20,
        cwd=None, env=None, stdin_fd=None, stdout_fd=None
    ):
        self.is_child = False
        if isinstance(argv, str):
            argv = shlex.split(argv)
        self.write_buf = b''
        if argv is None:
            from kitty.child import openpty
            self.master_fd, self.slave_fd = openpty()
            self.child_pid = 0
        else:
            self.child_pid, self.master_fd = fork()
            self.is_child = self.child_pid == CHILD
        self.child_waited_for = False
        if self.is_child:
            while read_screen_size().width != columns * cell_width:
                time.sleep(0.01)
            if cwd:
                os.chdir(cwd)
            if stdin_fd is not None:
                os.dup2(stdin_fd, STDIN_FILENO)
                os.close(stdin_fd)
            if stdout_fd is not None:
                os.dup2(stdout_fd, STDOUT_FILENO)
                os.close(stdout_fd)
            signal.pthread_sigmask(signal.SIG_SETMASK, ())
            env = os.environ if env is None else env
            if debug_stdout > -1:
                env['KITTY_STDIO_FORWARDED'] = str(debug_stdout)
            os.execvpe(argv[0], argv, env)
        if stdin_fd is not None:
            os.close(stdin_fd)
        if stdout_fd is not None:
            os.close(stdout_fd)
        os.set_blocking(self.master_fd, False)
        self.cell_width = cell_width
        self.cell_height = cell_height
        self.set_window_size(rows=rows, columns=columns)
        self.callbacks = Callbacks(self)
        self.screen = Screen(self.callbacks, rows, columns, scrollback, cell_width, cell_height, 0, self.callbacks)
        self.received_bytes = b''

    def turn_off_echo(self):
        s = termios.tcgetattr(self.master_fd)
        s[3] &= ~termios.ECHO
        termios.tcsetattr(self.master_fd, termios.TCSANOW, s)

    def is_echo_on(self):
        s = termios.tcgetattr(self.master_fd)
        return True if s[3] & termios.ECHO else False

    def __del__(self):
        if not self.is_child:
            if hasattr(self, 'master_fd'):
                os.close(self.master_fd)
                del self.master_fd
            if hasattr(self, 'slave_fd'):
                os.close(self.slave_fd)
                del self.slave_fd
            if self.child_pid > 0 and not self.child_waited_for:
                os.waitpid(self.child_pid, 0)
                self.child_waited_for = True

    def write_to_child(self, data, flush=False):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.write_buf += data
        if flush:
            self.process_input_from_child(0)

    def send_cmd_to_child(self, cmd, flush=False):
        self.callbacks.last_cmd_exit_status = sys.maxsize
        self.last_cmd = cmd
        self.write_to_child(cmd + '\r', flush=flush)

    def process_input_from_child(self, timeout=10):
        rd, wd, _ = select.select([self.master_fd], [self.master_fd] if self.write_buf else [], [], max(0, timeout))
        if wd:
            n = os.write(self.master_fd, self.write_buf)
            self.write_buf = self.write_buf[n:]

        bytes_read = 0
        if rd:
            data = os.read(self.master_fd, io.DEFAULT_BUFFER_SIZE)
            bytes_read += len(data)
            self.received_bytes += data
            parse_bytes(self.screen, data)
        return bytes_read

    def wait_till(self, q, timeout=10, timeout_msg=None):
        end_time = time.monotonic() + timeout
        while not q() and time.monotonic() <= end_time:
            try:
                self.process_input_from_child(timeout=end_time - time.monotonic())
            except OSError as e:
                if not q():
                    raise Exception(f'Failed to read from pty with error: {e}. {self.screen_contents_for_error()}') from e
                return
        if not q():
            msg = 'The condition was not met'
            if timeout_msg is not None:
                msg = timeout_msg()
            raise TimeoutError(f'Timed out after {timeout} seconds: {msg}. {self.screen_contents_for_error()}')

    def wait_till_child_exits(self, timeout=30 if BaseTest.is_ci else 10, require_exit_code=None):
        end_time = time.monotonic() + timeout
        while time.monotonic() <= end_time:
            si_pid, status = os.waitpid(self.child_pid, os.WNOHANG)
            if si_pid == self.child_pid and os.WIFEXITED(status):
                ec = os.waitstatus_to_exitcode(status) if hasattr(os, 'waitstatus_to_exitcode') else require_exit_code
                self.child_waited_for = True
                if require_exit_code is not None and ec != require_exit_code:
                    raise AssertionError(
                        f'Child exited with exit status: {status} code: {ec} != {require_exit_code}.'
                        f' {self.screen_contents_for_error()}')
                return status
            with suppress(OSError):
                self.process_input_from_child(timeout=0.02)
        raise AssertionError(f'Child did not exit in {timeout} seconds. {self.screen_contents_for_error()}')

    def set_window_size(self, rows=25, columns=80, send_signal=True):
        if hasattr(self, 'screen'):
            self.screen.resize(rows, columns)
        if send_signal:
            x_pixels = columns * self.cell_width
            y_pixels = rows * self.cell_height
            s = struct.pack('HHHH', rows, columns, x_pixels, y_pixels)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, s)

    def screen_contents_for_error(self):
        from kitty.window import as_text
        ans = as_text(self.screen, add_history=True, as_ansi=False)
        return f'Screen contents as repr:\n{ans!r}\nScreen contents:\n{ans.rstrip()}'

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
