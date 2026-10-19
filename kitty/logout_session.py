#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Save the state of every kitty instance when the user logs out and restore it the next time kitty is started.
#
# Every kitty instance saves a snapshot, a directory in snapshots_dir() named by its pid, containing the session, the scrollback
# of its windows and the command line, working directory and environment of the instance. When kitty is started, it claims all
# snapshots by renaming them, restores the one saved by an instance with the same command line itself and starts a new kitty
# instance for each of the others, so that every instance is restored with its own command line and environment. Snapshots are
# deleted only after they have been restored.
#
# On macOS, snapshots are encrypted with a random key per snapshot, stored in the macOS Keychain. The Keychain is never allowed to
# show any UI, if it needs user interaction, saving or restoring fails instead. The key is deleted before the snapshot is, so that
# any copies of the snapshot left on disk or in backups cannot be read. On Linux, there is no way to store the key securely without
# user interaction, so snapshots are not encrypted and are protected only by their file permissions.
#
# On macOS, the OS asks kitty to quit when the user logs out and the snapshot is saved when the quit is confirmed. On Linux, the
# desktop portal tells kitty that the session is about to end and kitty is then killed, so the snapshot is saved immediately and is
# deleted if the logout is cancelled.
#
# An instance that saved a snapshot holds a lock on a file in it for as long as it is running, so that the snapshot of an instance
# that is still running, for example because the logout was cancelled, is never claimed. The kernel releases the lock when the
# instance dies, however it dies.

import fcntl
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from gettext import gettext as _
from typing import TYPE_CHECKING, NamedTuple, Protocol

from .constants import cache_dir, clear_handled_signals, is_macos, kitty_exe
from .fast_data_types import AES256GCMDecrypt, AES256GCMEncrypt, Screen, Secret, application_logout_requested_at, get_options, monotonic, random_secret
from .options.types import Options
from .typing_compat import BossType
from .utils import is_pid_alive, kitty_ansi_sanitizer_pat, lock_with_file, log_error, run_once

if TYPE_CHECKING:
    from .session import Session

SESSION_FILE = 'session.kitty-session'
PROCESS_FILE = 'process.json'
SCROLLBACK_DIR = 'scrollback'
ATTEMPTS_FILE = 'attempts'
KEY_ID_FILE = 'key-id'
SAVER_LOCK_FILE = 'saver.lock'
KEY_ID_BYTES = 16
KEYCHAIN_SERVICE = 'net.kovidgoyal.kitty.session-saved-at-logout'
ENCRYPTED_FILE_MAGIC = b'kitty-snapshot-1'
IV_SIZE, TAG_SIZE = 12, 16
CLAIMED_MARKER = '.claimed-by-'
# A snapshot that has failed to be restored this many times, for example because kitty crashed, is deleted
MAX_RESTORE_ATTEMPTS = 2
# The environment variable used to tell a kitty instance started to restore a snapshot which snapshot to restore
SNAPSHOT_ENV_VAR = 'KITTY_RESTORE_LOGOUT_SNAPSHOT'
# A quit confirmed by the user later than this many seconds after the OS asked kitty to quit for a logout is treated as an
# ordinary quit, since the OS will have given up on the logout by then
LOGOUT_CONFIRMATION_TIMEOUT = 60
# Environment variables that refer to the login session, such as the display server and the session bus. A kitty instance started to
# restore a snapshot gets these from the kitty instance that started it, as the saved values refer to the login session that ended.
LOGIN_SESSION_ENV_VARS = frozenset(
    (
        'DBUS_SESSION_BUS_ADDRESS',
        'DESKTOP_SESSION',
        'DISPLAY',
        'GPG_AGENT_INFO',
        'HYPRLAND_INSTANCE_SIGNATURE',
        'I3SOCK',
        'NIRI_SOCKET',
        'SESSION_MANAGER',
        'SSH_AGENT_PID',
        'SSH_AUTH_SOCK',
        'SWAYSOCK',
        'WAYLAND_DISPLAY',
        'XAUTHORITY',
        'XDG_CURRENT_DESKTOP',
        'XDG_RUNTIME_DIR',
        'XDG_SEAT',
        'XDG_SESSION_CLASS',
        'XDG_SESSION_DESKTOP',
        'XDG_SESSION_ID',
        'XDG_SESSION_TYPE',
        'XDG_VTNR',
    )
)
# Environment variables used to pass a single use token to a newly started application, never passed on to restored instances
STARTUP_TOKEN_ENV_VARS = frozenset(('DESKTOP_STARTUP_ID', 'XDG_ACTIVATION_TOKEN', 'WAYLAND_SOCKET'))
# The session states reported by the Inhibit desktop portal on Linux
DESKTOP_SESSION_RUNNING, DESKTOP_SESSION_QUERY_END, DESKTOP_SESSION_ENDING = 1, 2, 3


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


class KeyStore(Protocol):
    def store(self, key_id: str, key: Secret) -> None: ...
    def read(self, key_id: str) -> Secret | None: ...
    def delete(self, key_id: str) -> None: ...
    def list_ids(self) -> list[str]: ...


class MacOSKeychain:
    def store(self, key_id: str, key: Secret) -> None:
        from .fast_data_types import cocoa_keychain_store_secret

        cocoa_keychain_store_secret(KEYCHAIN_SERVICE, key_id, _('kitty session saved at logout'), key)

    def read(self, key_id: str) -> Secret | None:
        from .fast_data_types import cocoa_keychain_read_secret

        return cocoa_keychain_read_secret(KEYCHAIN_SERVICE, key_id)

    def delete(self, key_id: str) -> None:
        from .fast_data_types import cocoa_keychain_delete

        cocoa_keychain_delete(KEYCHAIN_SERVICE, key_id)

    def list_ids(self) -> list[str]:
        from .fast_data_types import cocoa_keychain_list_accounts

        return cocoa_keychain_list_accounts(KEYCHAIN_SERVICE)


def get_key_store() -> KeyStore | None:
    # Snapshots are encrypted only on platforms that have a key store that can be used without user interaction
    return MacOSKeychain() if is_macos else None


def encrypt(key: Secret, name: str, data: bytes) -> bytes:
    # The name of the file is authenticated, so that files cannot be swapped
    e = AES256GCMEncrypt(key)
    e.add_authenticated_but_unencrypted_data(ENCRYPTED_FILE_MAGIC + name.encode())
    ciphertext = e.add_data_to_be_encrypted(data, True)
    if len(e.iv) != IV_SIZE or len(e.tag) != TAG_SIZE:
        raise ValueError(f'Unexpected IV or tag size when encrypting: {len(e.iv)}, {len(e.tag)}')
    return ENCRYPTED_FILE_MAGIC + e.iv + e.tag + ciphertext


def decrypt(key: Secret, name: str, data: bytes) -> bytes:
    h = len(ENCRYPTED_FILE_MAGIC)
    if not data.startswith(ENCRYPTED_FILE_MAGIC) or len(data) < h + IV_SIZE + TAG_SIZE:
        raise ValueError(f'{name} in the snapshot is not a valid encrypted file')
    d = AES256GCMDecrypt(key, data[h : h + IV_SIZE], data[h + IV_SIZE : h + IV_SIZE + TAG_SIZE])
    d.add_data_to_be_authenticated_but_not_decrypted(ENCRYPTED_FILE_MAGIC + name.encode())
    return d.add_data_to_be_decrypted(data[h + IV_SIZE + TAG_SIZE :], True)


def write_snapshot_file(snapshot_dir: str, key: Secret | None, name: str, data: bytes) -> None:
    write_private_file(os.path.join(snapshot_dir, name), data if key is None else encrypt(key, name, data))


def read_snapshot_file(snapshot_dir: str, key: Secret | None, name: str) -> bytes:
    with open(os.path.join(snapshot_dir, name), 'rb') as f:
        data = f.read()
    return data if key is None else decrypt(key, name, data)


def read_key_id(snapshot_dir: str) -> str:
    try:
        with open(os.path.join(snapshot_dir, KEY_ID_FILE)) as f:
            return f.read()
    except (FileNotFoundError, NotADirectoryError):
        return ''


def snapshot_key(snapshot_dir: str, key_store: KeyStore | None) -> Secret | None:
    # Returns None if snapshots are not encrypted on this platform
    key_id = read_key_id(snapshot_dir)
    if key_store is None:
        if key_id:
            raise ValueError('The snapshot is encrypted, but there is no key store to read its key from')
        return None
    if not key_id:
        raise ValueError('The snapshot has no encryption key id')
    key = key_store.read(key_id)
    if key is None:
        raise ValueError('The encryption key for the snapshot is not in the keychain')
    return key


def delete_key(key_store: KeyStore, key_id: str, path: str) -> None:
    try:
        key_store.delete(key_id)
    except OSError as e:
        log_error(f'Failed to delete the encryption key for the session saved at logout in {path} from the keychain. Error: {e}')


def new_key_id() -> str:
    return secrets.token_hex(KEY_ID_BYTES)


@run_once
def key_id_pat() -> 're.Pattern[str]':
    return re.compile(f'[0-9a-f]{{{2 * KEY_ID_BYTES}}}')


def remove_orphaned_keys(base: str, key_store: KeyStore | None) -> None:
    # Must be called with the lock held. Deletes the keys of snapshots that no longer exist, for example because they were deleted
    # by something other than kitty. Snapshots being saved or restored hold the lock, so their keys are never orphans here.
    if key_store is None:
        return
    try:
        key_ids = key_store.list_ids()
    except OSError as e:
        log_error(f'Failed to list the encryption keys for sessions saved at logout in the keychain. Error: {e}')
        return
    used = set()
    with suppress(FileNotFoundError), os.scandir(base) as entries:
        for entry in entries:
            if key_id := read_key_id(entry.path):
                used.add(key_id)
    pat = key_id_pat()
    for key_id in key_ids:
        # Only keys created by kitty, so items added by anything else with the same service are not touched
        if key_id not in used and pat.fullmatch(key_id) is not None:
            delete_key(key_store, key_id, base)


def remove_snapshot(path: str, key_store: KeyStore | None) -> None:
    # The key is deleted first, so that the snapshot cannot be read even if deleting its files fails or leaves copies on disk
    if (key_id := read_key_id(path)) and key_store is not None:
        delete_key(key_store, key_id, path)
    remove_path(path)


process_state = ProcessState((), '', {}, time.time())
# The path and locked file descriptor of the snapshot saved by this kitty instance, if any
saver_lock: tuple[str, int] | None = None
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


def lock_snapshot_for_saver(path: str) -> None:
    # Must be called with the lock held, by the kitty instance that saved the snapshot. Raises OSError if the lock cannot be taken.
    global saver_lock
    release_saver_lock()
    fd = os.open(os.path.join(path, SAVER_LOCK_FILE), os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise
    saver_lock = path, fd


def release_saver_lock(path: str = '') -> None:
    # Releases the lock on the snapshot saved by this instance, if path is empty or is the path of that snapshot
    global saver_lock
    if saver_lock is not None and (not path or saver_lock[0] == path):
        fd, saver_lock = saver_lock[1], None
        os.close(fd)


def is_saver_running(path: str) -> bool:
    try:
        fd = os.open(os.path.join(path, SAVER_LOCK_FILE), os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


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


def save_snapshot(base: str, pid: int, session: str, scrollback: Mapping[int, bytes], state: ProcessState, key_store: KeyStore | None) -> str:
    # Must be called with the lock held. Nothing is saved if the key cannot be stored. The snapshot is written to a temporary
    # directory and renamed, so that an incomplete snapshot is never restored. The snapshot is encrypted only if there is a key store.
    key: Secret | None = None
    key_id = ''
    if key_store is not None:
        key, key_id = random_secret(), new_key_id()
        key_store.store(key_id, key)
    tdir = ''
    try:
        os.makedirs(base, mode=0o700, exist_ok=True)
        tdir = tempfile.mkdtemp(dir=base, prefix=f'{pid}.', suffix='.tmp')
        if key_id:
            write_private_file(os.path.join(tdir, KEY_ID_FILE), key_id.encode())
        os.mkdir(os.path.join(tdir, SCROLLBACK_DIR), 0o700)
        for window_id, data in scrollback.items():
            write_snapshot_file(tdir, key, f'{SCROLLBACK_DIR}/{window_id}', data)
        pdata = {'argv': state.argv, 'cwd': state.cwd, 'environ': state.environ, 'saved_at': time.time()}
        write_snapshot_file(tdir, key, PROCESS_FILE, json.dumps(pdata).encode())
        write_snapshot_file(tdir, key, SESSION_FILE, session.encode())
        path = os.path.join(base, str(pid))
        remove_snapshot(path, key_store)
        os.rename(tdir, path)
    except BaseException:
        if tdir:
            remove_path(tdir)
        if key_store is not None:
            delete_key(key_store, key_id, tdir or base)
        raise
    return path


def remove_stale_snapshots(base: str, started_at: float, key_store: KeyStore | None) -> None:
    # Must be called with the lock held. All kitty instances running at a logout quit, so the running instances were all started
    # after it. Snapshots older than this instance are therefore from an earlier logout, and were never restored.
    try:
        with os.scandir(base) as entries:
            for entry in entries:
                if entry.stat(follow_symlinks=False).st_mtime < started_at:
                    remove_snapshot(entry.path, key_store)
    except FileNotFoundError:
        pass
    remove_orphaned_keys(base, key_store)


def save_session_at_logout(boss: BossType) -> str:
    # Returns the path to the saved snapshot or an empty string if there was nothing to save
    from .session import default_save_as_session_opts, parse_session

    ser_opts = default_save_as_session_opts()
    ser_opts.os_window_geometry = True
    session = '\n'.join(boss.serialize_state_as_session('', ser_opts))
    base = snapshots_dir()
    os.makedirs(os.path.dirname(base), exist_ok=True)
    key_store = get_key_store()
    with lock_with_file(lock_path(base)):
        remove_stale_snapshots(base, process_state.started_at, key_store)
        if not session:
            return ''
        serialized_ids = {w.serialized_id for s in parse_session(session, get_options()) for t in s.tabs for w in t.windows}
        scrollback = {}
        for window in boss.all_windows:
            if window.id in serialized_ids and (data := scrollback_for_restore(window.screen)):
                scrollback[window.id] = data
        path = save_snapshot(base, os.getpid(), session, scrollback, process_state, key_store)
        try:
            lock_snapshot_for_saver(path)
        except OSError as e:
            # The snapshot is still useful, but could be restored by another kitty instance while this one is running
            log_error(f'Failed to lock the session saved at logout in {path}. Error: {e}')
        return path


def is_logout_in_progress() -> bool:
    requested_at = application_logout_requested_at()
    return requested_at >= 0 and monotonic() - requested_at <= LOGOUT_CONFIRMATION_TIMEOUT


def parse_claimed_name(name: str) -> tuple[str, int]:
    # Returns the name of the snapshot and the pid of the process that claimed it, which is zero if it is not claimed
    snapshot_name, sep, claimer = name.partition(CLAIMED_MARKER)
    if not snapshot_name.isdigit() or (sep and not claimer.isdigit()):
        return '', 0
    return snapshot_name, int(claimer or 0)


def read_snapshot(path: str, key: Secret | None) -> Snapshot:
    pdata = json.loads(read_snapshot_file(path, key, PROCESS_FILE))
    argv, cwd, environ = pdata['argv'], pdata['cwd'], pdata['environ']
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise ValueError('Invalid command line in the snapshot')
    if not isinstance(cwd, str):
        raise ValueError('Invalid working directory in the snapshot')
    if not isinstance(environ, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in environ.items()):
        raise ValueError('Invalid environment in the snapshot')
    return Snapshot(path, ProcessState(tuple(argv), cwd, environ, 0), float(pdata['saved_at']))


def claim_snapshots(base: str, pid: int, key_store: KeyStore | None, is_alive: Callable[[int], bool] = is_pid_alive) -> list[Snapshot]:
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
            if not claimer and is_saver_running(os.path.join(base, name)):
                # The instance that saved it is still running, for example, because the logout was cancelled
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
                    remove_snapshot(path, key_store)
                    continue
                with open(attempts_path, 'w') as f:
                    f.write(str(attempts + 1))
                ans.append(read_snapshot(path, snapshot_key(path, key_store)))
            except Exception as e:
                log_error(f'Failed to read the session saved at logout in {path}, deleting it. Error: {e}')
                remove_snapshot(path, key_store)
        remove_orphaned_keys(base, key_store)
    ans.sort(key=lambda s: s.saved_at)
    return ans


def load_snapshot(path: str, opts: Options, key_store: KeyStore | None) -> tuple['Session', ...]:
    from .session import parse_session

    key = snapshot_key(path, key_store)
    raw = read_snapshot_file(path, key, SESSION_FILE).decode()
    saved_at = read_snapshot(path, key).saved_at
    sessions = tuple(parse_session(raw, opts))
    marker = '\r\n\x1b[m\x1b[7m ' + _('Restored from {}').format(time.strftime('%c', time.localtime(saved_at))) + ' \x1b[m\r\n'
    for session in sessions:
        for tab in session.tabs:
            for window in tab.windows:
                with suppress(FileNotFoundError):
                    data = read_snapshot_file(path, key, f'{SCROLLBACK_DIR}/{window.serialized_id}')
                    window.restored_scrollback = (sanitize_restored_output(data.decode('utf-8', 'replace')) + marker).encode()
    return sessions


def environment_for_snapshot(saved: Mapping[str, str], current: Mapping[str, str]) -> dict[str, str]:
    env = {k: v for k, v in saved.items() if k not in LOGIN_SESSION_ENV_VARS and k not in STARTUP_TOKEN_ENV_VARS}
    env.update((k, v) for k, v in current.items() if k in LOGIN_SESSION_ENV_VARS)
    return env


def start_instance_for_snapshot(snapshot: Snapshot) -> None:
    import subprocess

    env = environment_for_snapshot(snapshot.process_state.environ, process_state.environ)
    env[SNAPSHOT_ENV_VAR] = snapshot.path
    cwd = snapshot.process_state.cwd
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser('~')
    subprocess.Popen(
        (kitty_exe(),) + snapshot.process_state.argv,
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        preexec_fn=clear_handled_signals,
    )


class RestoredSnapshot(NamedTuple):
    path: str
    sessions: tuple['Session', ...]


def load_or_discard_snapshot(path: str, opts: Options) -> RestoredSnapshot | None:
    key_store = get_key_store()
    try:
        return RestoredSnapshot(path, load_snapshot(path, opts, key_store))
    except Exception as e:
        log_error(f'Failed to restore the session saved at logout in {path}, deleting it. Error: {e}')
        remove_snapshot(path, key_store)
    return None


def restore_snapshots(opts: Options, argv: tuple[str, ...]) -> RestoredSnapshot | None:
    """
    Claims all snapshots, starting new kitty instances for the ones saved by kitty instances with a different command line and
    returns the one to restore in this kitty instance, if any. Errors are logged, so that they never prevent kitty from starting.
    """
    try:
        snapshots = claim_snapshots(snapshots_dir(), os.getpid(), get_key_store())
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


def delete_snapshot(path: str) -> None:
    with lock_with_file(lock_path(os.path.dirname(path))):
        remove_snapshot(path, get_key_store())
        release_saver_lock(path)


def finish_restore(path: str) -> None:
    # Called once the windows of a restored snapshot have been created, as a snapshot is restored only once
    delete_snapshot(path)


def remove_all_snapshots() -> None:
    base = snapshots_dir()
    if os.path.exists(base):
        key_store = get_key_store()
        with lock_with_file(lock_path(base)):
            with os.scandir(base) as entries:
                for entry in entries:
                    remove_snapshot(entry.path, key_store)
            remove_path(base)
            remove_orphaned_keys(base, key_store)
