#!/usr/bin/env python3
# License: GPL v3 Copyright: 2026, kitty contributors

"""Compare layout allocation before and after the Amoeba migration.

The coordinator exports the pre-Amoeba kitty source tree, reuses the current
build's extension modules, and runs identical layout workloads in isolated
Python processes. This keeps the extension layer and test machine constant.
It measures cached relayout, cached viewport resize, and kitty window topology
changes. Run from the kitty source root after building kitty:

    python3 tools/layout_benchmark.py
"""

import argparse
import gc
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from statistics import mean, median
from typing import Any

BASELINE_COMMIT = 'd4d6db3cfd32e47aacd7ba12b1d19196dc256373'
LAYOUT_NAMES = 'Stack', 'Vertical', 'Horizontal', 'Tall', 'Fat', 'Grid', 'Splits'
PHASES = 'relayout', 'resize', 'topology'
RESULT_MARKER = 'KITTY_LAYOUT_BENCHMARK_RESULT='


def set_viewport(lgd: Any, Region: Any, width: int, height: int) -> None:
    lgd.central = Region((0, 0, width - 1, height - 1, width, height))
    lgd.cell_width, lgd.cell_height = 10, 20
    lgd.draw_minimal_borders = False
    lgd.alignment_x = lgd.alignment_y = 0


def timed(action: Callable[[], int], repetitions: int, samples: int) -> float:
    values: list[float] = []
    gc_enabled = gc.isenabled()
    try:
        gc.disable()
        for _ in range(samples):
            start = time.perf_counter_ns()
            calls = 0
            for _ in range(repetitions):
                calls += action()
            values.append((time.perf_counter_ns() - start) / calls)
    finally:
        if gc_enabled:
            gc.enable()
    return median(values)


def run_worker(counts: Sequence[int], repetitions: int, samples: int) -> dict[str, Any]:
    from kitty.fast_data_types import Region
    from kitty.layout.base import lgd
    from kitty.layout.interface import Fat, Grid, Horizontal, Splits, Stack, Tall, Vertical
    from kitty_tests.layout import Window, create_layout, create_windows

    classes = {cls.__name__: cls for cls in (Stack, Vertical, Horizontal, Tall, Fat, Grid, Splits)}

    def setup(layout_name: str, count: int) -> tuple[Any, Any]:
        layout = create_layout(classes[layout_name])
        windows = create_windows(layout, 0)
        for window_id in range(1, count + 1):
            layout.add_window(windows, Window(window_id))
        set_viewport(lgd, Region, 1200, 800)
        layout.do_layout(windows)
        return layout, windows

    results: dict[str, float] = {}
    geometry: dict[str, list[list[Any]]] = {}
    for layout_name in LAYOUT_NAMES:
        for count in counts:
            key = f'{layout_name}/{count}'

            layout, windows = setup(layout_name, count)

            def relayout() -> int:
                layout.do_layout(windows)
                return 1

            results[f'{key}/relayout'] = timed(relayout, repetitions, samples)
            geometry[key] = [list(window.geometry) for window in windows.all_windows]

            layout, windows = setup(layout_name, count)
            resize_step = 0

            def resize() -> int:
                nonlocal resize_step
                resize_step ^= 1
                set_viewport(lgd, Region, 1200 + 37 * resize_step, 800 + 23 * resize_step)
                layout.do_layout(windows)
                return 1

            results[f'{key}/resize'] = timed(resize, repetitions, samples)

            layout, windows = setup(layout_name, count)
            next_window_id = count + 1

            def topology() -> int:
                nonlocal next_window_id
                window = Window(next_window_id)
                next_window_id += 1
                layout.add_window(windows, window)
                layout.do_layout(windows)
                windows.remove_window(window)
                layout.do_layout(windows)
                return 2

            topology_repetitions = max(5, repetitions // 10)
            results[f'{key}/topology'] = timed(topology, topology_repetitions, samples)

    return {'times_ns': results, 'geometry': geometry}


def python_executable(requested: str) -> str:
    if requested:
        return requested
    name = Path(sys.executable).name.lower()
    if name.startswith(('python', 'pypy')):
        return sys.executable
    ans = shutil.which('python3')
    if ans is None:
        raise SystemExit('Could not find python3; use --python to specify it')
    return ans


def copy_extension_modules(source_root: Path, destination_root: Path) -> None:
    extensions = [path for pattern in ('*.so', '*.dylib', '*.pyd') for path in (source_root / 'kitty').glob(pattern)]
    if not extensions:
        raise SystemExit('No built kitty extension modules found. Build kitty before running this benchmark.')
    for source in extensions:
        destination = destination_root / 'kitty' / source.name
        destination.symlink_to(source)


def export_revision(repo: Path, revision: str, destination: Path) -> None:
    try:
        archive = subprocess.run(
            ['git', '-C', str(repo), 'archive', '--format=tar', revision], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ).stdout
    except subprocess.CalledProcessError as err:
        raise SystemExit(err.stderr.decode('utf-8', 'replace').strip()) from None
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as tf:
        tf.extractall(destination, filter='data')


def invoke_worker(python: str, script: Path, source_root: Path, counts: Sequence[int], repetitions: int, samples: int) -> dict[str, Any]:
    cmd = [
        python,
        str(script),
        '--worker',
        '--source-root',
        str(source_root),
        '--counts',
        ','.join(map(str, counts)),
        '--repetitions',
        str(repetitions),
        '--samples',
        str(samples),
    ]
    env = os.environ.copy()
    env['PYTHONPATH'] = str(source_root)
    proc = subprocess.run(cmd, cwd=source_root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f'Layout benchmark worker failed for {source_root}')
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(RESULT_MARKER):
            return json.loads(line.removeprefix(RESULT_MARKER))
    sys.stderr.write(proc.stdout)
    raise SystemExit(f'Layout benchmark worker produced no result for {source_root}')


def ratio(after: float, before: float) -> str:
    return f'{after / before:.2f}x ({(after / before - 1) * 100:+.0f}%)'


def print_table(before: dict[str, Any], after: dict[str, Any], counts: Sequence[int], detailed: bool) -> None:
    before_times, after_times = before['times_ns'], after['times_ns']
    headings = {'relayout': 'Cached relayout', 'resize': 'Cached resize', 'topology': 'Topology change'}
    for phase in PHASES:
        print(f'\n### {headings[phase]}\n')
        if detailed:
            print('| Layout | Kitty windows | Before (µs) | After (µs) | After/before |')
            print('|---|---:|---:|---:|---:|')
            for layout_name in LAYOUT_NAMES:
                for count in counts:
                    key = f'{layout_name}/{count}/{phase}'
                    b, a = before_times[key], after_times[key]
                    print(f'| {layout_name} | {count} | {b / 1000:.2f} | {a / 1000:.2f} | {ratio(a, b)} |')
        else:
            print('| Kitty windows | Before mean (µs) | After mean (µs) | After/before |')
            print('|---:|---:|---:|---:|')
            for count in counts:
                b = mean(before_times[f'{layout_name}/{count}/{phase}'] for layout_name in LAYOUT_NAMES)
                a = mean(after_times[f'{layout_name}/{count}/{phase}'] for layout_name in LAYOUT_NAMES)
                print(f'| {count} | {b / 1000:.2f} | {a / 1000:.2f} | {ratio(a, b)} |')


def parse_counts(raw: str) -> tuple[int, ...]:
    try:
        ans = tuple(int(x) for x in raw.split(','))
    except ValueError:
        raise argparse.ArgumentTypeError('counts must be comma-separated integers') from None
    if not ans or min(ans) < 1:
        raise argparse.ArgumentTypeError('all kitty window counts must be positive')
    return ans


def main() -> None:
    parser = argparse.ArgumentParser(description='Compare pre-Cassowary and Amoeba-backed kitty layout performance')
    parser.add_argument('--baseline', default=BASELINE_COMMIT, help='Git revision to use as the pre-Cassowary baseline')
    parser.add_argument('--counts', type=parse_counts, default=parse_counts('1,4,8,16,32'), help='Comma-separated kitty window counts')
    parser.add_argument('--repetitions', type=int, default=200, help='Repetitions per sample for cached workloads')
    parser.add_argument('--samples', type=int, default=7, help='Samples to collect; the median is reported')
    parser.add_argument('--detailed', action='store_true', help='Report every layout instead of means across layouts')
    parser.add_argument('--json', action='store_true', help='Print machine-readable results')
    parser.add_argument('--python', default='', help='Python interpreter for isolated workers')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--source-root', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repetitions < 1 or args.samples < 1:
        parser.error('--repetitions and --samples must be positive')

    if args.worker:
        if args.source_root is None:
            parser.error('--source-root is required for a worker')
        os.chdir(args.source_root)
        sys.path.insert(0, str(args.source_root))
        print(RESULT_MARKER + json.dumps(run_worker(args.counts, args.repetitions, args.samples), separators=(',', ':')))
        return

    repo = Path(__file__).resolve().parents[1]
    script = Path(__file__).resolve()
    python = python_executable(args.python)
    with tempfile.TemporaryDirectory(prefix='kitty-layout-benchmark-') as tdir:
        baseline_root = Path(tdir)
        export_revision(repo, args.baseline, baseline_root)
        copy_extension_modules(repo, baseline_root)
        before = invoke_worker(python, script, baseline_root, args.counts, args.repetitions, args.samples)
        after = invoke_worker(python, script, repo, args.counts, args.repetitions, args.samples)

    mismatches = [key for key, value in before['geometry'].items() if after['geometry'].get(key) != value]
    if mismatches:
        print(f'Warning: geometry differed for: {", ".join(mismatches)}', file=sys.stderr)
    current = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    payload = {
        'baseline': args.baseline,
        'current': current,
        'counts': args.counts,
        'repetitions': args.repetitions,
        'samples': args.samples,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'python': platform.python_version(),
        'before': before,
        'after': after,
        'geometry_mismatches': mismatches,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f'Baseline: {args.baseline}')
        print(f'Current:  {current}')
        print(f'Platform: {platform.platform()} ({platform.machine()})')
        print(f'Python:   {platform.python_version()}')
        print(f'Median of {args.samples} samples; {args.repetitions} cached repetitions per sample.')
        if not args.detailed:
            print(f'Summary values are arithmetic means across {len(LAYOUT_NAMES)} layouts.')
        print_table(before, after, args.counts, args.detailed)


if __name__ == '__main__':
    main()
