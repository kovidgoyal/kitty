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
version = tuple(
    map(
        int,
        re.search(
            r"^version = \((\d+), (\d+), (\d+)\)", constants, re.MULTILINE
        ).group(1, 2, 3)
    )
)
_plat = sys.platform.lower()
isosx = 'darwin' in _plat
is_travis = os.environ.get('TRAVIS') == 'true'

cflags = ldflags = cc = ldpaths = None
PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')


def pkg_config(pkg, *args):
    return list(
        filter(
            None,
            shlex.split(
                subprocess.check_output([PKGCONFIG, pkg] + list(args))
                .decode('utf-8')
            )
        )
    )


def cc_version():
    cc = os.environ.get('CC', 'gcc')
    raw = subprocess.check_output([cc, '-dumpversion']).decode('utf-8')
    ver = raw.split('.')[:2]
    try:
        ver = tuple(map(int, ver))
    except Exception:
        ver = (0, 0)
    return cc, ver


def get_python_flags(cflags):
    cflags.extend(
        '-I' + sysconfig.get_path(x) for x in 'include platinclude'.split()
    )
    libs = []
    libs += sysconfig.get_config_var('LIBS').split()
    libs += sysconfig.get_config_var('SYSLIBS').split()
    fw = sysconfig.get_config_var('PYTHONFRAMEWORK')
    if fw:
        for var in 'data include stdlib'.split():
            val = sysconfig.get_path(var)
            if val and '/{}.framework'.format(fw) in val:
                fdir = val[:val.index('/{}.framework'.format(fw))]
                if os.path.isdir(
                    os.path.join(fdir, '{}.framework'.format(fw))
                ):
                    framework_dir = fdir
                    break
        else:
            raise SystemExit('Failed to find Python framework')
        libs.append(
            os.path.join(framework_dir, sysconfig.get_config_var('LDLIBRARY'))
        )
    else:
        libs += ['-L' + sysconfig.get_config_var('LIBDIR')]
        libs += [
            '-lpython' + sysconfig.get_config_var('VERSION') + sys.abiflags
        ]
        libs += sysconfig.get_config_var('LINKFORSHARED').split()
    return libs


def get_sanitize_args(cc, ccver):
    sanitize_args = set()
    sanitize_args.add('-fno-omit-frame-pointer')
    sanitize_args.add('-fsanitize=address')
    if (cc == 'gcc' and ccver >= (5, 0)) or cc == 'clang':
        sanitize_args.add('-fsanitize=undefined')
        # if cc == 'gcc' or (cc == 'clang' and ccver >= (4, 2)):
        #     sanitize_args.add('-fno-sanitize-recover=all')
    return sanitize_args


def init_env(debug=False, sanitize=False, native_optimizations=True, profile=False):
    global cflags, ldflags, cc, ldpaths
    native_optimizations = native_optimizations and not sanitize and not debug
    cc, ccver = cc_version()
    print('CC:', cc, ccver)
    stack_protector = '-fstack-protector'
    if ccver >= (4, 9) and cc == 'gcc':
        stack_protector += '-strong'
    missing_braces = ''
    if ccver < (5, 2) and cc == 'gcc':
        missing_braces = '-Wno-missing-braces'
    optimize = '-ggdb' if debug or sanitize else '-O3'
    sanitize_args = get_sanitize_args(cc, ccver) if sanitize else set()
    cflags = os.environ.get(
        'OVERRIDE_CFLAGS', (
            '-Wextra -Wno-missing-field-initializers -Wall -std=c99 -D_XOPEN_SOURCE=700'
            ' -pedantic-errors -Werror {} {} -D{}DEBUG -fwrapv {} {} -pipe {} -fvisibility=hidden'
        ).format(
            optimize, ' '.join(sanitize_args), ('' if debug else 'N'), stack_protector, missing_braces,
            '-march=native' if native_optimizations else '',
        )
    )
    cflags = shlex.split(cflags
                         ) + shlex.split(sysconfig.get_config_var('CCSHARED'))
    ldflags = os.environ.get(
        'OVERRIDE_LDFLAGS', '-Wall ' + ' '.join(sanitize_args) + ('' if debug else ' -O3')
    )
    ldflags = shlex.split(ldflags)
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags += shlex.split(os.environ.get('LDFLAGS', ''))
    if not debug:
        cflags.append('-flto'), ldflags.append('-flto')

    if profile:
        cflags.append('-DWITH_PROFILER')
        cflags.append('-g')
        ldflags.append('-lprofiler')
    cflags.append('-pthread')
    # We add 4000 to the primary version because vim turns on SGR mouse mode
    # automatically if this version is high enough
    cflags.append('-DPRIMARY_VERSION={}'.format(version[0] + 4000))
    cflags.append('-DSECONDARY_VERSION={}'.format(version[1]))
    if not is_travis and not isosx and subprocess.Popen(
        [PKGCONFIG, 'glew', '--atleast-version=2']
    ).wait() != 0:
        try:
            ver = subprocess.check_output([PKGCONFIG, 'glew', '--modversion']
                                          ).decode('utf-8').strip()
            major = int(re.match(r'\d+', ver).group())
        except Exception:
            ver = 'not found'
            major = 0
        if major < 2:
            raise SystemExit(
                'glew >= 2.0.0 is required, found version: ' + ver
            )
    cflags.extend(pkg_config('libpng', '--cflags-only-I'))
    if not isosx:
        cflags.extend(pkg_config('glew', '--cflags-only-I'))
    if isosx:
        font_libs = ['-framework', 'CoreText', '-framework', 'CoreGraphics']
    else:
        cflags.extend(pkg_config('fontconfig', '--cflags-only-I'))
        font_libs = pkg_config('fontconfig', '--libs')
        cflags.extend(pkg_config('harfbuzz', '--cflags-only-I'))
        font_libs.extend(pkg_config('harfbuzz', '--libs'))
    cflags.extend(pkg_config('glfw3', '--cflags-only-I'))
    ldflags.append('-shared')
    pylib = get_python_flags(cflags)
    if isosx:
        glfw_ldflags = pkg_config('--libs', '--static', 'glfw3'
                                  ) + ['-framework', 'OpenGL']
        glew_libs = []
    else:
        glfw_ldflags = pkg_config('glfw3', '--libs')
        glew_libs = pkg_config('glew', '--libs')
    libpng = pkg_config('libpng', '--libs')
    ldpaths = pylib + glew_libs + font_libs + glfw_ldflags + libpng + ['-lunistring']
    if not isosx:
        ldpaths += ['-lrt']
    if '-lz' not in ldpaths:
        ldpaths.append('-lz')

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
    'kitty/shaders_debug.c': ('kitty/shaders.c', ['ENABLE_DEBUG_GL']),
}


def newer(dest, *sources):
    try:
        dtime = os.path.getmtime(dest)
    except EnvironmentError:
        return True
    for s in sources:
        if os.path.getmtime(s) >= dtime:
            return True
    return False


def dependecies_for(src, obj, all_headers):
    dep_file = obj.rpartition('.')[0] + '.d'
    try:
        deps = open(dep_file).read()
    except FileNotFoundError:
        yield src
        yield from iter(all_headers)
    else:
        RE_INC = re.compile(r'^(?P<target>.+?):\s+(?P<deps>.+?)$', re.MULTILINE)
        SPACE_TOK = '\x1B'

        text = deps.replace('\\\n', ' ').replace('\\ ', SPACE_TOK)
        for match in RE_INC.finditer(text):
            files = (f.replace(SPACE_TOK, ' ') for f in match.group('deps').split())
            for path in files:
                path = os.path.abspath(path)
                if path.startswith(base):
                    yield path


def compile_c_extension(module, incremental, sources, headers):
    prefix = os.path.basename(module)
    objects = [
        os.path.join(build_dir, prefix + '-' + os.path.basename(src) + '.o')
        for src in sources
    ]

    for src, dest in zip(sources, objects):
        cflgs = cflags[:]
        if src in SPECIAL_SOURCES:
            src, defines = SPECIAL_SOURCES[src]
            cflgs.extend(map(define, defines))

        src = os.path.join(base, src)
        if not incremental or newer(dest, *dependecies_for(src, dest, headers)):
            run_tool([cc, '-MMD'] + cflgs + ['-c', src] + ['-o', dest])
    dest = os.path.join(base, module + '.so')
    if not incremental or newer(dest, *objects):
        run_tool([cc] + ldflags + objects + ldpaths + ['-o', dest])


def option_parser():
    p = argparse.ArgumentParser()
    p.add_argument(
        'action',
        nargs='?',
        default='build',
        choices='build test linux-package osx-bundle clean'.split(),
        help='Action to perform (default is build)'
    )
    p.add_argument(
        '--debug',
        default=False,
        action='store_true',
        help='Build extension modules with debugging symbols'
    )
    p.add_argument(
        '--sanitize',
        default=False,
        action='store_true',
        help='Turn on sanitization to detect memory access errors and undefined behavior. Note that if you do turn it on,'
        ' a special executable will be built for running the test suite. If you want to run normal kitty'
        ' with sanitization, use LD_PRELOAD=libasan.so (for gcc) and'
        ' LD_PRELOAD=/usr/lib/clang/4.0.0/lib/linux/libclang_rt.asan-x86_64.so (for clang, changing path as appropriate).'
    )
    p.add_argument(
        '--prefix',
        default='./linux-package',
        help='Where to create the linux package'
    )
    p.add_argument(
        '--incremental',
        default=False,
        action='store_true',
        help='Only build changed files'
    )
    p.add_argument(
        '--profile',
        default=False,
        action='store_true',
        help='Use the -pg compile flag to add profiling information'
    )
    return p


def find_c_files():
    ans, headers = [], []
    d = os.path.join(base, 'kitty')
    exclude = {'freetype.c', 'fontconfig.c'} if isosx else {'core_text.m', 'cocoa_window.m'}
    for x in os.listdir(d):
        ext = os.path.splitext(x)[1]
        if ext in ('.c', '.m') and os.path.basename(x) not in exclude:
            ans.append(os.path.join('kitty', x))
        elif ext == '.h':
            headers.append(os.path.join('kitty', x))
    ans.sort(
        key=lambda x: os.path.getmtime(os.path.join(base, x)), reverse=True
    )
    ans.append('kitty/parser_dump.c')
    ans.append('kitty/shaders_debug.c')
    return tuple(ans), tuple(headers)


def build(args, native_optimizations=True):
    init_env(args.debug, args.sanitize, native_optimizations, args.profile)
    compile_c_extension(
        'kitty/fast_data_types', args.incremental, *find_c_files()
    )


def safe_makedirs(path):
    os.makedirs(path, exist_ok=True)


def build_test_launcher(args):
    cc, ccver = cc_version()
    cflags = '-g -Wall -Werror -fpie'.split()
    pylib = get_python_flags(cflags)
    sanitize_lib = (['-lasan'] if cc == 'gcc' else []) if args.sanitize else []
    cflags.extend(get_sanitize_args(cc, ccver) if args.sanitize else [])
    cmd = [cc] + cflags + [
        'test-launcher.c', '-o', 'test-launcher',
    ] + sanitize_lib + pylib
    run_tool(cmd)


def build_linux_launcher(args, launcher_dir='.', for_bundle=False):
    cflags = '-Wall -Werror -fpie'.split()
    libs = []
    if args.profile:
        cflags.append('-DWITH_PROFILER'), cflags.append('-g')
        libs.append('-lprofiler')
    else:
        cflags.append('-O3')
    if for_bundle:
        cflags.append('-DFOR_BUNDLE')
        cflags.append('-DPYVER="{}"'.format(sysconfig.get_python_version()))
    pylib = get_python_flags(cflags)
    exe = 'kitty-profile' if args.profile else 'kitty'
    cmd = [cc] + cflags + [
        'linux-launcher.c', '-o', os.path.join(launcher_dir, exe)
    ] + libs + pylib
    run_tool(cmd)


def package(args, for_bundle=False):  # {{{
    ddir = args.prefix
    libdir = os.path.join(ddir, 'lib', 'kitty')
    if os.path.exists(libdir):
        shutil.rmtree(libdir)
    os.makedirs(os.path.join(libdir, 'logo'))
    for x in (libdir, os.path.join(ddir, 'share')):
        odir = os.path.join(x, 'terminfo')
        safe_makedirs(odir)
        subprocess.check_call(['tic', '-o' + odir, 'terminfo/kitty.terminfo'])
    shutil.copy2('__main__.py', libdir)
    shutil.copy2('logo/kitty.rgba', os.path.join(libdir, 'logo'))

    def src_ignore(parent, entries):
        return [
            x for x in entries
            if '.' in x and x.rpartition('.')[2] not in ('py', 'so', 'conf', 'glsl')
        ]

    shutil.copytree('kitty', os.path.join(libdir, 'kitty'), ignore=src_ignore)
    import compileall
    compileall.compile_dir(ddir, quiet=1, workers=4)
    for root, dirs, files in os.walk(ddir):
        for f in files:
            path = os.path.join(root, f)
            os.chmod(path, 0o755 if f.endswith('.so') else 0o644)
    launcher_dir = os.path.join(ddir, 'bin')
    safe_makedirs(launcher_dir)
    build_linux_launcher(args, launcher_dir, for_bundle)
    if not isosx:  # {{{ linux desktop gunk
        icdir = os.path.join(ddir, 'share', 'icons', 'hicolor', '256x256')
        safe_makedirs(icdir)
        shutil.copy2('logo/kitty.png', icdir)
        deskdir = os.path.join(ddir, 'share', 'applications')
        safe_makedirs(deskdir)
        with open(os.path.join(deskdir, 'kitty.desktop'), 'w') as f:
            f.write(
                '''\
[Desktop Entry]
Version=1.0
Type=Application
Name=kitty
GenericName=Terminal emulator
Comment=A modern, hackable, featureful, OpenGL based terminal emulator
TryExec=kitty
Exec=kitty
Icon=kitty
Categories=System;
'''
            )
    # }}}

    if for_bundle:  # OS X bundle gunk {{{
        os.chdir(ddir)
        os.mkdir('Contents')
        os.chdir('Contents')
        os.rename('../share', 'Resources')
        os.rename('../bin', 'MacOS')
        os.rename('../lib', 'Frameworks')
    # }}}
    # }}}


def clean():
    for f in subprocess.check_output('git ls-files --others --ignored --exclude-from=.gitignore'.split()).decode('utf-8').splitlines():
        if f.startswith('logo/kitty.iconset') or f.startswith('dev/'):
            continue
        os.unlink(f)
        if os.sep in f and not os.listdir(os.path.dirname(f)):
            os.rmdir(os.path.dirname(f))


def main():
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args()
    args.prefix = os.path.abspath(args.prefix)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if args.action == 'build':
        build(args)
        build_test_launcher(args)
        if args.profile:
            build_linux_launcher(args)
            print('kitty profile executable is', 'kitty-profile')
    elif args.action == 'test':
        os.execlp(
            sys.executable, sys.executable, os.path.join(base, 'test.py')
        )
    elif args.action == 'linux-package':
        build(args, native_optimizations=False)
        package(args)
    elif args.action == 'osx-bundle':
        build(args, native_optimizations=False)
        package(args, for_bundle=True)
    elif args.action == 'clean':
        clean()


if __name__ == '__main__':
    main()
