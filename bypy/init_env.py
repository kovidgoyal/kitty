#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shutil
import subprocess
import sys

from bypy.constants import (
    LIBDIR, PREFIX, PYTHON, SRC as KITTY_DIR, ismacos, worker_env
)
from bypy.utils import run_shell


def read_src_file(name):
    with open(os.path.join(KITTY_DIR, 'kitty', name), 'rb') as f:
        return f.read().decode('utf-8')


def initialize_constants():
    kitty_constants = {}
    src = read_src_file('constants.py')
    nv = re.search(r'Version\((\d+), (\d+), (\d+)\)', src)
    kitty_constants['version'] = '%s.%s.%s' % (nv.group(1), nv.group(2), nv.group(3))
    kitty_constants['appname'] = re.search(
            r'appname: str\s+=\s+(u{0,1})[\'"]([^\'"]+)[\'"]', src
    ).group(2)
    return kitty_constants


def run(*args, **extra_env):
    env = os.environ.copy()
    env.update(worker_env)
    env.update(extra_env)
    env['SW'] = PREFIX
    env['LD_LIBRARY_PATH'] = LIBDIR
    if ismacos:
        env['PKGCONFIG_EXE'] = os.path.join(PREFIX, 'bin', 'pkg-config')
    cwd = env.pop('cwd', KITTY_DIR)
    return subprocess.call(list(args), env=env, cwd=cwd)


def build_c_extensions(ext_dir, args):
    writeable_src_dir = os.path.join(ext_dir, 'src')
    shutil.copytree(
        KITTY_DIR, writeable_src_dir, symlinks=True,
        ignore=shutil.ignore_patterns('b', 'build', 'dist', '*_commands.json', '*.o'))
    cmd = [PYTHON, 'setup.py']
    bundle = 'macos-freeze' if ismacos else 'linux-freeze'
    cmd.append(bundle)
    dest = kitty_constants['appname'] + ('.app' if ismacos else '')
    dest = os.path.join(ext_dir, dest)
    cmd += ['--prefix', dest]
    if run(*cmd, cwd=writeable_src_dir) != 0:
        print('Building of kitty package failed', file=sys.stderr)
        os.chdir(KITTY_DIR)
        run_shell()
        raise SystemExit('Building of kitty package failed')
    return ext_dir


def run_tests(path_to_kitty, cwd_on_failure):
    ret = run(PYTHON, 'test.py', cwd=cwd_on_failure)
    if ret != 0:
        os.chdir(cwd_on_failure)
        print(
            'running kitty tests failed with return code:', ret, file=sys.stderr)
        run_shell()
        raise SystemExit('running kitty tests failed')


if __name__ == 'program':
    kitty_constants = initialize_constants()
