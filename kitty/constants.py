#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import pwd
import ctypes
import sys
from collections import namedtuple

from .fast_data_types import set_boss as set_c_boss, handle_for_window_id

appname = 'kitty'
version = (0, 5, 1)
str_version = '.'.join(map(str, version))
_plat = sys.platform.lower()
isosx = 'darwin' in _plat


ScreenGeometry = namedtuple('ScreenGeometry', 'xstart ystart xnum ynum dx dy')
WindowGeometry = namedtuple('WindowGeometry', 'left top right bottom xnum ynum')


def _get_config_dir():
    # This must be called before calling setApplicationName
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['VISE_CONFIG_DIRECTORY']))

    candidate = os.path.abspath(os.path.expanduser(os.environ.get('XDG_CONFIG_HOME') or ('~/Library/Preferences' if isosx else '~/.config')))
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

GLint = ctypes.c_int if ctypes.sizeof(ctypes.c_int) == 4 else ctypes.c_long
GLuint = ctypes.c_uint if ctypes.sizeof(ctypes.c_uint) == 4 else ctypes.c_ulong
GLfloat = ctypes.c_float
if ctypes.sizeof(GLfloat) != 4:
    raise RuntimeError('float size is not 4')
if ctypes.sizeof(GLint) != 4:
    raise RuntimeError('int size is not 4')


def get_glfw_lib_name():
    try:
        for line in open('/proc/self/maps'):
            lib = line.split()[-1]
            if '/libglfw.so' in lib:
                return lib
    except Exception as err:
        try:
            print(str(err), file=sys.stderr)
        except Exception:
            pass
    return 'libglfw.so.3'


def glfw_lib():
    ans = getattr(glfw_lib, 'ans', None)
    if ans is None:
        ans = glfw_lib.ans = ctypes.CDLL('libglfw.3.dylib' if isosx else get_glfw_lib_name())
    return ans


def selection_clipboard_funcs():
    ans = getattr(selection_clipboard_funcs, 'ans', None)
    if ans is None:
        lib = glfw_lib()
        if hasattr(lib, 'glfwGetX11SelectionString'):
            g = lib.glfwGetX11SelectionString
            g.restype = ctypes.c_char_p
            g.argtypes = []
            s = lib.glfwSetX11SelectionString
            s.restype = None
            s.argtypes = [ctypes.c_char_p]
            ans = g, s
        else:
            ans = None, None
        selection_clipboard_funcs.ans = ans
    return ans


def x11_window_id(window_id):
    lib = glfw_lib()
    lib.glfwGetX11Window.restype = ctypes.c_int32
    lib.glfwGetX11Window.argtypes = [ctypes.c_void_p]
    return lib.glfwGetX11Window(handle_for_window_id(window_id))


def x11_display():
    lib = glfw_lib()
    ans = lib.glfwGetX11Display
    ans.restype = ctypes.c_void_p
    ans.argtypes = []
    return ans()


iswayland = not isosx and hasattr(glfw_lib(), 'glfwGetWaylandDisplay')
