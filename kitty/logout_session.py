#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Save the state of every kitty instance when the user logs out and restore it the next time kitty is started.
#
# Every kitty instance saves a snapshot, a directory in snapshots_dir() named by its pid, containing the session, the scrollback
# of its windows and the command line, working directory and environment of the instance. When kitty is started, it claims all
# snapshots by renaming them, restores the one saved by an instance with the same command line itself and starts a new kitty
# instance for each of the others, so that every instance is restored with its own command line and environment. Snapshots are
# deleted only after they have been restored.

import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from gettext import gettext as _
from typing import TYPE_CHECKING, NamedTuple

from .constants import cache_dir, clear_handled_signals, kitty_exe
from .fast_data_types import Screen, application_logout_requested_at, get_options, monotonic
from .options.types import Options
from .typing_compat import BossType
from .utils import is_pid_alive, kitty_ansi_sanitizer_pat, lock_with_file, log_error, run_once

if TYPE_CHECKING:
    from .session import Session

SESSION_FILE = 'session.kitty-session'
PROCESS_FILE = 'process.json'
SCROLLBACK_DIR = 'scrollback'
ATTEMPTS_FILE = 'attempts'
CLAIMED_MARKER = '.claimed-by-'
# A snapshot that has failed to be restored this many times, for example because kitty crashed, is deleted
MAX_RESTORE_ATTEMPTS = 2
# The environment variable used to tell a kitty instance started to restore a snapshot which snapshot to restore
SNAPSHOT_ENV_VAR = 'KITTY_RESTORE_LOGOUT_SNAPSHOT'
# A quit confirmed by the user later than this many seconds after the OS asked kitty to quit for a logout is treated as an
# ordinary quit, since the OS will have given up on the logout by then
LOGOUT_CONFIRMATION_TIMEOUT = 60


class ProcessState(NamedTuple):
    argv: tuple[str, ...]
    cwd: str
    environ: dict[str, str]
    # The wall clock time at which the process was started
    started_at: float


class Snapshot(NamedTuple):
    path: str
    process_state: ProcessState
    saved_at: float


process_state = ProcessState((), '', {}, time.time())
# The snapshot this kitty instance was started to restore by the kitty instance that claimed it, if any
snapshot_requested_by_parent = ''


def record_process_state(argv: tuple[str, ...]) -> None:
    # Must be called at startup, before kitty reads or changes the environment. Removes the snapshot requested by the parent from
    # the environment, so that it is not inherited by child processes.
    global process_state, snapshot_requested_by_parent
    snapshot_requested_by_parent = os.environ.pop(SNAPSHOT_ENV_VAR, '')
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ''  # the working directory was deleted, the home directory is used instead when restoring
    process_state = ProcessState(argv, cwd, dict(os.environ), time.time())


def snapshots_dir() -> str:
    return os.path.join(cache_dir(), 'saved-at-logout')


def lock_path(base: str) -> str:
    return base + '.lock'


def remove_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    else:
        with suppress(FileNotFoundError):
            os.remove(path)


def write_private_file(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with open(fd, 'wb') as f:
        f.write(data)


def scrollback_for_restore(screen: Screen) -> bytes:
    # The output in the main screen and its scrollback (but not the scrollback pager history), formatted, ready to be parsed by a
    # new screen. The current shell prompt, if any, is not included, as the restored shell will show a new one, and neither are
    # trailing blank lines. Wrapped lines are joined so that they are re-wrapped to the width of the new screen.
    history: list[str] = []
    screen.as_text_for_history_buf(history.append, True, True)
    on_screen: list[str] = []
    if screen.is_using_alternate_linebuf():
        screen.as_text_alternate(on_screen.append, True, True)
        prompt_line = -1  # the cursor is on the alternate screen
    else:
        screen.as_text_non_visual(on_screen.append, True, True)
        prompt_line = screen.cursor_prompt_line()
    # With wrap markers every line ends with \r, followed by \n unless the line is continued on the next line
    screen_lines = ''.join(on_screen).split('\r')
    if prompt_line > -1:
        del screen_lines[prompt_line:-1]
    text = ''.join(history).replace('\r', '') + '\x1b[m' + ''.join(screen_lines)
    lines = text.split('\n')
    pat = kitty_ansi_sanitizer_pat()
    while lines and not pat.sub('', lines[-1]).strip():
        lines.pop()
    return '\r\n'.join(lines).encode()


@run_once
def restored_output_sanitizer_pat() -> 're.Pattern[str]':
    allowed = r'\x1b\[[0-9:;]*m|\x1b\](?:8|66);[^\x07\x1b]*(?:\x07|\x1b\\)'
    escape_code = r'\x1b(?:\[[0-?]*[ -/]*[@-~]?|[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\)?|.?)'
    controls = r'[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f-\x9f]'
    return re.compile(f'({allowed})|{escape_code}|{controls}', re.DOTALL)


def sanitize_restored_output(text: str) -> str:
    # Restored output is parsed as though it came from the child, so allow only the escape codes kitty uses for formatting text:
    # SGR, hyperlinks (OSC 8) and text sizing (OSC 66). Shell integration marks (OSC 133) are removed as well, so that the
    # restored output is not treated as the output of commands run in the window.
    return restored_output_sanitizer_pat().sub(lambda m: m.group(1) or '', text)


def save_snapshot(base: str, pid: int, session: str, scrollback: Mapping[int, bytes], state: ProcessState) -> str:
    # Must be called with the lock held. The snapshot is written to a temporary directory and renamed, so that an incomplete
    # snapshot is never restored.
    os.makedirs(base, mode=0o700, exist_ok=True)
    tdir = tempfile.mkdtemp(dir=base, prefix=f'{pid}.', suffix='.tmp')
    try:
        os.mkdir(os.path.join(tdir, SCROLLBACK_DIR), 0o700)
        for window_id, data in scrollback.items():
            write_private_file(os.path.join(tdir, SCROLLBACK_DIR, str(window_id)), data)
        pdata = {'argv': state.argv, 'cwd': state.cwd, 'environ': state.environ, 'saved_at': time.time()}
        write_private_file(os.path.join(tdir, PROCESS_FILE), json.dumps(pdata).encode())
        write_private_file(os.path.join(tdir, SESSION_FILE), session.encode())
        path = os.path.join(base, str(pid))
        remove_path(path)
        os.rename(tdir, path)
    except BaseException:
        remove_path(tdir)
        raise
    return path


def remove_stale_snapshots(base: str, started_at: float) -> None:
    # Must be called with the lock held. All kitty instances running at a logout quit, so the running instances were all started
    # after it. Snapshots older than this instance are therefore from an earlier logout, and were never restored.
    try:
        with os.scandir(base) as entries:
            for entry in entries:
                if entry.stat(follow_symlinks=False).st_mtime < started_at:
                    remove_path(entry.path)
    except FileNotFoundError:
        pass


def save_session_at_logout(boss: BossType) -> None:
    from .session import default_save_as_session_opts, parse_session

    ser_opts = default_save_as_session_opts()
    ser_opts.os_window_geometry = True
    session = '\n'.join(boss.serialize_state_as_session('', ser_opts))
    base = snapshots_dir()
    os.makedirs(os.path.dirname(base), exist_ok=True)
    with lock_with_file(lock_path(base)):
        remove_stale_snapshots(base, process_state.started_at)
        if not session:
            return
        serialized_ids = {w.serialized_id for s in parse_session(session, get_options()) for t in s.tabs for w in t.windows}
        scrollback = {}
        for window in boss.all_windows:
            if window.id in serialized_ids and (data := scrollback_for_restore(window.screen)):
                scrollback[window.id] = data
        save_snapshot(base, os.getpid(), session, scrollback, process_state)


def is_logout_in_progress() -> bool:
    requested_at = application_logout_requested_at()
    return requested_at >= 0 and monotonic() - requested_at <= LOGOUT_CONFIRMATION_TIMEOUT


def parse_claimed_name(name: str) -> tuple[str, int]:
    # Returns the name of the snapshot and the pid of the process that claimed it, which is zero if it is not claimed
    snapshot_name, sep, claimer = name.partition(CLAIMED_MARKER)
    if not snapshot_name.isdigit() or (sep and not claimer.isdigit()):
        return '', 0
    return snapshot_name, int(claimer or 0)


def read_snapshot(path: str) -> Snapshot:
    with open(os.path.join(path, PROCESS_FILE), 'rb') as f:
        pdata = json.loads(f.read())
    argv, cwd, environ = pdata['argv'], pdata['cwd'], pdata['environ']
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise ValueError('Invalid command line in the snapshot')
    if not isinstance(cwd, str):
        raise ValueError('Invalid working directory in the snapshot')
    if not isinstance(environ, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in environ.items()):
        raise ValueError('Invalid environment in the snapshot')
    return Snapshot(path, ProcessState(tuple(argv), cwd, environ, 0), float(pdata['saved_at']))


def claim_snapshots(base: str, pid: int, is_alive: Callable[[int], bool] = is_pid_alive) -> list[Snapshot]:
    # Claim all snapshots that are not being restored by a running kitty instance
    ans: list[Snapshot] = []
    if not os.path.isdir(base):
        return ans
    with lock_with_file(lock_path(base)):
        with os.scandir(base) as entries:
            names = [e.name for e in entries]
        for name in names:
            snapshot_name, claimer = parse_claimed_name(name)
            if not snapshot_name or (claimer and is_alive(claimer)):
                continue
            path = os.path.join(base, f'{snapshot_name}{CLAIMED_MARKER}{pid}')
            try:
                os.rename(os.path.join(base, name), path)
                attempts_path = os.path.join(path, ATTEMPTS_FILE)
                attempts = 0
                with suppress(FileNotFoundError), open(attempts_path) as f:
                    attempts = int(f.read())
                if attempts >= MAX_RESTORE_ATTEMPTS:
                    log_error(f'Restoring the session saved at logout in {path} failed {attempts} times, deleting it')
                    remove_path(path)
                    continue
                with open(attempts_path, 'w') as f:
                    f.write(str(attempts + 1))
                ans.append(read_snapshot(path))
            except Exception as e:
                log_error(f'Failed to read the session saved at logout in {path}, deleting it. Error: {e}')
                remove_path(path)
    ans.sort(key=lambda s: s.saved_at)
    return ans


def load_snapshot(path: str, opts: Options) -> tuple['Session', ...]:
    from .session import parse_session

    with open(os.path.join(path, SESSION_FILE), encoding='utf-8') as f:
        raw = f.read()
    saved_at = read_snapshot(path).saved_at
    sessions = tuple(parse_session(raw, opts))
    marker = '\r\n\x1b[m\x1b[7m ' + _('Restored from {}').format(time.strftime('%c', time.localtime(saved_at))) + ' \x1b[m\r\n'
    for session in sessions:
        for tab in session.tabs:
            for window in tab.windows:
                with suppress(FileNotFoundError), open(os.path.join(path, SCROLLBACK_DIR, str(window.serialized_id)), 'rb') as f:
                    text = sanitize_restored_output(f.read().decode('utf-8', 'replace'))
                    window.restored_scrollback = (text + marker).encode()
    return sessions


def start_instance_for_snapshot(snapshot: Snapshot) -> None:
    import subprocess

    env = dict(snapshot.process_state.environ)
    env[SNAPSHOT_ENV_VAR] = snapshot.path
    cwd = snapshot.process_state.cwd
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser('~')
    subprocess.Popen(
        (kitty_exe(),) + snapshot.process_state.argv,
        env=env, cwd=cwd, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True, preexec_fn=clear_handled_signals,
    )


class RestoredSnapshot(NamedTuple):
    path: str
    sessions: tuple['Session', ...]


def load_or_discard_snapshot(path: str, opts: Options) -> RestoredSnapshot | None:
    try:
        return RestoredSnapshot(path, load_snapshot(path, opts))
    except Exception as e:
        log_error(f'Failed to restore the session saved at logout in {path}, deleting it. Error: {e}')
        remove_path(path)
    return None


def restore_snapshots(opts: Options, argv: tuple[str, ...]) -> RestoredSnapshot | None:
    '''
    Claims all snapshots, starting new kitty instances for the ones saved by kitty instances with a different command line and
    returns the one to restore in this kitty instance, if any. Errors are logged, so that they never prevent kitty from starting.
    '''
    try:
        snapshots = claim_snapshots(snapshots_dir(), os.getpid())
    except Exception as e:
        log_error(f'Failed to restore the sessions saved at logout, ignoring. Error: {e}')
        return None
    own = next((s for s in snapshots if s.process_state.argv == argv), None)
    for s in snapshots:
        if s is not own:
            try:
                start_instance_for_snapshot(s)
            except Exception as e:
                log_error(f'Failed to start kitty to restore the session saved at logout in {s.path}. Error: {e}')
    return None if own is None else load_or_discard_snapshot(own.path, opts)


def finish_restore(path: str) -> None:
    # Called once the windows of a restored snapshot have been created, as a snapshot is restored only once
    with lock_with_file(lock_path(os.path.dirname(path))):
        remove_path(path)


def remove_all_snapshots() -> None:
    base = snapshots_dir()
    if os.path.exists(base):
        with lock_with_file(lock_path(base)):
            remove_path(base)
