#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import os
import sys
from collections import defaultdict
from contextlib import contextmanager, suppress
from typing import (
    DefaultDict, Dict, Generator, List, Optional, Sequence, Tuple
)

import kitty.fast_data_types as fast_data_types

from .constants import is_macos, shell_path, terminfo_dir

try:
    from typing import TypedDict
except ImportError:
    TypedDict = dict


if is_macos:
    from kitty.fast_data_types import (
            cmdline_of_process, cwd_of_process as _cwd, environ_of_process as _environ_of_process,
            process_group_map as _process_group_map
    )

    def cwd_of_process(pid: int) -> str:
        return os.path.realpath(_cwd(pid))

    def process_group_map() -> DefaultDict[int, List[int]]:
        ans: DefaultDict[int, List] = defaultdict(list)
        for pid, pgid in _process_group_map():
            ans[pgid].append(pid)
        return ans

else:

    def cmdline_of_process(pid: int) -> List[str]:
        with open('/proc/{}/cmdline'.format(pid), 'rb') as f:
            return list(filter(None, f.read().decode('utf-8').split('\0')))

    def cwd_of_process(pid: int) -> str:
        ans = '/proc/{}/cwd'.format(pid)
        return os.path.realpath(ans)

    def _environ_of_process(pid: int) -> str:
        with open('/proc/{}/environ'.format(pid), 'rb') as f:
            return f.read().decode('utf-8')

    def process_group_map() -> DefaultDict[int, List[int]]:
        ans: DefaultDict[int, List[int]] = defaultdict(list)
        for x in os.listdir('/proc'):
            try:
                pid = int(x)
            except Exception:
                continue
            try:
                with open('/proc/' + x + '/stat', 'rb') as f:
                    raw = f.read().decode('utf-8')
            except OSError:
                continue
            try:
                q = int(raw.split(' ', 5)[4])
            except Exception:
                continue
            ans[q].append(pid)
        return ans


def checked_terminfo_dir() -> Optional[str]:
    q = getattr(checked_terminfo_dir, 'ans', False)
    if q is False:
        ans = terminfo_dir if os.path.isdir(terminfo_dir) else None
        setattr(checked_terminfo_dir, 'ans', ans)
    else:
        ans = q
    return ans


def processes_in_group(grp: int) -> List[int]:
    gmap: Optional[DefaultDict[int, List[int]]] = getattr(process_group_map, 'cached_map', None)
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


def parse_environ_block(data: str) -> Dict[str, str]:
    """Parse a C environ block of environment variables into a dictionary."""
    # The block is usually raw data from the target process.  It might contain
    # trailing garbage and lines that do not look like assignments.
    ret: Dict[str, str] = {}
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


def environ_of_process(pid: int) -> Dict[str, str]:
    return parse_environ_block(_environ_of_process(pid))


def remove_cloexec(fd: int) -> None:
    fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.fcntl(fd, fcntl.F_GETFD) & ~fcntl.FD_CLOEXEC)


def remove_blocking(fd: int) -> None:
    os.set_blocking(fd, False)


def process_env() -> Dict[str, str]:
    ans = dict(os.environ)
    ssl_env_var = getattr(sys, 'kitty_ssl_env_var', None)
    if ssl_env_var is not None:
        ans.pop(ssl_env_var, None)
    return ans


def default_env() -> Dict[str, str]:
    ans: Optional[Dict[str, str]] = getattr(default_env, 'env', None)
    if ans is None:
        return process_env()
    return ans


def set_default_env(val: Optional[Dict[str, str]] = None) -> None:
    env = process_env().copy()
    has_lctype = False
    if val:
        has_lctype = 'LC_CTYPE' in val
        env.update(val)
    setattr(default_env, 'env', env)
    setattr(default_env, 'lc_ctype_set_by_user', has_lctype)


def openpty() -> Tuple[int, int]:
    master, slave = os.openpty()  # Note that master and slave are in blocking mode
    remove_cloexec(slave)
    fast_data_types.set_iutf8_fd(master, True)
    return master, slave


class ProcessDesc(TypedDict):
    cwd: Optional[str]
    pid: int
    cmdline: Optional[Sequence[str]]


class Child:

    child_fd: Optional[int] = None
    pid: Optional[int] = None
    forked = False

    def __init__(
        self,
        argv: Sequence[str],
        cwd: str,
        stdin: Optional[bytes] = None,
        env: Optional[Dict[str, str]] = None,
        cwd_from: Optional[int] = None,
        allow_remote_control: bool = False
    ):
        self.allow_remote_control = allow_remote_control
        self.argv = argv
        if cwd_from is not None:
            try:
                cwd = cwd_of_process(cwd_from)
            except Exception:
                import traceback
                traceback.print_exc()
        else:
            cwd = os.path.expandvars(os.path.expanduser(cwd or os.getcwd()))
        self.cwd = os.path.abspath(cwd)
        self.stdin = stdin
        self.env = env or {}

    @property
    def final_env(self) -> Dict[str, str]:
        env: Optional[Dict[str, str]] = getattr(self, '_final_env', None)
        if env is None:
            env = self._final_env = default_env().copy()
            if is_macos and env.get('LC_CTYPE') == 'UTF-8' and not sys._xoptions.get(
                    'lc_ctype_before_python') and not getattr(default_env, 'lc_ctype_set_by_user', False):
                del env['LC_CTYPE']
            env.update(self.env)
            env['TERM'] = fast_data_types.get_options().term
            env['COLORTERM'] = 'truecolor'
            if self.cwd:
                # needed in case cwd is a symlink, in which case shells
                # can use it to display the current directory name rather
                # than the resolved path
                env['PWD'] = self.cwd
            tdir = checked_terminfo_dir()
            if tdir:
                env['TERMINFO'] = tdir
        return env

    def fork(self) -> Optional[int]:
        if self.forked:
            return None
        self.forked = True
        master, slave = openpty()
        stdin, self.stdin = self.stdin, None
        ready_read_fd, ready_write_fd = os.pipe()
        remove_cloexec(ready_read_fd)
        if stdin is not None:
            stdin_read_fd, stdin_write_fd = os.pipe()
            remove_cloexec(stdin_read_fd)
        else:
            stdin_read_fd = stdin_write_fd = -1
        env = tuple('{}={}'.format(k, v) for k, v in self.final_env.items())
        argv = list(self.argv)
        exe = argv[0]
        if is_macos and exe == shell_path:
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
            argv[0] = ('-' + exe.split('/')[-1])
        pid = fast_data_types.spawn(exe, self.cwd, tuple(argv), env, master, slave, stdin_read_fd, stdin_write_fd, ready_read_fd, ready_write_fd)
        os.close(slave)
        self.pid = pid
        self.child_fd = master
        if stdin is not None:
            os.close(stdin_read_fd)
            fast_data_types.thread_write(stdin_write_fd, stdin)
        os.close(ready_read_fd)
        self.terminal_ready_fd = ready_write_fd
        if self.child_fd is not None:
            remove_blocking(self.child_fd)
        return pid

    def mark_terminal_ready(self) -> None:
        os.close(self.terminal_ready_fd)
        self.terminal_ready_fd = -1

    @property
    def foreground_processes(self) -> List[ProcessDesc]:
        if self.child_fd is None:
            return []
        try:
            pgrp = os.tcgetpgrp(self.child_fd)
            foreground_processes = processes_in_group(pgrp) if pgrp >= 0 else []

            def process_desc(pid: int) -> ProcessDesc:
                ans: ProcessDesc = {'pid': pid, 'cmdline': None, 'cwd': None}
                with suppress(Exception):
                    ans['cmdline'] = cmdline_of_process(pid)
                with suppress(Exception):
                    ans['cwd'] = cwd_of_process(pid) or None
                return ans

            return [process_desc(x) for x in foreground_processes]
        except Exception:
            return []

    @property
    def cmdline(self) -> List[str]:
        try:
            assert self.pid is not None
            return cmdline_of_process(self.pid) or list(self.argv)
        except Exception:
            return list(self.argv)

    @property
    def foreground_cmdline(self) -> List[str]:
        try:
            assert self.pid_for_cwd is not None
            return cmdline_of_process(self.pid_for_cwd) or self.cmdline
        except Exception:
            return self.cmdline

    @property
    def environ(self) -> Dict[str, str]:
        try:
            assert self.pid is not None
            return environ_of_process(self.pid)
        except Exception:
            return {}

    @property
    def current_cwd(self) -> Optional[str]:
        with suppress(Exception):
            assert self.pid is not None
            return cwd_of_process(self.pid)

    @property
    def pid_for_cwd(self) -> Optional[int]:
        with suppress(Exception):
            assert self.child_fd is not None
            pgrp = os.tcgetpgrp(self.child_fd)
            foreground_processes = processes_in_group(pgrp) if pgrp >= 0 else []
            if len(foreground_processes) == 1:
                return foreground_processes[0]
        return self.pid

    @property
    def foreground_cwd(self) -> Optional[str]:
        with suppress(Exception):
            assert self.pid_for_cwd is not None
            return cwd_of_process(self.pid_for_cwd) or None

    @property
    def foreground_environ(self) -> Dict[str, str]:
        try:
            assert self.pid_for_cwd is not None
            return environ_of_process(self.pid_for_cwd)
        except Exception:
            try:
                assert self.pid is not None
                return environ_of_process(self.pid)
            except Exception:
                pass
        return {}
