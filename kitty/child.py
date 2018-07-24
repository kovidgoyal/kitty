#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import fcntl
import os

import kitty.fast_data_types as fast_data_types

from .constants import is_macos, shell_path, terminfo_dir

if is_macos:
    from kitty.fast_data_types import cmdline_of_process as _cmdl, cwd_of_process as _cwd

    def cmdline_of_process(pid):
        return _cmdl(pid)

    def cwd_of_process(pid):
        return os.path.realpath(_cwd(pid))

else:

    def cmdline_of_process(pid):
        return list(filter(None, open('/proc/{}/cmdline'.format(pid), 'rb').read().decode('utf-8').split('\0')))

    def cwd_of_process(pid):
        ans = '/proc/{}/cwd'.format(pid)
        return os.path.realpath(ans)


def remove_cloexec(fd):
    fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.fcntl(fd, fcntl.F_GETFD) & ~fcntl.FD_CLOEXEC)


def default_env():
    try:
        return default_env.env
    except AttributeError:
        return os.environ


def set_default_env(val=None):
    env = os.environ.copy()
    if val:
        env.update(val)
    default_env.env = env


class Child:

    child_fd = pid = None
    forked = False

    def __init__(self, argv, cwd, opts, stdin=None, env=None, cwd_from=None):
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
        self.opts = opts
        self.stdin = stdin
        self.env = env or {}

    def fork(self):
        if self.forked:
            return
        self.forked = True
        master, slave = os.openpty()  # Note that master and slave are in blocking mode
        remove_cloexec(slave)
        fast_data_types.set_iutf8(master, True)
        stdin, self.stdin = self.stdin, None
        if stdin is not None:
            stdin_read_fd, stdin_write_fd = os.pipe()
            remove_cloexec(stdin_read_fd)
        else:
            stdin_read_fd = stdin_write_fd = -1
        env = default_env().copy()
        env.update(self.env)
        env['TERM'] = self.opts.term
        env['COLORTERM'] = 'truecolor'
        if os.path.isdir(terminfo_dir):
            env['TERMINFO'] = terminfo_dir
        env = tuple('{}={}'.format(k, v) for k, v in env.items())
        argv = list(self.argv)
        exe = argv[0]
        if is_macos and exe == shell_path:
            # Some macOS machines need the shell to have argv[0] prefixed by
            # hyphen, see https://github.com/kovidgoyal/kitty/issues/247
            argv[0] = ('-' + exe.split('/')[-1])
        pid = fast_data_types.spawn(exe, self.cwd, tuple(argv), env, master, slave, stdin_read_fd, stdin_write_fd)
        os.close(slave)
        self.pid = pid
        self.child_fd = master
        if stdin is not None:
            os.close(stdin_read_fd)
            fast_data_types.thread_write(stdin_write_fd, stdin)
        fcntl.fcntl(self.child_fd, fcntl.F_SETFL, fcntl.fcntl(self.child_fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        return pid

    @property
    def cmdline(self):
        try:
            return cmdline_of_process(self.pid) or list(self.argv)
        except Exception:
            return list(self.argv)

    @property
    def current_cwd(self):
        try:
            return cwd_of_process(self.pid)
        except Exception:
            pass
