#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import errno
import fcntl
import math
import os
import re
import string
import sys
from contextlib import suppress
from functools import lru_cache
from time import monotonic
from typing import (
    Any, Callable, Dict, Generator, Iterable, List, Mapping, Match, NamedTuple,
    Optional, Tuple, Union, cast
)

from .constants import (
    appname, is_macos, is_wayland, read_kitty_resource, shell_path,
    supports_primary_selection
)
from .options_stub import Options
from .rgb import Color, to_color
from .types import run_once
from .typing import AddressFamily, PopenType, Socket, StartupCtx


def expandvars(val: str, env: Mapping[str, str] = {}, fallback_to_os_env: bool = True) -> str:

    def sub(m: Match) -> str:
        key = m.group(1) or m.group(2)
        result = env.get(key)
        if result is None and fallback_to_os_env:
            result = os.environ.get(key)
        if result is None:
            result = m.group()
        return result

    if '$' not in val:
        return val

    return re.sub(r'\$(?:(\w+)|\{([^}]+)\})', sub, val)


def platform_window_id(os_window_id: int) -> Optional[int]:
    if is_macos:
        from .fast_data_types import cocoa_window_id
        with suppress(Exception):
            return cocoa_window_id(os_window_id)
    if not is_wayland():
        from .fast_data_types import x11_window_id
        with suppress(Exception):
            return x11_window_id(os_window_id)


def load_shaders(name: str) -> Tuple[str, str]:
    from .fast_data_types import GLSL_VERSION

    def load(which: str) -> str:
        return read_kitty_resource(f'{name}_{which}.glsl').decode('utf-8').replace('GLSL_VERSION', str(GLSL_VERSION), 1)

    return load('vertex'), load('fragment')


def safe_print(*a: Any, **k: Any) -> None:
    with suppress(Exception):
        print(*a, **k)


def log_error(*a: Any, **k: str) -> None:
    from .fast_data_types import log_error_string
    with suppress(Exception):
        msg = k.get('sep', ' ').join(map(str, a)) + k.get('end', '')
        log_error_string(msg.replace('\0', ''))


def ceil_int(x: float) -> int:
    return int(math.ceil(x))


def sanitize_title(x: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[\0-\x19\x80-\x9f]', '', x))


def color_as_int(val: Tuple[int, int, int]) -> int:
    return val[0] << 16 | val[1] << 8 | val[2]


def color_from_int(val: int) -> Color:
    return Color((val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF)


def parse_color_set(raw: str) -> Generator[Tuple[int, Optional[int]], None, None]:
    parts = raw.split(';')
    lp = len(parts)
    if lp % 2 != 0:
        return
    for c_, spec in [parts[i:i + 2] for i in range(0, len(parts), 2)]:
        try:
            c = int(c_)
            if c < 0 or c > 255:
                continue
            if spec == '?':
                yield c, None
            else:
                q = to_color(spec)
                if q is not None:
                    r, g, b = q
                    yield c, r << 16 | g << 8 | b
        except Exception:
            continue


class ScreenSize(NamedTuple):
    rows: int
    cols: int
    width: int
    height: int
    cell_width: int
    cell_height: int


class ScreenSizeGetter:
    changed = True
    Size = ScreenSize
    ans: Optional[ScreenSize] = None

    def __init__(self, fd: Optional[int]):
        if fd is None:
            fd = sys.stdout.fileno()
        self.fd = fd

    def __call__(self) -> ScreenSize:
        if self.changed:
            import array
            import fcntl
            import termios
            buf = array.array('H', [0, 0, 0, 0])
            fcntl.ioctl(self.fd, termios.TIOCGWINSZ, cast(bytearray, buf))
            rows, cols, width, height = tuple(buf)
            cell_width, cell_height = width // (cols or 1), height // (rows or 1)
            self.ans = ScreenSize(rows, cols, width, height, cell_width, cell_height)
            self.changed = False
        return cast(ScreenSize, self.ans)


@lru_cache(maxsize=64)
def screen_size_function(fd: Optional[int] = None) -> ScreenSizeGetter:
    return ScreenSizeGetter(fd)


def fit_image(width: int, height: int, pwidth: int, pheight: int) -> Tuple[int, int]:
    from math import floor
    if height > pheight:
        corrf = pheight / float(height)
        width, height = floor(corrf * width), pheight
    if width > pwidth:
        corrf = pwidth / float(width)
        width, height = pwidth, floor(corrf * height)
    if height > pheight:
        corrf = pheight / float(height)
        width, height = floor(corrf * width), pheight

    return int(width), int(height)


def set_primary_selection(text: Union[str, bytes]) -> None:
    if not supports_primary_selection:
        return  # There is no primary selection
    from kitty.fast_data_types import set_primary_selection as s
    s(text)


def get_primary_selection() -> str:
    if not supports_primary_selection:
        return ''  # There is no primary selection
    from kitty.fast_data_types import get_primary_selection as g
    return (g() or b'').decode('utf-8', 'replace')


def base64_encode(
    integer: int,
    chars: str = string.ascii_uppercase + string.ascii_lowercase + string.digits +
    '+/'
) -> str:
    ans = ''
    while True:
        integer, remainder = divmod(integer, 64)
        ans = chars[remainder] + ans
        if integer == 0:
            break
    return ans


def command_for_open(program: Union[str, List[str]] = 'default') -> List[str]:
    if isinstance(program, str):
        from .conf.utils import to_cmdline
        program = to_cmdline(program)
    if program == ['default']:
        cmd = ['open'] if is_macos else ['xdg-open']
    else:
        cmd = program
    return cmd


def open_cmd(cmd: Union[Iterable[str], List[str]], arg: Union[None, Iterable[str], str] = None, cwd: Optional[str] = None) -> PopenType:
    import subprocess
    if arg is not None:
        cmd = list(cmd)
        if isinstance(arg, str):
            cmd.append(arg)
        else:
            cmd.extend(arg)
    return subprocess.Popen(tuple(cmd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd or None)


def open_url(url: str, program: Union[str, List[str]] = 'default', cwd: Optional[str] = None) -> PopenType:
    return open_cmd(command_for_open(program), url, cwd=cwd)


def detach(fork: bool = True, setsid: bool = True, redirect: bool = True) -> None:
    if fork:
        # Detach from the controlling process.
        if os.fork() != 0:
            raise SystemExit(0)
    if setsid:
        os.setsid()
    if redirect:
        from .fast_data_types import redirect_std_streams
        redirect_std_streams(os.devnull)


def adjust_line_height(cell_height: int, val: Union[int, float]) -> int:
    if isinstance(val, int):
        return cell_height + val
    return int(cell_height * val)


def init_startup_notification_x11(window_handle: int, startup_id: Optional[str] = None) -> Optional['StartupCtx']:
    # https://specifications.freedesktop.org/startup-notification-spec/startup-notification-latest.txt
    from kitty.fast_data_types import init_x11_startup_notification
    sid = startup_id or os.environ.pop('DESKTOP_STARTUP_ID', None)  # ensure child processes don't get this env var
    if not sid:
        return None
    from .fast_data_types import x11_display
    display = x11_display()
    if not display:
        return None
    return init_x11_startup_notification(display, window_handle, sid)


def end_startup_notification_x11(ctx: 'StartupCtx') -> None:
    from kitty.fast_data_types import end_x11_startup_notification
    end_x11_startup_notification(ctx)


def init_startup_notification(window_handle: Optional[int], startup_id: Optional[str] = None) -> Optional['StartupCtx']:
    if is_macos or is_wayland():
        return None
    if window_handle is None:
        log_error('Could not perform startup notification as window handle not present')
        return None
    try:
        return init_startup_notification_x11(window_handle, startup_id)
    except Exception:
        import traceback
        traceback.print_exc()


def end_startup_notification(ctx: Optional['StartupCtx']) -> None:
    if not ctx:
        return
    if is_macos or is_wayland():
        return
    try:
        end_startup_notification_x11(ctx)
    except Exception:
        import traceback
        traceback.print_exc()


class startup_notification_handler:

    def __init__(self, do_notify: bool = True, startup_id: Optional[str] = None, extra_callback: Optional[Callable] = None):
        self.do_notify = do_notify
        self.startup_id = startup_id
        self.extra_callback = extra_callback
        self.ctx: Optional['StartupCtx'] = None

    def __enter__(self) -> Callable[[int], None]:

        def pre_show_callback(window_handle: int) -> None:
            if self.extra_callback is not None:
                self.extra_callback(window_handle)
            if self.do_notify:
                self.ctx = init_startup_notification(window_handle, self.startup_id)

        return pre_show_callback

    def __exit__(self, *a: Any) -> None:
        if self.ctx is not None:
            end_startup_notification(self.ctx)


def remove_socket_file(s: 'Socket', path: Optional[str] = None) -> None:
    with suppress(OSError):
        s.close()
    if path:
        with suppress(OSError):
            os.unlink(path)


def unix_socket_paths(name: str, ext: str = '.lock') -> Generator[str, None, None]:
    import tempfile
    home = os.path.expanduser('~')
    candidates = [tempfile.gettempdir(), home]
    if is_macos:
        from .fast_data_types import user_cache_dir
        candidates = [user_cache_dir(), '/Library/Caches']
    for loc in candidates:
        if os.access(loc, os.W_OK | os.R_OK | os.X_OK):
            filename = ('.' if loc == home else '') + name + ext
            yield os.path.join(loc, filename)


def single_instance_unix(name: str) -> bool:
    import socket
    for path in unix_socket_paths(name):
        socket_path = path.rpartition('.')[0] + '.sock'
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC)
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as err:
            if err.errno in (errno.EAGAIN, errno.EACCES):
                # Client
                s = socket.socket(family=socket.AF_UNIX)
                s.connect(socket_path)
                single_instance.socket = s
                return False
            raise
        s = socket.socket(family=socket.AF_UNIX)
        try:
            s.bind(socket_path)
        except OSError as err:
            if err.errno in (errno.EADDRINUSE, errno.EEXIST):
                os.unlink(socket_path)
                s.bind(socket_path)
            else:
                raise
        single_instance.socket = s  # prevent garbage collection from closing the socket
        atexit.register(remove_socket_file, s, socket_path)
        s.listen()
        s.set_inheritable(False)
        return True
    return False


class SingleInstance:

    socket: Optional['Socket'] = None

    def __call__(self, group_id: Optional[str] = None) -> bool:
        import socket
        name = '{}-ipc-{}'.format(appname, os.geteuid())
        if group_id:
            name += '-{}'.format(group_id)

        s = socket.socket(family=socket.AF_UNIX)
        # First try with abstract UDS
        addr = '\0' + name
        try:
            s.bind(addr)
        except OSError as err:
            if err.errno == errno.ENOENT:
                return single_instance_unix(name)
            if err.errno == errno.EADDRINUSE:
                s.connect(addr)
                self.socket = s
                return False
            raise
        s.listen()
        self.socket = s  # prevent garbage collection from closing the socket
        s.set_inheritable(False)
        atexit.register(remove_socket_file, s)
        return True


single_instance = SingleInstance()


def parse_address_spec(spec: str) -> Tuple[AddressFamily, Union[Tuple[str, int], str], Optional[str]]:
    import socket
    protocol, rest = spec.split(':', 1)
    socket_path = None
    address: Union[str, Tuple[str, int]] = ''
    if protocol == 'unix':
        family = socket.AF_UNIX
        address = rest
        if address.startswith('@') and len(address) > 1:
            address = '\0' + address[1:]
        else:
            socket_path = address
    elif protocol in ('tcp', 'tcp6'):
        family = socket.AF_INET if protocol == 'tcp' else socket.AF_INET6
        host, port = rest.rsplit(':', 1)
        address = host, int(port)
    else:
        raise ValueError('Unknown protocol in --listen-on value: {}'.format(spec))
    return family, address, socket_path


def write_all(fd: int, data: Union[str, bytes]) -> None:
    if isinstance(data, str):
        data = data.encode('utf-8')
    while data:
        n = os.write(fd, data)
        if not n:
            break
        data = data[n:]


class TTYIO:

    def __enter__(self) -> 'TTYIO':
        from .fast_data_types import open_tty
        self.tty_fd, self.original_termios = open_tty(True)
        return self

    def __exit__(self, *a: Any) -> None:
        from .fast_data_types import close_tty
        close_tty(self.tty_fd, self.original_termios)

    def send(self, data: Union[str, bytes, Iterable[Union[str, bytes]]]) -> None:
        if isinstance(data, (str, bytes)):
            write_all(self.tty_fd, data)
        else:
            for chunk in data:
                write_all(self.tty_fd, chunk)

    def recv(self, more_needed: Callable[[bytes], bool], timeout: float, sz: int = 1) -> None:
        fd = self.tty_fd
        start_time = monotonic()
        while timeout > monotonic() - start_time:
            # will block for 0.1 secs waiting for data because we have set
            # VMIN=0 VTIME=1 in termios
            data = os.read(fd, sz)
            if data and not more_needed(data):
                break


def natsort_ints(iterable: Iterable[str]) -> List[str]:

    def convert(text: str) -> Union[int, str]:
        return int(text) if text.isdigit() else text

    def alphanum_key(key: str) -> Tuple[Union[int, str], ...]:
        return tuple(map(convert, re.split(r'(\d+)', key)))

    return sorted(iterable, key=alphanum_key)


def resolve_editor_cmd(editor: str, shell_env: Mapping[str, str]) -> Optional[str]:
    import shlex
    editor_cmd = shlex.split(editor)
    editor_exe = (editor_cmd or ('',))[0]
    if editor_exe and os.path.isabs(editor_exe):
        return editor
    if not editor_exe:
        return None

    def patched(exe: str) -> str:
        editor_cmd[0] = exe
        return ' '.join(map(shlex.quote, editor_cmd))

    if shell_env is os.environ:
        q = find_exe(editor_exe)
        if q:
            return patched(q)
    elif 'PATH' in shell_env:
        import shutil
        q = shutil.which(editor_exe, path=shell_env['PATH'])
        if q:
            return patched(q)


def get_editor_from_env(env: Mapping[str, str]) -> Optional[str]:
    for var in ('VISUAL', 'EDITOR'):
        editor = env.get(var)
        if editor:
            editor = resolve_editor_cmd(editor, env)
            if editor:
                return editor


def get_editor_from_env_vars(opts: Optional[Options] = None) -> List[str]:
    import shlex
    import shutil

    editor = get_editor_from_env(os.environ)
    if not editor:
        shell_env = read_shell_environment(opts)
        editor = get_editor_from_env(shell_env)

    for ans in (editor, 'vim', 'nvim', 'vi', 'emacs', 'kak', 'micro', 'nano', 'vis'):
        if ans and shutil.which(shlex.split(ans)[0]):
            break
    else:
        ans = 'vim'
    return shlex.split(ans)


def get_editor(opts: Optional[Options] = None) -> List[str]:
    if opts is None:
        from .cli import create_default_opts
        opts = create_default_opts()
    if opts.editor == '.':
        return get_editor_from_env_vars()
    import shlex
    return shlex.split(opts.editor)


def is_path_in_temp_dir(path: str) -> bool:
    if not path:
        return False

    def abspath(x: Optional[str]) -> str:
        if x:
            x = os.path.abspath(os.path.realpath(x))
        return x or ''

    import tempfile
    path = abspath(path)
    candidates = frozenset(map(abspath, ('/tmp', '/dev/shm', os.environ.get('TMPDIR', None), tempfile.gettempdir())))
    for q in candidates:
        if q and path.startswith(q):
            return True
    return False


def func_name(f: Any) -> str:
    if hasattr(f, '__name__'):
        return str(f.__name__)
    if hasattr(f, 'func') and hasattr(f.func, '__name__'):
        return str(f.func.__name__)
    return str(f)


def resolved_shell(opts: Optional[Options] = None) -> List[str]:
    q: str = getattr(opts, 'shell', '.')
    if q == '.':
        ans = [shell_path]
    else:
        import shlex
        ans = shlex.split(q)
    return ans


@run_once
def system_paths_on_macos() -> List[str]:
    entries, seen = [], set()

    def add_from_file(x: str) -> None:
        try:
            f = open(x)
        except FileNotFoundError:
            return
        with f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and line not in seen:
                    if os.path.isdir(line):
                        seen.add(line)
                        entries.append(line)
    try:
        files = os.listdir('/etc/paths.d')
    except FileNotFoundError:
        files = []
    for name in sorted(files):
        add_from_file(os.path.join('/etc/paths.d', name))
    add_from_file('/etc/paths')
    return entries


@lru_cache(maxsize=32)
def find_exe(name: str) -> Optional[str]:
    import shutil
    ans = shutil.which(name)
    if ans is None:
        # In case PATH is messed up
        if is_macos:
            paths = system_paths_on_macos()
        else:
            paths = ['/usr/local/bin', '/opt/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
        paths.insert(0, os.path.expanduser('~/.local/bin'))
        path = os.pathsep.join(paths) + os.pathsep + os.defpath
        ans = shutil.which(name, path=path)
    return ans


def read_shell_environment(opts: Optional[Options] = None) -> Dict[str, str]:
    ans: Optional[Dict[str, str]] = getattr(read_shell_environment, 'ans', None)
    if ans is None:
        from .child import openpty, remove_blocking
        ans = {}
        setattr(read_shell_environment, 'ans', ans)
        import subprocess
        shell = resolved_shell(opts)
        master, slave = openpty()
        remove_blocking(master)
        try:
            p = subprocess.Popen(shell + ['-l', '-c', 'env'], stdout=slave, stdin=slave, stderr=slave, start_new_session=True, close_fds=True)
        except FileNotFoundError:
            log_error('Could not find shell to read environment')
            return ans
        with os.fdopen(master, 'rb') as stdout, os.fdopen(slave, 'wb'):
            raw = b''
            from subprocess import TimeoutExpired
            from time import monotonic
            start_time = monotonic()
            while monotonic() - start_time < 1.5:
                try:
                    ret: Optional[int] = p.wait(0.01)
                except TimeoutExpired:
                    ret = None
                with suppress(Exception):
                    raw += stdout.read()
                if ret is not None:
                    break
            if cast(Optional[int], p.returncode) is None:
                log_error('Timed out waiting for shell to quit while reading shell environment')
                p.kill()
            elif p.returncode == 0:
                while True:
                    try:
                        x = stdout.read()
                    except Exception:
                        break
                    if not x:
                        break
                    raw += x
                draw = raw.decode('utf-8', 'replace')
                for line in draw.splitlines():
                    k, v = line.partition('=')[::2]
                    if k and v:
                        ans[k] = v
            else:
                log_error('Failed to run shell to read its environment')
    return ans


def parse_uri_list(text: str) -> Generator[str, None, None]:
    ' Get paths from file:// URLs '
    from urllib.parse import unquote, urlparse
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        if not line.startswith('file://'):
            yield line
            continue
        try:
            purl = urlparse(line, allow_fragments=False)
        except Exception:
            yield line
            continue
        if purl.path:
            yield unquote(purl.path)


def edit_config_file() -> None:
    from kitty.config import prepare_config_file_for_editing
    p = prepare_config_file_for_editing()
    editor = get_editor()
    os.execvp(editor[0], editor + [p])


class SSHConnectionData(NamedTuple):
    binary: str
    hostname: str
    port: Optional[int] = None
