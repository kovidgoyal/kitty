#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import pwd
import sys
from collections import namedtuple

appname = 'kitty'
version = (0, 13, 3)
str_version = '.'.join(map(str, version))
_plat = sys.platform.lower()
is_macos = 'darwin' in _plat
base = os.path.dirname(os.path.abspath(__file__))


ScreenGeometry = namedtuple('ScreenGeometry', 'xstart ystart xnum ynum dx dy')
WindowGeometry = namedtuple('WindowGeometry', 'left top right bottom xnum ynum')


def kitty_exe():
    ans = getattr(kitty_exe, 'ans', None)
    if ans is None:
        rpath = sys._xoptions.get('bundle_exe_dir')
        if not rpath:
            items = os.environ['PATH'].split(os.pathsep)
            seen = set()
            for candidate in items:
                if candidate not in seen:
                    seen.add(candidate)
                    if os.access(os.path.join(candidate, 'kitty'), os.X_OK):
                        rpath = candidate
                        break
            else:
                rpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'launcher')
        ans = kitty_exe.ans = os.path.join(rpath, 'kitty')
    return ans


def _get_config_dir():
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['KITTY_CONFIG_DIRECTORY']))

    locations = []
    if 'XDG_CONFIG_HOME' in os.environ:
        locations.append(os.path.abspath(os.path.expanduser(os.environ['XDG_CONFIG_HOME'])))
    locations.append(os.path.expanduser('~/.config'))
    if is_macos:
        locations.append(os.path.expanduser('~/Library/Preferences'))
    if 'XDG_CONFIG_DIRS' in os.environ:
        for loc in os.environ['XDG_CONFIG_DIRS'].split(os.pathsep):
            locations.append(os.path.abspath(os.path.expanduser(loc)))
    for loc in locations:
        if loc:
            q = os.path.join(loc, appname)
            if os.access(q, os.W_OK) and os.path.exists(os.path.join(q, 'kitty.conf')):
                return q

    candidate = os.path.abspath(os.path.expanduser(os.environ.get('XDG_CONFIG_HOME') or '~/.config'))
    ans = os.path.join(candidate, appname)
    try:
        os.makedirs(ans, exist_ok=True)
    except FileExistsError:
        raise SystemExit('A file {} already exists. It must be a directory, not a file.'.format(ans))
    except PermissionError:
        import tempfile
        import atexit
        ans = tempfile.mkdtemp(prefix='kitty-conf-')

        def cleanup():
            import shutil
            try:
                shutil.rmtree(ans)
            except Exception:
                pass
        atexit.register(cleanup)
    return ans


config_dir = _get_config_dir()
del _get_config_dir
defconf = os.path.join(config_dir, 'kitty.conf')


def _get_cache_dir():
    if 'KITTY_CACHE_DIRECTORY' in os.environ:
        candidate = os.path.abspath(os.environ['KITTY_CACHE_DIRECTORY'])
    elif is_macos:
        candidate = os.path.join(os.path.expanduser('~/Library/Caches'), appname)
    else:
        candidate = os.environ.get('XDG_CACHE_HOME', '~/.cache')
        candidate = os.path.join(os.path.expanduser(candidate), appname)
    os.makedirs(candidate, exist_ok=True)
    return candidate


def cache_dir():
    ans = getattr(cache_dir, 'ans', None)
    if ans is None:
        ans = cache_dir.ans = _get_cache_dir()
    return ans


def get_boss():
    return get_boss.boss


def set_boss(m):
    from .fast_data_types import set_boss as set_c_boss
    get_boss.boss = m
    set_c_boss(m)


def wakeup():
    get_boss.boss.child_monitor.wakeup()


base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
terminfo_dir = os.path.join(base_dir, 'terminfo')
logo_data_file = os.path.join(base_dir, 'logo', 'kitty.rgba')
logo_png_file = os.path.join(base_dir, 'logo', 'kitty.png')
beam_cursor_data_file = os.path.join(base_dir, 'logo', 'beam-cursor.png')
try:
    shell_path = pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'
except KeyError:
    try:
        print('Failed to read login shell via getpwuid() for current user, falling back to /bin/sh', file=sys.stderr)
    except Exception:
        pass
    shell_path = '/bin/sh'


def glfw_path(module):
    return os.path.join(base, 'glfw-{}.so'.format(module))


is_wayland = False
if os.environ.get('WAYLAND_DISPLAY') and 'KITTY_DISABLE_WAYLAND' not in os.environ and os.path.exists(glfw_path('wayland')):
    is_wayland = True


supports_primary_selection = not is_macos
