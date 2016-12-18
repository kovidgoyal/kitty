#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
import sysconfig
import shlex
import subprocess
import argparse

base = os.path.dirname(os.path.abspath(__file__))
build_dir = os.path.join(base, 'build')
constants = os.path.join(base, 'kitty', 'constants.py')
with open(constants, 'rb') as f:
    constants = f.read().decode('utf-8')
appname = re.search(r"^appname = '([^']+)'", constants, re.MULTILINE).group(1)
version = tuple(map(int, re.search(r"^version = \((\d+), (\d+), (\d+)\)", constants, re.MULTILINE).group(1, 2, 3)))
is_travis = os.environ.get('TRAVIS') == 'true'


cflags = ldflags = cc = ldpaths = None


def pkg_config(pkg, *args):
    return list(filter(None, shlex.split(subprocess.check_output(['pkg-config', pkg] + list(args)).decode('utf-8'))))


def cc_version():
    cc = os.environ.get('CC', 'gcc')
    raw = subprocess.check_output([cc, '-dumpversion']).decode('utf-8')
    ver = raw.split('.')[:2]
    try:
        ver = tuple(map(int, ver))
    except Exception:
        ver = (0, 0)
    return ver


def init_env(debug=False, asan=False):
    global cflags, ldflags, cc, ldpaths
    ccver = cc_version()
    stack_protector = '-fstack-protector'
    if ccver >= (4, 9):
        stack_protector += '-strong'
    missing_braces = ''
    if ccver < (5, 2):
        missing_braces = '-Wno-missing-braces'
    cc = os.environ.get('CC', 'gcc')
    optimize = '-O3'
    if debug or asan:
        optimize = '-ggdb'
        if asan:
            optimize += ' -fsanitize=address -fno-omit-frame-pointer'
    cflags = os.environ.get('OVERRIDE_CFLAGS', (
        '-Wextra -Wno-missing-field-initializers -Wall -std=c99 -D_XOPEN_SOURCE=700'
        ' -pedantic-errors -Werror {} -DNDEBUG -fwrapv {} {} -pipe').format(optimize, stack_protector, missing_braces))
    cflags = shlex.split(cflags) + shlex.split(sysconfig.get_config_var('CCSHARED'))
    ldflags = os.environ.get('OVERRIDE_LDFLAGS', '-Wall ' + (
        '-fsanitize=address' if asan else ('' if debug else '-O3')))
    ldflags = shlex.split(ldflags)
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags += shlex.split(os.environ.get('LDFLAGS', ''))

    cflags.append('-pthread')
    cflags.extend(pkg_config('glew', '--cflags-only-I'))
    cflags.extend(pkg_config('freetype2', '--cflags-only-I'))
    cflags.extend(pkg_config('glfw3', '--cflags-only-I'))
    ldflags.append('-pthread')
    ldflags.append('-shared')
    cflags.append('-I' + sysconfig.get_config_var('CONFINCLUDEPY'))
    lib = sysconfig.get_config_var('LDLIBRARY')[3:-3]
    ldpaths = ['-L' + sysconfig.get_config_var('LIBDIR'), '-l' + lib] + \
        pkg_config('glew', '--libs') + pkg_config('freetype2', '--libs') + pkg_config('glfw3', '--libs')

    try:
        os.mkdir(build_dir)
    except FileExistsError:
        pass


def define(x):
    return '-D' + x


def run_tool(cmd):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd[0])
    print(' '.join(cmd))
    p = subprocess.Popen(cmd)
    ret = p.wait()
    if ret != 0:
        raise SystemExit(ret)


SPECIAL_SOURCES = {
    'kitty/parser_dump.c': ('kitty/parser.c', ['DUMP_COMMANDS']),
}


def compile_c_extension(module, *sources):
    prefix = os.path.basename(module)
    objects = [os.path.join(build_dir, prefix + '-' + os.path.basename(src) + '.o') for src in sources]
    for src, dest in zip(sources, objects):
        cflgs = cflags[:]
        if src in SPECIAL_SOURCES:
            src, defines = SPECIAL_SOURCES[src]
            cflgs.extend(map(define, defines))

        src = os.path.join(base, src)
        run_tool([cc] + cflgs + ['-c', src] + ['-o', dest])
    run_tool([cc] + ldflags + objects + ldpaths + ['-o', os.path.join(base, module + '.so')])


def option_parser():
    p = argparse.ArgumentParser()
    p.add_argument('action', nargs='?', default='build', choices='build test'.split(), help='Action to perform (default is build)')
    p.add_argument('--debug', default=False, action='store_true',
                   help='Build extension modules with debugging symbols')
    p.add_argument('--asan', default=False, action='store_true',
                   help='Turn on address sanitization to detect memory access errors. Note that if you do turn it on,'
                   ' you have to run kitty with the environment variable LD_PRELOAD=/usr/lib/libasan.so')
    return p


def find_c_files():
    ans = []
    d = os.path.join(base, 'kitty')
    for x in os.listdir(d):
        if x.endswith('.c'):
            ans.append(os.path.join('kitty', x))
    ans.sort(key=lambda x: os.path.getmtime(os.path.join(base, x)), reverse=True)
    ans.append('kitty/parser_dump.c')
    return tuple(ans)


def main():
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args()
    if args.action == 'build':
        init_env(args.debug, args.asan)
        compile_c_extension('kitty/fast_data_types', *find_c_files())
    elif args.action == 'test':
        os.execlp(sys.executable, sys.executable, os.path.join(base, 'test.py'))


if __name__ == '__main__':
    main()
