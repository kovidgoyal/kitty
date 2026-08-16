#!./kitty/launcher/kitty +launch
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import fcntl
import os
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pty import CHILD, fork

from kitty.constants import kitten_exe, kitty_exe
from kitty.fast_data_types import ChildMonitor, Screen, safe_pipe
from kitty.utils import read_screen_size

BENCHMARK_WINDOW_ID = 1
ALL_BENCHMARKS = ('ascii', 'unicode', 'unique_unicode', 'csi', 'images', 'long_escape_codes')

def perf_output() -> str:
    return os.path.join(tempfile.gettempdir(), 'kitty-benchmark.perf')

# Set by the re-exec wrapper so we don't recurse when --perf is in argv.
_UNDER_PERF_ENV = '_KITTY_BENCHMARK_UNDER_PERF'


def find_perf() -> str | None:
    return shutil.which('perf')


def run_perf_reports(perf_exe: str) -> None:
    sep = '=' * 70
    print(f'\n{sep}')
    print('PERF PROFILING RESULTS')
    print(sep)
    print(f'Profile data saved to: {perf_output()}')
    print(f'Re-run interactively:   perf report -i {perf_output()}\n')

    print('--- Top CPU hotspots (call graph, >=0.5% threshold) ---\n')
    subprocess.run(
        [
            perf_exe,
            'report',
            '--stdio',
            '-n',
            '--call-graph',
            'fractal,0.5',
            '--percent-limit',
            '0.5',
            '-i',
            perf_output(),
        ],
        check=False,
    )

    print('\n--- Per-process CPU breakdown ---\n')
    subprocess.run(
        [
            perf_exe,
            'report',
            '--stdio',
            '-n',
            '--sort',
            'overhead,pid,comm,symbol',
            '--percent-limit',
            '1.0',
            '-i',
            perf_output(),
        ],
        check=False,
    )

    print(f'\n{sep}\n')


def run_parsing_benchmark(
    benchmarks: tuple[str, ...] = ALL_BENCHMARKS,
    with_scrollback: bool = True,
    cell_width: int = 10,
    cell_height: int = 20,
    scrollback: int = 20000,
    repetitions: int | None = None,
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
    if repetitions is not None:
        argv.extend(['--repetitions', str(repetitions)])
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


def exec_under_perf(perf_exe: str, print_report: bool = False) -> None:
    """Re-exec this script as a child of perf record.

    perf becomes the outer process so it can profile the entire benchmark
    run without any subprocess/SIGCHLD conflicts with ChildMonitor.
    After the benchmark exits perf finalises its output, then optionally
    runs perf report to print the results.
    """
    script = os.path.abspath(__file__)
    env = {**os.environ, _UNDER_PERF_ENV: '1'}
    cmd = [
        perf_exe,
        'record',
        '-g',
        '-F',
        '999',
        '--call-graph',
        'dwarf',
        '-o',
        perf_output(),
        '--',
        kitty_exe(),
        '+launch',
        script,
    ] + sys.argv[1:]
    subprocess.run(cmd, env=env, check=False)
    if print_report:
        run_perf_reports(perf_exe)
    else:
        print(f'Profile data saved to: {perf_output()}')


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
    p.add_argument(
        '--perf',
        action='store_true',
        default=False,
        help=(
            'Profile with Linux perf: records at 999 Hz with DWARF call graphs '
            'and saves raw data to ' + perf_output() + '. '
            'Requires perf in PATH with setcap cap_sys_admin,cap_sys_ptrace,cap_syslog=ep /usr/bin/perf'
        ),
    )
    p.add_argument(
        '--perf-report',
        action='store_true',
        default=False,
        help='After --perf recording, print call-graph hotspots and per-process CPU breakdown to stdout (default: only print path to raw data)',
    )
    p.add_argument(
        '--repetitions',
        type=int,
        default=None,
        metavar='N',
        help='Number of repetitions of each benchmark (default: kitten default of 100)',
    )
    args = p.parse_args()

    if args.perf and not os.environ.get(_UNDER_PERF_ENV):
        perf_exe = find_perf()
        if perf_exe is None:
            print('Warning: perf not found in PATH, running without profiling', file=sys.stderr)
        else:
            exec_under_perf(perf_exe, print_report=args.perf_report)
            return

    benchmarks = tuple(args.benchmarks) if args.benchmarks else ALL_BENCHMARKS
    run_parsing_benchmark(benchmarks=benchmarks, with_scrollback=args.with_scrollback, repetitions=args.repetitions)


if __name__ == '__main__':
    main()
