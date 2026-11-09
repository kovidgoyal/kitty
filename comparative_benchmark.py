#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

"""
Run the kitty benchmark kitten in all installed terminals from a fixed set and
present the results for comparison. Linux only.

Every terminal is run with its default configuration, except for the font
family, font size and window size, which are made the same for all terminals.
User configuration is ignored by pointing all the XDG base directories at
a temporary directory. The terminals are pinned to the fast cores on machines
with heterogeneous cores and the CPU frequency governor is set to performance
for the duration of the run, if possible.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

BASE = os.path.dirname(os.path.abspath(__file__))
CPU_SYSFS = '/sys/devices/system/cpu'
READY_FILE, GO_FILE, DONE_FILE, PROGRESS_FILE = 'ready.json', 'go', 'done.json', 'progress'
ENV_PREFIXES_TO_REMOVE = (
    'KITTY_',
    'TMUX',
    'WEZTERM_',
    'GHOSTTY_',
    'ALACRITTY_',
    'KONSOLE_',
    'VTE_',
    'TERM_PROGRAM',
    'TERMINFO',
    'COLORTERM',
    'WINDOWID',
    'XTERM_',
    'PTYXIS_',
    'SHELL_SESSION_ID',
)


@dataclass(frozen=True)
class Settings:
    font_family: str
    font_size: float
    columns: int
    lines: int
    window_width: int
    window_height: int


@dataclass
class Terminal:
    name: str
    executable: str
    # Build the command line to run cmd in the terminal, given the per-run
    # directory for config files and the settings
    build_cmd: Callable[[str, list[str], Settings], list[str]]
    version_cmd: list[str] = field(default_factory=list)
    # Run after the terminal is done, to cleanup any left over processes
    cleanup: Callable[[str], None] | None = None
    # Needs an X11 display, a private rootful Xwayland is started if DISPLAY is not set
    needs_x11: bool = False
    # Needs a D-Bus session bus and a systemd user instance (to spawn processes in scopes)
    needs_session: bool = False


# Terminal definitions {{{


def write_file(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)
    return path


def fmt_size(x: float) -> str:
    return str(int(x)) if x == int(x) else str(x)


def toml_str(x: str) -> str:
    return json.dumps(x)


def xterm_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    return ['xterm', '-fa', s.font_family, '-fs', fmt_size(s.font_size), '-geometry', f'{s.columns}x{s.lines}', '-e'] + cmd


def foot_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    conf = write_file(os.path.join(d, 'foot.ini'), f'font={s.font_family}:size={fmt_size(s.font_size)}\ninitial-window-size-chars={s.columns}x{s.lines}\n')
    return ['foot', '--config', conf] + cmd


def kitty_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    conf = write_file(
        os.path.join(d, 'kitty.conf'),
        '\n'.join(
            (
                f'font_family family="{s.font_family}"',
                f'font_size {fmt_size(s.font_size)}',
                'remember_window_size no',
                f'initial_window_width {s.columns}c',
                f'initial_window_height {s.lines}c',
                '',
            )
        ),
    )
    return [kitty_exe(), '--config', conf] + cmd


def ghostty_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    conf = write_file(
        os.path.join(d, 'ghostty.conf'),
        '\n'.join(
            (
                f'font-family = {s.font_family}',
                f'font-size = {fmt_size(s.font_size)}',
                f'window-width = {s.columns}',
                f'window-height = {s.lines}',
                # Needed so that the window is created in a new process that exits when the command finishes
                'gtk-single-instance = false',
                'confirm-close-surface = false',
                'quit-after-last-window-closed = true',
                '',
            )
        ),
    )
    return ['ghostty', '--config-default-files=false', f'--config-file={conf}', '-e'] + cmd


def alacritty_config(d: str, s: Settings) -> str:
    return write_file(
        os.path.join(d, 'alacritty.toml'),
        '\n'.join(
            (
                '[font]',
                f'size = {float(s.font_size)}',
                f'normal = {{ family = {toml_str(s.font_family)} }}',
                '[window]',
                f'dimensions = {{ columns = {s.columns}, lines = {s.lines} }}',
                '',
            )
        ),
    )


def alacritty_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    return ['alacritty', '--config-file', alacritty_config(d, s), '-e'] + cmd


def wezterm_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    conf = write_file(
        os.path.join(d, 'wezterm.lua'),
        '\n'.join(
            (
                'local wezterm = require "wezterm"',
                'local config = wezterm.config_builder()',
                f'config.font = wezterm.font({json.dumps(s.font_family)})',
                f'config.font_size = {float(s.font_size)}',
                f'config.initial_cols = {s.columns}',
                f'config.initial_rows = {s.lines}',
                'return config',
                '',
            )
        ),
    )
    return ['wezterm', '--config-file', conf, 'start', '--always-new-process', '--'] + cmd


def konsole_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    return [
        'konsole',
        '--separate',
        '--builtin-profile',
        '-p',
        f'Font={s.font_family},{fmt_size(s.font_size)}',
        '-p',
        f'TerminalColumns={s.columns}',
        '-p',
        f'TerminalRows={s.lines}',
        '-e',
    ] + cmd


def ptyxis_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    # ptyxis uses GSettings, the run environment sets GSETTINGS_BACKEND=keyfile
    # with XDG_CONFIG_HOME pointing into d, so this is where its settings are read from
    write_file(
        os.path.join(d, 'xdg', 'config', 'glib-2.0', 'settings', 'keyfile'),
        '\n'.join(
            (
                '[org/gnome/Ptyxis]',
                'use-system-font=false',
                f"font-name='{s.font_family} {fmt_size(s.font_size)}'",
                f'default-columns=uint32 {s.columns}',
                f'default-rows=uint32 {s.lines}',
                'restore-window-size=false',
                'restore-session=false',
                '',
            )
        ),
    )
    return ['ptyxis', '--standalone', '--'] + cmd


TMUX_SOCKET = 'kitty-comparative-benchmark'


def alacritty_tmux_cmd(d: str, cmd: list[str], s: Settings) -> list[str]:
    return ['alacritty', '--config-file', alacritty_config(d, s), '-e', 'tmux', '-L', TMUX_SOCKET, '-f', '/dev/null', 'new-session', '--'] + cmd


def tmux_cleanup(d: str) -> None:
    subprocess.run(['tmux', '-L', TMUX_SOCKET, 'kill-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kitty_exe() -> str:
    q = os.path.join(BASE, 'kitty', 'launcher', 'kitty')
    return q if os.access(q, os.X_OK) else 'kitty'


def kitten_exe() -> str:
    q = os.path.join(BASE, 'kitty', 'launcher', 'kitten')
    if os.access(q, os.X_OK):
        return q
    ans = shutil.which('kitten')
    if not ans:
        raise SystemExit('Could not find the kitten executable, build kitty first with: make debug')
    return ans


def all_terminals() -> list[Terminal]:
    return [
        Terminal('xterm', 'xterm', xterm_cmd, ['xterm', '-version'], needs_x11=True),
        Terminal('foot', 'foot', foot_cmd, ['foot', '--version']),
        Terminal('kitty', kitty_exe(), kitty_cmd, [kitty_exe(), '--version']),
        Terminal('ghostty', 'ghostty', ghostty_cmd, ['ghostty', '--version']),
        Terminal('alacritty', 'alacritty', alacritty_cmd, ['alacritty', '--version']),
        Terminal('wezterm', 'wezterm', wezterm_cmd, ['wezterm', '--version']),
        Terminal('konsole', 'konsole', konsole_cmd, ['konsole', '--version']),
        Terminal('ptyxis', 'ptyxis', ptyxis_cmd, ['ptyxis', '--version'], needs_session=True),
        Terminal('alacritty+tmux', 'alacritty', alacritty_tmux_cmd, ['tmux', '-V'], tmux_cleanup),
    ]


def is_installed(t: Terminal) -> bool:
    if t.name == 'alacritty+tmux' and not shutil.which('tmux'):
        return False
    return bool(shutil.which(t.executable))


def terminal_version(t: Terminal) -> str:
    if not t.version_cmd:
        return ''
    try:
        cp = subprocess.run(t.version_cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f'unknown ({e})'
    lines = [x.strip() for x in (cp.stdout or cp.stderr).splitlines() if x.strip()]
    ans = lines[0] if lines else 'unknown'
    if t.name == 'alacritty+tmux':
        a = Terminal('alacritty', 'alacritty', alacritty_cmd, ['alacritty', '--version'])
        ans = f'{terminal_version(a)} + {ans}'
    return ans


# }}}


# CPU setup {{{


def read_sysfs(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ''


def online_cpus() -> list[int]:
    return sorted(os.sched_getaffinity(0))


# Per CPU sysfs files that indicate relative CPU performance: cpu_capacity (ARM
# big.LITTLE, constant on x86), CPPC highest perf (AMD and Intel) and max frequency
PERF_METRICS = ('cpu_capacity', 'cpufreq/amd_pstate_highest_perf', 'acpi_cppc/highest_perf', 'cpufreq/cpuinfo_max_freq')


def physical_core_key(cpu: int) -> tuple[str, str]:
    base = f'{CPU_SYSFS}/cpu{cpu}/topology'
    return read_sysfs(f'{base}/physical_package_id'), read_sysfs(f'{base}/core_id')


def detect_fast_cpus(one_thread_per_core: bool) -> tuple[list[int], str]:
    cpus = online_cpus()
    intel_core = read_sysfs('/sys/devices/cpu_core/cpus')
    fast: list[int]
    if intel_core:  # Intel hybrid, P-cores
        fast = [c for c in parse_cpu_list(intel_core) if c in cpus]
        how = 'Intel hybrid P-cores'
    else:
        for q in PERF_METRICS:
            vals = {c: read_sysfs(f'{CPU_SYSFS}/cpu{c}/{q}') for c in cpus}
            if not all(v.isdigit() for v in vals.values()):
                continue
            metrics = {c: int(v) for c, v in vals.items()}
            top = max(metrics.values())
            # Ignore small per-core variations from binning, e.g. AMD preferred cores
            fast = [c for c in cpus if metrics[c] >= 0.9 * top]
            if len(fast) < len(cpus):
                how = f'heterogeneous cores, using the fastest as per {q}'
                break
        else:
            return cpus, 'homogeneous cores, using all CPUs'
    if one_thread_per_core:
        seen: set[tuple[str, str]] = set()
        ans = []
        for c in fast:
            k = physical_core_key(c)
            if k not in seen:
                seen.add(k)
                ans.append(c)
        fast, how = ans, how + ', one thread per core'
    return fast, how


def parse_cpu_list(spec: str) -> list[int]:
    ans: list[int] = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            ans.extend(range(int(a), int(b) + 1))
        else:
            ans.append(int(part))
    return ans


def write_sysfs_values(values: dict[str, str]) -> str:
    """Write the values, using sudo if needed. Returns an error message on failure."""
    if not values:
        return ''
    try:
        for path, val in values.items():
            with open(path, 'w') as f:
                f.write(val)
        return ''
    except PermissionError:
        pass
    except OSError as e:
        return str(e)
    script = '\n'.join(f'echo {shlex.quote(v)} > {shlex.quote(p)}' for p, v in values.items())
    cp = subprocess.run(['sudo', '-n', 'sh', '-c', script], capture_output=True, text=True)
    if cp.returncode == 0:
        return ''
    if sys.stdin.isatty():
        print('Root access is needed to change the CPU frequency governor, asking sudo for your password', file=sys.stderr)
        cp = subprocess.run(['sudo', 'sh', '-c', script], stdout=subprocess.PIPE, text=True)
        if cp.returncode == 0:
            return ''
    return 'permission denied: not root and passwordless sudo is not available'


@contextmanager
def performance_governor(enabled: bool) -> Generator[str]:
    """Yields a description of what was done"""
    if not enabled:
        yield 'not changed (disabled on command line)'
        return
    original: dict[str, str] = {}
    for cpu in online_cpus():
        p = f'{CPU_SYSFS}/cpu{cpu}/cpufreq/scaling_governor'
        if cur := read_sysfs(p):
            avail = read_sysfs(f'{CPU_SYSFS}/cpu{cpu}/cpufreq/scaling_available_governors').split()
            if 'performance' not in avail:
                yield f'not changed: the performance governor is not available (available: {" ".join(avail)})'
                return
            original[p] = cur
    if not original:
        yield 'not changed: no cpufreq support'
        return
    to_change = {p: 'performance' for p, v in original.items() if v != 'performance'}
    if not to_change:
        yield 'performance (already set)'
        return
    if err := write_sysfs_values(to_change):
        yield f'not changed ({", ".join(sorted(set(original.values())))}): {err}'
        return
    try:
        yield f'performance (was {", ".join(sorted(set(original.values())))}, will be restored)'
    finally:
        if err := write_sysfs_values({p: original[p] for p in to_change}):
            print(f'Failed to restore the CPU frequency governor: {err}', file=sys.stderr)


# }}}


# Sway support for making window sizes identical {{{


def sway_available() -> bool:
    return bool(os.environ.get('SWAYSOCK')) and bool(shutil.which('swaymsg'))


def sway_find_window(pid: int, marker: str) -> int | None:
    try:
        cp = subprocess.run(['swaymsg', '-t', 'get_tree', '-r'], capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    tree: dict[str, Any] = json.loads(cp.stdout)
    stack = [tree]
    while stack:
        n = stack.pop()
        if n.get('type') in ('con', 'floating_con') and (n.get('pid') == pid or marker in (n.get('name') or '')):
            con_id = n.get('id')
            if isinstance(con_id, int):
                return con_id
        stack.extend(n.get('nodes', ()))
        stack.extend(n.get('floating_nodes', ()))
    return None


def sway_float(pid: int, marker: str, width: int, height: int, timeout: float = 15) -> str:
    """Make the window floating, so that it gets its natural (requested) size,
    unless width and height are non-zero in which case it is resized to them."""
    deadline = time.monotonic() + timeout
    while (con_id := sway_find_window(pid, marker)) is None:
        if time.monotonic() > deadline:
            return 'could not find terminal window in the sway tree'
        time.sleep(0.1)
    resize = ['resize', 'set', 'width', f'{width}px', 'height', f'{height}px,'] if width and height else []
    cp = subprocess.run(
        ['swaymsg', f'[con_id={con_id}]', 'floating', 'enable,'] + resize + ['move', 'position', '0', '0,', 'focus'], capture_output=True, text=True
    )
    if cp.returncode != 0:
        return f'swaymsg failed: {cp.stdout.strip()} {cp.stderr.strip()}'
    return ''


# }}}


# Helpers for running terminals in minimal sessions {{{


@contextmanager
def private_xwayland(width: int, height: int) -> Generator[tuple[str, int]]:
    """Start a rootful Xwayland, yields (DISPLAY, pid)"""
    if not os.environ.get('WAYLAND_DISPLAY') or not shutil.which('Xwayland'):
        raise RuntimeError('DISPLAY is not set and Xwayland is not available to create one')
    r, w = os.pipe()
    try:
        proc = subprocess.Popen(
            ['Xwayland', '-displayfd', str(w), '-geometry', f'{width}x{height}', '-nolisten', 'tcp'],
            pass_fds=(w,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        os.close(w)
    try:
        with open(r, 'rb') as f:
            num = f.readline().strip().decode()
        if not num.isdigit():
            raise RuntimeError(f'Xwayland failed to start, exit code: {proc.poll()}')
        yield f':{num}', proc.pid
    finally:
        kill_process_group(proc)


def has_session_bus() -> bool:
    rd = os.environ.get('XDG_RUNTIME_DIR', '')
    return bool(os.environ.get('DBUS_SESSION_BUS_ADDRESS')) or (bool(rd) and os.path.exists(os.path.join(rd, 'bus')))


def has_systemd_user_instance() -> bool:
    if not shutil.which('systemctl'):
        return False
    return subprocess.run(['systemctl', '--user', 'show-environment'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


SYSTEMD_RUN_SHIM = """#!/bin/sh
# Used when there is no systemd user instance: ignore all options and run the command directly
while [ $# -gt 0 ]; do case "$1" in --) shift; break;; -*) shift;; *) break;; esac; done
exec "$@"
"""


def setup_session(d: str, cmd: list[str], env: dict[str, str]) -> list[str]:
    """Make up for a missing session bus and/or systemd user instance, as found in headless sessions"""
    if not has_systemd_user_instance():
        shim = write_file(os.path.join(d, 'shim', 'systemd-run'), SYSTEMD_RUN_SHIM)
        os.chmod(shim, 0o755)
        env['PATH'] = os.path.dirname(shim) + os.pathsep + env.get('PATH', '')
    if not has_session_bus():
        if not shutil.which('dbus-run-session'):
            raise RuntimeError('there is no D-Bus session bus and dbus-run-session is not available to create one')
        env['GTK_A11Y'] = 'none'  # the accessibility bus is not available in a private session
        cmd = ['dbus-run-session', '--'] + cmd
    return cmd


# }}}


# Running a single terminal {{{


@dataclass
class BenchmarkResult:
    name: str
    status: str = 'ok'  # ok, timeout or failed
    error: str = ''
    description: str = ''
    duration: float = 0
    data_size: int = 0
    repetitions: int = 0
    mb_per_second: float = 0
    cells_per_second: float = 0


@dataclass
class TerminalRun:
    terminal: str
    version: str
    results: list[BenchmarkResult] = field(default_factory=list)
    error: str = ''
    size: str = ''
    size_warning: str = ''
    wall_time: float = 0


def clean_env(xdg_root: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(ENV_PREFIXES_TO_REMOVE)}
    env.pop('TERM', None)
    for name in ('CONFIG', 'DATA', 'STATE', 'CACHE'):
        p = os.path.join(xdg_root, name.lower())
        os.makedirs(p, exist_ok=True)
        env[f'XDG_{name}_HOME'] = p
    env['GSETTINGS_BACKEND'] = 'keyfile'
    return env


def wait_for(predicate: Callable[[], bool], proc: subprocess.Popen[bytes], timeout: float, on_poll: Callable[[], None] | None = None) -> str:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return f'timed out after {timeout:.0f} seconds'
        if (rc := proc.poll()) is not None and not predicate():
            # some launchers fork and exit, so give the real process a chance
            time.sleep(0.5)
            if predicate():
                break
            if rc != 0:
                return f'terminal process exited with code {rc}'
        if on_poll is not None:
            on_poll()
        time.sleep(0.05)
    return ''


def kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sig)
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            continue


def available_benchmarks() -> list[str]:
    cp = subprocess.run([kitten_exe(), '__benchmark__', '--help'], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    ans = re.findall(r'^\s*\*\s+(\w+):', cp.stdout, flags=re.MULTILINE)
    if not ans:
        raise SystemExit(f'Failed to get the list of benchmarks from the benchmark kitten: {cp.stderr}')
    return ans


def load_result(name: str, info: dict[str, Any], path: str) -> BenchmarkResult:
    status = str(info.get('status', 'failed'))
    if status != 'ok':
        return BenchmarkResult(name, status=status, error=str(info.get('error', '')))
    with open(path) as f:
        raw: list[dict[str, Any]] = json.load(f)
    r = raw[0]
    return BenchmarkResult(
        name=str(r['name']),
        description=str(r['description']),
        duration=float(r['duration_seconds']),
        data_size=int(r['data_size_bytes']),
        repetitions=int(r['repetitions']),
        mb_per_second=float(r['mb_per_second']),
        cells_per_second=float(r.get('cells_per_second', 0)),
    )


def check_size(size: str, settings: Settings) -> str:
    if settings.window_width or not size:
        return ''  # forced pixel size, so the number of cells is expected to differ
    cols, lines = map(int, size.split('x'))
    # allow for off by one because of padding, and the status line in tmux
    if abs(cols - settings.columns) > 1 or abs(lines - settings.lines) > 1:
        return f'window size is {size} cells instead of {settings.columns}x{settings.lines}'
    return ''


def run_terminal(
    t: Terminal, args: argparse.Namespace, settings: Settings, cpus: list[int], log: Callable[[str], None], progress: Callable[[str], None]
) -> TerminalRun:
    ans = TerminalRun(t.name, terminal_version(t))
    with tempfile.TemporaryDirectory(prefix='kitty-cbench-') as d:
        marker = f'cbench-{os.getpid()}-{t.name}'
        inner = [sys.executable, os.path.abspath(__file__), '--inner', d, marker, kitten_exe(), str(args.repetitions), str(args.benchmark_timeout)] + list(
            args.benchmarks
        )
        cmd = t.build_cmd(d, inner, settings)
        env = clean_env(os.path.join(d, 'xdg'))
        stack = ExitStack()
        window_pid = 0
        try:
            if t.needs_x11 and not env.get('DISPLAY'):
                env['DISPLAY'], window_pid = stack.enter_context(private_xwayland(settings.window_width or 1600, settings.window_height or 1000))
            if t.needs_session:
                cmd = setup_session(d, cmd, env)
        except RuntimeError as e:
            stack.close()
            ans.error = str(e)
            return ans
        log(f'Running: {shlex.join(cmd)}')
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=d,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                preexec_fn=lambda: os.sched_setaffinity(0, cpus),
            )
        except OSError as e:
            stack.close()
            ans.error = f'failed to launch: {e}'
            return ans
        try:
            ans.error = run_in_launched_terminal(proc, window_pid or proc.pid, d, marker, args, settings, progress)
            if not ans.error:
                with open(os.path.join(d, DONE_FILE)) as f:
                    done: dict[str, Any] = json.load(f)
                ans.size = str(done.get('size', ''))
                ans.size_warning = check_size(ans.size, settings)
                statuses: dict[str, dict[str, Any]] = done['benchmarks']
                ans.results = [load_result(name, info, os.path.join(d, f'results-{name}.json')) for name, info in statuses.items()]
        except (OSError, ValueError, KeyError, IndexError) as e:
            ans.error = f'failed to read results: {e}'
        finally:
            ans.wall_time = time.monotonic() - start
            kill_process_group(proc)
            if t.cleanup is not None:
                t.cleanup(d)
            stack.close()
    return ans


def run_in_launched_terminal(
    proc: subprocess.Popen[bytes],
    window_pid: int,
    d: str,
    marker: str,
    args: argparse.Namespace,
    settings: Settings,
    progress: Callable[[str], None],
) -> str:
    if err := wait_for(lambda: os.path.exists(os.path.join(d, READY_FILE)), proc, 60):
        return f'terminal did not start: {err}'
    if args.sway:
        if err := sway_float(window_pid, marker, settings.window_width, settings.window_height):
            return f'could not resize the window: {err}'
        time.sleep(0.5)  # let the terminal process the resize
    with open(os.path.join(d, GO_FILE), 'w'):
        pass
    progress_file = os.path.join(d, PROGRESS_FILE)
    last_progress = ''

    def report_progress() -> None:
        nonlocal last_progress
        try:
            with open(progress_file) as f:
                current = f.read()
        except FileNotFoundError:
            return
        if current and current != last_progress:
            last_progress = current
            progress(current)

    # The inner process enforces the per benchmark timeout, allow some extra time for startup and cleanup
    timeout = (args.benchmark_timeout + 30) * len(args.benchmarks) + 60
    if err := wait_for(lambda: os.path.exists(os.path.join(d, DONE_FILE)), proc, timeout, report_progress):
        return f'benchmark did not complete: {err}'
    return ''


def write_atomic(path: str, data: str) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(data)
    os.replace(tmp, path)


def recover_tty_after_kill(tty_fd: int) -> None:
    import termios

    # Wait for the terminal to process whatever is left in the pty buffer, reset
    # it and then discard any responses it sent to queries
    os.write(tty_fd, b'\x1b[?2026l\x1b[m\x1bc')
    time.sleep(1)
    termios.tcflush(tty_fd, termios.TCIFLUSH)


def inner_main(argv: list[str]) -> None:
    """Runs inside the terminal being benchmarked"""
    d, marker, kitten, repetitions, timeout_str, *benchmarks = argv
    timeout = float(timeout_str)
    tty_fd = os.open('/dev/tty', os.O_RDWR | os.O_CLOEXEC)
    os.write(tty_fd, f'\x1b]2;{marker}\x1b\\Waiting to start benchmark...\r\n'.encode())
    write_atomic(os.path.join(d, READY_FILE), json.dumps({'pid': os.getpid()}))
    go = os.path.join(d, GO_FILE)
    while not os.path.exists(go):
        time.sleep(0.05)
    size = os.get_terminal_size(tty_fd)
    statuses: dict[str, dict[str, str]] = {}
    for name in benchmarks:
        write_atomic(os.path.join(d, PROGRESS_FILE), name)
        with open(os.path.join(d, f'log-{name}.txt'), 'w+') as log:
            p = subprocess.Popen(
                [kitten, '__benchmark__', '--repetitions', repetitions, '--output', os.path.join(d, f'results-{name}.json'), name],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                recover_tty_after_kill(tty_fd)
                statuses[name] = {'status': 'timeout', 'error': f'took longer than {timeout:.0f} seconds'}
                continue
            if rc == 0:
                statuses[name] = {'status': 'ok'}
            else:
                log.seek(0)
                statuses[name] = {'status': 'failed', 'error': f'exit code {rc}: {log.read()[-1000:].strip()}'}
    write_atomic(os.path.join(d, DONE_FILE), json.dumps({'benchmarks': statuses, 'size': f'{size.columns}x{size.lines}'}))


# }}}


# Output {{{


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *codes: int) -> str:
        if not self.enabled or not codes:
            return text
        return f'\x1b[{";".join(map(str, codes))}m{text}\x1b[m'

    def bold(self, text: str) -> str:
        return self(text, 1)

    def dim(self, text: str) -> str:
        return self(text, 2)

    def green(self, text: str) -> str:
        return self(text, 32)

    def red(self, text: str) -> str:
        return self(text, 31)

    def yellow(self, text: str) -> str:
        return self(text, 33)

    def cyan(self, text: str) -> str:
        return self(text, 36)


ANSI_PAT = re.compile(r'\x1b\[[0-9;]*m')


def visible_len(text: str) -> int:
    return len(ANSI_PAT.sub('', text))


def pad(text: str, width: int, right: bool = True) -> str:
    p = ' ' * max(0, width - visible_len(text))
    return p + text if right else text + p


def table(header: Sequence[str], rows: Sequence[Sequence[str]], style: Style) -> str:
    widths = [max(visible_len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    lines = ['  '.join(pad(style.bold(h), w, i > 0) for i, (h, w) in enumerate(zip(header, widths)))]
    lines.append(style.dim('  '.join('─' * w for w in widths)))
    for r in rows:
        lines.append('  '.join(pad(c, w, i > 0) for i, (c, w) in enumerate(zip(r, widths))))
    return '\n'.join(lines)


def fmt_cells(x: float) -> str:
    return f'{x / 1e6:.1f}M' if x else '-'


def fmt_duration(x: float) -> str:
    return f'{x:.2f}s' if x < 60 else f'{int(x // 60)}m{x % 60:04.1f}s'


def print_terminal_run(r: TerminalRun, style: Style) -> None:
    title = style.bold(style.cyan(r.terminal))
    meta = ', '.join(x for x in (r.version, f'{r.size} cells' if r.size else '', f'took {fmt_duration(r.wall_time)}') if x)
    print(f'{title} {style.dim(f"({meta})")}')
    if r.size_warning:
        print(style.yellow(f'  WARNING: {r.size_warning}'))
    if r.error:
        print(style.red(f'  FAILED: {r.error}'))
        print()
        return
    rows = []
    for b in r.results:
        if b.status == 'ok':
            rows.append([b.name, f'{b.mb_per_second:.1f}', fmt_cells(b.cells_per_second), fmt_duration(b.duration), f'{b.data_size / (1024 * 1024):.0f} MB'])
        else:
            rows.append([b.name, style.red(b.status), '', '', ''])
    print('\n'.join('  ' + x for x in table(['Benchmark', 'MB/s', 'Cells/s', 'Time', 'Data'], rows, style).splitlines()))
    for b in r.results:
        if b.status != 'ok':
            print(style.red(f'  {b.name} {b.status}: {b.error}'))
    print()


def print_summary(runs: list[TerminalRun], style: Style) -> None:
    ok = [r for r in runs if r.results and not r.error]
    if not ok:
        return
    names: list[str] = []
    for r in ok:
        for b in r.results:
            if b.name not in names:
                names.append(b.name)
    print(
        style.bold('Summary: throughput in MB/s, higher is better. ')
        + style.dim('Fastest in green, slowest in red, (n×) is how many times slower than the fastest.')
    )
    rows = []
    for name in names:
        vals = {r.terminal: b.mb_per_second for r in ok for b in r.results if b.name == name and b.status == 'ok'}
        statuses = {r.terminal: b.status for r in ok for b in r.results if b.name == name}
        best, worst = max(vals.values(), default=0), min(vals.values(), default=0)
        row = [name]
        for r in ok:
            v = vals.get(r.terminal)
            if v is None:
                row.append(style.red(statuses.get(r.terminal, '-')))
                continue
            text = f'{v:.1f}'
            if v == best:
                text = style.bold(style.green(text))
            elif len(vals) > 2 and v == worst:
                text = style.red(text)
            if v != best and v > 0:
                text += style.dim(f' ({best / v:.1f}×)')
            row.append(text)
        rows.append(row)
    print(table(['Benchmark'] + [r.terminal for r in ok], rows, style))
    print()


# }}}


def parse_args() -> argparse.Namespace:
    terminal_names = [t.name for t in all_terminals()]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('benchmarks', nargs='*', help='Benchmarks to run, by default all are run. See kitten __benchmark__ --help for the list')
    p.add_argument(
        '--terminals', '-t', default=','.join(terminal_names), help=f'Comma separated list of terminals to benchmark, from: {", ".join(terminal_names)}'
    )
    p.add_argument('--repetitions', '-r', type=int, default=500, help='The number of repetitions of each benchmark. Default: %(default)s')
    p.add_argument('--font-family', default='DejaVu Sans Mono', help='Font family to use in all terminals. Default: %(default)s')
    p.add_argument('--font-size', type=float, default=11, help='Font size in pts to use in all terminals. Default: %(default)s')
    p.add_argument('--columns', type=int, default=120, help='Initial window width in cells. Default: %(default)s')
    p.add_argument('--lines', type=int, default=40, help='Initial window height in cells. Default: %(default)s')
    p.add_argument(
        '--window-size',
        default='',
        help='Window size in pixels, used only when running under sway. Under sway, windows are made floating so that tiling does not'
        ' override the initial size in cells. If this is specified they are additionally resized to it.',
    )
    p.add_argument('--cpus', default='', help='Comma separated list of CPUs to pin the terminals to, overrides automatic fast core detection')
    p.add_argument('--all-smt-threads', action='store_true', help='Use all SMT threads of the fast cores instead of one per core')
    p.add_argument('--no-governor', action='store_true', help='Do not change the CPU frequency governor')
    p.add_argument('--no-sway', action='store_true', help='Do not use sway to make window sizes identical, even if running under sway')
    p.add_argument(
        '--benchmark-timeout',
        type=float,
        default=180,
        help='Max time in seconds for each benchmark in each terminal, after which it is aborted and reported as timed out. Default: %(default)s',
    )
    p.add_argument('--output', '-o', default='', help='Also write all results as JSON to the specified file')
    p.add_argument('--verbose', '-v', action='store_true', help='Print the command lines used to run the terminals')
    args = p.parse_args()
    args.sway = sway_available() and not args.no_sway
    if args.benchmarks:
        avail = available_benchmarks()
        if unknown := [x for x in args.benchmarks if x not in avail]:
            raise SystemExit(f'Unknown benchmarks: {", ".join(unknown)}. Choose from: {", ".join(avail)}')
    else:
        args.benchmarks = available_benchmarks()
    return args


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == '--inner':
        inner_main(sys.argv[2:])
        return
    if not sys.platform.startswith('linux'):
        raise SystemExit('This script only works on Linux')
    args = parse_args()
    # Ensure cleanup code (killing terminals, restoring the governor) runs when terminated
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    style = Style(sys.stdout.isatty())
    err_style = Style(sys.stderr.isatty())
    wanted = [x.strip() for x in args.terminals.split(',') if x.strip()]
    known = {t.name: t for t in all_terminals()}
    if unknown := [x for x in wanted if x not in known]:
        raise SystemExit(f'Unknown terminals: {", ".join(unknown)}')
    terminals = [known[x] for x in wanted]
    missing = [t.name for t in terminals if not is_installed(t)]
    terminals = [t for t in terminals if is_installed(t)]
    if not terminals:
        raise SystemExit('None of the terminals are installed')
    ww = wh = 0
    if args.window_size:
        try:
            ww, wh = map(int, args.window_size.lower().split('x'))
        except ValueError:
            raise SystemExit(f'Invalid window size: {args.window_size}')
    settings = Settings(args.font_family, args.font_size, args.columns, args.lines, ww, wh)
    kitten_exe()  # fail early if not found
    if args.cpus:
        cpus, cpu_how = parse_cpu_list(args.cpus), 'specified on command line'
    else:
        cpus, cpu_how = detect_fast_cpus(not args.all_smt_threads)
    if shutil.which('fc-list'):
        fc = subprocess.run(['fc-list', f'{settings.font_family}:spacing=mono', 'family'], capture_output=True, text=True)
        if not fc.stdout.strip():
            print(
                err_style.yellow(f'Warning: the font {settings.font_family!r} does not seem to be installed, terminals will use fallback fonts'),
                file=sys.stderr,
            )

    def log(msg: str) -> None:
        if args.verbose:
            print(err_style.dim(msg), file=sys.stderr)

    runs: list[TerminalRun] = []
    with performance_governor(not args.no_governor) as governor:
        print(style.bold('Comparative terminal benchmark'))
        print(f'  CPUs:      {",".join(map(str, cpus))} ({cpu_how})')
        print(f'  Governor:  {governor}')
        print(f'  Font:      {settings.font_family} {fmt_size(settings.font_size)}pt')
        win = f'{settings.columns}x{settings.lines} cells'
        if args.sway:
            win += f', resized to {ww}x{wh} pixels' if ww else ', floating sway window'
        print(f'  Window:    {win}')
        print(f'  Reps:      {args.repetitions} (timeout of {args.benchmark_timeout:.0f}s per benchmark)')
        if missing:
            print(f'  Skipped:   {", ".join(missing)} (not installed)')
        print()
        sys.stdout.flush()
        for t in terminals:
            print(err_style.dim(f'Benchmarking {t.name}...'), file=sys.stderr)
            r = run_terminal(t, args, settings, cpus, log, lambda name: print(err_style.dim(f'  {name}'), file=sys.stderr))
            runs.append(r)
            print_terminal_run(r, style)
            sys.stdout.flush()
    print_summary(runs, style)
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(
                [
                    {
                        'terminal': r.terminal,
                        'version': r.version,
                        'size': r.size,
                        'size_warning': r.size_warning,
                        'error': r.error,
                        'wall_time': r.wall_time,
                        'results': [b.__dict__ for b in r.results],
                    }
                    for r in runs
                ],
                f,
                indent=2,
            )


if __name__ == '__main__':
    main()
