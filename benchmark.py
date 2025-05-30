#!./kitty/launcher/kitty +launch
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import io
import os
import select
import signal
import struct
import sys
import termios
import time
from pty import CHILD, fork

from kitty.constants import kitten_exe
from kitty.fast_data_types import Screen, safe_pipe
from kitty.utils import read_screen_size


def run_parsing_benchmark(cell_width: int = 10, cell_height: int = 20, scrollback: int = 20000) -> None:
    isatty = sys.stdout.isatty()
    if isatty:
        sz = read_screen_size()
        columns, rows = sz.cols, sz.rows
    else:
        columns, rows = 80, 25
    child_pid, master_fd = fork()
    is_child = child_pid == CHILD
    argv = [kitten_exe(), '__benchmark__', '--with-scrollback']
    if is_child:
        while read_screen_size().width != columns * cell_width:
            time.sleep(0.01)
        signal.pthread_sigmask(signal.SIG_SETMASK, ())
        os.execvp(argv[0], argv)
    # os.set_blocking(master_fd, False)
    x_pixels = columns * cell_width
    y_pixels = rows * cell_height
    s = struct.pack('HHHH', rows, columns, x_pixels, y_pixels)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, s)

    write_buf = b''
    r_pipe, w_pipe = safe_pipe(True)
    class ToChild:
        def write(self, x: bytes | str) -> None:
            nonlocal write_buf
            if isinstance(x, str):
                x = x.encode()
            write_buf += x
            os.write(w_pipe, b'1')

    screen = Screen(None, rows, columns, scrollback, cell_width, cell_height, 0, ToChild())

    def parse_bytes(data: bytes|memoryview) -> None:
        data = memoryview(data)
        while data:
            dest = screen.test_create_write_buffer()
            s = screen.test_commit_write_buffer(data, dest)
            data = data[s:]
            screen.test_parse_written_data()


    while True:
        rd, wd, _ = select.select([master_fd, r_pipe], [master_fd] if write_buf else [], [])
        if r_pipe in rd:
            os.read(r_pipe, 256)
        if master_fd in rd:
            try:
                data = os.read(master_fd, io.DEFAULT_BUFFER_SIZE)
            except OSError:
                data = b''
            if not data:
                break
            parse_bytes(data)
        if master_fd in wd:
            n = os.write(master_fd, write_buf)
            write_buf = write_buf[n:]
    if isatty:
        lines: list[str] = []
        screen.linebuf.as_ansi(lines.append)
        sys.stdout.write(''.join(lines))
    else:
        sys.stdout.write(str(screen.linebuf))


def main() -> None:
    run_parsing_benchmark()


if __name__ == '__main__':
    main()
