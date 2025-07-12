#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from collections import defaultdict
from collections.abc import Generator, Sequence
from contextlib import contextmanager, suppress
from itertools import count
from typing import TYPE_CHECKING, DefaultDict, Iterable, Mapping, Optional, TypedDict

import kitty.fast_data_types as fast_data_types

from .constants import handled_signals, is_freebsd, is_macos, kitten_exe, kitty_base_dir, shell_path, terminfo_dir
from .types import run_once
from .utils import cmdline_for_hold, log_error, which

if TYPE_CHECKING:
    from .window import CwdRequest


if is_macos:
    from kitty.fast_data_types import cmdline_of_process as cmdline_
    from kitty.fast_data_types import cwd_of_process as _cwd
    from kitty.fast_data_types import environ_of_process as _environ_of_process
    from kitty.fast_data_types import process_group_map as _process_group_map

    def cwd_of_process(pid: int) -> str:
        # The underlying code on macos returns a path with symlinks resolved
        # anyway but we use realpath for extra safety.
        return os.path.realpath(_cwd(pid))

    def process_group_map() -> DefaultDict[int, list[int]]:
        ans: DefaultDict[int, list[int]] = defaultdict(list)
        for pid, pgid in _process_group_map():
            ans[pgid].append(pid)
        return ans

    def cmdline_of_pid(pid: int) -> list[str]:
        return cmdline_(pid)
else:

    def cmdline_of_pid(pid: int) -> list[str]:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return list(filter(None, f.read().decode('utf-8').split('\0')))

    if is_freebsd:
        def cwd_of_process(pid: int) -> str:
            import subprocess
            cp = subprocess.run(['pwdx', str(pid)], capture_output=True)
            if cp.returncode != 0:
                raise ValueError(f'Failed to find cwd of process with pid: {pid}')
            ans = cp.stdout.decode('utf-8', 'replace').split()[1]
            return os.path.realpath(ans)
    else:
        def cwd_of_process(pid: int) -> str:
            # We use realpath instead of readlink to match macOS behavior where
            # the underlying OS API returns real paths.
            ans = f'/proc/{pid}/cwd'
            return os.path.realpath(ans)

    def _environ_of_process(pid: int) -> str:
        with open(f'/proc/{pid}/environ', 'rb') as f:
            return f.read().decode('utf-8')

    def process_group_map() -> DefaultDict[int, list[int]]:
        ans: DefaultDict[int, list[int]] = defaultdict(list)
        for x in os.listdir('/proc'):
            try:
                pid = int(x)
            except Exception:
                continue
            try:
                with open(f'/proc/{x}/stat', 'rb') as f:
                    raw = f.read().decode('utf-8')
            except OSError:
                continue
            try:
                q = int(raw.split(' ', 5)[4])
            except Exception:
                continue
            ans[q].append(pid)
        return ans


@run_once
def checked_terminfo_dir() -> str | None:
    return terminfo_dir if os.path.isdir(terminfo_dir) else None


def processes_in_group(grp: int) -> list[int]:
    gmap: DefaultDict[int, list[int]] | None = getattr(process_group_map, 'cached_map', None)
    if gmap is None:
        try:
            gmap = process_group_map()
        except Exception:
            gmap = defaultdict(list)
    return gmap.get(grp, [])


@contextmanager
def cached_process_data() -> Generator[None, None, None]:
    try:
        cm = process_group_map()
    except Exception:
        cm = defaultdict(list)
    setattr(process_group_map, 'cached_map', cm)
    try:
        yield
    finally:
        delattr(process_group_map, 'cached_map')


def session_id(pids: Iterable[int]) -> int:
    for pid in pids:
        with suppress(OSError):
            if (sid := os.getsid(pid)) > -1:
                return sid
    return -1

def parse_environ_block(data: str) -> dict[str, str]:
    """Parse a C environ block of environment variables into a dictionary."""
    # The block is usually raw data from the target process.  It might contain
    # trailing garbage and lines that do not look like assignments.
    ret: dict[str, str] = {}
    pos = 0

    while True:
        next_pos = data.find("\0", pos)
        # nul byte at the beginning or double nul byte means finish
        if next_pos <= pos:
            break
        # there might not be an equals sign
        equal_pos = data.find("=", pos, next_pos)
        if equal_pos > pos:
            key = data[pos:equal_pos]
            value = data[equal_pos + 1:next_pos]
            ret[key] = value
        pos = next_pos + 1

    return ret


def environ_of_process(pid: int) -> dict[str, str]:
    return parse_environ_block(_environ_of_process(pid))


def process_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    ans = dict(os.environ if env is None else env)
    ssl_env_var = getattr(sys, 'kitty_ssl_env_var', None)
    if ssl_env_var is not None:
        ans.pop(ssl_env_var, None)
    ans.pop('XDG_ACTIVATION_TOKEN', None)
    ans.pop('VTE_VERSION', None)  # Used by the stupid VTE shell integration script that is installed system wide, sigh
    return ans


def default_env() -> dict[str, str]:
    ans: dict[str, str] | None = getattr(default_env, 'env', None)
    if ans is None:
        return process_env()
    return ans


def set_default_env(val: dict[str, str] | None = None) -> None:
    env = process_env().copy()
    has_lctype = False
    if val:
        has_lctype = 'LC_CTYPE' in val
        env.update(val)
    setattr(default_env, 'env', env)
    setattr(default_env, 'lc_ctype_set_by_user', has_lctype)


def set_LANG_in_default_env(val: str) -> None:
    default_env().setdefault('LANG', val)


def openpty() -> tuple[int, int]:
    master, slave = os.openpty()  # Note that master and slave are in blocking mode
    os.set_inheritable(slave, True)
    os.set_inheritable(master, False)
    fast_data_types.set_iutf8_fd(master, True)
    return master, slave


@run_once
def getpid() -> str:
    return str(os.getpid())


@run_once
def base64_terminfo_data() -> str:
    return (b'b64:' + fast_data_types.base64_encode(fast_data_types.terminfo_data(), True)).decode('ascii')


class ProcessDesc(TypedDict):
    cwd: str | None
    pid: int
    cmdline: Sequence[str] | None


child_counter = count()


class Child:

    child_fd: int | None = None
    pid: int | None = None
    forked = False

    def __init__(
        self,
        argv: Sequence[str],
        cwd: str,
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
        cwd_from: Optional['CwdRequest'] = None,
        is_clone_launch: str = '',
        add_listen_on_env_var: bool = True,
        hold: bool = False,
        pass_fds: tuple[int, ...] = (),
        remote_control_fd: int = -1,
        hold_after_ssh: bool = False
    ):
        self.is_clone_launch = is_clone_launch
        self.id = next(child_counter)
        self.add_listen_on_env_var = add_listen_on_env_var
        self.argv = list(argv)
        self.pass_fds = pass_fds
        self.remote_control_fd = remote_control_fd
        if cwd_from:
            try:
                cwd = cwd_from.modify_argv_for_launch_with_cwd(self.argv, env, hold_after_ssh=hold_after_ssh) or cwd
            except Exception as err:
                log_error(f'Failed to read cwd of {cwd_from} with error: {err}')
        else:
            cwd = os.path.expandvars(os.path.expanduser(cwd or os.getcwd()))
        self.cwd = os.path.abspath(cwd)
        self.stdin = stdin
        self.env = env or {}
        self.final_env:dict[str, str] = {}
        self.is_default_shell = bool(self.argv and self.argv[0] == shell_path)
        self.should_run_via_run_shell_kitten = is_macos and self.is_default_shell
        self.hold = hold

    def get_final_env(self) -> dict[str, str]:
        from kitty.options.utils import DELETE_ENV_VAR
        env = default_env().copy()
        opts = fast_data_types.get_options()
        boss = fast_data_types.get_boss()
        if is_macos and env.get('LC_CTYPE') == 'UTF-8' and not getattr(sys, 'kitty_run_data').get(
                'lc_ctype_before_python') and not getattr(default_env, 'lc_ctype_set_by_user', False):
            del env['LC_CTYPE']
        env.update(self.env)
        env['TERM'] = opts.term
        env['COLORTERM'] = 'truecolor'
        env['KITTY_PID'] = getpid()
        env['KITTY_PUBLIC_KEY'] = boss.encryption_public_key
        if self.remote_control_fd > -1:
            env['KITTY_LISTEN_ON'] = f'fd:{self.remote_control_fd}'
        elif self.add_listen_on_env_var and boss.listening_on:
            env['KITTY_LISTEN_ON'] = boss.listening_on
        else:
            env.pop('KITTY_LISTEN_ON', None)
        env.pop('KITTY_STDIO_FORWARDED', None)
        if self.cwd:
            # needed in case cwd is a symlink, in which case shells
            # can use it to display the current directory name rather
            # than the resolved path
            env['PWD'] = self.cwd
        if opts.terminfo_type == 'path':
            tdir = checked_terminfo_dir()
            if tdir:
                env['TERMINFO'] = tdir
        elif opts.terminfo_type == 'direct':
            env['TERMINFO'] = base64_terminfo_data()
        env['KITTY_INSTALLATION_DIR'] = kitty_base_dir
        self.unmodified_argv = list(self.argv)
        if not self.should_run_via_run_shell_kitten and 'disabled' not in opts.shell_integration:
            from .shell_integration import modify_shell_environ
            modify_shell_environ(opts, env, self.argv)
        env = {k: v for k, v in env.items() if v is not DELETE_ENV_VAR}
        if self.is_clone_launch:
            env['KITTY_IS_CLONE_LAUNCH'] = self.is_clone_launch
            self.is_clone_launch = '1'  # free memory
        else:
            env.pop('KITTY_IS_CLONE_LAUNCH', None)
        return env

    def fork(self) -> int | None:
        if self.forked:
            return None
        opts = fast_data_types.get_options()
        self.forked = True
        master, slave = openpty()
        stdin, self.stdin = self.stdin, None
        ready_read_fd, ready_write_fd = os.pipe()
        os.set_inheritable(ready_write_fd, False)
        os.set_inheritable(ready_read_fd, True)
        if stdin is not None:
            stdin_read_fd, stdin_write_fd = os.pipe()
            os.set_inheritable(stdin_write_fd, False)
            os.set_inheritable(stdin_read_fd, True)
        else:
            stdin_read_fd = stdin_write_fd = -1
        self.final_env = self.get_final_env()
        argv = list(self.argv)
        cwd = self.cwd
        pass_fds = self.pass_fds
        if self.remote_control_fd > -1:
            pass_fds += self.remote_control_fd,
        if self.should_run_via_run_shell_kitten:
            # bash will only source ~/.bash_profile if it detects it is a login
            # shell (see the invocation section of the bash man page), which it
            # does if argv[0] is prefixed by a hyphen see
            # https://github.com/kovidgoyal/kitty/issues/247
            # it is apparently common to use ~/.bash_profile instead of the
            # more correct ~/.bashrc on macOS to setup env vars, so if
            # the default shell is used prefix argv[0] by '-'
            #
            # it is arguable whether graphical terminals should start shells
            # in login mode in general, there are at least a few Linux users
            # that also make this incorrect assumption, see for example
            # https://github.com/kovidgoyal/kitty/issues/1870
            # xterm, urxvt, konsole and gnome-terminal do not do it in my
            # testing.
            import shlex
            ksi = ' '.join(opts.shell_integration)
            if ksi == 'invalid':
                ksi = 'enabled'
            argv = [kitten_exe(), 'run-shell', '--shell', shlex.join(argv), '--shell-integration', ksi]
            if is_macos and not pass_fds and not opts.forward_stdio:
                # In addition for getlogin() to work we need to run the shell
                # via the /usr/bin/login wrapper, sigh.
                # And login on macOS looks for .hushlogin in CWD instead of
                # HOME, bloody idiotic so we cant cwd when running it.
                # https://github.com/kovidgoyal/kitty/issues/6511
                # login closes inherited file descriptors so dont use it when
                # forward_stdio or pass_fds are used.
                import pwd
                user = pwd.getpwuid(os.geteuid()).pw_name
                if cwd:
                    argv.append('--cwd=' + cwd)
                    cwd = os.path.expanduser('~')
                argv = ['/usr/bin/login', '-f', '-l', '-p', user] + argv
        self.final_exe = final_exe = which(argv[0]) or argv[0]
        self.final_argv0 = argv[0]
        if self.hold:
            argv = cmdline_for_hold(argv)
            final_exe = argv[0]
        env = tuple(f'{k}={v}' for k, v in self.final_env.items())
        pid = fast_data_types.spawn(
            final_exe, cwd, tuple(argv), env, master, slave, stdin_read_fd, stdin_write_fd,
            ready_read_fd, ready_write_fd, tuple(handled_signals), kitten_exe(), opts.forward_stdio, pass_fds)
        os.close(slave)
        self.pid = pid
        self.child_fd = master
        if stdin is not None:
            os.close(stdin_read_fd)
            fast_data_types.thread_write(stdin_write_fd, stdin)
        os.close(ready_read_fd)
        self.terminal_ready_fd = ready_write_fd
        if self.child_fd is not None:
            os.set_blocking(self.child_fd, False)
        if not is_macos:
            ppid = getpid()
            try:
                fast_data_types.systemd_move_pid_into_new_scope(pid, f'kitty-{ppid}-{self.id}.scope', f'kitty child process: {pid} launched by: {ppid}')
            except NotImplementedError:
                pass
            except OSError as err:
                log_error("Could not move child process into a systemd scope: " + str(err))
        return pid

    def __del__(self) -> None:
        fd = getattr(self, 'terminal_ready_fd', -1)
        if fd > -1:
            os.close(fd)
        self.terminal_ready_fd = -1

    def mark_terminal_ready(self) -> None:
        os.close(self.terminal_ready_fd)
        self.terminal_ready_fd = -1

    def cmdline_of_pid(self, pid: int) -> list[str]:
        try:
            ans = cmdline_of_pid(pid)
        except Exception:
            ans = []
        if pid == self.pid and (not ans):
            ans = list(self.argv)
        return ans

    def process_desc(self, pid: int) -> ProcessDesc:
        ans: ProcessDesc = {'pid': pid, 'cmdline': None, 'cwd': None}
        with suppress(Exception):
            ans['cmdline'] = self.cmdline_of_pid(pid)
        with suppress(Exception):
            ans['cwd'] = cwd_of_process(pid) or None
        return ans

    @property
    def foreground_processes(self) -> list[ProcessDesc]:
        if self.child_fd is None:
            return []
        try:
            pgrp = os.tcgetpgrp(self.child_fd)
            foreground_processes = processes_in_group(pgrp) if pgrp >= 0 else []
            return [self.process_desc(x) for x in foreground_processes]
        except Exception:
            return []

    @property
    def background_processes(self) -> list[ProcessDesc]:
        if self.child_fd is None:
            return []
        try:
            foreground_process_group_id = os.tcgetpgrp(self.child_fd)
            if foreground_process_group_id < 0:
                return []
            gmap = process_group_map()

            sid = session_id(gmap.get(foreground_process_group_id, ()))
            if sid < 0:
                return []
            ans: list[ProcessDesc] = []
            for grp_id, pids in gmap.items():
                if grp_id != foreground_process_group_id and session_id(pids) == sid:
                    ans.extend(map(self.process_desc, pids))
            return ans
        except Exception:
            return []

    @property
    def cmdline(self) -> list[str]:
        try:
            assert self.pid is not None
            return self.cmdline_of_pid(self.pid) or list(self.argv)
        except Exception:
            return list(self.argv)

    @property
    def foreground_cmdline(self) -> list[str]:
        try:
            assert self.pid_for_cwd is not None
            return self.cmdline_of_pid(self.pid_for_cwd) or self.cmdline
        except Exception:
            return self.cmdline

    @property
    def environ(self) -> dict[str, str]:
        try:
            assert self.pid is not None
            return environ_of_process(self.pid) or self.final_env.copy()
        except Exception:
            return self.final_env.copy()

    @property
    def current_cwd(self) -> str | None:
        with suppress(Exception):
            assert self.pid is not None
            return cwd_of_process(self.pid)
        return None

    def get_pid_for_cwd(self, oldest: bool = False) -> int | None:
        with suppress(Exception):
            assert self.child_fd is not None
            pgrp = os.tcgetpgrp(self.child_fd)
            foreground_processes = processes_in_group(pgrp) if pgrp >= 0 else []
            if foreground_processes:
                # there is no easy way that I know of to know which process is the
                # foreground process in this group from the users perspective,
                # so we assume the one with the highest PID is as that is most
                # likely to be the newest process. This situation can happen
                # for example with a shell script such as:
                # #!/bin/bash
                # cd /tmp
                # vim
                # With this script , the foreground process group will contain
                # both the bash instance running the script and vim.
                return min(foreground_processes) if oldest else max(foreground_processes)
        return self.pid

    @property
    def pid_for_cwd(self) -> int | None:
        return self.get_pid_for_cwd()

    def get_foreground_cwd(self, oldest: bool = False) -> str | None:
        with suppress(Exception):
            pid = self.get_pid_for_cwd(oldest)
            if pid is not None:
                return cwd_of_process(pid) or None
        return None

    def get_foreground_exe(self, oldest: bool = False) -> str | None:
        with suppress(Exception):
            pid = self.get_pid_for_cwd(oldest)
            if pid is not None:
                c = cmdline_of_pid(pid)
                if c:
                    return c[0]
        return None

    @property
    def foreground_cwd(self) -> str | None:
        return self.get_foreground_cwd()

    @property
    def foreground_environ(self) -> dict[str, str]:
        pid = self.pid_for_cwd
        if pid is not None:
            with suppress(Exception):
                return environ_of_process(pid)
        pid = self.pid
        if pid is not None:
            with suppress(Exception):
                return environ_of_process(pid)
        return {}

    def send_signal_for_key(self, key_num: bytes) -> bool:
        import signal
        import termios
        if self.child_fd is None:
            return False
        t = termios.tcgetattr(self.child_fd)
        if not t[3] & termios.ISIG:
            return False
        cc = t[-1]
        if key_num == cc[termios.VINTR]:
            s: signal.Signals = signal.SIGINT
        elif key_num == cc[termios.VSUSP]:
            s = signal.SIGTSTP
        elif key_num == cc[termios.VQUIT]:
            s = signal.SIGQUIT
        else:
            return False
        pgrp = os.tcgetpgrp(self.child_fd)
        os.killpg(pgrp, s)
        return True
