#!./kitty/launcher/kitty +launch
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import fcntl
import os
import select
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pty import CHILD, fork
from types import ModuleType
from unittest.mock import patch

from kitty.constants import kitten_exe, kitty_exe
from kitty.fast_data_types import ChildMonitor, Region, Screen, safe_pipe, set_options
from kitty.utils import read_screen_size

BENCHMARK_WINDOW_ID = 1
PARSING_BENCHMARKS = ('ascii', 'unicode', 'unique_unicode', 'csi', 'images', 'long_escape_codes')
ALL_BENCHMARKS = PARSING_BENCHMARKS + ('tab_bar',)
TAB_BAR_STYLES = ('fade', 'separator', 'powerline', 'slant')
TAB_BAR_NUM_TABS = (10, 50, 200)
TAB_BAR_COLUMNS = 200


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
    benchmarks: tuple[str, ...] = PARSING_BENCHMARKS,
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
    # we add render as we aren't rendering anyway and it means the synchronized
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


def tab_bar_module_at(rev: str) -> ModuleType:
    "Load kitty/tab_bar.py as it is at the specified git revision"
    src = subprocess.check_output(['git', 'show', f'{rev}:kitty/tab_bar.py'], text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    m = ModuleType(f'kitty.tab_bar_at_{rev}')
    m.__package__ = 'kitty'
    exec(compile(src, f'{rev}:kitty/tab_bar.py', 'exec'), m.__dict__)
    return m


class TabBarBenchmarkBoss:
    class mappings:
        current_keyboard_mode_name = ''

    window_id_map: dict[int, object] = {}

    def tab_for_id(self, tab_id: int) -> None:
        return None


def time_tab_bar_updates(tab_bar: ModuleType, style: str, num_tabs: int, repetitions: int | None) -> float:
    "Return the median time in seconds taken to lay out and draw a horizontal tab bar"
    from kitty.options.types import defaults

    set_options(defaults._replace(tab_bar_style=style))
    cell_width, cell_height = 10, 20
    width, height = TAB_BAR_COLUMNS * cell_width, 200
    central = Region((0, 0, width, height - cell_height, width, height - cell_height))
    bar = Region((0, height - cell_height, width, height, width, cell_height))
    boss = TabBarBenchmarkBoss()
    with ExitStack() as stack:
        # There is no OS window, so replace the functions that need one with
        # plain functions, rather than mocks, whose overhead would distort timings
        for name, func in {
            'cell_size_for_window': lambda *a: (cell_width, cell_height),
            'viewport_for_window': lambda *a: (central, bar, width, height, cell_width, cell_height),
            'set_tab_bar_render_data': lambda *a: None,
            'update_tab_bar_edge_colors': lambda *a: None,
            'get_boss': lambda: boss,
        }.items():
            stack.enter_context(patch.object(tab_bar, name, new=func))
        tb = tab_bar.TabBar(1)
        tb.layout()
        # A mix of short and long titles, so that the long ones need truncating
        data = tuple(tab_bar.TabBarData(title='~' if i % 3 == 0 else f'~/projects/some-project-{i}', tab_id=i + 1, is_active=i == 1) for i in range(num_tabs))
        for _ in range(5):
            tb.update(data)
        times = []
        for _ in range(repetitions or max(20, 4000 // num_tabs)):
            start = time.perf_counter()
            tb.update(data)
            times.append(time.perf_counter() - start)
    return statistics.median(times)


def run_tab_bar_benchmark(compare_with: str = '', repetitions: int | None = None) -> None:
    import kitty.tab_bar

    modules = {'working tree': kitty.tab_bar}
    if compare_with:
        try:
            modules = {compare_with: tab_bar_module_at(compare_with), **modules}
        except subprocess.CalledProcessError:
            raise SystemExit(f'Could not read kitty/tab_bar.py at the git revision: {compare_with}')
    width = max(12, *map(len, modules))

    def rows() -> Iterator[str]:
        yield f'{"style":<10} {"tabs":>4} ' + ' '.join(f'{name:>{width}}' for name in modules)
        for style in TAB_BAR_STYLES:
            for num_tabs in TAB_BAR_NUM_TABS:
                times = (time_tab_bar_updates(m, style, num_tabs, repetitions) * 1000 for m in modules.values())
                yield f'{style:<10} {num_tabs:>4} ' + ' '.join(f'{t:>{width - 2}.3f}ms' for t in times)

    print(f'Median time to update a horizontal tab bar of {TAB_BAR_COLUMNS} cells:')
    for row in rows():
        print(row, flush=True)


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
    p = argparse.ArgumentParser(description='Run kitty parsing and tab bar benchmarks')
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
        help='Number of repetitions of each benchmark (default: kitten default of 100, for tab_bar it depends on the number of tabs)',
    )
    p.add_argument(
        '--compare-with',
        default='',
        metavar='GIT_REVISION',
        help='For the tab_bar benchmark, also time kitty/tab_bar.py as it is at the specified git revision, for comparison',
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
    if parsing_benchmarks := tuple(b for b in benchmarks if b in PARSING_BENCHMARKS):
        run_parsing_benchmark(benchmarks=parsing_benchmarks, with_scrollback=args.with_scrollback, repetitions=args.repetitions)
    if 'tab_bar' in benchmarks:
        run_tab_bar_benchmark(compare_with=args.compare_with, repetitions=args.repetitions)


if __name__ == '__main__':
    main()
