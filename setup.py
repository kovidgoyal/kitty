#!/usr/bin/env python3
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import glob
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
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import (
    Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional,
    Sequence, Set, Tuple, Union
)

from glfw import glfw  # noqa

if sys.version_info[:2] < (3, 6):
    raise SystemExit('kitty requires python >= 3.6')
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
del sys.path[0]

verbose = False
build_dir = 'build'
constants = os.path.join('kitty', 'constants.py')
with open(constants, 'rb') as f:
    constants = f.read().decode('utf-8')
appname = re.search(r"^appname: str = '([^']+)'", constants, re.MULTILINE).group(1)  # type: ignore
version = tuple(
    map(
        int,
        re.search(  # type: ignore
            r"^version: Version = Version\((\d+), (\d+), (\d+)\)", constants, re.MULTILINE
        ).group(1, 2, 3)
    )
)
_plat = sys.platform.lower()
is_macos = 'darwin' in _plat
is_openbsd = 'openbsd' in _plat
Env = glfw.Env
env = Env()
PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')


class Options(argparse.Namespace):
    action: str = 'build'
    debug: bool = False
    verbose: int = 0
    sanitize: bool = False
    prefix: str = './linux-package'
    incremental: bool = True
    profile: bool = False
    for_freeze: bool = False
    libdir_name: str = 'lib'
    extra_logging: List[str] = []
    update_check_interval: float = 24
    egl_library: Optional[str] = None
    startup_notification_library: Optional[str] = None
    canberra_library: Optional[str] = None


class CompileKey(NamedTuple):
    src: str
    dest: str


class Command(NamedTuple):
    desc: str
    cmd: Sequence[str]
    is_newer_func: Callable[[], bool]
    on_success: Callable[[], None]
    key: Optional[CompileKey]
    keyfile: Optional[str]


def emphasis(text: str) -> str:
    if sys.stdout.isatty():
        text = '\033[32m' + text + '\033[39m'
    return text


def error(text: str) -> str:
    if sys.stdout.isatty():
        text = '\033[91m' + text + '\033[39m'
    return text


def pkg_config(pkg: str, *args: str) -> List[str]:
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


def at_least_version(package: str, major: int, minor: int = 0) -> None:
    q = '{}.{}'.format(major, minor)
    if subprocess.run([PKGCONFIG, package, '--atleast-version=' + q]
                      ).returncode != 0:
        qmajor = qminor = 0
        try:
            ver = subprocess.check_output([PKGCONFIG, package, '--modversion']
                                          ).decode('utf-8').strip()
            m = re.match(r'(\d+).(\d+)', ver)
            if m is not None:
                qmajor, qminor = map(int, m.groups())
        except Exception:
            ver = 'not found'
        if qmajor < major or (qmajor == major and qminor < minor):
            raise SystemExit(
                '{} >= {}.{} is required, found version: {}'.format(
                    error(package), major, minor, ver
                )
            )


def cc_version() -> Tuple[str, Tuple[int, int]]:
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
    ver_ = raw.strip().split('.')[:2]
    try:
        if len(ver_) == 1:
            ver = int(ver_[0]), 0
        else:
            ver = int(ver_[0]), int(ver_[1])
    except Exception:
        ver = (0, 0)
    return cc, ver


def get_python_include_paths() -> List[str]:
    ans = []
    for name in sysconfig.get_path_names():
        if 'include' in name:
            ans.append(name)

    def gp(x: str) -> Optional[str]:
        return sysconfig.get_path(x)

    return sorted(frozenset(filter(None, map(gp, sorted(ans)))))


def get_python_flags(cflags: List[str]) -> List[str]:
    cflags.extend('-I' + x for x in get_python_include_paths())
    libs: List[str] = []
    libs += (sysconfig.get_config_var('LIBS') or '').split()
    libs += (sysconfig.get_config_var('SYSLIBS') or '').split()
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
        ldlib = sysconfig.get_config_var('LDLIBRARY')
        if ldlib:
            libs.append(os.path.join(framework_dir, ldlib))
    else:
        ldlib = sysconfig.get_config_var('LIBDIR')
        if ldlib:
            libs += ['-L' + ldlib]
        ldlib = sysconfig.get_config_var('VERSION')
        if ldlib:
            libs += ['-lpython' + ldlib + sys.abiflags]
        libs += (sysconfig.get_config_var('LINKFORSHARED') or '').split()
    return libs


def get_sanitize_args(cc: str, ccver: Tuple[int, int]) -> List[str]:
    sanitize_args = ['-fsanitize=address']
    if ccver >= (5, 0):
        sanitize_args.append('-fsanitize=undefined')
        # if cc == 'gcc' or (cc == 'clang' and ccver >= (4, 2)):
        #     sanitize_args.append('-fno-sanitize-recover=all')
    sanitize_args.append('-fno-omit-frame-pointer')
    return sanitize_args


def test_compile(cc: str, *cflags: str, src: Optional[str] = None) -> bool:
    src = src or 'int main(void) { return 0; }'
    p = subprocess.Popen([cc] + list(cflags) + ['-x', 'c', '-o', os.devnull, '-'], stdin=subprocess.PIPE)
    stdin = p.stdin
    assert stdin is not None
    try:
        stdin.write(src.encode('utf-8'))
        stdin.close()
    except BrokenPipeError:
        return False
    return p.wait() == 0


def first_successful_compile(cc: str, *cflags: str, src: Optional[str] = None) -> str:
    for x in cflags:
        if test_compile(cc, *shlex.split(x), src=src):
            return x
    return ''


def init_env(
    debug: bool = False,
    sanitize: bool = False,
    native_optimizations: bool = True,
    profile: bool = False,
    egl_library: Optional[str] = None,
    startup_notification_library: Optional[str] = None,
    canberra_library: Optional[str] = None,
    extra_logging: Iterable[str] = ()
) -> Env:
    native_optimizations = native_optimizations and not sanitize and not debug
    cc, ccver = cc_version()
    print('CC:', cc, ccver)
    stack_protector = first_successful_compile(cc, '-fstack-protector-strong', '-fstack-protector')
    missing_braces = ''
    if ccver < (5, 2) and cc == 'gcc':
        missing_braces = '-Wno-missing-braces'
    df = '-g3'
    float_conversion = ''
    if ccver >= (5, 0):
        df += ' -Og'
        float_conversion = '-Wfloat-conversion'
    fortify_source = '-D_FORTIFY_SOURCE=2'
    optimize = df if debug or sanitize else '-O3'
    sanitize_args = get_sanitize_args(cc, ccver) if sanitize else set()
    cppflags_ = os.environ.get(
        'OVERRIDE_CPPFLAGS', '-D{}DEBUG'.format('' if debug else 'N'),
    )
    cppflags = shlex.split(cppflags_)
    for el in extra_logging:
        cppflags.append('-DDEBUG_{}'.format(el.upper().replace('-', '_')))
    cflags_ = os.environ.get(
        'OVERRIDE_CFLAGS', (
            '-Wextra {} -Wno-missing-field-initializers -Wall -Wstrict-prototypes -std=c11'
            ' -pedantic-errors -Werror {} {} -fwrapv {} {} -pipe {} -fvisibility=hidden {}'
        ).format(
            float_conversion,
            optimize,
            ' '.join(sanitize_args),
            stack_protector,
            missing_braces,
            '-march=native' if native_optimizations else '',
            fortify_source
        )
    )
    cflags = shlex.split(cflags_) + shlex.split(
        sysconfig.get_config_var('CCSHARED') or ''
    )
    ldflags_ = os.environ.get(
        'OVERRIDE_LDFLAGS',
        '-Wall ' + ' '.join(sanitize_args) + ('' if debug else ' -O3')
    )
    ldflags = shlex.split(ldflags_)
    ldflags.append('-shared')
    cppflags += shlex.split(os.environ.get('CPPFLAGS', ''))
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags += shlex.split(os.environ.get('LDFLAGS', ''))
    if not debug and not sanitize:
        # See https://github.com/google/sanitizers/issues/647
        cflags.append('-flto')
        ldflags.append('-flto')

    if profile:
        cppflags.append('-DWITH_PROFILER')
        cflags.append('-g3')
        ldflags.append('-lprofiler')

    library_paths = {}

    if egl_library is not None:
        assert('"' not in egl_library)
        library_paths['glfw/egl_context.c'] = ['_GLFW_EGL_LIBRARY="' + egl_library + '"']

    desktop_libs = []
    if startup_notification_library is not None:
        assert('"' not in startup_notification_library)
        desktop_libs = ['_KITTY_STARTUP_NOTIFICATION_LIBRARY="' + startup_notification_library + '"']

    if canberra_library is not None:
        assert('"' not in canberra_library)
        desktop_libs += ['_KITTY_CANBERRA_LIBRARY="' + canberra_library + '"']

    if desktop_libs != []:
        library_paths['kitty/desktop.c'] = desktop_libs

    return Env(cc, cppflags, cflags, ldflags, library_paths, ccver=ccver)


def kitty_env() -> Env:
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
        font_libs = ['-framework', 'CoreText', '-framework', 'CoreGraphics', '-framework', 'UserNotifications']
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
    elif not is_openbsd:
        ans.ldpaths += ['-lrt']
        if '-ldl' not in ans.ldpaths:
            ans.ldpaths.append('-ldl')
    if '-lz' not in ans.ldpaths:
        ans.ldpaths.append('-lz')

    with suppress(FileExistsError):
        os.mkdir(build_dir)
    return ans


def define(x: str) -> str:
    return '-D' + x


def run_tool(cmd: Union[str, List[str]], desc: Optional[str] = None) -> None:
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


def get_vcs_rev_defines(env: Env, src: str) -> List[str]:
    ans = []
    if os.path.exists('.git'):
        try:
            rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8')
        except FileNotFoundError:
            try:
                with open('.git/refs/heads/master') as f:
                    rev = f.read()
            except NotADirectoryError:
                with open('.git') as f:
                    gitloc = f.read()
                with open(os.path.join(gitloc, 'refs/heads/master')) as f:
                    rev = f.read()

        ans.append('KITTY_VCS_REV="{}"'.format(rev.strip()))
    return ans


def get_library_defines(env: Env, src: str) -> Optional[List[str]]:
    try:
        return env.library_paths[src]
    except KeyError:
        return None


SPECIAL_SOURCES: Dict[str, Tuple[str, Union[List[str], Callable[[Env, str], Union[Optional[List[str]], Iterator[str]]]]]] = {
    'glfw/egl_context.c': ('glfw/egl_context.c', get_library_defines),
    'kitty/desktop.c': ('kitty/desktop.c', get_library_defines),
    'kitty/parser_dump.c': ('kitty/parser.c', ['DUMP_COMMANDS']),
    'kitty/data-types.c': ('kitty/data-types.c', get_vcs_rev_defines),
}


def newer(dest: str, *sources: str) -> bool:
    try:
        dtime = os.path.getmtime(dest)
    except OSError:
        return True
    for s in sources:
        with suppress(FileNotFoundError):
            if os.path.getmtime(s) >= dtime:
                return True
    return False


def dependecies_for(src: str, obj: str, all_headers: Iterable[str]) -> Iterable[str]:
    dep_file = obj.rpartition('.')[0] + '.d'
    try:
        with open(dep_file) as f:
            deps = f.read()
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


def parallel_run(items: List[Command]) -> None:
    try:
        num_workers = max(2, os.cpu_count() or 1)
    except Exception:
        num_workers = 2
    items = list(reversed(items))
    workers: Dict[int, Tuple[Optional[Command], Optional[subprocess.Popen]]] = {}
    failed = None
    num, total = 0, len(items)

    def wait() -> None:
        nonlocal failed
        if not workers:
            return
        pid, s = os.wait()
        compile_cmd, w = workers.pop(pid, (None, None))
        if compile_cmd is None:
            return
        if ((s & 0xff) != 0 or ((s >> 8) & 0xff) != 0):
            if failed is None:
                failed = compile_cmd
        elif compile_cmd.on_success is not None:
            compile_cmd.on_success()

    printed = False
    while items and failed is None:
        while len(workers) < num_workers and items:
            compile_cmd = items.pop()
            num += 1
            if verbose:
                print(' '.join(compile_cmd.cmd))
            else:
                print('\r\x1b[K[{}/{}] {}'.format(num, total, compile_cmd.desc), end='')
            printed = True
            w = subprocess.Popen(compile_cmd.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            workers[w.pid] = compile_cmd, w
        wait()
    while len(workers):
        wait()
    if not verbose and printed:
        print(' done')
    if failed:
        print(failed.desc)
        run_tool(list(failed.cmd))


class CompilationDatabase:

    def __init__(self, incremental: bool):
        self.incremental = incremental
        self.compile_commands: List[Command] = []
        self.link_commands: List[Command] = []

    def add_command(
        self,
        desc: str,
        cmd: List[str],
        is_newer_func: Callable,
        key: Optional[CompileKey] = None,
        on_success: Optional[Callable] = None,
        keyfile: Optional[str] = None
    ) -> None:
        def no_op() -> None:
            pass

        queue = self.link_commands if keyfile is None else self.compile_commands
        queue.append(Command(desc, cmd, is_newer_func, on_success or no_op, key, keyfile))

    def build_all(self) -> None:
        def sort_key(compile_cmd: Command) -> int:
            if compile_cmd.keyfile:
                return os.path.getsize(compile_cmd.keyfile)
            return 0

        items = []
        for compile_cmd in self.compile_commands:
            if not self.incremental or self.cmd_changed(compile_cmd) or compile_cmd.is_newer_func():
                items.append(compile_cmd)
        items.sort(key=sort_key, reverse=True)
        parallel_run(items)

        items = []
        for compile_cmd in self.link_commands:
            if not self.incremental or compile_cmd.is_newer_func():
                items.append(compile_cmd)
        parallel_run(items)

    def cmd_changed(self, compile_cmd: Command) -> bool:
        key, cmd = compile_cmd.key, compile_cmd.cmd
        return bool(self.db.get(key) != cmd)

    def __enter__(self) -> 'CompilationDatabase':
        self.all_keys: Set[CompileKey] = set()
        self.dbpath = os.path.abspath('compile_commands.json')
        self.linkdbpath = os.path.join(os.path.dirname(self.dbpath), 'link_commands.json')
        try:
            with open(self.dbpath) as f:
                compilation_database = json.load(f)
        except FileNotFoundError:
            compilation_database = []
        try:
            with open(self.linkdbpath) as f:
                link_database = json.load(f)
        except FileNotFoundError:
            link_database = []
        compilation_database = {
            CompileKey(k['file'], k['output']): k['arguments'] for k in compilation_database
        }
        self.db = compilation_database
        self.linkdb = {tuple(k['output']): k['arguments'] for k in link_database}
        return self

    def __exit__(self, *a: object) -> None:
        cdb = self.db
        for key in set(cdb) - self.all_keys:
            del cdb[key]
        compilation_database = [
            {'file': c.key.src, 'arguments': c.cmd, 'directory': base, 'output': c.key.dest} for c in self.compile_commands if c.key is not None
        ]
        with open(self.dbpath, 'w') as f:
            json.dump(compilation_database, f, indent=2, sort_keys=True)
        with open(self.linkdbpath, 'w') as f:
            json.dump([{'output': c.key, 'arguments': c.cmd, 'directory': base} for c in self.link_commands], f, indent=2, sort_keys=True)


def compile_c_extension(
    kenv: Env,
    module: str,
    compilation_database: CompilationDatabase,
    sources: List[str],
    headers: List[str],
    desc_prefix: str = ''
) -> None:
    prefix = os.path.basename(module)
    objects = [
        os.path.join(build_dir, prefix + '-' + os.path.basename(src) + '.o')
        for src in sources
    ]

    for original_src, dest in zip(sources, objects):
        src = original_src
        cppflags = kenv.cppflags[:]
        is_special = src in SPECIAL_SOURCES
        if is_special:
            src, defines_ = SPECIAL_SOURCES[src]
            defines = defines_(kenv, src) if callable(defines_) else defines_
            if defines is not None:
                cppflags.extend(map(define, defines))

        cmd = [kenv.cc, '-MMD'] + cppflags + kenv.cflags
        cmd += ['-c', src] + ['-o', dest]
        key = CompileKey(original_src, os.path.basename(dest))
        desc = 'Compiling {} ...'.format(emphasis(desc_prefix + src))
        compilation_database.add_command(desc, cmd, partial(newer, dest, *dependecies_for(src, dest, headers)), key=key, keyfile=src)
    dest = os.path.join(build_dir, module + '.so')
    real_dest = module + '.so'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    desc = 'Linking {} ...'.format(emphasis(desc_prefix + module))
    # Old versions of clang don't like -pthread being passed to the linker
    # Don't treat linker warnings as errors (linker generates spurious
    # warnings on some old systems)
    unsafe = {'-pthread', '-Werror', '-pedantic-errors'}
    linker_cflags = list(filter(lambda x: x not in unsafe, kenv.cflags))
    cmd = [kenv.cc] + linker_cflags + kenv.ldflags + objects + kenv.ldpaths + ['-o', dest]

    def on_success() -> None:
        os.rename(dest, real_dest)

    compilation_database.add_command(desc, cmd, partial(newer, real_dest, *objects), on_success=on_success, key=CompileKey('', module + '.so'))


def find_c_files() -> Tuple[List[str], List[str]]:
    ans, headers = [], []
    d = 'kitty'
    exclude = {'fontconfig.c', 'freetype.c', 'desktop.c'} if is_macos else {'core_text.m', 'cocoa_window.m', 'macos_process_info.c'}
    for x in sorted(os.listdir(d)):
        ext = os.path.splitext(x)[1]
        if ext in ('.c', '.m') and os.path.basename(x) not in exclude:
            ans.append(os.path.join('kitty', x))
        elif ext == '.h':
            headers.append(os.path.join('kitty', x))
    ans.append('kitty/parser_dump.c')
    return ans, headers


def compile_glfw(compilation_database: CompilationDatabase) -> None:
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
                glfw.build_wayland_protocols(genv, Command, parallel_run, emphasis, newer, 'glfw')
            except SystemExit as err:
                print(err, file=sys.stderr)
                print(error('Disabling building of wayland backend'), file=sys.stderr)
                continue
        compile_c_extension(
            genv, 'kitty/glfw-' + module, compilation_database,
            sources, all_headers, desc_prefix='[{}] '.format(module))


def kittens_env() -> Env:
    kenv = env.copy()
    cflags = kenv.cflags
    cflags.append('-pthread')
    cflags.append('-Ikitty')
    pylib = get_python_flags(cflags)
    kenv.ldpaths += pylib
    return kenv


def compile_kittens(compilation_database: CompilationDatabase) -> None:
    kenv = kittens_env()

    def list_files(q: str) -> List[str]:
        return sorted(glob.glob(q))

    def files(
            kitten: str,
            output: str,
            extra_headers: Sequence[str] = (),
            extra_sources: Sequence[str] = (),
            filter_sources: Optional[Callable[[str], bool]] = None
    ) -> Tuple[List[str], List[str], str]:
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
            kenv, dest, compilation_database, sources, all_headers + ['kitty/data-types.h'])


def build(args: Options, native_optimizations: bool = True) -> None:
    global env
    env = init_env(
        args.debug, args.sanitize, native_optimizations, args.profile,
        args.egl_library, args.startup_notification_library, args.canberra_library,
        args.extra_logging
    )
    sources, headers = find_c_files()
    compile_c_extension(
        kitty_env(), 'kitty/fast_data_types', args.compilation_database, sources, headers
    )
    compile_glfw(args.compilation_database)
    compile_kittens(args.compilation_database)


def safe_makedirs(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def build_launcher(args: Options, launcher_dir: str = '.', bundle_type: str = 'source') -> None:
    cflags = '-Wall -Werror -fpie'.split()
    cppflags = []
    libs: List[str] = []
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
        klp = '../Resources/kitty'
    elif bundle_type.startswith('linux-'):
        klp = '../{}/kitty'.format(args.libdir_name.strip('/'))
    elif bundle_type == 'source':
        klp = os.path.relpath('.', launcher_dir)
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
    desc = 'Building {}...'.format(emphasis('launcher'))
    args.compilation_database.add_command(desc, cmd, partial(newer, dest, src), key=key, keyfile=src)
    args.compilation_database.build_all()


# Packaging {{{


def copy_man_pages(ddir: str) -> None:
    mandir = os.path.join(ddir, 'share', 'man')
    safe_makedirs(mandir)
    with suppress(FileNotFoundError):
        shutil.rmtree(os.path.join(mandir, 'man1'))
    src = 'docs/_build/man'
    if not os.path.exists(src):
        raise SystemExit('''\
The kitty man page is missing. If you are building from git then run:
make && make docs
(needs the sphinx documentation system to be installed)
''')
    shutil.copytree(src, os.path.join(mandir, 'man1'))


def copy_html_docs(ddir: str) -> None:
    htmldir = os.path.join(ddir, 'share', 'doc', appname, 'html')
    safe_makedirs(os.path.dirname(htmldir))
    with suppress(FileNotFoundError):
        shutil.rmtree(htmldir)
    src = 'docs/_build/html'
    if not os.path.exists(src):
        raise SystemExit('''\
The kitty html docs are missing. If you are building from git then run:
make && make docs
(needs the sphinx documentation system to be installed)
''')
    shutil.copytree(src, htmldir)


def compile_python(base_path: str) -> None:
    import compileall
    import py_compile
    try:
        num_workers = max(1, os.cpu_count() or 1)
    except Exception:
        num_workers = 1
    for root, dirs, files in os.walk(base_path):
        for f in files:
            if f.rpartition('.')[-1] in ('pyc', 'pyo'):
                os.remove(os.path.join(root, f))

    def c(base_path: str, **kw: object) -> None:
        try:
            kw['invalidation_mode'] = py_compile.PycInvalidationMode.UNCHECKED_HASH
        except AttributeError:
            pass
        compileall.compile_dir(base_path, **kw)  # type: ignore

    for optimize in (0, 1, 2):
        c(base_path, ddir='', force=True, optimize=optimize, quiet=1, workers=num_workers)


def create_linux_bundle_gunk(ddir: str, libdir_name: str) -> None:
    if not os.path.exists('docs/_build/html'):
        run_tool(['make', 'docs'])
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

    base = Path(ddir)
    in_src_launcher = base / (libdir_name + '/kitty/kitty/launcher/kitty')
    launcher = base / 'bin/kitty'
    if os.path.exists(in_src_launcher):
        os.remove(in_src_launcher)
    os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
    os.symlink(os.path.relpath(launcher, os.path.dirname(in_src_launcher)), in_src_launcher)


def macos_info_plist() -> bytes:
    import plistlib
    VERSION = '.'.join(map(str, version))
    pl = dict(
        # see https://github.com/kovidgoyal/kitty/issues/1233
        CFBundleDevelopmentRegion='English',
        CFBundleAllowMixedLocalizations=True,

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
        CFBundleGetInfoString='kitty, an OpenGL based terminal emulator https://sw.kovidgoyal.net/kitty/',
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
    return plistlib.dumps(pl)


def create_macos_app_icon(where: str = 'Resources') -> None:
    iconset_dir = os.path.abspath(os.path.join('logo', appname + '.iconset'))
    icns_dir = os.path.join(where, appname + '.icns')
    try:
        subprocess.check_call([
            'iconutil', '-c', 'icns', iconset_dir, '-o', icns_dir
        ])
    except FileNotFoundError:
        print(error('iconutil not found') + ', using png2icns (without retina support) to convert the logo', file=sys.stderr)
        subprocess.check_call([
            'png2icns', icns_dir
        ] + [os.path.join(iconset_dir, logo) for logo in [
            # png2icns does not support retina icons, so only pass the non-retina icons
            'icon_16x16.png',
            'icon_32x32.png',
            'icon_128x128.png',
            'icon_256x256.png',
            'icon_512x512.png',
        ]])


def create_minimal_macos_bundle(args: Options, where: str) -> None:
    if os.path.exists(where):
        shutil.rmtree(where)
    bin_dir = os.path.join(where, 'kitty.app/Contents/MacOS')
    resources_dir = os.path.join(where, 'kitty.app/Contents/Resources')
    os.makedirs(resources_dir)
    os.makedirs(bin_dir)
    with open(os.path.join(where, 'kitty.app/Contents/Info.plist'), 'wb') as f:
        f.write(macos_info_plist())
    build_launcher(args, bin_dir)
    os.symlink(
        os.path.join(os.path.relpath(bin_dir, where), appname),
        os.path.join(where, appname))
    create_macos_app_icon(resources_dir)


def create_macos_bundle_gunk(dest: str) -> None:
    ddir = Path(dest)
    os.mkdir(ddir / 'Contents')
    with open(ddir / 'Contents/Info.plist', 'wb') as fp:
        fp.write(macos_info_plist())
    os.rename(ddir / 'share', ddir / 'Contents/Resources')
    os.rename(ddir / 'bin', ddir / 'Contents/MacOS')
    os.rename(ddir / 'lib', ddir / 'Contents/Frameworks')
    os.rename(ddir / 'Contents/Frameworks/kitty', ddir / 'Contents/Resources/kitty')
    launcher = ddir / 'Contents/MacOS/kitty'
    in_src_launcher = ddir / 'Contents/Resources/kitty/kitty/launcher/kitty'
    if os.path.exists(in_src_launcher):
        os.remove(in_src_launcher)
    os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
    os.symlink(os.path.relpath(launcher, os.path.dirname(in_src_launcher)), in_src_launcher)
    create_macos_app_icon(os.path.join(ddir, 'Contents', 'Resources'))


def package(args: Options, bundle_type: str) -> None:
    ddir = args.prefix
    if bundle_type == 'linux-freeze':
        args.libdir_name = 'lib'
    libdir = os.path.join(ddir, args.libdir_name.strip('/'), 'kitty')
    if os.path.exists(libdir):
        shutil.rmtree(libdir)
    launcher_dir = os.path.join(ddir, 'bin')
    safe_makedirs(launcher_dir)
    build_launcher(args, launcher_dir, bundle_type)
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

    def src_ignore(parent: str, entries: Iterable[str]) -> List[str]:
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
        for f_ in files:
            path = os.path.join(root, f_)
            os.chmod(path, 0o755 if f_.endswith('.so') else 0o644)
    if not is_macos:
        create_linux_bundle_gunk(ddir, args.libdir_name)

    if bundle_type.startswith('macos-'):
        create_macos_bundle_gunk(ddir)
# }}}


def clean() -> None:

    def safe_remove(*entries: str) -> None:
        for x in entries:
            if os.path.exists(x):
                if os.path.isdir(x):
                    shutil.rmtree(x)
                else:
                    os.unlink(x)

    safe_remove(
        'build', 'compile_commands.json', 'link_commands.json',
        'linux-package', 'kitty.app', 'asan-launcher',
        'kitty-profile', 'kitty/launcher')
    exclude = ('.git',)
    for root, dirs, files in os.walk('.', topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude]
        remove_dirs = {d for d in dirs if d == '__pycache__' or d.endswith('.dSYM')}
        for d in remove_dirs:
            shutil.rmtree(os.path.join(root, d))
            dirs.remove(d)
        for f in files:
            ext = f.rpartition('.')[-1]
            if ext in ('so', 'dylib', 'pyc', 'pyo'):
                os.unlink(os.path.join(root, f))
    for x in glob.glob('glfw/wayland-*-protocol.[ch]'):
        os.unlink(x)


def option_parser() -> argparse.ArgumentParser:  # {{{
    p = argparse.ArgumentParser()
    p.add_argument(
        'action',
        nargs='?',
        default=Options.action,
        choices='build test linux-package kitty.app linux-freeze macos-freeze clean'.split(),
        help='Action to perform (default is build)'
    )
    p.add_argument(
        '--debug',
        default=Options.debug,
        action='store_true',
        help='Build extension modules with debugging symbols'
    )
    p.add_argument(
        '-v', '--verbose',
        default=Options.verbose,
        action='count',
        help='Be verbose'
    )
    p.add_argument(
        '--sanitize',
        default=Options.sanitize,
        action='store_true',
        help='Turn on sanitization to detect memory access errors and undefined behavior. This is a big performance hit.'
    )
    p.add_argument(
        '--prefix',
        default=Options.prefix,
        help='Where to create the linux package'
    )
    p.add_argument(
        '--full',
        dest='incremental',
        default=Options.incremental,
        action='store_false',
        help='Do a full build, even for unchanged files'
    )
    p.add_argument(
        '--profile',
        default=Options.profile,
        action='store_true',
        help='Use the -pg compile flag to add profiling information'
    )
    p.add_argument(
        '--for-freeze',
        default=Options.for_freeze,
        action='store_true',
        help='Internal use'
    )
    p.add_argument(
        '--libdir-name',
        default=Options.libdir_name,
        help='The name of the directory inside --prefix in which to store compiled files. Defaults to "lib"'
    )
    p.add_argument(
        '--extra-logging',
        action='append',
        default=Options.extra_logging,
        choices=('event-loop',),
        help='Turn on extra logging for debugging in this build. Can be specified multiple times, to turn'
        ' on different types of logging.'
    )
    p.add_argument(
        '--update-check-interval',
        type=float,
        default=Options.update_check_interval,
        help='When building a package, the default value for the update_check_interval setting will'
        ' be set to this number. Use zero to disable update checking.'
    )
    p.add_argument(
        '--egl-library',
        type=str,
        default=Options.egl_library,
        help='The filename argument passed to dlopen for libEGL.'
        ' This can be used to change the name of the loaded library or specify an absolute path.'
    )
    p.add_argument(
        '--startup-notification-library',
        type=str,
        default=Options.startup_notification_library,
        help='The filename argument passed to dlopen for libstartup-notification-1.'
        ' This can be used to change the name of the loaded library or specify an absolute path.'
    )
    p.add_argument(
        '--canberra-library',
        type=str,
        default=Options.canberra_library,
        help='The filename argument passed to dlopen for libcanberra.'
        ' This can be used to change the name of the loaded library or specify an absolute path.'
    )
    return p
# }}}


def main() -> None:
    global verbose
    if sys.version_info < (3, 5):
        raise SystemExit('python >= 3.5 required')
    args = option_parser().parse_args(namespace=Options())
    verbose = args.verbose > 0
    args.prefix = os.path.abspath(args.prefix)
    os.chdir(base)
    if args.action == 'test':
        os.execlp(
            sys.executable, sys.executable, 'test.py'
        )
    if args.action == 'clean':
        clean()
        return
    launcher_dir = 'kitty/launcher'

    with CompilationDatabase(args.incremental) as cdb:
        args.compilation_database = cdb
        if args.action == 'build':
            build(args)
            if is_macos:
                create_minimal_macos_bundle(args, launcher_dir)
            else:
                build_launcher(args, launcher_dir=launcher_dir)
        elif args.action == 'linux-package':
            build(args, native_optimizations=False)
            package(args, bundle_type='linux-package')
        elif args.action == 'linux-freeze':
            build(args, native_optimizations=False)
            package(args, bundle_type='linux-freeze')
        elif args.action == 'macos-freeze':
            build(args, native_optimizations=False)
            build_launcher(args, launcher_dir=launcher_dir)
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
