#!./kitty/launcher/kitty +launch
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import fcntl
import os
import select
import signal
import struct
import sys
import termios
import time
from pty import CHILD, fork

from kitty.constants import kitten_exe
from kitty.fast_data_types import ChildMonitor, Screen, safe_pipe
from kitty.utils import read_screen_size

BENCHMARK_WINDOW_ID = 1
ALL_BENCHMARKS = ('ascii', 'unicode', 'unique_unicode', 'csi', 'images', 'long_escape_codes')


def run_parsing_benchmark(
    benchmarks: tuple[str, ...] = ALL_BENCHMARKS,
    with_scrollback: bool = True,
    cell_width: int = 10,
    cell_height: int = 20,
    scrollback: int = 20000,
) -> None:
    isatty = sys.stdout.isatty()
    if isatty:
        sz = read_screen_size()
        columns, rows = sz.cols, sz.rows
    else:
        columns, rows = 80, 25
    child_pid, master_fd = fork()
    is_child = child_pid == CHILD
    # we add render as we arent rendering anyway and it means the synchronized
    # escape codes are no longer needed.
    argv = [kitten_exe(), '__benchmark__', '--render']
    if with_scrollback:
        argv.append('--with-scrollback')
    argv.extend(benchmarks)
    if is_child:
        while read_screen_size().width != columns * cell_width:
            time.sleep(0.01)
        signal.pthread_sigmask(signal.SIG_SETMASK, ())
        os.execvp(argv[0], argv)
    x_pixels = columns * cell_width
    y_pixels = rows * cell_height
    s = struct.pack('HHHH', rows, columns, x_pixels, y_pixels)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, s)

    child_died = False

    def on_child_death(window_id: int, died: bool, exit_status: int) -> None:
        nonlocal child_died
        child_died = True

    child_monitor = ChildMonitor(on_child_death, None)

    # r_pipe: benchmark polls this; w_pipe: io_thread writes here on data ready
    r_pipe, w_pipe = safe_pipe(False)
    child_monitor.set_wakeup_fd(w_pipe)

    screen = Screen(None, rows, columns, scrollback, cell_width, cell_height, BENCHMARK_WINDOW_ID)
    child_monitor.add_child(BENCHMARK_WINDOW_ID, child_pid, master_fd, screen)
    child_monitor.start()

    try:
        while not child_died:
            rd, _, _ = select.select([r_pipe], [], [], 1.0)
            if rd:
                # drain all accumulated wakeup bytes
                try:
                    os.read(r_pipe, 256)
                except OSError:
                    pass
            child_monitor.parse_input_once()
    finally:
        child_monitor.shutdown_monitor()  # io_loop closes master_fd via cleanup_child
        os.close(r_pipe)
        os.close(w_pipe)

    if isatty:
        lines: list[str] = []
        screen.linebuf.as_ansi(lines.append)
        sys.stdout.write(''.join(lines))
    else:
        sys.stdout.write(str(screen.linebuf))


def main() -> None:
    p = argparse.ArgumentParser(description='Run kitty parsing benchmarks')
    p.add_argument(
        'benchmarks',
        nargs='*',
        choices=list(ALL_BENCHMARKS),
        metavar='BENCHMARK',
        help=f'Benchmarks to run (default: all). Choose from: {", ".join(ALL_BENCHMARKS)}',
    )
    p.add_argument(
        '--with-scrollback',
        dest='with_scrollback',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Use the main screen instead of the alt screen so scrollback speed is also tested (default: enabled)',
    )
    args = p.parse_args()
    benchmarks = tuple(args.benchmarks) if args.benchmarks else ALL_BENCHMARKS
    run_parsing_benchmark(benchmarks=benchmarks, with_scrollback=args.with_scrollback)


if __name__ == '__main__':
    main()
