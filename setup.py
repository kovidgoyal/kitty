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
PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')


def pkg_config(pkg, *args):
    return list(filter(None, shlex.split(subprocess.check_output([PKGCONFIG, pkg] + list(args)).decode('utf-8'))))


def cc_version():
    cc = os.environ.get('CC', 'gcc')
    raw = subprocess.check_output([cc, '-dumpversion']).decode('utf-8')
    ver = raw.split('.')[:2]
    try:
        ver = tuple(map(int, ver))
    except Exception:
        ver = (0, 0)
    return ver


def get_python_flags(cflags):
    cflags.extend('-I' + sysconfig.get_path(x) for x in 'include platinclude'.split())
    libs = []
    libs += sysconfig.get_config_var('LIBS').split()
    libs += sysconfig.get_config_var('SYSLIBS').split()
    fw = sysconfig.get_config_var('PYTHONFRAMEWORK')
    if fw:
        for var in 'data include stdlib'.split():
            val = sysconfig.get_path(var)
            if val and '/{}.framework'.format(fw) in val:
                fdir = val[:val.index('/{}.framework'.format(fw))]
                if os.path.isdir(os.path.join(fdir, '{}.framework'.format(fw))):
                    libs.append('-F' + fdir)
                    break
        libs.extend(['-framework', fw])
    else:
        libs += ['-L' + sysconfig.get_config_var('LIBDIR')]
        libs += ['-lpython' + sysconfig.get_config_var('VERSION') + sys.abiflags]
        libs += sysconfig.get_config_var('LINKFORSHARED').split()
    return libs


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
    if not is_travis and subprocess.Popen([PKGCONFIG, 'glew', '--atleast-version=2']).wait() != 0:
        try:
            ver = subprocess.check_output([PKGCONFIG, 'glew', '--modversion']).decode('utf-8').strip()
            major = int(re.match(r'\d+', ver).group())
        except Exception:
            ver = 'not found'
            major = 0
        if major < 2:
            raise SystemExit('glew >= 2.0.0 is required, found version: ' + ver)
    cflags.extend(pkg_config('glew', '--cflags-only-I'))
    if isosx:
        font_libs = ['-framework', 'CoreText', '-framework', 'CoreGraphics']
    else:
        cflags.extend(pkg_config('freetype2', '--cflags-only-I'))
        font_libs = pkg_config('freetype2', '--libs')
    cflags.extend(pkg_config('glfw3', '--cflags-only-I'))
    ldflags.append('-shared')
    pylib = get_python_flags(cflags)
    if isosx:
        glfw_ldflags = pkg_config('--libs', '--static', 'glfw3') + ['-framework', 'OpenGL']
    else:
        glfw_ldflags = pkg_config('glfw3', '--libs')
    ldpaths = pylib + \
        pkg_config('glew', '--libs') + font_libs + glfw_ldflags

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
    p.add_argument('--prefix', default='./linux-package', help='Where to create the linux package')
    return p


def find_c_files():
    ans = []
    d = os.path.join(base, 'kitty')
    exclude = {'freetype.c'} if isosx else {'core_text.m'}
    for x in os.listdir(d):
        if (x.endswith('.c') or x.endswith('.m')) and os.path.basename(x) not in exclude:
            ans.append(os.path.join('kitty', x))
    ans.sort(key=lambda x: os.path.getmtime(os.path.join(base, x)), reverse=True)
    ans.append('kitty/parser_dump.c')
    return tuple(ans)


def build(args):
    init_env(args.debug, args.asan)
    compile_c_extension('kitty/fast_data_types', *find_c_files())


def safe_makedirs(path):
    try:
        os.makedirs(path)
    except FileExistsError:
        pass


def package(args):
    ddir = args.prefix
    libdir = os.path.join(ddir, 'lib', 'kitty')
    terminfo_dir = os.path.join(ddir, 'share/terminfo/x')
    if os.path.exists(libdir):
        shutil.rmtree(libdir)
    os.makedirs(os.path.join(libdir, 'terminfo/x'))
    safe_makedirs(terminfo_dir)
    shutil.copy2('__main__.py', libdir)
    shutil.copy2('terminfo/x/xterm-kitty', terminfo_dir)
    shutil.copy2('terminfo/x/xterm-kitty', os.path.join(libdir, 'terminfo/x'))

    def src_ignore(parent, entries):
        return [x for x in entries if '.' in x and x.rpartition('.')[2] not in ('py', 'so', 'conf')]

    shutil.copytree('kitty', os.path.join(libdir, 'kitty'), ignore=src_ignore)
    import compileall
    compileall.compile_dir(ddir, quiet=1, workers=4)
    for root, dirs, files in os.walk(ddir):
        for f in files:
            path = os.path.join(root, f)
            os.chmod(path, 0o755 if f.endswith('.so') else 0o644)
    launcher_dir = os.path.join(ddir, 'bin')
    safe_makedirs(launcher_dir)
    run_tool([cc, '-O3', 'linux-launcher.c', '-o', os.path.join(launcher_dir, 'kitty')])


def main():
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args()
    args.prefix = os.path.abspath(args.prefix)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if args.action == 'build':
        build(args)
    elif args.action == 'test':
        os.execlp(sys.executable, sys.executable, os.path.join(base, 'test.py'))
    elif args.action == 'linux-package':
        build(args)
        package(args)


if __name__ == '__main__':
    main()
