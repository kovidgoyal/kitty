#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import re
import subprocess
import ctypes
from contextlib import contextmanager
from functools import lru_cache
from time import monotonic


libc = ctypes.CDLL(None)
wcwidth_native = libc.wcwidth
del libc
wcwidth_native.argtypes = [ctypes.c_wchar]
wcwidth_native.restype = ctypes.c_int


@lru_cache(maxsize=2**13)
def wcwidth(c: str) -> int:
    ans = min(2, wcwidth_native(c))
    if ans == -1:
        ans = 1
    return ans


@contextmanager
def timeit(name, do_timing=False):
    if do_timing:
        st = monotonic()
    yield
    if do_timing:
        print('Time for {}: {}'.format(name, monotonic() - st))


def sanitize_title(x):
    return re.sub(br'\s+', b' ', re.sub(br'[\0-\x19]', b'', x))


def get_logical_dpi():
    if not hasattr(get_logical_dpi, 'ans'):
        raw = subprocess.check_output(['xdpyinfo']).decode('utf-8')
        m = re.search(r'^\s*resolution:\s*(\d+)+x(\d+)', raw, flags=re.MULTILINE)
        get_logical_dpi.ans = int(m.group(1)), int(m.group(2))
    return get_logical_dpi.ans


def get_dpi():
    import glfw
    if not hasattr(get_dpi, 'ans'):
        m = glfw.glfwGetPrimaryMonitor()
        width, height = glfw.glfwGetMonitorPhysicalSize(m)
        vmode = glfw.glfwGetVideoMode(m)
        dpix = vmode.width / (width / 25.4)
        dpiy = vmode.height / (height / 25.4)
        get_dpi.ans = {'physical': (dpix, dpiy), 'logical': get_logical_dpi()}
    return get_dpi.ans
