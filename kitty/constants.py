#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import os
import pwd
import sys
from contextlib import suppress
from functools import lru_cache
from typing import NamedTuple, Optional, Set

from .options_stub import Options


class Version(NamedTuple):
    major: int
    minor: int
    patch: int


appname: str = 'kitty'
version: Version = Version(0, 17, 2)
str_version: str = '.'.join(map(str, version))
_plat = sys.platform.lower()
is_macos: bool = 'darwin' in _plat
base = os.path.dirname(os.path.abspath(__file__))


class ScreenGeometry(NamedTuple):
    xstart: float
    ystart: float
    xnum: int
    ynum: int
    dx: float
    dy: float


class WindowGeometry(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int
    xnum: int
    ynum: int


@lru_cache(maxsize=2)
def kitty_exe() -> str:
    rpath = sys._xoptions.get('bundle_exe_dir')
    if not rpath:
        items = filter(None, os.environ.get('PATH', '').split(os.pathsep))
        seen: Set[str] = set()
        for candidate in items:
            if candidate not in seen:
                seen.add(candidate)
                if os.access(os.path.join(candidate, 'kitty'), os.X_OK):
                    rpath = candidate
                    break
        else:
            rpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'launcher')
    return os.path.join(rpath, 'kitty')


def _get_config_dir() -> str:
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['KITTY_CONFIG_DIRECTORY']))

    locations = []
    if 'XDG_CONFIG_HOME' in os.environ:
        locations.append(os.path.abspath(os.path.expanduser(os.environ['XDG_CONFIG_HOME'])))
    locations.append(os.path.expanduser('~/.config'))
    if is_macos:
        locations.append(os.path.expanduser('~/Library/Preferences'))
    for loc in filter(None, os.environ.get('XDG_CONFIG_DIRS', '').split(os.pathsep)):
        locations.append(os.path.abspath(os.path.expanduser(loc)))
    for loc in locations:
        if loc:
            q = os.path.join(loc, appname)
            if os.access(q, os.W_OK) and os.path.exists(os.path.join(q, 'kitty.conf')):
                return q

    def make_tmp_conf() -> None:
        import tempfile
        import atexit
        ans = tempfile.mkdtemp(prefix='kitty-conf-')

        def cleanup() -> None:
            import shutil
            with suppress(Exception):
                shutil.rmtree(ans)
        atexit.register(cleanup)

    candidate = os.path.abspath(os.path.expanduser(os.environ.get('XDG_CONFIG_HOME') or '~/.config'))
    ans = os.path.join(candidate, appname)
    try:
        os.makedirs(ans, exist_ok=True)
    except FileExistsError:
        raise SystemExit('A file {} already exists. It must be a directory, not a file.'.format(ans))
    except PermissionError:
        make_tmp_conf()
    except OSError as err:
        if err.errno != errno.EROFS:  # Error other than read-only file system
            raise
        make_tmp_conf()
    return ans


config_dir = _get_config_dir()
del _get_config_dir
defconf = os.path.join(config_dir, 'kitty.conf')


@lru_cache(maxsize=2)
def cache_dir() -> str:
    if 'KITTY_CACHE_DIRECTORY' in os.environ:
        candidate = os.path.abspath(os.environ['KITTY_CACHE_DIRECTORY'])
    elif is_macos:
        candidate = os.path.join(os.path.expanduser('~/Library/Caches'), appname)
    else:
        candidate = os.environ.get('XDG_CACHE_HOME', '~/.cache')
        candidate = os.path.join(os.path.expanduser(candidate), appname)
    os.makedirs(candidate, exist_ok=True)
    return candidate


def wakeup() -> None:
    from .fast_data_types import get_boss
    b = get_boss()
    if b is not None:
        b.child_monitor.wakeup()


base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
terminfo_dir = os.path.join(base_dir, 'terminfo')
logo_data_file = os.path.join(base_dir, 'logo', 'kitty.rgba')
logo_png_file = os.path.join(base_dir, 'logo', 'kitty.png')
beam_cursor_data_file = os.path.join(base_dir, 'logo', 'beam-cursor.png')
try:
    shell_path = pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'
except KeyError:
    with suppress(Exception):
        print('Failed to read login shell via getpwuid() for current user, falling back to /bin/sh', file=sys.stderr)
    shell_path = '/bin/sh'


def glfw_path(module: str) -> str:
    return os.path.join(base, 'glfw-{}.so'.format(module))


def detect_if_wayland_ok() -> bool:
    if 'WAYLAND_DISPLAY' not in os.environ:
        return False
    if 'KITTY_DISABLE_WAYLAND' in os.environ:
        return False
    wayland = glfw_path('wayland')
    if not os.path.exists(wayland):
        return False
    # GNOME does not support xdg-decorations
    # https://gitlab.gnome.org/GNOME/mutter/issues/217
    import ctypes
    lib = ctypes.CDLL(wayland)
    check = lib.glfwWaylandCheckForServerSideDecorations
    check.restype = ctypes.c_char_p
    check.argtypes = ()
    try:
        ans = bytes(check())
    except Exception:
        return False
    if ans == b'NO':
        print(
                'Your Wayland compositor does not support server side window decorations,'
                ' disabling Wayland. You can force Wayland support using the'
                ' linux_display_server option in kitty.conf'
                ' See https://drewdevault.com/2018/01/27/Sway-and-client-side-decorations.html'
                ' for more information.',
                file=sys.stderr)
    return ans == b'YES'


def is_wayland(opts: Optional[Options] = None) -> bool:
    if is_macos:
        return False
    if opts is None:
        return bool(getattr(is_wayland, 'ans'))
    if opts.linux_display_server == 'auto':
        ans = detect_if_wayland_ok()
    else:
        ans = opts.linux_display_server == 'wayland'
    setattr(is_wayland, 'ans', ans)
    return ans


supports_primary_selection = not is_macos


def running_in_kitty(set_val: Optional[bool] = None) -> bool:
    if set_val is not None:
        setattr(running_in_kitty, 'ans', set_val)
    return bool(getattr(running_in_kitty, 'ans', False))


def resolve_custom_file(path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isabs(path):
        path = os.path.join(config_dir, path)
    return path
