#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base, 'glfw'))
glfw = importlib.import_module('glfw')
verbose = False
del sys.path[0]
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
is_macos = 'darwin' in _plat
is_travis = os.environ.get('TRAVIS') == 'true'
env = None

PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')


def emphasis(text):
    if sys.stdout.isatty():
        text = '\033[32m' + text + '\033[39m'
    return text


def error(text):
    if sys.stdout.isatty():
        text = '\033[91m' + text + '\033[39m'
    return text


def pkg_config(pkg, *args):
    try:
        return list(
            filter(
                None,
                shlex.split(
                    subprocess.check_output([PKGCONFIG, pkg] + list(args))
                    .decode('utf-8')
                )
            )
        )
    except subprocess.CalledProcessError:
        raise SystemExit('The package {} was not found on your system'.format(error(pkg)))


def at_least_version(package, major, minor=0):
    q = '{}.{}'.format(major, minor)
    if subprocess.run([PKGCONFIG, package, '--atleast-version=' + q]
                      ).returncode != 0:
        try:
            ver = subprocess.check_output([PKGCONFIG, package, '--modversion']
                                          ).decode('utf-8').strip()
            qmajor, qminor = map(int, re.match(r'(\d+).(\d+)', ver).groups())
        except Exception:
            ver = 'not found'
            qmajor = qminor = 0
        if qmajor < major or (qmajor == major and qminor < minor):
            raise SystemExit(
                '{} >= {}.{} is required, found version: {}'.format(
                    error(package), major, minor, ver
                )
            )


def cc_version():
    cc = os.environ.get('CC', 'clang' if is_macos else 'gcc')
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
    sanitize_args = ['-fsanitize=address']
    if ccver >= (5, 0):
        sanitize_args.append('-fsanitize=undefined')
        # if cc == 'gcc' or (cc == 'clang' and ccver >= (4, 2)):
        #     sanitize_args.append('-fno-sanitize-recover=all')
    sanitize_args.append('-fno-omit-frame-pointer')
    return sanitize_args


class Env:

    def __init__(self, cc, cflags, ldflags, ldpaths=[]):
        self.cc, self.cflags, self.ldflags, self.ldpaths = cc, cflags, ldflags, ldpaths

    def copy(self):
        return Env(self.cc, list(self.cflags), list(self.ldflags), list(self.ldflags))


def init_env(
    debug=False, sanitize=False, native_optimizations=True, profile=False
):
    native_optimizations = native_optimizations and not sanitize and not debug
    cc, ccver = cc_version()
    print('CC:', cc, ccver)
    stack_protector = '-fstack-protector'
    if ccver >= (4, 9) and cc == 'gcc':
        stack_protector += '-strong'
    missing_braces = ''
    if ccver < (5, 2) and cc == 'gcc':
        missing_braces = '-Wno-missing-braces'
    df = '-g3'
    if ccver >= (5, 0):
        df += ' -Og'
    optimize = df if debug or sanitize else '-O3'
    sanitize_args = get_sanitize_args(cc, ccver) if sanitize else set()
    cflags = os.environ.get(
        'OVERRIDE_CFLAGS', (
            '-Wextra -Wno-missing-field-initializers -Wall -std=c99 -D_XOPEN_SOURCE=700'
            ' -pedantic-errors {} {} -D{}DEBUG -fwrapv {} {} -pipe {} -fvisibility=hidden'
        ).format(
            optimize,
            ' '.join(sanitize_args),
            ('' if debug else 'N'),
            stack_protector,
            missing_braces,
            '-march=native' if native_optimizations else '',
        )
    )
    cflags = shlex.split(cflags) + shlex.split(
        sysconfig.get_config_var('CCSHARED')
    )
    ldflags = os.environ.get(
        'OVERRIDE_LDFLAGS',
        '-Wall ' + ' '.join(sanitize_args) + ('' if debug else ' -O3')
    )
    ldflags = shlex.split(ldflags)
    ldflags.append('-shared')
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags += shlex.split(os.environ.get('LDFLAGS', ''))
    if not debug and not sanitize:
        # See https://github.com/google/sanitizers/issues/647
        cflags.append('-flto'), ldflags.append('-flto')

    if profile:
        cflags.append('-DWITH_PROFILER')
        cflags.append('-g3')
        ldflags.append('-lprofiler')
    return Env(cc, cflags, ldflags)


def kitty_env():
    ans = env.copy()
    cflags = ans.cflags
    cflags.append('-pthread')
    # We add 4000 to the primary version because vim turns on SGR mouse mode
    # automatically if this version is high enough
    cflags.append('-DPRIMARY_VERSION={}'.format(version[0] + 4000))
    cflags.append('-DSECONDARY_VERSION={}'.format(version[1]))
    at_least_version('harfbuzz', 1, 5)
    cflags.extend(pkg_config('libpng', '--cflags-only-I'))
    if is_macos:
        font_libs = ['-framework', 'CoreText', '-framework', 'CoreGraphics']
    else:
        cflags.extend(pkg_config('fontconfig', '--cflags-only-I'))
        font_libs = pkg_config('fontconfig', '--libs')
    cflags.extend(pkg_config('harfbuzz', '--cflags-only-I'))
    font_libs.extend(pkg_config('harfbuzz', '--libs'))
    pylib = get_python_flags(cflags)
    gl_libs = ['-framework', 'OpenGL'] if is_macos else pkg_config('gl', '--libs')
    libpng = pkg_config('libpng', '--libs')
    ans.ldpaths += pylib + font_libs + gl_libs + libpng + [
        '-lunistring'
    ]
    if is_macos:
        ans.ldpaths.extend('-framework Cocoa'.split())
        if is_travis and 'SW' in os.environ:
            cflags.append('-I{}/include'.format(os.environ['SW']))
            ans.ldpaths.append('-L{}/lib'.format(os.environ['SW']))
    else:
        ans.ldpaths += ['-lrt']
        if '-ldl' not in ans.ldpaths:
            ans.ldpaths.append('-ldl')
    if '-lz' not in ans.ldpaths:
        ans.ldpaths.append('-lz')

    try:
        os.mkdir(build_dir)
    except FileExistsError:
        pass
    return ans


def define(x):
    return '-D' + x


def run_tool(cmd, desc=None):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd[0])
    if verbose:
        desc = None
    print(desc or ' '.join(cmd))
    p = subprocess.Popen(cmd)
    ret = p.wait()
    if ret != 0:
        if desc:
            print(' '.join(cmd))
        raise SystemExit(ret)


SPECIAL_SOURCES = {
    'kitty/parser_dump.c': ('kitty/parser.c', ['DUMP_COMMANDS']),
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
        RE_INC = re.compile(
            r'^(?P<target>.+?):\s+(?P<deps>.+?)$', re.MULTILINE
        )
        SPACE_TOK = '\x1B'

        text = deps.replace('\\\n', ' ').replace('\\ ', SPACE_TOK)
        for match in RE_INC.finditer(text):
            files = (
                f.replace(SPACE_TOK, ' ') for f in match.group('deps').split()
            )
            for path in files:
                path = os.path.abspath(path)
                if path.startswith(base):
                    yield path


def parallel_run(todo, desc='Compiling {} ...'):
    try:
        from multiprocessing import cpu_count
        num_workers = max(1, cpu_count())
    except Exception:
        num_workers = 2
    items = list(reversed(tuple(todo.items())))
    workers = {}
    failed = None

    def wait():
        nonlocal failed
        if not workers:
            return
        pid, s = os.wait()
        name, cmd, w = workers.pop(pid, (None, None, None))
        if name is not None and ((s & 0xff) != 0 or ((s >> 8) & 0xff) != 0) and failed is None:
            failed = name, cmd

    while items and failed is None:
        while len(workers) < num_workers and items:
            name, cmd = items.pop()
            if verbose:
                print(' '.join(cmd))
            else:
                print(desc.format(emphasis(name)))
            w = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            workers[w.pid] = name, cmd, w
        wait()
    while len(workers):
        wait()
    if failed:
        run_tool(failed[1])


def compile_c_extension(kenv, module, incremental, compilation_database, all_keys, sources, headers):
    prefix = os.path.basename(module)
    objects = [
        os.path.join(build_dir, prefix + '-' + os.path.basename(src) + '.o')
        for src in sources
    ]

    todo = {}

    for original_src, dest in zip(sources, objects):
        src = original_src
        cflgs = kenv.cflags[:]
        is_special = src in SPECIAL_SOURCES
        if is_special:
            src, defines = SPECIAL_SOURCES[src]
            cflgs.extend(map(define, defines))

        cmd = [kenv.cc, '-MMD'] + cflgs
        key = original_src, os.path.basename(dest)
        all_keys.add(key)
        cmd_changed = compilation_database.get(key, [])[:-4] != cmd
        must_compile = not incremental or cmd_changed
        src = os.path.join(base, src)
        if must_compile or newer(
            dest, *dependecies_for(src, dest, headers)
        ):
            cmd += ['-c', src] + ['-o', dest]
            compilation_database[key] = cmd
            todo[original_src] = cmd
    if todo:
        parallel_run(todo)
    dest = os.path.join(base, module + '.so')
    if not incremental or newer(dest, *objects):
        run_tool([kenv.cc] + kenv.ldflags + objects + kenv.ldpaths + ['-o', dest] + ['-L', '/opt/local/lib'], desc='Linking {} ...'.format(emphasis(module)))


def find_c_files():
    ans, headers = [], []
    d = os.path.join(base, 'kitty')
    exclude = {'fontconfig.c', 'freetype.c', 'desktop.c'} if is_macos else {'core_text.m', 'cocoa_window.m'}
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
    return tuple(ans), tuple(headers)


def compile_glfw(incremental, compilation_database, all_keys):
    modules = 'cocoa' if is_macos else 'x11 wayland'
    for module in modules.split():
        try:
            genv = glfw.init_env(env, pkg_config, at_least_version, module)
        except SystemExit as err:
            if module != 'wayland':
                raise
            print(err, file=sys.stderr)
            print(error('Disabling building of wayland backend'), file=sys.stderr)
            continue
        sources = [os.path.join('glfw', x) for x in genv.sources]
        all_headers = [os.path.join('glfw', x) for x in genv.all_headers]
        if module == 'wayland':
            try:
                glfw.build_wayland_protocols(genv, run_tool, emphasis, newer, os.path.join(base, 'glfw'))
            except SystemExit as err:
                print(err, file=sys.stderr)
                print(error('Disabling building of wayland backend'), file=sys.stderr)
                continue
        compile_c_extension(genv, 'kitty/glfw-' + module, incremental, compilation_database, all_keys, sources, all_headers)


def build(args, native_optimizations=True):
    global env
    try:
        with open('compile_commands.json') as f:
            compilation_database = json.load(f)
    except FileNotFoundError:
        compilation_database = []
    all_keys = set()
    compilation_database = {
        (k['file'], k.get('output')): k['arguments'] for k in compilation_database
    }
    env = init_env(args.debug, args.sanitize, native_optimizations, args.profile)
    try:
        compile_c_extension(
            kitty_env(), 'kitty/fast_data_types', args.incremental, compilation_database, all_keys, *find_c_files()
        )
        compile_glfw(args.incremental, compilation_database, all_keys)
        for key in set(compilation_database) - all_keys:
            del compilation_database[key]
    finally:
        compilation_database = [
            {'file': k[0], 'arguments': v, 'directory': base, 'output': k[1]} for k, v in compilation_database.items()
        ]
        with open('compile_commands.json', 'w') as f:
            json.dump(compilation_database, f, indent=2, sort_keys=True)


def safe_makedirs(path):
    os.makedirs(path, exist_ok=True)


def build_asan_launcher(args):
    dest = 'asan-launcher'
    src = 'asan-launcher.c'
    if args.incremental and not newer(dest, src):
        return
    cc, ccver = cc_version()
    cflags = '-g3 -Wall -Werror -fpie -std=c99'.split()
    pylib = get_python_flags(cflags)
    sanitize_lib = ['-lasan'] if cc == 'gcc' and not is_macos else []
    cflags.extend(get_sanitize_args(cc, ccver))
    cmd = [cc] + cflags + [src, '-o', dest] + sanitize_lib + pylib + ['-L', '/opt/local/lib']
    run_tool(cmd, desc='Creating {} ...'.format(emphasis('asan-launcher')))


def build_linux_launcher(args, launcher_dir='.', for_bundle=False):
    cflags = '-Wall -fpie'.split()
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
    cmd = [env.cc] + cflags + [
        'linux-launcher.c', '-o',
        os.path.join(launcher_dir, exe)
    ] + libs + pylib + ['-L', '/opt/local/lib']
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
            if '.' in x and x.rpartition('.')[2] not in
            ('py', 'so', 'conf', 'glsl')
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
    if not is_macos:  # {{{ linux desktop gunk
        icdir = os.path.join(ddir, 'share', 'icons', 'hicolor', '256x256', 'apps')
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
    for f in subprocess.check_output(
        'git ls-files --others --ignored --exclude-from=.gitignore'.split()
    ).decode('utf-8').splitlines():
        if f.startswith('logo/kitty.iconset') or f.startswith('dev/'):
            continue
        os.unlink(f)
        if os.sep in f and not os.listdir(os.path.dirname(f)):
            os.rmdir(os.path.dirname(f))


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
        '-v', '--verbose',
        default=0,
        action='count',
        help='Be verbose'
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
        '--full',
        dest='incremental',
        default=True,
        action='store_false',
        help='Do a full build, even for unchanged files'
    )
    p.add_argument(
        '--profile',
        default=False,
        action='store_true',
        help='Use the -pg compile flag to add profiling information'
    )
    return p


def main():
    global verbose
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args()
    verbose = args.verbose > 0
    args.prefix = os.path.abspath(args.prefix)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if args.action == 'build':
        build(args)
        build_asan_launcher(args)
        if args.profile:
            build_linux_launcher(args)
            print('kitty profile executable is', 'kitty-profile')
    elif args.action == 'test':
        os.execlp(
            sys.executable, sys.executable, os.path.join(base, 'test.py')
        )
    elif args.action == 'linux-package':
        build(args)
        package(args)
    elif args.action == 'osx-bundle':
        build(args)
        package(args, for_bundle=True)
    elif args.action == 'clean':
        clean()


if __name__ == '__main__':
    main()
