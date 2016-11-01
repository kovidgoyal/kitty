#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
import sysconfig
import shlex
import subprocess

base = os.path.dirname(os.path.abspath(__file__))
build_dir = os.path.join(base, 'build')
constants = os.path.join(base, 'kitty', 'constants.py')
with open(constants, 'rb') as f:
    constants = f.read().decode('utf-8')
appname = re.search(r"^appname = '([^']+)'", constants, re.MULTILINE).group(1)
version = tuple(map(int, re.search(r"^version = \((\d+), (\d+), (\d+)\)", constants, re.MULTILINE).group(1, 2, 3)))


cflags = ldflags = cc = ldpaths = None


def init_env():
    global cflags, ldflags, cc, ldpaths
    cc = os.environ.get('CC', 'gcc')
    cflags = os.environ.get('OVERRIDE_CFLAGS',
                            '-Wextra -Wno-missing-field-initializers -Wall -std=c99 -D_XOPEN_SOURCE=700'
                            ' -pedantic-errors -Werror -O3 -DNDEBUG -fwrapv -fstack-protector-strong -pipe')
    cflags = shlex.split(cflags) + shlex.split(sysconfig.get_config_var('CCSHARED'))
    ldflags = os.environ.get('OVERRIDE_LDFLAGS', '-Wall -O3')
    ldflags = shlex.split(ldflags)
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags += shlex.split(os.environ.get('LDFLAGS', ''))

    cflags.append('-pthread')
    ldflags.append('-pthread')
    ldflags.append('-shared')
    cflags.append('-I' + sysconfig.get_config_var('CONFINCLUDEPY'))
    lib = sysconfig.get_config_var('LDLIBRARY')[3:-3]
    ldpaths = ['-L' + sysconfig.get_config_var('LIBDIR'), '-l' + lib]

    try:
        os.mkdir(build_dir)
    except FileExistsError:
        pass


def run_tool(cmd):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd[0])
    print(' '.join(cmd))
    p = subprocess.Popen(cmd)
    ret = p.wait()
    if ret != 0:
        raise SystemExit(ret)


def compile_c_extension(module, *sources):
    prefix = os.path.basename(module)
    objects = [os.path.join(build_dir, prefix + '-' + os.path.basename(src) + '.o') for src in sources]
    for src, dest in zip(sources, objects):
        src = os.path.join(base, src)
        run_tool([cc] + cflags + ['-c', src] + ['-o', dest])
    run_tool([cc] + ldflags + objects + ldpaths + ['-o', os.path.join(base, module + '.so')])

if __name__ == '__main__':
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    init_env()
    compile_c_extension('kitty/fast_data_types', 'kitty/line.c', 'kitty/data-types.c', 'kitty/line-buf.c', 'kitty/cursor.c')
