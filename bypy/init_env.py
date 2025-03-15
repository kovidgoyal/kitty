#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress

from bypy.constants import LIBDIR, PREFIX, PYTHON, ismacos, worker_env
from bypy.constants import SRC as KITTY_DIR
from bypy.utils import run_shell, walk


def read_src_file(name):
    with open(os.path.join(KITTY_DIR, 'kitty', name), 'rb') as f:
        return f.read().decode('utf-8')


def initialize_constants():
    kitty_constants = {}
    src = read_src_file('constants.py')
    nv = re.search(r'Version\((\d+), (\d+), (\d+)\)', src)
    kitty_constants['version'] = f'{nv.group(1)}.{nv.group(2)}.{nv.group(3)}'
    kitty_constants['appname'] = re.search(
            r'appname: str\s+=\s+(u{0,1})[\'"]([^\'"]+)[\'"]', src
    ).group(2)
    kitty_constants['cacerts_url'] = 'https://curl.haxx.se/ca/cacert.pem'
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
    print(' '.join(map(shlex.quote, args)), flush=True)
    return subprocess.call(list(args), env=env, cwd=cwd)


SETUP_CMD = [PYTHON, 'setup.py']


def build_frozen_launcher(extra_include_dirs):
    inc_dirs = [f'--extra-include-dirs={x}' for x in extra_include_dirs]
    cmd = SETUP_CMD + ['--prefix', build_frozen_launcher.prefix] + inc_dirs + ['build-frozen-launcher']
    if run(*cmd, cwd=build_frozen_launcher.writeable_src_dir) != 0:
        print('Building of frozen kitty launcher failed', file=sys.stderr)
        os.chdir(KITTY_DIR)
        run_shell()
        raise SystemExit('Building of kitty launcher failed')
    return build_frozen_launcher.writeable_src_dir


def run_tests(kitty_exe):
    with tempfile.TemporaryDirectory() as tdir:
        uenv = {
            'KITTY_CONFIG_DIRECTORY': os.path.join(tdir, 'conf'),
            'KITTY_CACHE_DIRECTORY': os.path.join(tdir, 'cache')
        }
        [os.mkdir(x) for x in uenv.values()]
        env = os.environ.copy()
        env.update(uenv)
        cmd = [kitty_exe, '+runpy', 'from kitty_tests.main import run_tests; run_tests(report_env=True)']
        print(*map(shlex.quote, cmd), flush=True)
        if subprocess.call(cmd, env=env, cwd=build_frozen_launcher.writeable_src_dir) != 0:
            print('Checking of kitty build failed, in directory:', build_frozen_launcher.writeable_src_dir, file=sys.stderr)
            os.chdir(os.path.dirname(kitty_exe))
            run_shell()
            raise SystemExit('Checking of kitty build failed')


def build_frozen_tools(kitty_exe):
    cmd = SETUP_CMD + ['--prefix', os.path.dirname(kitty_exe)] + ['build-frozen-tools']
    if run(*cmd, cwd=build_frozen_launcher.writeable_src_dir) != 0:
        print('Building of frozen kitten failed', file=sys.stderr)
        os.chdir(KITTY_DIR)
        run_shell()
        raise SystemExit('Building of kitten launcher failed')


def sanitize_source_folder(path: str) -> None:
    for q in walk(path):
        if os.path.splitext(q)[1] not in ('.py', '.glsl', '.ttf', '.otf', '.json'):
            os.unlink(q)


def build_c_extensions(ext_dir, args):
    writeable_src_dir = os.path.join(ext_dir, 'src')
    build_frozen_launcher.writeable_src_dir = writeable_src_dir
    shutil.copytree(
        KITTY_DIR, writeable_src_dir, symlinks=True,
        ignore=shutil.ignore_patterns('b', 'build', 'dist', '*_commands.json', '*.o', '*.so', '*.dylib', '*.pyd'))

    with suppress(FileNotFoundError):
        os.unlink(os.path.join(writeable_src_dir, 'kitty', 'launcher', 'kitty'))

    cmd = SETUP_CMD + ['macos-freeze' if ismacos else 'linux-freeze']
    if args.dont_strip:
        cmd.append('--debug')
    if args.extra_program_data:
        cmd.append(f'--vcs-rev={args.extra_program_data}')
    dest = kitty_constants['appname'] + ('.app' if ismacos else '')
    dest = build_frozen_launcher.prefix = os.path.join(ext_dir, dest)
    cmd += ['--prefix', dest, '--full']
    if run(*cmd, cwd=writeable_src_dir) != 0:
        print('Building of kitty package failed', file=sys.stderr)
        os.chdir(writeable_src_dir)
        run_shell()
        raise SystemExit('Building of kitty package failed')
    return ext_dir


if __name__ == 'program':
    kitty_constants = initialize_constants()
