#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import re
import sys
import sysconfig
import shlex
import shutil
import subprocess
import argparse

base = os.path.dirname(os.path.abspath(__file__))
build_dir = os.path.join(base, 'build')
constants = os.path.join(base, 'kitty', 'constants.py')
with open(constants, 'rb') as f:
    constants = f.read().decode('utf-8')
appname = re.search(r"^appname = '([^']+)'", constants, re.MULTILINE).group(1)
version = tuple(map(int, re.search(r"^version = \((\d+), (\d+), (\d+)\)", constants, re.MULTILINE).group(1, 2, 3)))
_plat = sys.platform.lower()
isosx = 'darwin' in _plat
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
    if not is_travis and subprocess.Popen('pkg-config --atleast-version=2 glew'.split()).wait() != 0:
        try:
            ver = subprocess.check_output('pkg-config --modversion glew'.split()).decode('utf-8').strip()
        except Exception:
            ver = 'not found'
        major = int(re.match(r'\d+', ver))
        if major < 2:
            raise SystemExit('glew >= 2.0.0 is required, found version: ' + ver)
    cflags.extend(pkg_config('glew', '--cflags-only-I'))
    cflags.extend(pkg_config('freetype2', '--cflags-only-I'))
    cflags.extend(pkg_config('glfw3', '--cflags-only-I'))
    ldflags.append('-shared')
    cflags.append('-I' + sysconfig.get_config_var('CONFINCLUDEPY'))
    if isosx:
        fd = sysconfig.get_config_var('LIBDIR')
        try:
            fd = fd[:fd.index('/Python.framework')]
        except ValueError:
            fd = sysconfig.get_config_var('LIBDEST')
            fd = fd[:fd.index('/Python.framework')]
        pylib = ['-F' + fd, '-framework', 'Python']
    else:
        lib = sysconfig.get_config_var('LDLIBRARY')
        if lib.startswith('lib'):
            lib = lib[3:]
        if lib.endswith('.so'):
            lib = lib[:-3]
        pylib = ['-L' + sysconfig.get_config_var('LIBDIR'), '-l' + lib]
    ldpaths = pylib + \
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
    p.add_argument('action', nargs='?', default='build', choices='build test linux-package'.split(), help='Action to perform (default is build)')
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


def build(args):
    init_env(args.debug, args.asan)
    compile_c_extension('kitty/fast_data_types', *find_c_files())


def package(args):
    ddir = 'linux-package'
    if os.path.exists(ddir):
        shutil.rmtree(ddir)
    os.makedirs(ddir + '/terminfo/x')
    shutil.copy2('__main__.py', ddir)
    shutil.copy2('terminfo/x/xterm-kitty', ddir + '/terminfo/x')

    def src_ignore(parent, entries):
        return [x for x in entries if '.' in x and x.rpartition('.')[2] not in ('py', 'so', 'conf')]

    shutil.copytree('kitty', ddir + '/kitty', ignore=src_ignore)
    import compileall
    compileall.compile_dir(ddir, quiet=1, workers=4)


def main():
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args()
    if args.action == 'build':
        build(args)
    elif args.action == 'test':
        os.execlp(sys.executable, sys.executable, os.path.join(base, 'test.py'))
    elif args.action == 'linux-package':
        build(args)
        package(args)


if __name__ == '__main__':
    main()
