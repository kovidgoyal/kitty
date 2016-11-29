#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import threading
import pwd
import ctypes
from collections import namedtuple

appname = 'kitty'
version = (0, 1, 0)
str_version = '.'.join(map(str, version))
ScreenGeometry = namedtuple('ScreenGeometry', 'xstart ystart xnum ynum dx dy')
WindowGeometry = namedtuple('WindowGeometry', 'left top right bottom xnum ynum')


def _get_config_dir():
    # This must be called before calling setApplicationName
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['VISE_CONFIG_DIRECTORY']))

    candidate = os.path.abspath(os.path.expanduser(os.environ.get('XDG_CONFIG_HOME') or '~/.config'))
    ans = os.path.join(candidate, appname)
    try:
        os.makedirs(ans)
    except FileExistsError:
        pass
    return ans


config_dir = _get_config_dir()
del _get_config_dir


class ViewportSize:

    __slots__ = ('width', 'height')

    def __init__(self):
        self.width = self.height = 1024

    def __repr__(self):
        return '(width={}, height={})'.format(self.width, self.height)


def tab_manager():
    return tab_manager.manager


def set_tab_manager(m):
    tab_manager.manager = m


def wakeup():
    os.write(tab_manager.manager.write_wakeup_fd, b'1')


def queue_action(func, *args):
    tab_manager.manager.queue_action(func, *args)


viewport_size = ViewportSize()
cell_size = ViewportSize()
terminfo_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'terminfo')
main_thread = threading.current_thread()
shell_path = pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'

GLint = ctypes.c_int if ctypes.sizeof(ctypes.c_int) == 4 else ctypes.c_long
GLuint = ctypes.c_uint if ctypes.sizeof(ctypes.c_uint) == 4 else ctypes.c_ulong
GLfloat = ctypes.c_float
if ctypes.sizeof(GLfloat) != 4:
    raise RuntimeError('float size is not 4')
if ctypes.sizeof(GLint) != 4:
    raise RuntimeError('int size is not 4')
