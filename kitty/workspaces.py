#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Workspaces: named groups of tabs that can be saved, switched between and
# restored after a restart. A workspace is simply a kitty session whose
# session file lives in the workspaces directory, so all the session machinery
# (tagging new tabs with the session, switching, etc.) is reused.

import json
import os
import re
import shlex
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from .constants import config_dir, unserialize_launch_flag
from .fast_data_types import add_timer, current_focused_os_window_id, last_focused_os_window_id
from .session import (
    append_to_session_history,
    create_session,
    has_session_extension,
    parse_save_as_options_spec_args,
    seen_session_paths,
    session_arg_to_name,
    switch_to_session,
)
from .utils import log_error

if TYPE_CHECKING:
    from .boss import Boss
    from .tabs import Tab
    from .window import Window

EXTENSION = '.kitty-session'
AUTOSAVE_INTERVAL = 30  # seconds
ACTION_AUTOSAVE_DELAY = 2  # seconds after the user opens or closes a tab or split
# Programs that are safe to re-run when a workspace is restored. Anything else
# that was running in the foreground (for instance rm or git push) is dropped,
# leaving just the shell in its working directory.
DEFAULT_RESTORABLE_PROGRAMS = (
    'claude', 'codex', 'aider', 'gemini', 'opencode',
    'nvim', 'vim', 'vi', 'hx', 'nano', 'micro', 'emacs',
    'htop', 'btop', 'top', 'lazygit', 'tig', 'less', 'man', 'tail', 'watch',
    'ssh', 'mosh',
    'npm', 'pnpm', 'yarn', 'bun', 'deno', 'node', 'python', 'python3', 'ipython', 'uv',
    'cargo', 'go', 'docker',
)


def workspaces_dir() -> str:
    return os.path.join(config_dir, 'workspaces')


def state_path() -> str:
    return os.path.join(workspaces_dir(), 'state.json')


def path_for_name(name: str) -> str:
    return os.path.join(workspaces_dir(), name + EXTENSION)


def sanitize_name(name: str) -> str:
    name = re.sub(r'\s+', '-', name.strip())
    return re.sub(r'[/\\\0]', '', name).strip('.-')


def saved_workspaces() -> dict[str, str]:
    ans = {}
    with suppress(OSError), os.scandir(workspaces_dir()) as entries:
        for entry in entries:
            if entry.is_file() and has_session_extension(entry.name):
                ans[session_arg_to_name(entry.path)] = entry.path
    return ans


def is_workspace(name: str) -> bool:
    return bool(name) and os.path.exists(path_for_name(name))


# State {{{
# What to do with open workspaces when kitty is closed
ON_CLOSE_POLICIES = {
    'ask': 'спрашивать',
    'save': 'всегда сохранять',
    'discard': 'никогда не сохранять',
}
def read_state() -> dict[str, Any]:
    ans: dict[str, Any] = {}
    with suppress(OSError, ValueError), open(state_path()) as f:
        ans = json.load(f)
    if not isinstance(ans, dict):
        ans = {}
    ans.setdefault('restore_on_startup', True)
    ans.setdefault('restorable_programs', list(DEFAULT_RESTORABLE_PROGRAMS))
    ans.setdefault('open', [])
    ans.setdefault('active', '')
    if ans.get('on_close') not in ON_CLOSE_POLICIES:
        ans['on_close'] = 'ask'
    return ans


def write_state(state: dict[str, Any]) -> None:
    from .config import atomic_save
    os.makedirs(workspaces_dir(), exist_ok=True)
    atomic_save(json.dumps(state, indent=2, ensure_ascii=False).encode(), state_path())


lock_fd = -1


def acquire_primary_lock() -> bool:
    ' Only the first kitty instance restores and autosaves workspaces, so that a second instance does not duplicate or clobber them '
    global lock_fd
    if lock_fd > -1:
        return True
    import fcntl
    os.makedirs(workspaces_dir(), exist_ok=True)
    fd = os.open(os.path.join(workspaces_dir(), '.lock'), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    lock_fd = fd  # kept open for the lifetime of the process
    return True
# }}}


# Serialization {{{
def windows_in_workspace(boss: 'Boss', name: str) -> list['Window']:
    return [w for w in boss.all_windows if w.created_in_session_name == name]


def program_of(cmd: str | list[str]) -> str:
    if isinstance(cmd, str):
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()
    else:
        parts = list(cmd)
    while parts and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', parts[0]):  # skip leading env var assignments
        parts.pop(0)
    return os.path.basename(parts[0]) if parts else ''


# Claude Code {{{
# The SessionStart hook installed in ~/.claude/settings.json (see
# claude-session-hook.sh in the kitty-fork config dir) records the session
# running in each kitty window, keyed by kitty PID and window id.
CLAUDE_FLAGS_WITH_VALUE = frozenset((
    '--model', '--permission-mode', '--add-dir', '--settings', '--mcp-config', '--agent', '--agents',
    '--fallback-model', '--allowedTools', '--allowed-tools', '--disallowedTools', '--disallowed-tools',
    '--append-system-prompt', '--system-prompt', '--effort', '--setting-sources', '--plugin-dir',
))
# Flags that must not be carried over: they select a session themselves, or make claude non-interactive
CLAUDE_DROPPED_FLAGS = frozenset(('-c', '--continue', '-r', '--resume', '--session-id', '-p', '--print', '--fork-session'))


def claude_sessions_dir() -> str:
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'kitty-fork', 'claude-sessions')


def claude_session_for_window(window_id: int) -> str:
    try:
        with open(os.path.join(claude_sessions_dir(), f'{os.getpid()}-{window_id}.json')) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ''
    sid = data.get('session_id') if isinstance(data, dict) else None
    if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', sid):
        return ''
    transcript = data.get('transcript_path')
    if isinstance(transcript, str) and transcript and not os.path.exists(transcript):
        return ''  # the conversation was deleted, resuming it would fail
    return sid


def claude_resume_command(cmd: str | list[str], session_id: str) -> str | list[str]:
    ' Rewrite a claude command line to resume the given session, keeping only option flags '
    parts = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    env = []
    while parts and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', parts[0]):
        env.append(parts.pop(0))
    exe, args = parts[0], parts[1:]
    kept: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        name = arg.partition('=')[0]
        takes_value = name in CLAUDE_FLAGS_WITH_VALUE and '=' not in arg
        if name in CLAUDE_DROPPED_FLAGS:
            # skip the session id that may follow --resume/--session-id
            if name in ('-r', '--resume', '--session-id') and '=' not in arg and i + 1 < len(args) and not args[i + 1].startswith('-'):
                i += 1
        elif arg.startswith('-'):
            kept.append(arg)
            if takes_value and i + 1 < len(args):
                kept.append(args[i + 1])
                i += 1
        # positional arguments (an initial prompt) are dropped so it is not sent again
        i += 1
    ans = env + [exe] + kept + ['--resume', session_id]
    return shlex.join(ans) if isinstance(cmd, str) else ans


def prune_claude_sessions() -> None:
    ' Remove records left by kitty processes that are no longer running '
    with suppress(OSError), os.scandir(claude_sessions_dir()) as entries:
        for entry in entries:
            pid = entry.name.partition('-')[0]
            if pid.isdigit() and not os.path.exists(f'/proc/{pid}'):
                with suppress(OSError):
                    os.remove(entry.path)
# }}}


# Terminal contents {{{
# The text (with colors and scrollback) of terminals sitting at a shell prompt is
# saved next to the workspace and drawn into the terminal again when it is
# restored, before the shell starts, so the terminal looks as it was left.
# Terminals running a program that is restarted (such as claude --resume) are
# not saved, as that program redraws itself.
REPLAY_ENV_VAR = 'KITTY_FORK_REPLAY'
REPLAY_MAX_BYTES = 900 * 1024  # must fit in the 1MB VT parser buffer
RESTORE_MARKER = 'восстановлено, сохранено'.encode()


def scrollback_dir(name: str) -> str:
    return os.path.join(workspaces_dir(), name + '.scrollback')


def terminal_text(w: 'Window') -> str:
    if not w.screen.is_main_linebuf():
        return ''
    lines = w.as_text(as_ansi=True, add_history=True).rstrip().split('\n')
    # The last line is the current shell prompt, the restored shell will draw a new one
    return '\n'.join(lines[:-1]).rstrip()


def save_terminal_text(path: str, text: str) -> None:
    data = text.encode('utf-8', 'replace')
    with suppress(OSError), open(path, 'rb') as f:
        if f.read() == data:
            return
    from .config import atomic_save
    atomic_save(data, path)


def replay_into_screen(screen: Any, path: str) -> None:
    ' Draw saved terminal contents into a new screen. Must be called before the output of the child is read. '
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return
    if len(data) > REPLAY_MAX_BYTES:
        data = data[-REPLAY_MAX_BYTES:]
        data = data[data.find(b'\n') + 1:]
    # Nothing happened in the terminal since it was last restored: replace that separator instead of adding another
    lines = data.rstrip().split(b'\n')
    while lines and RESTORE_MARKER in re.sub(rb'\x1b\[[0-9;:]*m', b'', lines[-1]):
        lines.pop()
    data = b'\n'.join(lines)
    stamp = time.strftime('%d.%m %H:%M', time.localtime(os.path.getmtime(path)))
    footer = f'\x1b[m\r\n\x1b[2m── {RESTORE_MARKER.decode()} {stamp} ──\x1b[m\r\n'.encode()
    data = b'\x1b[m' + data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n') + footer
    try:
        buf = screen.test_create_write_buffer()
        screen.test_commit_write_buffer(data[:len(buf)], buf)
    except Exception as e:
        log_error(f'Failed to restore terminal contents from {path}: {e}')
# }}}


def process_launch_lines(lines: Sequence[str], restorable: Sequence[str], name: str, windows: dict[int, 'Window']) -> Iterator[str]:
    ' Drop unsafe commands, make claude resume its session and save terminal contents '
    allowed = frozenset(restorable)
    sdir = scrollback_dir(name)
    used_files: set[str] = set()
    for line in lines:
        if line.startswith('launch ') and unserialize_launch_flag in line:
            with suppress(ValueError):
                parts = [p for p in shlex.split(line) if not p.startswith(f'--env={REPLAY_ENV_VAR}=')]
                for i, part in enumerate(parts):
                    if part.startswith(unserialize_launch_flag):
                        data = json.loads(part[len(unserialize_launch_flag):])
                        cmd = data.get('cmd_at_shell_startup')
                        if cmd:
                            program = program_of(cmd)
                            if program not in allowed:
                                del data['cmd_at_shell_startup']
                            elif program == 'claude' and (sid := claude_session_for_window(data.get('id', 0))):
                                data['cmd_at_shell_startup'] = claude_resume_command(cmd, sid)
                            parts[i] = unserialize_launch_flag + json.dumps(data)
                        w = windows.get(data.get('id', 0))
                        if w is not None and not data.get('cmd_at_shell_startup') and w.at_prompt and (text := terminal_text(w)):
                            os.makedirs(sdir, exist_ok=True)
                            path = os.path.join(sdir, f'{w.id}.ansi')
                            save_terminal_text(path, text)
                            used_files.add(path)
                            parts.insert(i + 1, f'--env={REPLAY_ENV_VAR}={path}')
                        break
                line = shlex.join(parts)
        yield line
    with suppress(OSError), os.scandir(sdir) as entries:
        for entry in entries:
            if entry.path not in used_files:
                with suppress(OSError):
                    os.remove(entry.path)


def serialize_workspace(boss: 'Boss', name: str, path: str) -> str:
    windows = frozenset(windows_in_workspace(boss, name))
    if not windows:
        return ''
    ser_opts = parse_save_as_options_spec_args(['--save-only', '--use-foreground-process'])[0]
    lines: list[str] = []
    order = {current_focused_os_window_id(): 2, last_focused_os_window_id(): 1}
    is_first = True
    for os_window_id in sorted(boss.os_window_map, key=lambda wid: order.get(wid, 0)):
        tm = boss.os_window_map[os_window_id]
        if any(w in windows for t in tm for w in t):
            lines.extend(tm.serialize_state_as_session(path, windows, is_first=is_first, ser_opts=ser_opts))
            is_first = False
    if not any(line.startswith('launch ') for line in lines):
        return ''
    return '\n'.join(process_launch_lines(lines, read_state()['restorable_programs'], name, {w.id: w for w in windows}))


def save_workspace(boss: 'Boss', name: str) -> bool:
    ' Save the named workspace, returns False if it has no windows, in which case the previously saved file is left untouched '
    from .config import atomic_save
    path = path_for_name(name)
    data = serialize_workspace(boss, name, path)
    if not data:
        return False
    with suppress(OSError), open(path) as f:
        if f.read() == data:
            return True
    os.makedirs(workspaces_dir(), exist_ok=True)
    atomic_save(data.encode(), path)
    seen_session_paths[name] = path
    return True


# Set once the user has decided what happens to the workspaces on close, so that
# the windows being torn down afterwards do not overwrite that decision
frozen = False
pending_autosave = False


def autosave(boss: 'Boss') -> None:
    if lock_fd < 0 or frozen:
        return
    open_workspaces = [name for name in dict.fromkeys(boss.all_loaded_session_names) if is_workspace(name)]
    for name in open_workspaces:
        try:
            save_workspace(boss, name)
        except Exception as e:
            log_error(f'Failed to autosave workspace {name}: {e}')
    state = read_state()
    active = boss.active_session
    new_state = {**state, 'open': open_workspaces, 'active': active if active in open_workspaces else state['active']}
    if new_state != state:
        write_state(new_state)
# }}}


def schedule_autosave() -> None:
    ' Save shortly after the user opens or closes a tab or split, coalescing bursts of changes '
    global pending_autosave
    if lock_fd < 0 or frozen or pending_autosave:
        return
    from .fast_data_types import get_boss
    pending_autosave = True

    def fire(timer_id: int | None) -> None:
        global pending_autosave
        pending_autosave = False
        if (boss := get_boss()) is not None:
            autosave(boss)

    add_timer(fire, ACTION_AUTOSAVE_DELAY, False)


# Closing {{{
close_dialog_window_id = 0


def workspaces_in(boss: 'Boss', os_window_id: int | None) -> list[str]:
    tms = boss.all_tab_managers if os_window_id is None else (tm for tm in (boss.os_window_map.get(os_window_id),) if tm is not None)
    names = {w.created_in_session_name for tm in tms for t in tm for w in t}
    return sorted(n for n in names if is_workspace(n))


def finish_close(boss: 'Boss', names: Sequence[str], action: str, is_last: bool) -> None:
    ' Apply the save/discard decision for workspaces being closed '
    global frozen
    if action == 'save':
        autosave(boss)
        if is_last:
            frozen = True
    elif action == 'discard':
        autosave(boss)  # keeps the saved files fresh, but they will not be reopened
        state = read_state()
        state['open'] = [n for n in state['open'] if n not in names]
        if state['active'] in names:
            state['active'] = state['open'][0] if state['open'] else ''
        write_state(state)
        frozen = True if is_last else frozen


def before_close(boss: 'Boss', os_window_id: int | None, proceed: Callable[[], None], cancel: Callable[[], None]) -> bool:
    '''
    Called when an OS window (or, with os_window_id None, all of kitty) is about to close.
    Returns True if it took over the close: it then calls proceed() to close without
    further confirmation, or cancel() to abort. Returns False to let kitty close as usual.
    '''
    global close_dialog_window_id
    if lock_fd < 0:
        return False
    names = workspaces_in(boss, os_window_id)
    is_last = os_window_id is None or len(boss.os_window_map) <= 1
    if not names:
        autosave(boss)
        return False
    policy = read_state()['on_close']
    if policy != 'ask':
        finish_close(boss, names, policy, is_last)
        return False
    if close_dialog_window_id and (w := boss.window_id_map.get(close_dialog_window_id)) is not None:
        boss.set_active_window(w, switch_os_window_if_needed=True)
        return True
    tm = boss.os_window_map.get(os_window_id) if os_window_id is not None else boss.active_tab_manager
    window = tm.active_window if tm is not None else boss.active_window
    if window is None:
        return False
    result: dict[str, Any] = {}

    def on_result(data: dict[str, Any], target_window_id: int, boss: 'Boss') -> None:
        result.update(data)

    def on_removal(window_id: int, boss: 'Boss') -> None:
        global close_dialog_window_id
        close_dialog_window_id = 0
        action = result.get('action', 'cancel')
        if action == 'cancel':
            cancel()
            return
        if result.get('remember'):
            state = read_state()
            state['on_close'] = action
            write_state(state)
        finish_close(boss, names, action, is_last)
        proceed()

    what = 'kitty' if is_last else 'это окно kitty'
    message = [
        'Открытые воркспейсы: ' + ', '.join(names),
        '',
        'Сохранить их, чтобы при следующем запуске всё',
        'открылось как было, включая сессии claude?',
    ]
    w = boss.run_kitten_with_metadata(
        'close_workspaces', [f'Закрыть {what}?', *message], window=window,
        custom_callback=on_result, action_on_removal=on_removal, default_data={'action': 'cancel'})
    if not isinstance(w, type(window)):
        return False
    close_dialog_window_id = w.id
    return True
# }}}


# Actions {{{
def tag_with_workspace(tabs: Sequence['Tab'], name: str) -> None:
    for tab in tabs:
        tab.created_in_session_name = name
        for w in tab:
            w.created_in_session_name = name


def save_current_workspace(boss: 'Boss') -> None:
    current = boss.active_session
    if is_workspace(current):
        save_workspace(boss, current)
        autosave(boss)
        flash_title(boss, f'Воркспейс «{current}» сохранён')
        return
    tm = boss.active_tab_manager
    if tm is None:
        return
    wd = (tm.active_tab.get_cwd_of_active_window() if tm.active_tab else '') or ''
    suggestion = sanitize_name(os.path.basename(wd.rstrip(os.sep))) if wd and wd != os.path.expanduser('~') else ''

    def on_name(name: str) -> None:
        name = sanitize_name(name)
        if not name:
            return
        if is_workspace(name) and name not in boss.all_loaded_session_names:
            boss.confirm(
                f'Воркспейс «{name}» уже существует. Перезаписать?',
                lambda yes: yes and do_save(name), window=boss.active_window, title='Перезаписать воркспейс?')
            return
        do_save(name)

    def do_save(name: str) -> None:
        # The tabs not belonging to any workspace become the new workspace
        tag_with_workspace([t for t in tm if t.created_in_session_name in ('', current)], name)
        append_to_session_history(name)
        if save_workspace(boss, name):
            autosave(boss)
            flash_title(boss, f'Воркспейс «{name}» сохранён')
        tm.mark_tab_bar_dirty()

    boss.get_line(
        'Имя нового воркспейса (вкладки этого окна будут сохранены в него):', on_name,
        window=boss.active_window, initial_value=suggestion, window_title='Сохранить воркспейс')


def open_workspace(boss: 'Boss', name: str) -> None:
    current = boss.active_session
    if is_workspace(current):
        save_workspace(boss, current)
    if switch_to_session(boss, name, only_if_actual_windows_present=True):
        autosave(boss)
        return
    path = path_for_name(name)
    try:
        session_name, created_new_os_window = create_session(boss, path)
    except Exception as e:
        boss.show_error('Не удалось открыть воркспейс', f'{path}\n{e}')
        return
    seen_session_paths[session_name] = path
    if not created_new_os_window:
        switch_to_session(boss, session_name)
    autosave(boss)


def new_workspace(boss: 'Boss') -> None:
    def on_name(name: str) -> None:
        name = sanitize_name(name)
        if not name:
            return
        if is_workspace(name):
            open_workspace(boss, name)
            return
        tm = boss.active_tab_manager
        if tm is None:
            return
        current = boss.active_session
        if is_workspace(current):
            save_workspace(boss, current)
        tab = tm.new_tab()
        tag_with_workspace([tab], name)
        append_to_session_history(name)
        save_workspace(boss, name)
        autosave(boss)
        tm.mark_tab_bar_dirty()

    boss.get_line('Имя нового воркспейса:', on_name, window=boss.active_window, window_title='Новый воркспейс')


def delete_workspace(boss: 'Boss', name: str) -> None:
    def on_confirm(yes: bool) -> None:
        if not yes:
            return
        with suppress(FileNotFoundError):
            os.remove(path_for_name(name))
        import shutil
        shutil.rmtree(scrollback_dir(name), ignore_errors=True)
        seen_session_paths.pop(name, None)
        # Tabs of the deleted workspace stay open, they just no longer belong to a workspace
        tag_with_workspace([t for t in boss.all_tabs if t.created_in_session_name == name], '')
        for tm in boss.all_tab_managers:
            tm.mark_tab_bar_dirty()
        autosave(boss)

    boss.confirm(
        f'Удалить сохранённый воркспейс «{name}»?\nОткрытые вкладки не закроются.',
        on_confirm, window=boss.active_window, title='Удалить воркспейс?', confirm_on_accept=False)


def human_time(mtime: float) -> str:
    delta = time.time() - mtime
    if delta < 60:
        return 'только что'
    if delta < 3600:
        return f'{int(delta // 60)} мин назад'
    if delta < 86400:
        return f'{int(delta // 3600)} ч назад'
    return time.strftime('%d.%m.%Y', time.localtime(mtime))


def plural_tabs(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f'{n} вкладка'
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f'{n} вкладки'
    return f'{n} вкладок'


def workspace_dir(boss: 'Boss', name: str, path: str) -> str:
    ' The working directory a workspace is about: that of its first window, or the first cd in its session file '
    for w in windows_in_workspace(boss, name):
        if cwd := w.cwd_for_serialization:
            return cwd
    with suppress(OSError), open(path) as f:
        for line in f:
            if line.startswith('cd '):
                return line[3:].strip()
    return ''


def show_workspaces_panel(boss: 'Boss') -> None:
    ' The workspace switcher popover '
    from .tab_bar import git_branch_for_dir
    saved = saved_workspaces()
    loaded = set(boss.all_loaded_session_names)
    current = boss.active_session
    home = os.path.expanduser('~')
    items = []
    for name in sorted(saved, key=lambda n: (n != current, n not in loaded, n.lower())):
        d = workspace_dir(boss, name, saved[name])
        branch = git_branch_for_dir(d) if d else ''
        short = ('~' + d[len(home):]) if d == home or d.startswith(home + os.sep) else d
        if name in loaded:
            status = 'открыт · ' + plural_tabs(sum(1 for t in boss.all_tabs if t.created_in_session_name == name))
        else:
            status = human_time(os.path.getmtime(saved[name]))
        items.append({
            'name': name, 'current': name == current, 'loaded': name in loaded, 'status': status,
            'detail': ' · '.join(x for x in (branch, short) if x),
        })
    data = {'workspaces': items, 'on_close': read_state()['on_close'], 'policies': ON_CLOSE_POLICIES}

    def on_result(result: dict[str, Any]) -> None:
        action = result.get('action')
        name = sanitize_name(result.get('name', ''))
        if action == 'open' and name:
            open_workspace(boss, name)
        elif action == 'new' and name:
            create_workspace(boss, name)
        elif action == 'delete' and name:
            really_delete_workspace(boss, name)
            show_workspaces_panel(boss)
        elif action == 'save_current':
            save_current_workspace(boss)

    show_pixel_panel(boss, 'workspaces', data, on_result)


def show_pixel_panel(boss: 'Boss', view: str, data: dict[str, Any], on_result: Callable[[dict[str, Any]], None]) -> None:
    ' Show a panel of the pixel_ui kitten over the active window, on top of a blurred snapshot of that window '
    import tempfile
    window = boss.active_window
    tm = boss.active_tab_manager
    if window is None or tm is None:
        return
    result: dict[str, Any] = {}

    def on_kitten_result(res: dict[str, Any], target_window_id: int, boss: 'Boss') -> None:
        result.update(res)

    def on_removal(window_id: int, boss: 'Boss') -> None:
        if result.get('action', 'cancel') != 'cancel':
            on_result(result)

    def launch(background: str) -> None:
        with tempfile.NamedTemporaryFile('w', suffix='.json', prefix='kitty-panel-', delete=False) as f:
            json.dump({'view': view, 'data': data, 'background': background}, f)
        boss.run_kitten_with_metadata(
            'pixel_ui', [f.name], window=window, custom_callback=on_kitten_result, action_on_removal=on_removal, default_data={'action': 'cancel'})

    def on_thumbnail(os_window_id: int, window_id: int, pixels: bytes, width: int, height: int) -> None:
        background = ''
        if pixels:
            from .fast_data_types import png_from_32bit_rgba_data
            with suppress(Exception), tempfile.NamedTemporaryFile(suffix='.png', prefix='kitty-panel-bg-', delete=False) as f:
                f.write(png_from_32bit_rgba_data(pixels, width, height, True))
                background = f.name
        launch(background)

    boss.request_thumbnail(tm.os_window_id, on_thumbnail, window_id=window.id, no_scaling=True)


def create_workspace(boss: 'Boss', name: str) -> None:
    if is_workspace(name):
        open_workspace(boss, name)
        return
    tm = boss.active_tab_manager
    if tm is None:
        return
    current = boss.active_session
    if is_workspace(current):
        save_workspace(boss, current)
    tab = tm.new_tab()
    tag_with_workspace([tab], name)
    append_to_session_history(name)
    save_workspace(boss, name)
    autosave(boss)
    tm.mark_tab_bar_dirty()
    flash_title(boss, f'Воркспейс «{name}» создан')


def really_delete_workspace(boss: 'Boss', name: str) -> None:
    import shutil
    with suppress(FileNotFoundError):
        os.remove(path_for_name(name))
    shutil.rmtree(scrollback_dir(name), ignore_errors=True)
    seen_session_paths.pop(name, None)
    # Tabs of the deleted workspace stay open, they just no longer belong to a workspace
    tag_with_workspace([t for t in boss.all_tabs if t.created_in_session_name == name], '')
    for tm in boss.all_tab_managers:
        tm.mark_tab_bar_dirty()
    autosave(boss)


def show_workspaces(boss: 'Boss') -> None:
    saved = saved_workspaces()
    loaded = set(boss.all_loaded_session_names)
    current = boss.active_session
    entries: list[tuple[str | None, str]] = []
    for name in sorted(saved, key=lambda n: (n != current, n not in loaded, n.lower())):
        ntabs = sum(1 for t in boss.all_tabs if t.created_in_session_name == name)
        marker = '▶' if name == current else ('●' if name in loaded else '○')
        detail = f'открыт, вкладок: {ntabs}' if name in loaded else f'сохранён {human_time(os.path.getmtime(saved[name]))}'
        entries.append((f'open:{name}', f'{marker} {name}  —  {detail}'))
    entries.append(('new:', '＋ Новый воркспейс'))
    if saved:
        entries.append(('delete:', '✕ Удалить воркспейс…'))
    entries.append(('on_close:', f'⚙ При закрытии kitty: {ON_CLOSE_POLICIES[read_state()["on_close"]]}'))

    def chosen(ans: str | None) -> None:
        if not ans:
            return
        action, _, name = ans.partition(':')
        if action == 'open':
            open_workspace(boss, name)
        elif action == 'new':
            new_workspace(boss)
        elif action == 'on_close':
            boss.choose_entry(
                'Что делать с воркспейсами при закрытии kitty?',
                ((k, v) for k, v in ON_CLOSE_POLICIES.items()),
                lambda policy: policy and write_state({**read_state(), 'on_close': policy}))
        elif action == 'delete':
            boss.choose_entry(
                'Какой воркспейс удалить?', ((f'{n}', n) for n in sorted(saved, key=str.lower)),
                lambda n: n and delete_workspace(boss, n))

    subtitle = '' if saved else 'Сохранённых воркспейсов пока нет. Сохрани текущие вкладки кнопкой ⤓ в шапке.'
    boss.choose_entry('Воркспейсы', entries, chosen, subtitle=subtitle)


def flash_title(boss: 'Boss', msg: str) -> None:
    ' Briefly show a message in the titlebar '
    from .titlebar import show_toast
    if (tm := boss.active_tab_manager) is not None:
        show_toast(tm.os_window_id, msg)
# }}}


# Startup {{{
restoring_at_startup = False


def startup_workspace_path(args: Any, startup_session: str) -> str:
    ' The workspace to use as the startup session, empty if workspaces should not be restored '
    if getattr(args, 'session', None) or getattr(args, 'args', None) or (startup_session and startup_session != 'none'):
        return ''
    if not acquire_primary_lock():
        return ''
    state = read_state()
    if not state['restore_on_startup']:
        return ''
    open_workspaces = [n for n in state['open'] if is_workspace(n)]
    if not open_workspaces:
        return ''
    active = state['active'] if state['active'] in open_workspaces else open_workspaces[0]
    global restoring_at_startup
    restoring_at_startup = True
    return path_for_name(active)


def restore_remaining(boss: 'Boss') -> None:
    ' Load the other workspaces that were open when kitty last quit, then return focus to the active one '
    state = read_state()
    active = boss.active_session
    if active:
        seen_session_paths[active] = path_for_name(active)
        append_to_session_history(active)
    for name in state['open']:
        if name != active and is_workspace(name) and name not in set(boss.all_loaded_session_names):
            try:
                session_name, _ = create_session(boss, path_for_name(name))
            except Exception as e:
                log_error(f'Failed to restore workspace {name}: {e}')
                continue
            seen_session_paths[session_name] = path_for_name(name)
    if active:
        switch_to_session(boss, active)


def after_startup(boss: 'Boss') -> None:
    prune_claude_sessions()
    if restoring_at_startup:
        try:
            restore_remaining(boss)
        except Exception as e:
            log_error(f'Failed to restore workspaces: {e}')
    if acquire_primary_lock():
        add_timer(lambda timer_id: autosave(boss), AUTOSAVE_INTERVAL, True)
    from .titlebar import start_refresh_timer
    start_refresh_timer(boss)
# }}}
