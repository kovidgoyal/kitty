#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import pwd
import sys
from collections import namedtuple

from .fast_data_types import set_boss as set_c_boss

appname = 'kitty'
version = (0, 6, 0)
str_version = '.'.join(map(str, version))
_plat = sys.platform.lower()
is_macos = 'darwin' in _plat
base = os.path.dirname(os.path.abspath(__file__))


ScreenGeometry = namedtuple('ScreenGeometry', 'xstart ystart xnum ynum dx dy')
WindowGeometry = namedtuple('WindowGeometry', 'left top right bottom xnum ynum')


def _get_config_dir():
    # This must be called before calling setApplicationName
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['VISE_CONFIG_DIRECTORY']))

    candidate = os.path.abspath(os.path.expanduser(os.environ.get('XDG_CONFIG_HOME') or ('~/Library/Preferences' if is_macos else '~/.config')))
    ans = os.path.join(candidate, appname)
    os.makedirs(ans, exist_ok=True)
    return ans


config_dir = _get_config_dir()
del _get_config_dir
defconf = os.path.join(config_dir, 'kitty.conf')


def get_boss():
    return get_boss.boss


def set_boss(m):
    get_boss.boss = m
    set_c_boss(m)


def wakeup():
    get_boss.boss.child_monitor.wakeup()


base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
terminfo_dir = os.path.join(base_dir, 'terminfo')
logo_data_file = os.path.join(base_dir, 'logo', 'kitty.rgba')
try:
    shell_path = pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'
except KeyError:
    print('Failed to read login shell from /etc/passwd for current user, falling back to /bin/sh', file=sys.stderr)
    shell_path = '/bin/sh'


def glfw_path(module):
    return os.path.join(base, 'glfw-{}.so'.format(module))


is_wayland = False
if os.environ.get('WAYLAND_DISPLAY') and 'KITTY_ENABLE_WAYLAND' in os.environ and os.path.exists(glfw_path('wayland')):
    is_wayland = True
