#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import glob
import json
import os
import platform
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from contextlib import suppress
from functools import lru_cache, partial
from pathlib import Path
from typing import (
    Callable, Dict, FrozenSet, Iterable, Iterator, List, Optional, Sequence,
    Set, Tuple, Union
)

from glfw import glfw
from glfw.glfw import Command, CompileKey

if sys.version_info[:2] < (3, 7):
    raise SystemExit('kitty requires python >= 3.7')
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
is_freebsd = 'freebsd' in _plat
is_netbsd = 'netbsd' in _plat
is_dragonflybsd = 'dragonfly' in _plat
is_bsd = is_freebsd or is_netbsd or is_dragonflybsd or is_openbsd
is_arm = platform.processor() == 'arm' or platform.machine() == 'arm64'
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
    libdir_name: str = 'lib'
    extra_logging: List[str] = []
    extra_include_dirs: List[str] = []
    extra_library_dirs: List[str] = []
    link_time_optimization: bool = 'KITTY_NO_LTO' not in os.environ
    update_check_interval: float = 24.0
    shell_integration: str = 'enabled'
    egl_library: Optional[str] = os.getenv('KITTY_EGL_LIBRARY')
    startup_notification_library: Optional[str] = os.getenv('KITTY_STARTUP_NOTIFICATION_LIBRARY')
    canberra_library: Optional[str] = os.getenv('KITTY_CANBERRA_LIBRARY')


def emphasis(text: str) -> str:
    if sys.stdout.isatty():
        text = f'\033[32m{text}\033[39m'
    return text


def error(text: str) -> str:
    if sys.stdout.isatty():
        text = f'\033[91m{text}\033[39m'
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
        raise SystemExit(f'The package {error(pkg)} was not found on your system')


def pkg_version(package: str) -> Tuple[int, int]:
    ver = subprocess.check_output([
        PKGCONFIG, package, '--modversion']).decode('utf-8').strip()
    m = re.match(r'(\d+).(\d+)', ver)
    if m is not None:
        qmajor, qminor = map(int, m.groups())
        return qmajor, qminor
    return -1, -1


def at_least_version(package: str, major: int, minor: int = 0) -> None:
    q = f'{major}.{minor}'
    if subprocess.run([PKGCONFIG, package, f'--atleast-version={q}']
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
            raise SystemExit(f'{error(package)} >= {major}.{minor} is required, found version: {ver}')


def cc_version() -> Tuple[List[str], Tuple[int, int]]:
    if 'CC' in os.environ:
        q = os.environ['CC']
    else:
        if is_macos:
            q = 'clang'
        else:
            if shutil.which('gcc'):
                q = 'gcc'
            elif shutil.which('clang'):
                q = 'clang'
            else:
                q = 'cc'
    cc = shlex.split(q)
    raw = subprocess.check_output(cc + ['-dumpversion']).decode('utf-8')
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
    cflags.extend(f'-I{x}' for x in get_python_include_paths())
    libs: List[str] = []
    libs += (sysconfig.get_config_var('LIBS') or '').split()
    libs += (sysconfig.get_config_var('SYSLIBS') or '').split()
    fw = sysconfig.get_config_var('PYTHONFRAMEWORK')
    if fw:
        for var in 'data include stdlib'.split():
            val = sysconfig.get_path(var)
            if val and f'/{fw}.framework' in val:
                fdir = val[:val.index(f'/{fw}.framework')]
                if os.path.isdir(
                    os.path.join(fdir, f'{fw}.framework')
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
            libs += [f'-L{ldlib}']
        ldlib = sysconfig.get_config_var('VERSION')
        if ldlib:
            libs += [f'-lpython{ldlib}{sys.abiflags}']
        libs += (sysconfig.get_config_var('LINKFORSHARED') or '').split()
    return libs


def get_sanitize_args(cc: List[str], ccver: Tuple[int, int]) -> List[str]:
    sanitize_args = ['-fsanitize=address']
    if ccver >= (5, 0):
        sanitize_args.append('-fsanitize=undefined')
        # if cc == 'gcc' or (cc == 'clang' and ccver >= (4, 2)):
        #     sanitize_args.append('-fno-sanitize-recover=all')
    sanitize_args.append('-fno-omit-frame-pointer')
    return sanitize_args


def test_compile(
    cc: List[str], *cflags: str,
    src: str = '',
    source_ext: str = 'c',
    link_also: bool = True,
    show_stderr: bool = False,
    libraries: Iterable[str] = (),
    ldflags: Iterable[str] = (),
) -> bool:
    src = src or 'int main(void) { return 0; }'
    with tempfile.TemporaryDirectory(prefix='kitty-test-compile-') as tdir:
        with open(os.path.join(tdir, f'source.{source_ext}'), 'w', encoding='utf-8') as srcf:
            print(src, file=srcf)
        return subprocess.Popen(
            cc + ['-Werror=implicit-function-declaration'] + list(cflags) + ([] if link_also else ['-c']) +
            ['-o', os.path.join(tdir, 'source.output'), srcf.name] +
            [f'-l{x}' for x in libraries] + list(ldflags),
            stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            stderr=None if show_stderr else subprocess.DEVNULL
        ).wait() == 0


def first_successful_compile(cc: List[str], *cflags: str, src: str = '', source_ext: str = 'c') -> str:
    for x in cflags:
        if test_compile(cc, *shlex.split(x), src=src, source_ext=source_ext):
            return x
    return ''


def set_arches(flags: List[str], arches: Iterable[str] = ('x86_64', 'arm64')) -> None:
    while True:
        try:
            idx = flags.index('-arch')
        except ValueError:
            break
        del flags[idx]
        del flags[idx]
    for arch in arches:
        flags.extend(('-arch', arch))


def detect_librsync(cc: List[str], cflags: List[str], ldflags: List[str]) -> str:
    if not test_compile(
            cc, *cflags, libraries=('rsync',), ldflags=ldflags, show_stderr=True,
            src='#include <librsync.h>\nint main(void) { rs_strerror(0); return 0; }'):
        raise SystemExit('The librsync library is required')
    # check for rs_sig_args() which was added to librsync in Apr 2020 version 2.3.0
    if test_compile(cc, *cflags, libraries=('rsync',), ldflags=ldflags, src='''
#include <librsync.h>
int main(void) {
    rs_magic_number magic_number = 0;
    size_t block_len = 0, strong_len = 0;
    rs_sig_args(1024, &magic_number, &block_len, &strong_len);
    return 0;
}'''):
        return '-DKITTY_HAS_RS_SIG_ARGS'
    return ''


def is_gcc(cc: Iterable[str]) -> bool:

    @lru_cache()
    def f(cc: Tuple[str]) -> bool:
        raw = subprocess.check_output(cc + ('--version',)).decode('utf-8').splitlines()[0]
        return '(GCC)' in raw.split()

    return f(tuple(cc))


def init_env(
    debug: bool = False,
    sanitize: bool = False,
    native_optimizations: bool = True,
    link_time_optimization: bool = True,
    profile: bool = False,
    egl_library: Optional[str] = None,
    startup_notification_library: Optional[str] = None,
    canberra_library: Optional[str] = None,
    extra_logging: Iterable[str] = (),
    extra_include_dirs: Iterable[str] = (),
    ignore_compiler_warnings: bool = False,
    build_universal_binary: bool = False,
    extra_library_dirs: Iterable[str] = ()
) -> Env:
    native_optimizations = native_optimizations and not sanitize and not debug
    if native_optimizations and is_macos and is_arm:
        # see https://github.com/kovidgoyal/kitty/issues/3126
        # -march=native is not supported when targeting Apple Silicon
        native_optimizations = False
    cc, ccver = cc_version()
    print('CC:', cc, ccver)
    stack_protector = first_successful_compile(cc, '-fstack-protector-strong', '-fstack-protector')
    missing_braces = ''
    if ccver < (5, 2) and is_gcc(cc):
        missing_braces = '-Wno-missing-braces'
    df = '-g3'
    float_conversion = ''
    if ccver >= (5, 0):
        df += ' -Og'
        float_conversion = '-Wfloat-conversion'
    fortify_source = '' if sanitize and is_macos else '-D_FORTIFY_SOURCE=2'
    optimize = df if debug or sanitize else '-O3'
    sanitize_args = get_sanitize_args(cc, ccver) if sanitize else set()
    cppflags_ = os.environ.get(
        'OVERRIDE_CPPFLAGS', '-D{}DEBUG'.format('' if debug else 'N'),
    )
    cppflags = shlex.split(cppflags_)
    for el in extra_logging:
        cppflags.append('-DDEBUG_{}'.format(el.upper().replace('-', '_')))
    has_copy_file_range = test_compile(cc, src='#define _GNU_SOURCE 1\n#include <unistd.h>\nint main() { copy_file_range(1, NULL, 2, NULL, 0, 0); return 0; }')
    if has_copy_file_range:
        cppflags.append('-DHAS_COPY_FILE_RANGE')
    werror = '' if ignore_compiler_warnings else '-pedantic-errors -Werror'
    std = '' if is_openbsd else '-std=c11'
    sanitize_flag = ' '.join(sanitize_args)
    march = '-march=native' if native_optimizations else ''
    cflags_ = os.environ.get(
        'OVERRIDE_CFLAGS', (
            f'-Wextra {float_conversion} -Wno-missing-field-initializers -Wall -Wstrict-prototypes {std}'
            f' {werror} {optimize} {sanitize_flag} -fwrapv {stack_protector} {missing_braces}'
            f' -pipe {march} -fvisibility=hidden {fortify_source}'
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
    if not debug and not sanitize and not is_openbsd and link_time_optimization:
        # See https://github.com/google/sanitizers/issues/647
        cflags.append('-flto')
        ldflags.append('-flto')

    if debug:
        cflags.append('-DKITTY_DEBUG_BUILD')

    if profile:
        cppflags.append('-DWITH_PROFILER')
        cflags.append('-g3')
        ldflags.append('-lprofiler')

    library_paths = {}

    if egl_library is not None:
        assert('"' not in egl_library)
        library_paths['glfw/egl_context.c'] = [f'_GLFW_EGL_LIBRARY="{egl_library}"']

    desktop_libs = []
    if startup_notification_library is not None:
        assert('"' not in startup_notification_library)
        desktop_libs = [f'_KITTY_STARTUP_NOTIFICATION_LIBRARY="{startup_notification_library}"']

    if canberra_library is not None:
        assert('"' not in canberra_library)
        desktop_libs += [f'_KITTY_CANBERRA_LIBRARY="{canberra_library}"']

    if desktop_libs != []:
        library_paths['kitty/desktop.c'] = desktop_libs

    for path in extra_include_dirs:
        cflags.append(f'-I{path}')

    ldpaths = []
    for path in extra_library_dirs:
        ldpaths.append(f'-L{path}')

    rs_cflag = detect_librsync(cc, cflags, ldflags + ldpaths)
    if rs_cflag:
        cflags.append(rs_cflag)

    if build_universal_binary:
        set_arches(cflags)
        set_arches(ldflags)

    return Env(cc, cppflags, cflags, ldflags, library_paths, ccver=ccver, ldpaths=ldpaths)


def kitty_env() -> Env:
    ans = env.copy()
    cflags = ans.cflags
    cflags.append('-pthread')
    # We add 4000 to the primary version because vim turns on SGR mouse mode
    # automatically if this version is high enough
    cppflags = ans.cppflags
    cppflags.append(f'-DPRIMARY_VERSION={version[0] + 4000}')
    cppflags.append(f'-DSECONDARY_VERSION={version[1]}')
    cppflags.append('-DXT_VERSION="{}"'.format('.'.join(map(str, version))))
    at_least_version('harfbuzz', 1, 5)
    cflags.extend(pkg_config('libpng', '--cflags-only-I'))
    cflags.extend(pkg_config('lcms2', '--cflags-only-I'))
    if is_macos:
        platform_libs = [
            '-framework', 'Carbon', '-framework', 'CoreText', '-framework', 'CoreGraphics',
        ]
        test_program_src = '''#include <UserNotifications/UserNotifications.h>
        int main(void) { return 0; }\n'''
        user_notifications_framework = first_successful_compile(
            ans.cc, '-framework UserNotifications', src=test_program_src, source_ext='m')
        if user_notifications_framework:
            platform_libs.extend(shlex.split(user_notifications_framework))
        else:
            cppflags.append('-DKITTY_USE_DEPRECATED_MACOS_NOTIFICATION_API')
        # Apple deprecated OpenGL in Mojave (10.14) silence the endless
        # warnings about it
        cppflags.append('-DGL_SILENCE_DEPRECATION')
    else:
        cflags.extend(pkg_config('fontconfig', '--cflags-only-I'))
        platform_libs = pkg_config('fontconfig', '--libs')
    cflags.extend(pkg_config('harfbuzz', '--cflags-only-I'))
    platform_libs.extend(pkg_config('harfbuzz', '--libs'))
    pylib = get_python_flags(cflags)
    gl_libs = ['-framework', 'OpenGL'] if is_macos else pkg_config('gl', '--libs')
    libpng = pkg_config('libpng', '--libs')
    lcms2 = pkg_config('lcms2', '--libs')
    ans.ldpaths += pylib + platform_libs + gl_libs + libpng + lcms2
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
    return f'-D{x}'


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

        ans.append(f'KITTY_VCS_REV="{rev.strip()}"')
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
    workers: Dict[int, Tuple[Optional[Command], Optional['subprocess.Popen[bytes]']]] = {}
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
    isatty = sys.stdout.isatty()
    while items and failed is None:
        while len(workers) < num_workers and items:
            compile_cmd = items.pop()
            num += 1
            if verbose:
                print(' '.join(compile_cmd.cmd))
            elif isatty:
                print(f'\r\x1b[K[{num}/{total}] {compile_cmd.desc}', end='')
            else:
                print(f'[{num}/{total}] {compile_cmd.desc}', flush=True)
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
        is_newer_func: Callable[[], bool],
        key: Optional[CompileKey] = None,
        on_success: Optional[Callable[[], None]] = None,
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
        os.path.join(build_dir, f'{prefix}-{os.path.basename(src)}.o')
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

        cmd = kenv.cc + ['-MMD'] + cppflags + kenv.cflags
        cmd += ['-c', src] + ['-o', dest]
        key = CompileKey(original_src, os.path.basename(dest))
        desc = f'Compiling {emphasis(desc_prefix + src)} ...'
        compilation_database.add_command(desc, cmd, partial(newer, dest, *dependecies_for(src, dest, headers)), key=key, keyfile=src)
    dest = os.path.join(build_dir, f'{module}.so')
    real_dest = f'{module}.so'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    desc = f'Linking {emphasis(desc_prefix + module)} ...'
    # Old versions of clang don't like -pthread being passed to the linker
    # Don't treat linker warnings as errors (linker generates spurious
    # warnings on some old systems)
    unsafe = {'-pthread', '-Werror', '-pedantic-errors'}
    linker_cflags = list(filter(lambda x: x not in unsafe, kenv.cflags))
    cmd = kenv.cc + linker_cflags + kenv.ldflags + objects + kenv.ldpaths + ['-o', dest]

    def on_success() -> None:
        os.rename(dest, real_dest)

    compilation_database.add_command(desc, cmd, partial(newer, real_dest, *objects), on_success=on_success, key=CompileKey('', f'{module}.so'))


def find_c_files() -> Tuple[List[str], List[str]]:
    ans, headers = [], []
    d = 'kitty'
    exclude = {
        'fontconfig.c', 'freetype.c', 'desktop.c', 'freetype_render_ui_text.c'
    } if is_macos else {
        'core_text.m', 'cocoa_window.m', 'macos_process_info.c'
    }
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
            genv = glfw.init_env(env, pkg_config, pkg_version, at_least_version, test_compile, module)
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
                glfw.build_wayland_protocols(genv, parallel_run, emphasis, newer, 'glfw')
            except SystemExit as err:
                print(err, file=sys.stderr)
                print(error('Disabling building of wayland backend'), file=sys.stderr)
                continue
        compile_c_extension(
            genv, f'kitty/glfw-{module}', compilation_database,
            sources, all_headers, desc_prefix=f'[{module}] ')


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
            filter_sources: Optional[Callable[[str], bool]] = None,
            includes: Sequence[str] = (), libraries: Sequence[str] = (),
    ) -> Tuple[str, List[str], List[str], str, Sequence[str], Sequence[str]]:
        sources = list(filter(filter_sources, list(extra_sources) + list_files(os.path.join('kittens', kitten, '*.c'))))
        headers = list_files(os.path.join('kittens', kitten, '*.h')) + list(extra_headers)
        return kitten, sources, headers, f'kittens/{kitten}/{output}', includes, libraries

    for kitten, sources, all_headers, dest, includes, libraries in (
        files('unicode_input', 'unicode_names'),
        files('diff', 'diff_speedup'),
        files('transfer', 'rsync', libraries=('rsync',)),
        files(
            'choose', 'subseq_matcher',
            extra_headers=('kitty/charsets.h',),
            extra_sources=('kitty/charsets.c',),
            filter_sources=lambda x: 'windows_compat.c' not in x),
    ):
        final_env = kenv.copy()
        final_env.cflags.extend(f'-I{x}' for x in includes)
        final_env.ldpaths[:0] = list(f'-l{x}' for x in libraries)
        compile_c_extension(
            final_env, dest, compilation_database, sources, all_headers + ['kitty/data-types.h'])


def init_env_from_args(args: Options, native_optimizations: bool = False) -> None:
    global env
    env = init_env(
        args.debug, args.sanitize, native_optimizations, args.link_time_optimization, args.profile,
        args.egl_library, args.startup_notification_library, args.canberra_library,
        args.extra_logging, args.extra_include_dirs, args.ignore_compiler_warnings,
        args.build_universal_binary, args.extra_library_dirs
    )


def build(args: Options, native_optimizations: bool = True, call_init: bool = True) -> None:
    if call_init:
        init_env_from_args(args, native_optimizations)
    sources, headers = find_c_files()
    compile_c_extension(
        kitty_env(), 'kitty/fast_data_types', args.compilation_database, sources, headers
    )
    compile_glfw(args.compilation_database)
    compile_kittens(args.compilation_database)


def safe_makedirs(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def build_launcher(args: Options, launcher_dir: str = '.', bundle_type: str = 'source') -> None:
    werror = '' if args.ignore_compiler_warnings else '-pedantic-errors -Werror'
    cflags = f'-Wall {werror} -fpie'.split()
    if args.build_universal_binary:
        cflags += '-arch x86_64 -arch arm64'.split()
    cppflags = []
    libs: List[str] = []
    if args.profile or args.sanitize:
        if args.sanitize:
            cflags.append('-g3')
            cflags.extend(get_sanitize_args(env.cc, env.ccver))
            libs += ['-lasan'] if is_gcc(env.cc) and not is_macos else []
        else:
            cflags.append('-g')
        if args.profile:
            libs.append('-lprofiler')
    else:
        cflags.append('-O3')
    if bundle_type.endswith('-freeze'):
        cppflags.append('-DFOR_BUNDLE')
        cppflags.append(f'-DPYVER="{sysconfig.get_python_version()}"')
        cppflags.append(f'-DKITTY_LIB_DIR_NAME="{args.libdir_name}"')
    elif bundle_type == 'source':
        cppflags.append('-DFROM_SOURCE')
    if bundle_type.startswith('macos-'):
        klp = '../Resources/kitty'
    elif bundle_type.startswith('linux-'):
        klp = '../{}/kitty'.format(args.libdir_name.strip('/'))
    elif bundle_type == 'source':
        klp = os.path.relpath('.', launcher_dir)
    else:
        raise SystemExit(f'Unknown bundle type: {bundle_type}')
    cppflags.append(f'-DKITTY_LIB_PATH="{klp}"')
    pylib = get_python_flags(cflags)
    cppflags += shlex.split(os.environ.get('CPPFLAGS', ''))
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    for path in args.extra_include_dirs:
        cflags.append(f'-I{path}')
    if bundle_type == 'linux-freeze':
        # --disable-new-dtags prevents -rpath from generating RUNPATH instead of
        # RPATH entries in the launcher. The ld dynamic linker does not search
        # RUNPATH locations for transitive dependencies, unlike RPATH.
        ldflags += ['-Wl,--disable-new-dtags', '-Wl,-rpath,$ORIGIN/../lib']
    os.makedirs(launcher_dir, exist_ok=True)
    dest = os.path.join(launcher_dir, 'kitty')
    src = 'launcher.c'
    cmd = env.cc + cppflags + cflags + [
           src, '-o', dest] + ldflags + libs + pylib
    key = CompileKey('launcher.c', 'kitty')
    desc = f'Building {emphasis("launcher")} ...'
    args.compilation_database.add_command(desc, cmd, partial(newer, dest, src), key=key, keyfile=src)
    args.compilation_database.build_all()


# Packaging {{{


def copy_man_pages(ddir: str) -> None:
    mandir = os.path.join(ddir, 'share', 'man')
    safe_makedirs(mandir)
    man_levels = '15'
    with suppress(FileNotFoundError):
        for x in man_levels:
            shutil.rmtree(os.path.join(mandir, f'man{x}'))
    src = 'docs/_build/man'
    if not os.path.exists(src):
        raise SystemExit('''\
The kitty man pages are missing. If you are building from git then run:
make && make docs
(needs the sphinx documentation system to be installed)
''')
    for x in man_levels:
        os.makedirs(os.path.join(mandir, f'man{x}'))
        for y in glob.glob(os.path.join(src, f'*.{x}')):
            shutil.copy2(y, os.path.join(mandir, f'man{x}'))


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
        make = 'gmake' if is_freebsd else 'make'
        run_tool([make, 'docs'])
    copy_man_pages(ddir)
    copy_html_docs(ddir)
    for (icdir, ext) in {'256x256': 'png', 'scalable': 'svg'}.items():
        icdir = os.path.join(ddir, 'share', 'icons', 'hicolor', icdir, 'apps')
        safe_makedirs(icdir)
        shutil.copy2(f'logo/kitty.{ext}', icdir)
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
Comment=Fast, feature-rich, GPU based terminal
TryExec=kitty
Exec=kitty
Icon=kitty
Categories=System;TerminalEmulator;
'''
            )
    with open(os.path.join(deskdir, 'kitty-open.desktop'), 'w') as f:
        f.write(
            '''\
[Desktop Entry]
Version=1.0
Type=Application
Name=kitty URL Launcher
GenericName=Terminal emulator
Comment=Open URLs with kitty
TryExec=kitty
Exec=kitty +open %U
Icon=kitty
Categories=System;TerminalEmulator;
NoDisplay=true
MimeType=image/*;application/x-sh;inode/directory;text/*;x-scheme-handler/kitty;
'''
            )

    base = Path(ddir)
    in_src_launcher = base / (f'{libdir_name}/kitty/kitty/launcher/kitty')
    launcher = base / 'bin/kitty'
    if os.path.exists(in_src_launcher):
        os.remove(in_src_launcher)
    os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
    os.symlink(os.path.relpath(launcher, os.path.dirname(in_src_launcher)), in_src_launcher)


def macos_info_plist() -> bytes:
    import plistlib
    VERSION = '.'.join(map(str, version))

    def access(what: str, verb: str = 'would like to access') -> str:
        return f'A program running inside kitty {verb} {what}'

    docs = [
        {
            'CFBundleTypeName': 'Terminal scripts',
            'CFBundleTypeExtensions': ['command', 'sh', 'zsh', 'bash', 'fish', 'tool'],
            'CFBundleTypeIconFile': f'{appname}.icns',
            'CFBundleTypeRole': 'Editor',
        },
        {
            'CFBundleTypeName': 'Folders',
            'LSItemContentTypes': ['public.directory'],
            'CFBundleTypeRole': 'Editor',
            'LSHandlerRank': 'Alternate',
        },
        {
            'LSItemContentTypes': ['public.unix-executable'],
            'CFBundleTypeRole': 'Shell',
        },
        {
            'CFBundleTypeName': 'Text files',
            'LSItemContentTypes': ['public.text'],
            'CFBundleTypeRole': 'Editor',
            'LSHandlerRank': 'Alternate',
        },
        {
            'CFBundleTypeName': 'Image files',
            'LSItemContentTypes': ['public.image'],
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
        },
        # Allows dragging arbitrary files to kitty Dock icon, and list kitty in the Open With context menu.
        {
            'CFBundleTypeName': 'All files',
            'LSItemContentTypes': ['public.archive', 'public.content', 'public.data'],
            'CFBundleTypeRole': 'Editor',
            'LSHandlerRank': 'Alternate',
        },
    ]

    url_schemes = [
        {
            'CFBundleURLName': 'File URL',
            'CFBundleURLSchemes': ['file'],
        },
        {
            'CFBundleURLName': 'FTP URL',
            'CFBundleURLSchemes': ['ftp', 'ftps'],
        },
        {
            'CFBundleURLName': 'Gemini URL',
            'CFBundleURLSchemes': ['gemini'],
        },
        {
            'CFBundleURLName': 'Git URL',
            'CFBundleURLSchemes': ['git'],
        },
        {
            'CFBundleURLName': 'Gopher URL',
            'CFBundleURLSchemes': ['gopher'],
        },
        {
            'CFBundleURLName': 'HTTP URL',
            'CFBundleURLSchemes': ['http', 'https'],
        },
        {
            'CFBundleURLName': 'IRC URL',
            'CFBundleURLSchemes': ['irc', 'irc6', 'ircs'],
        },
        {
            'CFBundleURLName': 'kitty URL',
            'CFBundleURLSchemes': ['kitty'],
            'LSHandlerRank': 'Owner',
            'LSIsAppleDefaultForScheme': True,
        },
        {
            'CFBundleURLName': 'Mail Address URL',
            'CFBundleURLSchemes': ['mailto'],
        },
        {
            'CFBundleURLName': 'News URL',
            'CFBundleURLSchemes': ['news', 'nntp'],
        },
        {
            'CFBundleURLName': 'SSH and SFTP URL',
            'CFBundleURLSchemes': ['ssh', 'sftp'],
        },
        {
            'CFBundleURLName': 'Telnet URL',
            'CFBundleURLSchemes': ['telnet'],
        },
    ]

    services = [
        {
            'NSMenuItem': {'default': f'New {appname} Tab Here'},
            'NSMessage': 'openTab',
            'NSRequiredContext': {'NSTextContent': 'FilePath'},
            'NSSendTypes': ['NSFilenamesPboardType', 'public.plain-text'],
        },
        {
            'NSMenuItem': {'default': f'New {appname} Window Here'},
            'NSMessage': 'openOSWindow',
            'NSRequiredContext': {'NSTextContent': 'FilePath'},
            'NSSendTypes': ['NSFilenamesPboardType', 'public.plain-text'],
        },
        {
            'NSMenuItem': {'default': f'Open with {appname}'},
            'NSMessage': 'openFileURLs',
            'NSRequiredContext': {'NSTextContent': 'FilePath'},
            'NSSendTypes': ['NSFilenamesPboardType', 'public.plain-text'],
        },
    ]

    pl = dict(
        # Naming
        CFBundleName=appname,
        CFBundleDisplayName=appname,
        # Identification
        CFBundleIdentifier=f'net.kovidgoyal.{appname}',
        # Bundle Version Info
        CFBundleVersion=VERSION,
        CFBundleShortVersionString=VERSION,
        CFBundleInfoDictionaryVersion='6.0',
        NSHumanReadableCopyright=time.strftime('Copyright %Y, Kovid Goyal'),
        CFBundleGetInfoString='kitty - The fast, feature-rich, GPU based terminal emulator. https://sw.kovidgoyal.net/kitty/',
        # Operating System Version
        LSMinimumSystemVersion='10.12.0',
        # Categorization
        CFBundlePackageType='APPL',
        CFBundleSignature='????',
        LSApplicationCategoryType='public.app-category.utilities',
        # App Execution
        CFBundleExecutable=appname,
        LSEnvironment={'KITTY_LAUNCHED_BY_LAUNCH_SERVICES': '1'},
        LSRequiresNativeExecution=True,
        NSSupportsSuddenTermination=False,
        # Localization
        # see https://github.com/kovidgoyal/kitty/issues/1233
        CFBundleDevelopmentRegion='English',
        CFBundleAllowMixedLocalizations=True,
        TICapsLockLanguageSwitchCapable=True,
        # User Interface and Graphics
        CFBundleIconFile=f'{appname}.icns',
        NSHighResolutionCapable=True,
        NSSupportsAutomaticGraphicsSwitching=True,
        # Needed for dark mode in Mojave when linking against older SDKs
        NSRequiresAquaSystemAppearance='NO',
        # Document and URL Types
        CFBundleDocumentTypes=docs,
        CFBundleURLTypes=url_schemes,
        # Services
        NSServices=services,
        # Calendar and Reminders
        NSCalendarsUsageDescription=access('your calendar data.'),
        NSRemindersUsageDescription=access('your reminders.'),
        # Camera and Microphone
        NSCameraUsageDescription=access('the camera.'),
        NSMicrophoneUsageDescription=access('the microphone.'),
        # Contacts
        NSContactsUsageDescription=access('your contacts.'),
        # Location
        NSLocationUsageDescription=access('your location information.'),
        NSLocationTemporaryUsageDescriptionDictionary=access('your location temporarily.'),
        # Motion
        NSMotionUsageDescription=access('motion data.'),
        # Networking
        NSLocalNetworkUsageDescription=access('local network.'),
        # Photos
        NSPhotoLibraryUsageDescription=access('your photo library.'),
        # Scripting
        NSAppleScriptEnabled=False,
        # Security
        NSAppleEventsUsageDescription=access('AppleScript.'),
        NSSystemAdministrationUsageDescription=access('elevated privileges.', 'requires'),
        # Speech
        NSSpeechRecognitionUsageDescription=access('speech recognition.'),
    )
    return plistlib.dumps(pl)


def create_macos_app_icon(where: str = 'Resources') -> None:
    iconset_dir = os.path.abspath(os.path.join('logo', f'{appname}.iconset'))
    icns_dir = os.path.join(where, f'{appname}.icns')
    try:
        subprocess.check_call([
            'iconutil', '-c', 'icns', iconset_dir, '-o', icns_dir
        ])
    except FileNotFoundError:
        print(f'{error("iconutil not found")}, using png2icns (without retina support) to convert the logo', file=sys.stderr)
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
    for_freeze = bundle_type.endswith('-freeze')
    if bundle_type == 'linux-freeze':
        args.libdir_name = 'lib'
    libdir = os.path.join(ddir, args.libdir_name.strip('/'), 'kitty')
    if os.path.exists(libdir):
        shutil.rmtree(libdir)
    launcher_dir = os.path.join(ddir, 'bin')
    safe_makedirs(launcher_dir)
    if for_freeze:  # freeze launcher is built separately
        args.compilation_database.build_all()
    else:
        build_launcher(args, launcher_dir, bundle_type)
    os.makedirs(os.path.join(libdir, 'logo'))
    build_terminfo = runpy.run_path('build-terminfo', run_name='import_build')
    for x in (libdir, os.path.join(ddir, 'share')):
        odir = os.path.join(x, 'terminfo')
        safe_makedirs(odir)
        build_terminfo['compile_terminfo'](odir, add_other_versions=True)
    shutil.copy2('__main__.py', libdir)
    shutil.copy2('logo/kitty-128.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/kitty.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/beam-cursor.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/beam-cursor@2x.png', os.path.join(libdir, 'logo'))
    try:
        shutil.copytree('shell-integration', os.path.join(libdir, 'shell-integration'), dirs_exist_ok=True)
    except TypeError:  # python < 3.8
        shutil.copytree('shell-integration', os.path.join(libdir, 'shell-integration'))
    allowed_extensions = frozenset('py glsl so'.split())

    def src_ignore(parent: str, entries: Iterable[str]) -> List[str]:
        return [
            x for x in entries
            if '.' in x and x.rpartition('.')[2] not in
            allowed_extensions
        ]

    shutil.copytree('kitty', os.path.join(libdir, 'kitty'), ignore=src_ignore)
    shutil.copytree('kittens', os.path.join(libdir, 'kittens'), ignore=src_ignore)
    if for_freeze:
        shutil.copytree('kitty_tests', os.path.join(libdir, 'kitty_tests'))

    def repl(name: str, raw: str, defval: Union[str, float, FrozenSet[str]], val: Union[str, float, FrozenSet[str]]) -> str:
        if defval == val:
            return raw
        tname = type(defval).__name__
        if tname == 'frozenset':
            tname = 'typing.FrozenSet[str]'
        prefix = f'{name}: {tname} ='
        nraw = raw.replace(f'{prefix} {defval!r}', f'{prefix} {val!r}', 1)
        if nraw == raw:
            raise SystemExit(f'Failed to change the value of {name}')
        return nraw

    with open(os.path.join(libdir, 'kitty/options/types.py'), 'r+', encoding='utf-8') as f:
        oraw = raw = f.read()
        raw = repl('update_check_interval', raw, Options.update_check_interval, args.update_check_interval)
        raw = repl('shell_integration', raw, frozenset(Options.shell_integration.split()), frozenset(args.shell_integration.split()))
        if raw != oraw:
            f.seek(0), f.truncate(), f.write(raw)

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

    def excluded(root: str, d: str) -> bool:
        q = os.path.relpath(os.path.join(root, d), base).replace(os.sep, '/')
        return q in ('.git', 'bypy/b')

    for root, dirs, files in os.walk(base, topdown=True):
        dirs[:] = [d for d in dirs if not excluded(root, d)]
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
        choices=('build',
                 'test',
                 'linux-package',
                 'kitty.app',
                 'linux-freeze',
                 'macos-freeze',
                 'build-launcher',
                 'build-frozen-launcher',
                 'clean',
                 'export-ci-bundles',
                 'build-dep',
                 ),
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
        '--extra-include-dirs', '-I',
        action='append',
        default=Options.extra_include_dirs,
        help='Extra include directories to use while compiling'
    )
    p.add_argument(
        '--extra-library-dirs', '-L',
        action='append',
        default=Options.extra_library_dirs,
        help='Extra library directories to use while linking'
    )
    p.add_argument(
        '--update-check-interval',
        type=float,
        default=Options.update_check_interval,
        help='When building a package, the default value for the update_check_interval setting will'
        ' be set to this number. Use zero to disable update checking.'
    )
    p.add_argument(
        '--shell-integration',
        type=str,
        default=Options.shell_integration,
        help='When building a package, the default value for the shell_integration setting will'
        ' be set to this. Use "enabled no-rc" if you intend to install the shell integration scripts system wide.'
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
    p.add_argument(
        '--disable-link-time-optimization',
        dest='link_time_optimization',
        default=Options.link_time_optimization,
        action='store_false',
        help='Turn off Link Time Optimization (LTO).'
    )
    p.add_argument(
        '--ignore-compiler-warnings',
        default=False, action='store_true',
        help='Ignore any warnings from the compiler while building'
    )
    p.add_argument(
        '--build-universal-binary',
        default=False, action='store_true',
        help='Build a universal binary (ARM + Intel on macOS, ignored on other platforms)'
    )
    return p
# }}}


def build_dep() -> None:
    class Options(argparse.Namespace):
        platform: str
        deps: List[str]

    p = argparse.ArgumentParser(prog=f'{sys.argv[0]} build-dep', description='Build dependencies for the kitty binary packages')
    p.add_argument(
        '--platform',
        default='all',
        choices='all macos linux linux-32 linux-arm64 linux-64'.split(),
        help='Platforms to build the dep for'
    )
    p.add_argument(
        'deps',
        nargs='*',
        default=[],
        help='Names of the dependencies, if none provided, build all'
    )
    args = p.parse_args(sys.argv[2:], namespace=Options)
    linux_platforms = [
        ['linux', '--arch=64'],
        ['linux', '--arch=32'],
        ['linux', '--arch=arm64'],
    ]
    if args.platform == 'all':
        platforms = linux_platforms + [['macos']]
    elif args.platform == 'linux':
        platforms = linux_platforms
    elif args.platform == 'macos':
        platforms = [['macos']]
    elif '-' in args.platform:
        parts = args.platform.split('-')
        platforms = [[parts[0], f'--arch={parts[1]}']]
    else:
        raise SystemExit(f'Unknown platform: {args.platform}')
    base = [sys.executable, '../bypy']
    for pf in platforms:
        cmd = base + pf + ['dependencies'] + args.deps
        run_tool(cmd)


def main() -> None:
    global verbose
    if len(sys.argv) > 1 and sys.argv[1] == 'build-dep':
        return build_dep()
    args = option_parser().parse_args(namespace=Options())
    if not is_macos:
        args.build_universal_binary = False
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
        elif args.action == 'build-launcher':
            init_env_from_args(args, False)
            build_launcher(args, launcher_dir=launcher_dir)
        elif args.action == 'build-frozen-launcher':
            init_env_from_args(args, False)
            bundle_type = ('macos' if is_macos else 'linux') + '-freeze'
            build_launcher(args, launcher_dir=os.path.join(args.prefix, 'bin'), bundle_type=bundle_type)
        elif args.action == 'linux-package':
            build(args, native_optimizations=False)
            package(args, bundle_type='linux-package')
        elif args.action == 'linux-freeze':
            build(args, native_optimizations=False)
            package(args, bundle_type='linux-freeze')
        elif args.action == 'macos-freeze':
            init_env_from_args(args, native_optimizations=False)
            build_launcher(args, launcher_dir=launcher_dir)
            build(args, native_optimizations=False, call_init=False)
            package(args, bundle_type='macos-freeze')
        elif args.action == 'kitty.app':
            args.prefix = 'kitty.app'
            if os.path.exists(args.prefix):
                shutil.rmtree(args.prefix)
            build(args)
            package(args, bundle_type='macos-package')
            print('kitty.app successfully built!')
        elif args.action == 'export-ci-bundles':
            cmd = [sys.executable, '../bypy', 'export', 'download.calibre-ebook.com:/srv/download/ci/kitty']
            subprocess.check_call(cmd + ['linux'])
            subprocess.check_call(cmd + ['macos'])


if __name__ == '__main__':
    main()
