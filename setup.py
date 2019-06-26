#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import glob
import importlib
import json
import os
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import sysconfig
import time
from collections import namedtuple
from contextlib import suppress, contextmanager

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
env = None

PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')


@contextmanager
def current_dir(path):
    cwd = os.getcwd()
    try:
        os.chdir(path)
        yield path
    finally:
        os.chdir(cwd)


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
    if 'CC' in os.environ:
        cc = os.environ['CC']
    else:
        if is_macos:
            cc = 'clang'
        else:
            if shutil.which('gcc'):
                cc = 'gcc'
            elif shutil.which('clang'):
                cc = 'clang'
            else:
                cc = 'cc'
    raw = subprocess.check_output([cc, '-dumpversion']).decode('utf-8')
    ver = raw.split('.')[:2]
    try:
        ver = tuple(map(int, ver))
    except Exception:
        ver = (0, 0)
    return cc, ver


def get_python_include_paths():
    ans = []
    for name in sysconfig.get_path_names():
        if 'include' in name:
            ans.append(name)
    return sorted(frozenset(map(sysconfig.get_path, sorted(ans))))


def get_python_flags(cflags):
    cflags.extend('-I' + x for x in get_python_include_paths())
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


def test_compile(cc, *cflags, src=None):
    src = src or 'int main(void) { return 0; }'
    p = subprocess.Popen([cc] + list(cflags) + ['-x', 'c', '-o', os.devnull, '-'], stdin=subprocess.PIPE)
    try:
        p.stdin.write(src.encode('utf-8')), p.stdin.close()
    except BrokenPipeError:
        return False
    return p.wait() == 0


def first_successful_compile(cc, *cflags, src=None):
    for x in cflags:
        if test_compile(cc, *shlex.split(x), src=src):
            return x
    return ''


class Env:

    def __init__(self, cc, cppflags, cflags, ldflags, ldpaths=None, ccver=None):
        self.cc, self.cppflags, self.cflags, self.ldflags, self.ldpaths = cc, cppflags, cflags, ldflags, [] if ldpaths is None else ldpaths
        self.ccver = ccver

    def copy(self):
        return Env(self.cc, list(self.cppflags), list(self.cflags), list(self.ldflags), list(self.ldpaths), self.ccver)


def init_env(
    debug=False, sanitize=False, native_optimizations=True, profile=False,
    extra_logging=()
):
    native_optimizations = native_optimizations and not sanitize and not debug
    cc, ccver = cc_version()
    print('CC:', cc, ccver)
    stack_protector = first_successful_compile(cc, '-fstack-protector-strong', '-fstack-protector')
    missing_braces = ''
    if ccver < (5, 2) and cc == 'gcc':
        missing_braces = '-Wno-missing-braces'
    df = '-g3'
    if ccver >= (5, 0):
        df += ' -Og'
    optimize = df if debug or sanitize else '-O3'
    sanitize_args = get_sanitize_args(cc, ccver) if sanitize else set()
    cppflags = os.environ.get(
        'OVERRIDE_CPPFLAGS', (
            '-D{}DEBUG'
        ).format(
            ('' if debug else 'N'),
        )
    )
    cppflags = shlex.split(cppflags)
    for el in extra_logging:
        cppflags.append('-DDEBUG_{}'.format(el.upper().replace('-', '_')))
    cflags = os.environ.get(
        'OVERRIDE_CFLAGS', (
            '-Wextra -Wno-missing-field-initializers -Wall -Wstrict-prototypes -std=c11'
            ' -pedantic-errors -Werror {} {} -fwrapv {} {} -pipe {} -fvisibility=hidden'
        ).format(
            optimize,
            ' '.join(sanitize_args),
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
    cppflags += shlex.split(os.environ.get('CPPFLAGS', ''))
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags += shlex.split(os.environ.get('LDFLAGS', ''))
    if not debug and not sanitize:
        # See https://github.com/google/sanitizers/issues/647
        cflags.append('-flto'), ldflags.append('-flto')

    if profile:
        cppflags.append('-DWITH_PROFILER')
        cflags.append('-g3')
        ldflags.append('-lprofiler')
    return Env(cc, cppflags, cflags, ldflags, ccver=ccver)


def kitty_env():
    ans = env.copy()
    cflags = ans.cflags
    cflags.append('-pthread')
    # We add 4000 to the primary version because vim turns on SGR mouse mode
    # automatically if this version is high enough
    cppflags = ans.cppflags
    cppflags.append('-DPRIMARY_VERSION={}'.format(version[0] + 4000))
    cppflags.append('-DSECONDARY_VERSION={}'.format(version[1]))
    at_least_version('harfbuzz', 1, 5)
    cflags.extend(pkg_config('libpng', '--cflags-only-I'))
    if is_macos:
        font_libs = ['-framework', 'CoreText', '-framework', 'CoreGraphics']
        # Apple deprecated OpenGL in Mojave (10.14) silence the endless
        # warnings about it
        cppflags.append('-DGL_SILENCE_DEPRECATION')
    else:
        cflags.extend(pkg_config('fontconfig', '--cflags-only-I'))
        font_libs = pkg_config('fontconfig', '--libs')
    cflags.extend(pkg_config('harfbuzz', '--cflags-only-I'))
    font_libs.extend(pkg_config('harfbuzz', '--libs'))
    pylib = get_python_flags(cflags)
    gl_libs = ['-framework', 'OpenGL'] if is_macos else pkg_config('gl', '--libs')
    libpng = pkg_config('libpng', '--libs')
    ans.ldpaths += pylib + font_libs + gl_libs + libpng
    if is_macos:
        ans.ldpaths.extend('-framework Cocoa'.split())
    else:
        ans.ldpaths += ['-lrt']
        if '-ldl' not in ans.ldpaths:
            ans.ldpaths.append('-ldl')
    if '-lz' not in ans.ldpaths:
        ans.ldpaths.append('-lz')

    with suppress(FileExistsError):
        os.mkdir(build_dir)
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


def get_vcs_rev_defines():
    ans = []
    if os.path.exists('.git'):
        try:
            rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8').strip()
        except FileNotFoundError:
            try:
                with open('.git/refs/heads/master') as f:
                    rev = f.read()
            except NotADirectoryError:
                gitloc = open('.git').read()
                with open(os.path.join(gitloc, 'refs/heads/master')) as f:
                    rev = f.read()

        ans.append('KITTY_VCS_REV="{}"'.format(rev.strip()))
    return ans


SPECIAL_SOURCES = {
    'kitty/parser_dump.c': ('kitty/parser.c', ['DUMP_COMMANDS']),
    'kitty/data-types.c': ('kitty/data-types.c', get_vcs_rev_defines),
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
        num_workers = max(2, os.cpu_count())
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


CompileKey = namedtuple('CompileKey', 'src dest')


class CompilationDatabase:

    def cmd_changed(self, key, cmd):
        self.all_keys.add(key)
        return self.db.get(key) != cmd

    def update_cmd(self, key, cmd):
        self.db[key] = cmd

    def __enter__(self):
        self.all_keys = set()
        self.dbpath = os.path.abspath('compile_commands.json')
        try:
            with open(self.dbpath) as f:
                compilation_database = json.load(f)
        except FileNotFoundError:
            compilation_database = []
        compilation_database = {
            CompileKey(k['file'], k['output']): k['arguments'] for k in compilation_database
        }
        self.db = compilation_database
        return self

    def __exit__(self, *a):
        cdb = self.db
        for key in set(cdb) - self.all_keys:
            del cdb[key]
        compilation_database = [
            {'file': k.src, 'arguments': v, 'directory': base, 'output': k.dest} for k, v in cdb.items()
        ]
        with open(self.dbpath, 'w') as f:
            json.dump(compilation_database, f, indent=2, sort_keys=True)


def compile_c_extension(kenv, module, incremental, compilation_database, sources, headers):
    prefix = os.path.basename(module)
    objects = [
        os.path.join(build_dir, prefix + '-' + os.path.basename(src) + '.o')
        for src in sources
    ]

    todo = {}

    for original_src, dest in zip(sources, objects):
        src = original_src
        cppflags = kenv.cppflags[:]
        is_special = src in SPECIAL_SOURCES
        if is_special:
            src, defines = SPECIAL_SOURCES[src]
            if callable(defines):
                defines = defines()
            cppflags.extend(map(define, defines))

        cmd = [kenv.cc, '-MMD'] + cppflags + kenv.cflags
        cmd += ['-c', src] + ['-o', dest]
        key = CompileKey(original_src, os.path.basename(dest))
        cmd_changed = compilation_database.cmd_changed(key, cmd)
        must_compile = not incremental or cmd_changed
        src = os.path.join(base, src)
        if must_compile or newer(
            dest, *dependecies_for(src, dest, headers)
        ):
            compilation_database.update_cmd(key, cmd)
            todo[original_src] = cmd
    if todo:
        parallel_run(todo)
    dest = os.path.join(base, module + '.temp.so')
    real_dest = dest[:-len('.temp.so')] + '.so'
    if not incremental or newer(real_dest, *objects):
        # Old versions of clang don't like -pthread being passed to the linker
        # Don't treat linker warnings as errors (linker generates spurious
        # warnings on some old systems)
        unsafe = {'-pthread', '-Werror', '-pedantic-errors'}
        linker_cflags = list(filter(lambda x: x not in unsafe, kenv.cflags))
        try:
            run_tool([kenv.cc] + linker_cflags + kenv.ldflags + objects + kenv.ldpaths + ['-o', dest], desc='Linking {} ...'.format(emphasis(module)))
        except Exception:
            with suppress(EnvironmentError):
                os.remove(dest)
        else:
            os.rename(dest, real_dest)


def find_c_files():
    ans, headers = [], []
    d = os.path.join(base, 'kitty')
    exclude = {'fontconfig.c', 'freetype.c', 'desktop.c'} if is_macos else {'core_text.m', 'cocoa_window.m', 'macos_process_info.c'}
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


def compile_glfw(incremental, compilation_database):
    modules = 'cocoa' if is_macos else 'x11 wayland'
    for module in modules.split():
        try:
            genv = glfw.init_env(env, pkg_config, at_least_version, test_compile, module)
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
        compile_c_extension(genv, 'kitty/glfw-' + module, incremental, compilation_database, sources, all_headers)


def kittens_env():
    kenv = env.copy()
    cflags = kenv.cflags
    cflags.append('-pthread')
    cflags.append('-Ikitty')
    pylib = get_python_flags(cflags)
    kenv.ldpaths += pylib
    return kenv


def compile_kittens(incremental, compilation_database):
    kenv = kittens_env()

    def list_files(q):
        return [os.path.relpath(x, base) for x in glob.glob(q)]

    def files(kitten, output, extra_headers=(), extra_sources=(), filter_sources=None):
        sources = list(filter(filter_sources, list(extra_sources) + list_files(os.path.join('kittens', kitten, '*.c'))))
        headers = list_files(os.path.join('kittens', kitten, '*.h')) + list(extra_headers)
        return (sources, headers, 'kittens/{}/{}'.format(kitten, output))

    for sources, all_headers, dest in (
        files('unicode_input', 'unicode_names'),
        files('diff', 'diff_speedup'),
        files(
            'choose', 'subseq_matcher',
            extra_headers=('kitty/charsets.h',),
            extra_sources=('kitty/charsets.c',),
            filter_sources=lambda x: 'windows_compat.c' not in x),
    ):
        compile_c_extension(
            kenv, dest, incremental, compilation_database, sources, all_headers + ['kitty/data-types.h'])


def build(args, native_optimizations=True):
    global env
    env = init_env(args.debug, args.sanitize, native_optimizations, args.profile, args.extra_logging)
    compile_c_extension(
        kitty_env(), 'kitty/fast_data_types', args.incremental, args.compilation_database, *find_c_files()
    )
    compile_glfw(args.incremental, args.compilation_database)
    compile_kittens(args.incremental, args.compilation_database)


def safe_makedirs(path):
    os.makedirs(path, exist_ok=True)


def build_launcher(args, launcher_dir='.', bundle_type='source'):
    cflags = '-Wall -Werror -fpie'.split()
    cppflags = []
    libs = []
    if args.profile or args.sanitize:
        if args.sanitize:
            cflags.append('-g3')
            cflags.extend(get_sanitize_args(env.cc, env.ccver))
            libs += ['-lasan'] if env.cc == 'gcc' and not is_macos else []
        else:
            cflags.append('-g')
        if args.profile:
            libs.append('-lprofiler')
    else:
        cflags.append('-O3')
    if bundle_type.endswith('-freeze'):
        cppflags.append('-DFOR_BUNDLE')
        cppflags.append('-DPYVER="{}"'.format(sysconfig.get_python_version()))
        cppflags.append('-DKITTY_LIB_DIR_NAME="{}"'.format(args.libdir_name))
    elif bundle_type == 'source':
        cppflags.append('-DFROM_SOURCE')
    if bundle_type.startswith('macos-'):
        klp = '../Frameworks/kitty'
    elif bundle_type.startswith('linux-'):
        klp = '../{}/kitty'.format(args.libdir_name.strip('/'))
    elif bundle_type == 'source':
        klp = '../..'
    else:
        raise SystemExit('Unknown bundle type: {}'.format(bundle_type))
    cppflags.append('-DKITTY_LIB_PATH="{}"'.format(klp))
    pylib = get_python_flags(cflags)
    cppflags += shlex.split(os.environ.get('CPPFLAGS', ''))
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    if bundle_type == 'linux-freeze':
        ldflags += ['-Wl,-rpath,$ORIGIN/../lib']
    os.makedirs(launcher_dir, exist_ok=True)
    dest = os.path.join(launcher_dir, 'kitty')
    src = 'launcher.c'
    cmd = [env.cc] + cppflags + cflags + [
           src, '-o', dest] + ldflags + libs + pylib
    key = CompileKey('launcher.c', 'kitty')
    must_compile = not args.incremental or args.compilation_database.cmd_changed(key, cmd)
    if must_compile or newer(dest, src):
        run_tool(cmd, 'Building {}...'.format(emphasis('launcher')))
        args.compilation_database.update_cmd(key, cmd)


# Packaging {{{


def copy_man_pages(ddir):
    mandir = os.path.join(ddir, 'share', 'man')
    safe_makedirs(mandir)
    with suppress(FileNotFoundError):
        shutil.rmtree(os.path.join(mandir, 'man1'))
    src = os.path.join(base, 'docs/_build/man')
    if not os.path.exists(src):
        raise SystemExit('''\
The kitty man page is missing. If you are building from git then run:
make && make docs
(needs the sphinx documentation system to be installed)
''')
    shutil.copytree(src, os.path.join(mandir, 'man1'))


def copy_html_docs(ddir):
    htmldir = os.path.join(ddir, 'share', 'doc', appname, 'html')
    safe_makedirs(os.path.dirname(htmldir))
    with suppress(FileNotFoundError):
        shutil.rmtree(htmldir)
    src = os.path.join(base, 'docs/_build/html')
    if not os.path.exists(src):
        raise SystemExit('''\
The kitty html docs are missing. If you are building from git then run:
make && make docs
(needs the sphinx documentation system to be installed)
''')
    shutil.copytree(src, htmldir)


def compile_python(base_path):
    import compileall
    import py_compile
    try:
        num_workers = max(1, os.cpu_count())
    except Exception:
        num_workers = 1
    for root, dirs, files in os.walk(base_path):
        for f in files:
            if f.rpartition('.')[-1] in ('pyc', 'pyo'):
                os.remove(os.path.join(root, f))
    for optimize in (0, 1, 2):
        kwargs = dict(ddir='', force=True, optimize=optimize, quiet=1, workers=num_workers)
        if hasattr(py_compile, 'PycInvalidationMode'):
            kwargs['invalidation_mode'] = py_compile.PycInvalidationMode.UNCHECKED_HASH
        compileall.compile_dir(base_path, **kwargs)


def create_linux_bundle_gunk(ddir, libdir_name):
    copy_man_pages(ddir)
    copy_html_docs(ddir)
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
Comment=A fast, feature full, GPU based terminal emulator
TryExec=kitty
Exec=kitty
Icon=kitty
Categories=System;TerminalEmulator;
'''
            )
    with current_dir(ddir):
        in_src_launcher = libdir_name + '/kitty/kitty/launcher/kitty'
        launcher = 'bin/kitty'
        if os.path.exists(in_src_launcher):
            os.remove(in_src_launcher)
        os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
        os.symlink(os.path.relpath(launcher, os.path.dirname(in_src_launcher)), in_src_launcher)


def create_macos_bundle_gunk(ddir):
    import plistlib
    logo_dir = os.path.abspath(os.path.join('logo', appname + '.iconset'))
    with current_dir(ddir):
        os.mkdir('Contents')
        os.chdir('Contents')
        VERSION = '.'.join(map(str, version))
        pl = dict(
            CFBundleDevelopmentRegion='English',
            CFBundleDisplayName=appname,
            CFBundleName=appname,
            CFBundleIdentifier='net.kovidgoyal.' + appname,
            CFBundleVersion=VERSION,
            CFBundleShortVersionString=VERSION,
            CFBundlePackageType='APPL',
            CFBundleSignature='????',
            CFBundleExecutable=appname,
            LSMinimumSystemVersion='10.12.0',
            LSRequiresNativeExecution=True,
            NSAppleScriptEnabled=False,
            # Needed for dark mode in Mojave when linking against older SDKs
            NSRequiresAquaSystemAppearance='NO',
            NSHumanReadableCopyright=time.strftime(
                'Copyright %Y, Kovid Goyal'),
            CFBundleGetInfoString='kitty, an OpenGL based terminal emulator https://sw.kovidgoyal.net/kitty',
            CFBundleIconFile=appname + '.icns',
            NSHighResolutionCapable=True,
            NSSupportsAutomaticGraphicsSwitching=True,
            LSApplicationCategoryType='public.app-category.utilities',
            LSEnvironment={'KITTY_LAUNCHED_BY_LAUNCH_SERVICES': '1'},
            NSServices=[
                {
                    'NSMenuItem': {'default': 'New ' + appname + ' Tab Here'},
                    'NSMessage': 'openTab',
                    'NSRequiredContext': {'NSTextContent': 'FilePath'},
                    'NSSendTypes': ['NSFilenamesPboardType', 'public.plain-text'],
                },
                {
                    'NSMenuItem': {'default': 'New ' + appname + ' Window Here'},
                    'NSMessage': 'openOSWindow',
                    'NSRequiredContext': {'NSTextContent': 'FilePath'},
                    'NSSendTypes': ['NSFilenamesPboardType', 'public.plain-text'],
                },
            ],
        )
        with open('Info.plist', 'wb') as fp:
            plistlib.dump(pl, fp)
        os.rename('../share', 'Resources')
        os.rename('../bin', 'MacOS')
        os.rename('../lib', 'Frameworks')
        if not os.path.exists(logo_dir):
            raise SystemExit('The kitty logo has not been generated, you need to run logo/make.py')
        os.symlink(os.path.join('MacOS', 'kitty'), os.path.join('MacOS', 'kitty-deref-symlink'))
        subprocess.check_call([
            'iconutil', '-c', 'icns', logo_dir, '-o',
            os.path.join('Resources', os.path.basename(logo_dir).partition('.')[0] + '.icns')
        ])
        launcher = 'MacOS/kitty'
        in_src_launcher = 'Frameworks/kitty/kitty/launcher/kitty'
        if os.path.exists(in_src_launcher):
            os.remove(in_src_launcher)
        os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
        os.symlink(os.path.relpath(launcher, os.path.dirname(in_src_launcher)), in_src_launcher)


def package(args, bundle_type):
    ddir = args.prefix
    if bundle_type == 'linux-freeze':
        args.libdir_name = 'lib'
    libdir = os.path.join(ddir, args.libdir_name.strip('/'), 'kitty')
    if os.path.exists(libdir):
        shutil.rmtree(libdir)
    os.makedirs(os.path.join(libdir, 'logo'))
    build_terminfo = runpy.run_path('build-terminfo', run_name='import_build')
    for x in (libdir, os.path.join(ddir, 'share')):
        odir = os.path.join(x, 'terminfo')
        safe_makedirs(odir)
        build_terminfo['compile_terminfo'](odir)
    shutil.copy2('__main__.py', libdir)
    shutil.copy2('logo/kitty.rgba', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/kitty.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/beam-cursor.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/beam-cursor@2x.png', os.path.join(libdir, 'logo'))

    def src_ignore(parent, entries):
        return [
            x for x in entries
            if '.' in x and x.rpartition('.')[2] not in
            ('py', 'so', 'glsl')
        ]

    shutil.copytree('kitty', os.path.join(libdir, 'kitty'), ignore=src_ignore)
    shutil.copytree('kittens', os.path.join(libdir, 'kittens'), ignore=src_ignore)
    if args.update_check_interval != 24.0:
        with open(os.path.join(libdir, 'kitty/config_data.py'), 'r+', encoding='utf-8') as f:
            raw = f.read()
            nraw = raw.replace("update_check_interval', 24", "update_check_interval', {}".format(args.update_check_interval), 1)
            if nraw == raw:
                raise SystemExit('Failed to change the value of update_check_interval')
            f.seek(0), f.truncate(), f.write(nraw)
    compile_python(libdir)
    for root, dirs, files in os.walk(libdir):
        for f in files:
            path = os.path.join(root, f)
            os.chmod(path, 0o755 if f.endswith('.so') else 0o644)
    launcher_dir = os.path.join(ddir, 'bin')
    safe_makedirs(launcher_dir)
    build_launcher(args, launcher_dir, bundle_type)
    if not is_macos:
        create_linux_bundle_gunk(ddir, args.libdir_name)

    if bundle_type.startswith('macos-'):
        create_macos_bundle_gunk(ddir)
# }}}


def clean():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    def safe_remove(*entries):
        for x in entries:
            if os.path.exists(x):
                if os.path.isdir(x):
                    shutil.rmtree(x)
                else:
                    os.unlink(x)

    safe_remove('build', 'compile_commands.json', 'linux-package', 'kitty.app', 'asan-launcher', 'kitty-profile')
    exclude = ('.git',)
    for root, dirs, files in os.walk('.', topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude]
        remove_dirs = {d for d in dirs if d == '__pycache__' or d.endswith('.dSYM')}
        [(shutil.rmtree(os.path.join(root, d)), dirs.remove(d)) for d in remove_dirs]
        for f in files:
            ext = f.rpartition('.')[-1]
            if ext in ('so', 'dylib', 'pyc', 'pyo'):
                os.unlink(os.path.join(root, f))
    for x in glob.glob('glfw/wayland-*-protocol.[ch]'):
        os.unlink(x)


def option_parser():  # {{{
    p = argparse.ArgumentParser()
    p.add_argument(
        'action',
        nargs='?',
        default='build',
        choices='build test linux-package kitty.app linux-freeze macos-freeze clean'.split(),
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
        help='Turn on sanitization to detect memory access errors and undefined behavior. This is a big performance hit.'
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
    p.add_argument(
        '--for-freeze',
        default=False,
        action='store_true',
        help='Internal use'
    )
    p.add_argument(
        '--libdir-name',
        default='lib',
        help='The name of the directory inside --prefix in which to store compiled files. Defaults to "lib"'
    )
    p.add_argument(
        '--extra-logging',
        action='append',
        default=[],
        choices=('event-loop',),
        help='Turn on extra logging for debugging in this build. Can be specified multiple times, to turn'
        ' on different types of logging.'
    )
    p.add_argument(
        '--update-check-interval',
        type=float,
        default=24,
        help='When building a package, the default value for the update_check_interval setting will'
        ' be set to this number. Use zero to disable update checking.'
    )
    return p
# }}}


def main():
    global verbose
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args()
    verbose = args.verbose > 0
    args.prefix = os.path.abspath(args.prefix)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if args.action == 'test':
        os.execlp(
            sys.executable, sys.executable, os.path.join(base, 'test.py')
        )
    elif args.action == 'clean':
        clean()
    else:
        with CompilationDatabase() as cdb:
            args.compilation_database = cdb
            if args.action == 'build':
                build(args)
                build_launcher(args, launcher_dir='kitty/launcher')
            elif args.action == 'linux-package':
                build(args, native_optimizations=False)
                if not os.path.exists(os.path.join(base, 'docs/_build/html')):
                    run_tool(['make', 'docs'])
                package(args, bundle_type='linux-package')
            elif args.action == 'linux-freeze':
                build(args, native_optimizations=False)
                if not os.path.exists(os.path.join(base, 'docs/_build/html')):
                    run_tool(['make', 'docs'])
                package(args, bundle_type='linux-freeze')
            elif args.action == 'macos-freeze':
                build(args, native_optimizations=False)
                package(args, bundle_type='macos-freeze')
            elif args.action == 'kitty.app':
                args.prefix = 'kitty.app'
                if os.path.exists(args.prefix):
                    shutil.rmtree(args.prefix)
                build(args)
                package(args, bundle_type='macos-package')
                print('kitty.app successfully built!')


if __name__ == '__main__':
    main()
