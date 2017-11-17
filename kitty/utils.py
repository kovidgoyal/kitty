#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import atexit
import errno
import fcntl
import math
import os
import re
import shlex
import socket
import string
import subprocess
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from time import monotonic

from .constants import (
    appname, isosx, iswayland, selection_clipboard_funcs, x11_display,
    x11_window_id
)
from .fast_data_types import (
    GLSL_VERSION, glfw_get_physical_dpi, glfw_primary_monitor_content_scale,
    redirect_std_streams, wcwidth as wcwidth_impl
)
from .rgb import Color, to_color

BASE = os.path.dirname(os.path.abspath(__file__))


def load_shaders(name):
    vert = open(os.path.join(BASE, '{}_vertex.glsl'.format(name))).read().replace('GLSL_VERSION', str(GLSL_VERSION), 1)
    frag = open(os.path.join(BASE, '{}_fragment.glsl'.format(name))).read().replace('GLSL_VERSION', str(GLSL_VERSION), 1)
    return vert, frag


def safe_print(*a, **k):
    try:
        print(*a, **k)
    except Exception:
        pass


def ceil_int(x):
    return int(math.ceil(x))


@lru_cache(maxsize=2**13)
def wcwidth(c: str) -> int:
    try:
        return wcwidth_impl(ord(c))
    except TypeError:
        return wcwidth_impl(ord(c[0]))


@lru_cache()
def pt_to_px(pts):
    dpix, dpiy = get_dpi()['logical']
    dpi = (dpix + dpiy) / 2
    return round(pts * dpi / 72)


@contextmanager
def timeit(name, do_timing=False):
    if do_timing:
        st = monotonic()
    yield
    if do_timing:
        safe_print('Time for {}: {}'.format(name, monotonic() - st))


def sanitize_title(x):
    return re.sub(r'\s+', ' ', re.sub(r'[\0-\x19]', '', x))


@lru_cache()
def load_libx11():
    import ctypes
    from ctypes.util import find_library
    libx11 = ctypes.CDLL(find_library('X11'))

    def cdef(name, restype, *argtypes):
        f = getattr(libx11, name)
        if restype is not None:
            f.restype = restype
        if argtypes:
            f.argtypes = argtypes
        return f

    return cdef('XResourceManagerString', ctypes.c_char_p, ctypes.c_void_p)


def parse_xrdb(raw):
    q = 'Xft.dpi:\t'
    for line in raw.decode('utf-8', 'replace').splitlines():
        if line.startswith(q):
            return float(line[len(q):])


def x11_dpi():
    if iswayland:
        return
    XResourceManagerString = load_libx11()
    display = x11_display()
    if display:
        try:
            raw = XResourceManagerString(display)
            return parse_xrdb(raw)
        except Exception:
            pass


def get_logical_dpi(override_dpi=None):
    # See https://github.com/glfw/glfw/issues/1019 for why we cant use
    # glfw_get_physical_dpi()
    if override_dpi is not None:
        get_logical_dpi.ans = override_dpi
    if not hasattr(get_logical_dpi, 'ans'):
        if isosx:
            # TODO: Investigate if this needs a different implementation on OS X
            get_logical_dpi.ans = glfw_get_physical_dpi()
        else:
            try:
                xscale, yscale = glfw_primary_monitor_content_scale()
            except NotImplementedError:  # glfw < 3.3
                xdpi = ydpi = x11_dpi()
                if xdpi is None:
                    xdpi, ydpi = glfw_get_physical_dpi()
            else:
                xdpi, ydpi = xscale * 96.0, yscale * 96.0
            get_logical_dpi.ans = xdpi, ydpi
    return get_logical_dpi.ans


def get_dpi():
    if not hasattr(get_dpi, 'ans'):
        pdpi = glfw_get_physical_dpi()
        get_dpi.ans = {'physical': pdpi, 'logical': get_logical_dpi()}
    return get_dpi.ans


def color_as_int(val):
    return val[0] << 16 | val[1] << 8 | val[2]


def color_from_int(val):
    return Color((val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF)


def parse_color_set(raw):
    parts = raw.split(';')
    for c, spec in [parts[i:i + 2] for i in range(0, len(parts), 2)]:
        try:
            c = int(c)
            if c < 0 or c > 255:
                raise IndexError('Out of bounds')
            r, g, b = to_color(spec)
            yield c, r << 16 | g << 8 | b
        except Exception:
            continue


def set_primary_selection(text):
    if isosx:
        return  # There is no primary selection on OS X
    if isinstance(text, str):
        text = text.encode('utf-8')
    s = selection_clipboard_funcs()[1]
    if s is None:
        p = subprocess.Popen(['xsel', '-i', '-p'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.stdin.write(text), p.stdin.close()
        p.wait()
    else:
        s(text)


def get_primary_selection():
    if isosx:
        return ''  # There is no primary selection on OS X
    g = selection_clipboard_funcs()[0]
    if g is None:
        # We cannot use check_output as we set a SIGCHLD handler to reap zombies
        ans = subprocess.Popen(['xsel', '-p'], stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE).stdout.read().decode('utf-8')
        if ans:
            # Without this for some reason repeated pastes dont work
            set_primary_selection(ans)
    else:
        ans = (g() or b'').decode('utf-8', 'replace')
    return ans


def base64_encode(
    integer,
    chars=string.ascii_uppercase + string.ascii_lowercase + string.digits +
    '+/'
):
    ans = ''
    while True:
        integer, remainder = divmod(integer, 64)
        ans = chars[remainder] + ans
        if integer == 0:
            break
    return ans


def open_cmd(cmd, arg=None):
    if arg is not None:
        cmd = list(cmd)
        cmd.append(arg)
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url, program='default'):
    if program == 'default':
        cmd = ['open'] if isosx else ['xdg-open']
    else:
        cmd = shlex.split(program)
    return open_cmd(cmd, url)


def detach(fork=True, setsid=True, redirect=True):
    if fork:
        # Detach from the controlling process.
        if os.fork() != 0:
            raise SystemExit(0)
    if setsid:
        os.setsid()
    if redirect:
        redirect_std_streams(os.devnull)


def adjust_line_height(cell_height, val):
    if isinstance(val, int):
        return cell_height + val
    return int(cell_height * val)


def init_startup_notification_x11(window_id, startup_id=None):
    # https://specifications.freedesktop.org/startup-notification-spec/startup-notification-latest.txt
    from kitty.fast_data_types import init_x11_startup_notification
    sid = startup_id or os.environ.pop('DESKTOP_STARTUP_ID', None)  # ensure child processes dont get this env var
    if not sid:
        return
    display = x11_display()
    if not display:
        return
    window_id = x11_window_id(window_id)
    return init_x11_startup_notification(display, window_id, sid)


def end_startup_notification_x11(ctx):
    from kitty.fast_data_types import end_x11_startup_notification
    end_x11_startup_notification(ctx)


def init_startup_notification(window, startup_id=None):
    if isosx or iswayland:
        return
    try:
        return init_startup_notification_x11(window, startup_id)
    except Exception:
        import traceback
        traceback.print_exc()


def end_startup_notification(ctx):
    if not ctx:
        return
    if isosx or iswayland:
        return
    try:
        end_startup_notification_x11(ctx)
    except Exception:
        import traceback
        traceback.print_exc()


def remove_socket_file(s, path=None):
    try:
        s.close()
    except EnvironmentError:
        pass
    if path:
        try:
            os.unlink(path)
        except EnvironmentError:
            pass


def single_instance_unix(name):
    home = os.path.expanduser('~')
    candidates = [tempfile.gettempdir(), home]
    if isosx:
        from .fast_data_types import user_cache_dir
        candidates = [user_cache_dir(), '/Library/Caches']
    for loc in candidates:
        if os.access(loc, os.W_OK | os.R_OK | os.X_OK):
            filename = ('.' if loc == home else '') + name + '.lock'
            path = os.path.join(loc, filename)
            socket_path = path.rpartition('.')[0] + '.sock'
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC)
            try:
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except EnvironmentError as err:
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
            except EnvironmentError as err:
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


def single_instance(group_id=None):
    name = '{}-ipc-{}'.format(appname, os.geteuid())
    if group_id:
        name += '-{}'.format(group_id)

    s = socket.socket(family=socket.AF_UNIX)
    # First try with abstract UDS
    addr = '\0' + name
    try:
        s.bind(addr)
    except EnvironmentError as err:
        if err.errno == errno.ENOENT:
            return single_instance_unix(name)
        if err.errno == errno.EADDRINUSE:
            s.connect(addr)
            single_instance.socket = s
            return False
        raise
    s.listen()
    single_instance.socket = s  # prevent garbage collection from closing the socket
    s.set_inheritable(False)
    atexit.register(remove_socket_file, s)
    return True
