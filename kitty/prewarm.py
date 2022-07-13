#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import fcntl
import io
import json
import os
import select
import signal
import socket
import struct
import sys
import termios
import time
import traceback
import warnings
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from itertools import count
from typing import (
    IO, TYPE_CHECKING, Any, Callable, Dict, Iterator, List, NoReturn, Optional,
    Tuple, TypeVar, Union, cast
)

from kitty.constants import kitty_exe, running_in_kitty
from kitty.entry_points import main as main_entry_point
from kitty.fast_data_types import (
    CLD_EXITED, CLD_KILLED, CLD_STOPPED, get_options, getpeereid,
    install_signal_handlers, read_signals, remove_signal_handlers, safe_pipe,
    set_options
)
from kitty.options.types import Options
from kitty.shm import SharedMemory
from kitty.types import SignalInfo
from kitty.utils import log_error, random_unix_socket, safer_fork

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer, WriteableBuffer


error_events = select.POLLERR | select.POLLNVAL | select.POLLHUP
TIMEOUT = 15.0 if os.environ.get('CI') == 'true' else 5.0


def restore_python_signal_handlers() -> None:
    remove_signal_handlers()
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    signal.signal(signal.SIGUSR1, signal.SIG_DFL)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)


def print_error(*a: Any) -> None:
    log_error('Prewarm zygote:', *a)


class PrewarmProcessFailed(Exception):
    pass


@dataclass
class Child:
    child_id: int
    child_process_pid: int


def wait_for_child_death(child_pid: int, timeout: float = 1, options: int = 0) -> Optional[int]:
    st = time.monotonic()
    while not timeout or time.monotonic() - st < timeout:
        try:
            pid, status = os.waitpid(child_pid, options | os.WNOHANG)
        except ChildProcessError:
            return 0
        else:
            if pid == child_pid:
                return status
        if not timeout:
            break
        time.sleep(0.01)
    return None


class PrewarmProcess:

    def __init__(
        self,
        prewarm_process_pid: int,
        to_prewarm_stdin: int,
        from_prewarm_stdout: int,
        from_prewarm_death_notify: int,
        unix_socket_name: str,
    ) -> None:
        self.children: Dict[int, Child] = {}
        self.worker_pid = prewarm_process_pid
        self.from_prewarm_death_notify = from_prewarm_death_notify
        self.write_to_process_fd = to_prewarm_stdin
        self.read_from_process_fd = from_prewarm_stdout
        self.poll = select.poll()
        self.poll.register(self.read_from_process_fd, select.POLLIN)
        self.unix_socket_name = unix_socket_name

    def socket_env_var(self) -> str:
        return f'{os.geteuid()}:{os.getegid()}:{self.unix_socket_name}'

    def take_from_worker_fd(self, create_file: bool = False) -> int:
        if create_file:
            os.set_blocking(self.from_prewarm_death_notify, True)
            self.from_worker = open(self.from_prewarm_death_notify, mode='r', closefd=True)
            self.from_prewarm_death_notify = -1
            return -1
        ans, self.from_prewarm_death_notify = self.from_prewarm_death_notify, -1
        return ans

    def __del__(self) -> None:
        if self.write_to_process_fd > -1:
            safe_close(self.write_to_process_fd)
            self.write_to_process_fd = -1
        if self.from_prewarm_death_notify > -1:
            safe_close(self.from_prewarm_death_notify)
            self.from_prewarm_death_notify = -1
        if self.read_from_process_fd > -1:
            safe_close(self.read_from_process_fd)
            self.read_from_process_fd = -1

        if hasattr(self, 'from_worker'):
            self.from_worker.close()
            del self.from_worker
        if self.worker_pid > 0:
            if wait_for_child_death(self.worker_pid) is None:
                log_error('Prewarm process failed to quit gracefully, killing it')
                os.kill(self.worker_pid, signal.SIGKILL)
                os.waitpid(self.worker_pid, 0)

    def poll_to_send(self, yes: bool = True) -> None:
        if yes:
            self.poll.register(self.write_to_process_fd, select.POLLOUT)
        else:
            self.poll.unregister(self.write_to_process_fd)

    def reload_kitty_config(self, opts: Optional[Options] = None) -> None:
        if opts is None:
            opts = get_options()
        data = json.dumps({'paths': opts.config_paths, 'overrides': opts.config_overrides})
        if self.write_to_process_fd > -1:
            self.send_to_prewarm_process(f'reload_kitty_config:{data}\n')

    def __call__(
        self,
        tty_fd: int,
        argv: List[str],
        cwd: str = '',
        env: Optional[Dict[str, str]] = None,
        stdin_data: Optional[Union[str, bytes]] = None,
        timeout: float = TIMEOUT,
    ) -> Child:
        tty_name = os.ttyname(tty_fd)
        if isinstance(stdin_data, str):
            stdin_data = stdin_data.encode()
        if env is None:
            env = dict(os.environ)
        cmd: Dict[str, Union[int, List[str], str, Dict[str, str]]] = {
            'tty_name': tty_name, 'cwd': cwd or os.getcwd(), 'argv': argv, 'env': env,
        }
        total_size = 0
        if stdin_data is not None:
            cmd['stdin_size'] = len(stdin_data)
            total_size += len(stdin_data)
        data = json.dumps(cmd).encode()
        total_size += len(data) + SharedMemory.num_bytes_for_size
        with SharedMemory(size=total_size, unlink_on_exit=True) as shm:
            shm.write_data_with_size(data)
            if stdin_data:
                shm.write(stdin_data)
            shm.flush()
            self.send_to_prewarm_process(f'fork:{shm.name}\n')
            input_buf = b''
            st = time.monotonic()
            while time.monotonic() - st < timeout:
                for (fd, event) in self.poll.poll(2):
                    if event & error_events:
                        raise PrewarmProcessFailed('Failed doing I/O with prewarm process')
                    if fd == self.read_from_process_fd and event & select.POLLIN:
                        d = os.read(self.read_from_process_fd, io.DEFAULT_BUFFER_SIZE)
                        input_buf += d
                        while (idx := input_buf.find(b'\n')) > -1:
                            line = input_buf[:idx].decode()
                            input_buf = input_buf[idx+1:]
                            if line.startswith('CHILD:'):
                                _, cid, pid = line.split(':')
                                child = self.add_child(int(cid), int(pid))
                                shm.unlink_on_exit = False
                                return child
                            if line.startswith('ERR:'):
                                raise PrewarmProcessFailed(line.split(':', 1)[-1])
        raise PrewarmProcessFailed('Timed out waiting for I/O with prewarm process')

    def add_child(self, child_id: int, pid: int) -> Child:
        self.children[child_id] = c = Child(child_id, pid)
        return c

    def send_to_prewarm_process(self, output_buf: Union[str, bytes] = b'', timeout: float = TIMEOUT) -> None:
        if isinstance(output_buf, str):
            output_buf = output_buf.encode()
        st = time.monotonic()
        while time.monotonic() - st < timeout and output_buf:
            self.poll_to_send(bool(output_buf))
            for (fd, event) in self.poll.poll(2):
                if event & error_events:
                    raise PrewarmProcessFailed(f'Failed doing I/O with prewarm process: {event}')
                if fd == self.write_to_process_fd and event & select.POLLOUT:
                    n = os.write(self.write_to_process_fd, output_buf)
                    output_buf = output_buf[n:]
        self.poll_to_send(False)
        if output_buf:
            raise PrewarmProcessFailed('Timed out waiting to write to prewarm process')

    def mark_child_as_ready(self, child_id: int) -> bool:
        c = self.children.pop(child_id, None)
        if c is None:
            return False
        self.send_to_prewarm_process(f'ready:{child_id}\n')
        return True


def reload_kitty_config(payload: str) -> None:
    d = json.loads(payload)
    from kittens.tui.utils import set_kitty_opts
    set_kitty_opts(paths=d['paths'], overrides=d['overrides'])


def prewarm() -> None:
    from kittens.runner import all_kitten_names
    for kitten in all_kitten_names():
        with suppress(Exception):
            import_module(f'kittens.{kitten}.main')
    import_module('kitty.complete')


class MemoryViewReadWrapperBytes(io.BufferedIOBase):

    def __init__(self, mw: memoryview):
        self.mw = mw
        self.pos = 0

    def detach(self) -> io.RawIOBase:
        raise io.UnsupportedOperation('detach() not supported')

    def read(self, size: Optional[int] = -1) -> bytes:
        if size is None or size < 0:
            size = max(0, len(self.mw) - self.pos)
        oldpos = self.pos
        self.pos = min(len(self.mw), self.pos + size)
        if self.pos <= oldpos:
            return b''
        return bytes(self.mw[oldpos:self.pos])

    def readinto(self, b: 'WriteableBuffer') -> int:
        if not isinstance(b, memoryview):
            b = memoryview(b)
        b = b.cast('B')
        data = self.read(len(b))
        n = len(data)
        b[:n] = data
        return n
    readinto1 = readinto

    def readall(self) -> bytes:
        return self.read()

    def write(self, b: 'ReadableBuffer') -> int:
        raise io.UnsupportedOperation('readonly stream')

    def readable(self) -> bool:
        return True


class MemoryViewReadWrapper(io.TextIOWrapper):

    def __init__(self, mw: memoryview):
        super().__init__(cast(IO[bytes], MemoryViewReadWrapperBytes(mw)), encoding='utf-8', errors='replace')


parent_tty_name = ''
is_zygote = True


def debug(*a: Any) -> None:
    if parent_tty_name:
        with open(parent_tty_name, 'w') as f:
            print(*a, file=f)


def child_main(cmd: Dict[str, Any], ready_fd: int = -1, prewarm_type: str = 'direct') -> NoReturn:
    getattr(sys, 'kitty_run_data')['prewarmed'] = prewarm_type
    cwd = cmd.get('cwd')
    if cwd:
        with suppress(OSError):
            os.chdir(cwd)
    env = cmd.get('env')
    if env is not None:
        os.environ.clear()
        os.environ.update(env)
    argv = cmd.get('argv')
    if argv:
        sys.argv = list(argv)
    if ready_fd > -1:
        poll = select.poll()
        poll.register(ready_fd, select.POLLIN)
        tuple(poll.poll())
        safe_close(ready_fd)
    main_entry_point()
    raise SystemExit(0)


def fork(shm_address: str, free_non_child_resources: Callable[[], None]) -> Tuple[int, int]:
    global is_zygote
    sz = pos = 0
    with SharedMemory(name=shm_address, unlink_on_exit=True) as shm:
        data = shm.read_data_with_size()
        cmd = json.loads(data)
        sz = cmd.get('stdin_size', 0)
        if sz:
            pos = shm.tell()
            shm.unlink_on_exit = False

    r, w = safe_pipe()
    ready_fd_read, ready_fd_write = safe_pipe()
    try:
        child_pid = safer_fork()
    except OSError:
        safe_close(r)
        safe_close(w)
        safe_close(ready_fd_read)
        safe_close(ready_fd_write)
        if sz:
            with SharedMemory(shm_address, unlink_on_exit=True):
                pass
        raise
    if child_pid:
        # master process
        safe_close(w)
        safe_close(ready_fd_read)
        poll = select.poll()
        poll.register(r, select.POLLIN)
        tuple(poll.poll())
        safe_close(r)
        return child_pid, ready_fd_write
    # child process
    is_zygote = False
    restore_python_signal_handlers()
    safe_close(r)
    safe_close(ready_fd_write)
    free_non_child_resources()
    os.setsid()
    tty_name = cmd.get('tty_name')
    if tty_name:
        sys.__stdout__.flush()
        sys.__stderr__.flush()
        establish_controlling_tty(tty_name, sys.__stdin__.fileno(), sys.__stdout__.fileno(), sys.__stderr__.fileno())
    safe_close(w)
    if shm.unlink_on_exit:
        child_main(cmd, ready_fd_read)
    else:
        with SharedMemory(shm_address, unlink_on_exit=True) as shm:
            stdin_data = memoryview(shm.mmap)[pos:pos + sz]
            if stdin_data:
                sys.stdin = MemoryViewReadWrapper(stdin_data)
            try:
                child_main(cmd, ready_fd_read)
            finally:
                stdin_data.release()
                sys.stdin = sys.__stdin__


def verify_socket_creds(conn: socket.socket) -> bool:
    # needed as abstract unix sockets used on Linux have no permissions and
    # older BSDs ignore socket file permissions
    uid, gid = getpeereid(conn.fileno())
    return uid == os.geteuid() and gid == os.getegid()


class SocketChildData:
    def __init__(self) -> None:
        self.cwd = self.tty_name = ''
        self.argv: List[str] = []
        self.env: Dict[str, str] = {}


Funtion = TypeVar('Funtion', bound=Callable[..., Any])


def eintr_retry(func: Funtion) -> Funtion:
    def ret(*a: Any, **kw: Any) -> Any:
        while True:
            with suppress(InterruptedError):
                return func(*a, **kw)
    return cast(Funtion, ret)


safe_close = eintr_retry(os.close)
safe_open = eintr_retry(os.open)
safe_ioctl = eintr_retry(fcntl.ioctl)
safe_dup2 = eintr_retry(os.dup2)


def establish_controlling_tty(fd_or_tty_name: Union[str, int], *dups: int, closefd: bool = True) -> int:
    tty_name = os.ttyname(fd_or_tty_name) if isinstance(fd_or_tty_name, int) else fd_or_tty_name
    with open(safe_open(tty_name, os.O_RDWR | os.O_CLOEXEC), 'w', closefd=closefd) as f:
        tty_fd = f.fileno()
        safe_ioctl(tty_fd, termios.TIOCSCTTY, 0)
        for fd in dups:
            safe_dup2(tty_fd, fd)
        return -1 if closefd else tty_fd


interactive_and_job_control_signals = (
    signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP, signal.SIGTTIN, signal.SIGTTOU
)


def fork_socket_child(child_data: SocketChildData, tty_fd: int, stdio_fds: Dict[str, int], free_non_child_resources: Callable[[], None]) -> int:
    # see https://www.gnu.org/software/libc/manual/html_node/Launching-Jobs.html
    child_pid = safer_fork()
    if child_pid:
        return child_pid
    # child process
    eintr_retry(os.setpgid)(0, 0)
    eintr_retry(os.tcsetpgrp)(tty_fd, eintr_retry(os.getpgid)(0))
    for x in interactive_and_job_control_signals:
        signal.signal(x, signal.SIG_DFL)
    restore_python_signal_handlers()
    # the std streams fds are closed in free_non_child_resources()
    for which in ('stdin', 'stdout', 'stderr'):
        fd = stdio_fds[which] if stdio_fds[which] > -1 else tty_fd
        safe_dup2(fd, getattr(sys, which).fileno())
    free_non_child_resources()
    child_main({'cwd': child_data.cwd, 'env': child_data.env, 'argv': child_data.argv}, prewarm_type='socket')


def fork_socket_child_supervisor(conn: socket.socket, free_non_child_resources: Callable[[], None]) -> None:
    import array
    global is_zygote
    if safer_fork():
        conn.close()
        return
    is_zygote = False
    os.setsid()
    restore_python_signal_handlers()
    free_non_child_resources()
    signal_read_fd = install_signal_handlers(signal.SIGCHLD, signal.SIGUSR1)[0]
    # See https://www.gnu.org/software/libc/manual/html_node/Initializing-the-Shell.html
    for x in interactive_and_job_control_signals:
        signal.signal(x, signal.SIG_IGN)
    poll = select.poll()
    poll.register(signal_read_fd, select.POLLIN)
    from_socket_buf = b''
    to_socket_buf = b''
    keep_going = True
    child_pid = -1
    socket_fd = conn.fileno()
    launch_msg_read = False
    os.set_blocking(socket_fd, False)
    received_fds: List[int] = []
    stdio_positions = dict.fromkeys(('stdin', 'stdout', 'stderr'), -1)
    stdio_fds = dict.fromkeys(('stdin', 'stdout', 'stderr'), -1)
    winsize = 8
    exit_after_write = False
    child_data = SocketChildData()

    def handle_signal(siginfo: SignalInfo) -> None:
        nonlocal to_socket_buf, exit_after_write, child_pid
        if siginfo.si_signo != signal.SIGCHLD or siginfo.si_code not in (CLD_KILLED, CLD_EXITED, CLD_STOPPED):
            return
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG | os.WUNTRACED)
            except ChildProcessError:
                pid = 0
            if not pid:
                break
            if pid != child_pid:
                continue
            to_socket_buf += struct.pack('q', status)
            if not os.WIFSTOPPED(status):
                exit_after_write = True
                child_pid = -1

    def write_to_socket() -> None:
        nonlocal keep_going, to_socket_buf, keep_going
        buf = memoryview(to_socket_buf)
        while buf:
            try:
                n = os.write(socket_fd, buf)
            except OSError:
                n = 0
            if n == 0:
                keep_going = False
                return
            buf = buf[n:]
        to_socket_buf = bytes(buf)
        if exit_after_write and not to_socket_buf:
            keep_going = False

    def read_winsize() -> None:
        nonlocal from_socket_buf
        msg = conn.recv(io.DEFAULT_BUFFER_SIZE)
        if not msg:
            return
        from_socket_buf += msg
        data = memoryview(from_socket_buf)
        record = memoryview(b'')
        while len(data) >= winsize:
            record, data = data[:winsize], data[winsize:]
        if record:
            try:
                with open(safe_open(os.ctermid(), os.O_RDWR | os.O_CLOEXEC), 'w') as f:
                    safe_ioctl(f.fileno(), termios.TIOCSWINSZ, record)
            except OSError:
                traceback.print_exc()
        from_socket_buf = bytes(data)

    def read_launch_msg() -> bool:
        nonlocal keep_going, from_socket_buf, launch_msg_read, winsize
        try:
            msg, ancdata, flags, addr = conn.recvmsg(io.DEFAULT_BUFFER_SIZE, 1024)
        except OSError as e:
            if e.errno == errno.ENOMEM:
                # macOS does this when no ancilliary data is present
                msg, ancdata, flags, addr = conn.recvmsg(io.DEFAULT_BUFFER_SIZE)
            else:
                raise

        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds = array.array("i")   # Array of ints
                # Append data, ignoring any truncated integers at the end.
                fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
                received_fds.extend(fds)

        if not msg:
            return False
        from_socket_buf += msg
        while (idx := from_socket_buf.find(b'\0')) > -1:
            line = from_socket_buf[:idx].decode('utf-8')
            from_socket_buf = from_socket_buf[idx+1:]
            cmd, _, payload = line.partition(':')
            if cmd == 'finish':
                for x in received_fds:
                    os.set_inheritable(x, True)
                    os.set_blocking(x, True)
                for k, pos in stdio_positions.items():
                    if pos > -1:
                        stdio_fds[k] = received_fds[pos]
                del received_fds[:]
                return True
            elif cmd == 'cwd':
                child_data.cwd = payload
            elif cmd == 'env':
                k, _, v = payload.partition('=')
                child_data.env[k] = v
            elif cmd == 'argv':
                child_data.argv.append(payload)
            elif cmd in stdio_positions:
                stdio_positions[cmd] = int(payload)
            elif cmd == 'tty_name':
                child_data.tty_name = payload
            elif cmd == 'winsize':
                winsize = int(payload)
        return False

    def free_non_child_resources2() -> None:
        for fd in received_fds:
            safe_close(fd)
        for k, v in tuple(stdio_fds.items()):
            if v > -1:
                safe_close(v)
                stdio_fds[k] = -1
        conn.close()

    def launch_child() -> None:
        nonlocal to_socket_buf, child_pid
        sys.__stdout__.flush()
        sys.__stderr__.flush()
        tty_fd = establish_controlling_tty(child_data.tty_name, closefd=False)
        child_pid = fork_socket_child(child_data, tty_fd, stdio_fds, free_non_child_resources2)
        if child_pid:
            # this is also done in the child process, but we dont
            # know when, so do it here as well
            eintr_retry(os.setpgid)(child_pid, child_pid)
            eintr_retry(os.tcsetpgrp)(tty_fd, child_pid)
            for fd in stdio_fds.values():
                if fd > -1:
                    safe_close(fd)
            safe_close(tty_fd)
        else:
            raise SystemExit('fork_socket_child() returned in the child process')
        to_socket_buf += struct.pack('q', child_pid)

    def read_from_socket() -> None:
        nonlocal launch_msg_read
        if launch_msg_read:
            read_winsize()
        else:
            if read_launch_msg():
                launch_msg_read = True
                launch_child()

    try:
        while keep_going:
            poll.register(socket_fd, select.POLLIN | (select.POLLOUT if to_socket_buf else 0))
            for fd, event in poll.poll():
                if event & error_events:
                    keep_going = False
                    break
                if fd == socket_fd:
                    if event & select.POLLOUT:
                        write_to_socket()
                    if event & select.POLLIN:
                        read_from_socket()
                elif fd == signal_read_fd and event & select.POLLIN:
                    read_signals(signal_read_fd, handle_signal)
    finally:
        if child_pid:  # supervisor process
            with suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                conn.close()

    raise SystemExit(0)


def main(stdin_fd: int, stdout_fd: int, notify_child_death_fd: int, unix_socket: socket.socket) -> None:
    global parent_tty_name
    with suppress(OSError):
        parent_tty_name = os.ttyname(sys.stdout.fileno())
    os.set_blocking(notify_child_death_fd, False)
    os.set_blocking(stdin_fd, False)
    os.set_blocking(stdout_fd, False)
    signal_read_fd = install_signal_handlers(signal.SIGCHLD, signal.SIGUSR1)[0]
    os.set_blocking(unix_socket.fileno(), False)
    unix_socket.listen(5)
    poll = select.poll()
    poll.register(stdin_fd, select.POLLIN)
    poll.register(signal_read_fd, select.POLLIN)
    poll.register(unix_socket.fileno(), select.POLLIN)
    input_buf = output_buf = child_death_buf = b''
    child_ready_fds: Dict[int, int] = {}
    child_pid_map: Dict[int, int] = {}
    child_id_counter = count()
    # runpy issues a warning when running modules that have already been
    # imported. Ignore it.
    warnings.filterwarnings('ignore', category=RuntimeWarning, module='runpy')
    prewarm()

    def get_all_non_child_fds() -> Iterator[int]:
        yield notify_child_death_fd
        yield stdin_fd
        yield stdout_fd
        # the signal fds are closed by remove_signal_handlers()
        yield from child_ready_fds.values()

    def free_non_child_resources() -> None:
        for fd in get_all_non_child_fds():
            if fd > -1:
                safe_close(fd)
        unix_socket.close()

    def check_event(event: int, err_msg: str) -> None:
        if event & select.POLLHUP:
            raise SystemExit(0)
        if event & error_events:
            print_error(err_msg)
            raise SystemExit(1)

    def handle_input(event: int) -> None:
        nonlocal input_buf, output_buf
        check_event(event, 'Polling of input pipe failed')
        if not (event & select.POLLIN):
            return
        d = os.read(stdin_fd, io.DEFAULT_BUFFER_SIZE)
        if not d:
            raise SystemExit(0)
        input_buf += d
        while (idx := input_buf.find(b'\n')) > -1:
            line = input_buf[:idx].decode()
            input_buf = input_buf[idx+1:]
            cmd, _, payload = line.partition(':')
            if cmd == 'reload_kitty_config':
                reload_kitty_config(payload)
            elif cmd == 'ready':
                child_id = int(payload)
                cfd = child_ready_fds.pop(child_id, None)
                if cfd is not None:
                    safe_close(cfd)
            elif cmd == 'quit':
                raise SystemExit(0)
            elif cmd == 'fork':
                try:
                    child_pid, ready_fd_write = fork(payload, free_non_child_resources)
                except Exception as e:
                    es = str(e).replace('\n', ' ')
                    output_buf += f'ERR:{es}\n'.encode()
                else:
                    if is_zygote:
                        child_id = next(child_id_counter)
                        child_pid_map[child_pid] = child_id
                        child_ready_fds[child_id] = ready_fd_write
                        output_buf += f'CHILD:{child_id}:{child_pid}\n'.encode()
            elif cmd == 'echo':
                output_buf += f'{payload}\n'.encode()

    def handle_output(event: int) -> None:
        nonlocal output_buf
        check_event(event, 'Polling of output pipe failed')
        if not (event & select.POLLOUT):
            return
        if output_buf:
            n = os.write(stdout_fd, output_buf)
            if not n:
                raise SystemExit(0)
            output_buf = output_buf[n:]
        if not output_buf:
            poll.unregister(stdout_fd)

    def handle_notify_child_death(event: int) -> None:
        nonlocal child_death_buf
        check_event(event, 'Polling of notify child death pipe failed')
        if not (event & select.POLLOUT):
            return
        if child_death_buf:
            n = os.write(notify_child_death_fd, child_death_buf)
            if not n:
                raise SystemExit(0)
            child_death_buf = child_death_buf[n:]
        if not child_death_buf:
            poll.unregister(notify_child_death_fd)

    def handle_child_death(dead_child_id: int, dead_child_pid: int) -> None:
        nonlocal child_death_buf
        xfd = child_ready_fds.pop(dead_child_id, None)
        if xfd is not None:
            safe_close(xfd)
        child_death_buf += f'{dead_child_pid}\n'.encode()

    def handle_signals(event: int) -> None:
        check_event(event, 'Polling of signal pipe failed')
        if not event & select.POLLIN:
            return

        def handle_signal(siginfo: SignalInfo) -> None:
            if siginfo.si_signo != signal.SIGCHLD or siginfo.si_code not in (CLD_KILLED, CLD_EXITED, CLD_STOPPED):
                return
            while True:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG | os.WUNTRACED)
                except ChildProcessError:
                    pid = 0
                if not pid:
                    break
                child_id = child_pid_map.pop(pid, None)
                if child_id is not None:
                    handle_child_death(child_id, pid)

        read_signals(signal_read_fd, handle_signal)

    def handle_socket_client(event: int) -> None:
        check_event(event, 'UNIX socket fd listener failed')
        conn, addr = unix_socket.accept()
        if not verify_socket_creds(conn):
            print_error('Connection attempted with invalid credentials ignoring')
            conn.close()
            return
        fork_socket_child_supervisor(conn, free_non_child_resources)

    keep_type_checker_happy = True
    try:
        while is_zygote and keep_type_checker_happy:
            if output_buf:
                poll.register(stdout_fd, select.POLLOUT)
            if child_death_buf:
                poll.register(notify_child_death_fd, select.POLLOUT)
            for (q, event) in poll.poll():
                if q == stdin_fd:
                    handle_input(event)
                elif q == stdout_fd:
                    handle_output(event)
                elif q == signal_read_fd:
                    handle_signals(event)
                elif q == notify_child_death_fd:
                    handle_notify_child_death(event)
                elif q == unix_socket.fileno():
                    handle_socket_client(event)
    except (KeyboardInterrupt, EOFError, BrokenPipeError):
        if is_zygote:
            raise SystemExit(1)
        raise
    except Exception:
        if is_zygote:
            traceback.print_exc()
        raise
    finally:
        if is_zygote:
            restore_python_signal_handlers()
            for fmd in child_ready_fds.values():
                with suppress(OSError):
                    safe_close(fmd)


def get_socket_name(unix_socket: socket.socket) -> str:
    sname = unix_socket.getsockname()
    if isinstance(sname, bytes):
        sname = sname.decode('utf-8')
    assert isinstance(sname, str)
    if sname.startswith('\0'):
        sname = '@' + sname[1:]
    return sname


def exec_main(stdin_read: int, stdout_write: int, death_notify_write: int, unix_socket: Optional[socket.socket] = None) -> None:
    os.setsid()
    os.set_inheritable(stdin_read, False)
    os.set_inheritable(stdout_write, False)
    os.set_inheritable(death_notify_write, False)
    running_in_kitty(False)
    if unix_socket is None:
        unix_socket = random_unix_socket()
        os.write(stdout_write, f'{get_socket_name(unix_socket)}\n'.encode('utf-8'))
    try:
        main(stdin_read, stdout_write, death_notify_write, unix_socket)
    finally:
        set_options(None)
        if is_zygote:
            unix_socket.close()


def fork_prewarm_process(opts: Options, use_exec: bool = False) -> Optional[PrewarmProcess]:
    stdin_read, stdin_write = safe_pipe()
    stdout_read, stdout_write = safe_pipe()
    death_notify_read, death_notify_write = safe_pipe()
    if use_exec:
        import subprocess
        tp = subprocess.Popen(
            [kitty_exe(), '+runpy', f'from kitty.prewarm import exec_main; exec_main({stdin_read}, {stdout_write}, {death_notify_write})'],
            pass_fds=(stdin_read, stdout_write, death_notify_write))
        child_pid = tp.pid
        tp.returncode = 0  # prevent a warning when the popen object is deleted with the process still running
        os.set_blocking(stdout_read, True)
        with open(stdout_read, 'rb', closefd=False) as f:
            socket_name = f.readline().decode('utf-8').rstrip()
        os.set_blocking(stdout_read, False)
    else:
        unix_socket = random_unix_socket()
        socket_name = get_socket_name(unix_socket)
        child_pid = safer_fork()
    if child_pid:
        # master
        if not use_exec:
            unix_socket.close()
        safe_close(stdin_read)
        safe_close(stdout_write)
        safe_close(death_notify_write)
        p = PrewarmProcess(child_pid, stdin_write, stdout_read, death_notify_read, socket_name)
        if use_exec:
            p.reload_kitty_config()
        return p
    # child
    safe_close(stdin_write)
    safe_close(stdout_read)
    safe_close(death_notify_read)
    set_options(opts)
    exec_main(stdin_read, stdout_write, death_notify_write, unix_socket)
    raise SystemExit(0)
