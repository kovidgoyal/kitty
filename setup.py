#!/usr/bin/env python
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
import textwrap
import time
from contextlib import suppress
from functools import lru_cache, partial
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, Iterator, List, Optional, Sequence, Set, Tuple, Union, cast

from glfw import glfw
from glfw.glfw import Command, CompileKey

if sys.version_info[:2] < (3, 8):
    raise SystemExit('kitty requires python >= 3.8')
src_base = os.path.dirname(os.path.abspath(__file__))

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
is_arm = platform.processor() == 'arm' or platform.machine() in ('arm64', 'aarch64')
Env = glfw.Env
env = Env()
PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')


class CompilationDatabase:

    def __init__(self, incremental: bool = False):
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
        self.dbpath = os.path.abspath(os.path.join('build', 'compile_commands.json'))
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
            {'file': c.key.src, 'arguments': c.cmd, 'directory': src_base, 'output': c.key.dest} for c in self.compile_commands if c.key is not None
        ]
        with suppress(FileNotFoundError):
            with open(self.dbpath, 'w') as f:
                json.dump(compilation_database, f, indent=2, sort_keys=True)
            with open(self.linkdbpath, 'w') as f:
                json.dump([{'output': c.key, 'arguments': c.cmd, 'directory': src_base} for c in self.link_commands], f, indent=2, sort_keys=True)



class Options:
    action: str = 'build'
    debug: bool = False
    verbose: int = 0
    sanitize: bool = False
    prefix: str = './linux-package'
    dir_for_static_binaries: str = 'build/static'
    skip_code_generation: bool = False
    skip_building_kitten: bool = False
    clean_for_cross_compile: bool = False
    python_compiler_flags: str = ''
    python_linker_flags: str = ''
    incremental: bool = True
    build_universal_binary: bool = False
    ignore_compiler_warnings: bool = False
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
    fontconfig_library: Optional[str] = os.getenv('KITTY_FONTCONFIG_LIBRARY')

    # Extras
    compilation_database: CompilationDatabase = CompilationDatabase()
    vcs_rev: str = ''

def emphasis(text: str) -> str:
    if sys.stdout.isatty():
        text = f'\033[32m{text}\033[39m'
    return text


def error(text: str) -> str:
    if sys.stdout.isatty():
        text = f'\033[91m{text}\033[39m'
    return text


def pkg_config(pkg: str, *args: str, extra_pc_dir: str = '', fatal: bool = True) -> List[str]:
    env = os.environ.copy()
    if extra_pc_dir:
        pp = env.get('PKG_CONFIG_PATH', '')
        if pp:
            pp += os.pathsep
        env['PKG_CONFIG_PATH'] = f'{pp}{extra_pc_dir}'
    cmd = [PKGCONFIG, pkg] + list(args)
    try:
        return list(
            filter(
                None,
                shlex.split(
                    subprocess.check_output(cmd, env=env, stderr=None if fatal else subprocess.DEVNULL).decode('utf-8')
                )
            )
        )
    except subprocess.CalledProcessError:
        if fatal:
            raise SystemExit(f'The package {error(pkg)} was not found on your system')
        raise


def pkg_version(package: str) -> Tuple[int, int]:
    ver = subprocess.check_output([
        PKGCONFIG, package, '--modversion']).decode('utf-8').strip()
    m = re.match(r'(\d+).(\d+)', ver)
    if m is not None:
        qmajor, qminor = map(int, m.groups())
        return qmajor, qminor
    return -1, -1


def libcrypto_flags() -> Tuple[List[str], List[str]]:
    # Apple use their special snowflake TLS libraries and additionally
    # have an ancient broken system OpenSSL, so we need to check for one
    # installed by all the various macOS package managers.
    extra_pc_dir = ''

    try:
        cflags = pkg_config('libcrypto', '--cflags-only-I', fatal=False)
    except subprocess.CalledProcessError:
        if is_macos:
            import ssl
            v = ssl.OPENSSL_VERSION_INFO
            pats = f'{v[0]}.{v[1]}', f'{v[0]}'
            for pat in pats:
                q = f'opt/openssl@{pat}/lib/pkgconfig'
                openssl_dirs = glob.glob(f'/opt/homebrew/{q}') + glob.glob(f'/usr/local/{q}')
                if openssl_dirs:
                    break
            if not openssl_dirs:
                raise SystemExit(f'Failed to find OpenSSL version {v[0]}.{v[1]} on your system')
            extra_pc_dir = os.pathsep.join(openssl_dirs)
        cflags = pkg_config('libcrypto', '--cflags-only-I', extra_pc_dir=extra_pc_dir)
    return cflags, pkg_config('libcrypto', '--libs', extra_pc_dir=extra_pc_dir)


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


def get_python_flags(args: Options, cflags: List[str], for_main_executable: bool = False) -> List[str]:
    if args.python_compiler_flags:
        cflags.extend(shlex.split(args.python_compiler_flags))
    else:
        cflags.extend(f'-I{x}' for x in get_python_include_paths())
    if args.python_linker_flags:
        return shlex.split(args.python_linker_flags)
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
        lval = sysconfig.get_config_var('LINKFORSHARED') or ''
        if not for_main_executable:
            # Python sets the stack size on macOS which is not allowed unless
            # compiling an executable https://github.com/kovidgoyal/kitty/issues/289
            lval = re.sub(r'-Wl,-stack_size,\d+', '', lval)
        libs += list(filter(None, lval.split()))
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
    fontconfig_library: Optional[str] = None,
    extra_logging: Iterable[str] = (),
    extra_include_dirs: Iterable[str] = (),
    ignore_compiler_warnings: bool = False,
    build_universal_binary: bool = False,
    extra_library_dirs: Iterable[str] = (),
    verbose: bool = True,
    vcs_rev: str = '',
) -> Env:
    native_optimizations = native_optimizations and not sanitize
    if native_optimizations and is_macos and is_arm:
        # see https://github.com/kovidgoyal/kitty/issues/3126
        # -march=native is not supported when targeting Apple Silicon
        native_optimizations = False
    cc, ccver = cc_version()
    if verbose:
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
    # Using -mbranch-protection=standard causes crashes on Linux ARM, reported
    # in https://github.com/kovidgoyal/kitty/issues/6845#issuecomment-1835886938
    arm_control_flow_protection = '-mbranch-protection=standard' if is_macos else ''
    # Universal build fails with -fcf-protection clang is not smart enough to filter it out for the ARM part
    intel_control_flow_protection = '-fcf-protection=full' if ccver >= (9, 0) and not build_universal_binary else ''
    control_flow_protection = arm_control_flow_protection if is_arm else intel_control_flow_protection
    env_cflags = shlex.split(os.environ.get('CFLAGS', ''))
    env_cppflags = shlex.split(os.environ.get('CPPFLAGS', ''))
    env_ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    if control_flow_protection and not test_compile(cc, control_flow_protection, *env_cppflags, *env_cflags, ldflags=env_ldflags):
        control_flow_protection = ''
    cflags_ = os.environ.get(
        'OVERRIDE_CFLAGS', (
            f'-Wextra {float_conversion} -Wno-missing-field-initializers -Wall -Wstrict-prototypes {std}'
            f' {werror} {optimize} {sanitize_flag} -fwrapv {stack_protector} {missing_braces}'
            f' -pipe {march} -fvisibility=hidden {fortify_source} {control_flow_protection}'
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
    cppflags += env_cppflags
    cflags += env_cflags
    ldflags += env_ldflags
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

    if not native_optimizations:
        cflags.append('-msse4.2')
    library_paths: Dict[str, List[str]] = {}

    def add_lpath(which: str, name: str, val: Optional[str]) -> None:
        if val:
            if '"' in val:
                raise SystemExit(f'Cannot have quotes in library paths: {val}')
            library_paths.setdefault(which, []).append(f'{name}="{val}"')

    add_lpath('glfw/egl_context.c', '_GLFW_EGL_LIBRARY', egl_library)
    add_lpath('kitty/desktop.c', '_KITTY_STARTUP_NOTIFICATION_LIBRARY', startup_notification_library)
    add_lpath('kitty/desktop.c', '_KITTY_CANBERRA_LIBRARY', canberra_library)
    add_lpath('kitty/fontconfig.c', '_KITTY_FONTCONFIG_LIBRARY', fontconfig_library)

    for path in extra_include_dirs:
        cflags.append(f'-I{path}')

    ldpaths = []
    for path in extra_library_dirs:
        ldpaths.append(f'-L{path}')

    if os.environ.get("DEVELOP_ROOT"):
        cflags.insert(0, f'-I{os.environ["DEVELOP_ROOT"]}/include')
        ldpaths.insert(0, f'-L{os.environ["DEVELOP_ROOT"]}/lib')

    if build_universal_binary:
        set_arches(cflags)
        set_arches(ldflags)

    return Env(cc, cppflags, cflags, ldflags, library_paths, ccver=ccver, ldpaths=ldpaths, vcs_rev=vcs_rev)


def kitty_env(args: Options) -> Env:
    ans = env.copy()
    cflags = ans.cflags
    cflags.append('-pthread')
    # We add 4000 to the primary version because vim turns on SGR mouse mode
    # automatically if this version is high enough
    libcrypto_cflags, libcrypto_ldflags = libcrypto_flags()
    cppflags = ans.cppflags
    cppflags.append(f'-DPRIMARY_VERSION={version[0] + 4000}')
    cppflags.append(f'-DSECONDARY_VERSION={version[1]}')
    cppflags.append('-DXT_VERSION="{}"'.format('.'.join(map(str, version))))
    at_least_version('harfbuzz', 1, 5)
    cflags.extend(pkg_config('libpng', '--cflags-only-I'))
    cflags.extend(pkg_config('lcms2', '--cflags-only-I'))
    cflags.extend(libcrypto_cflags)
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
        platform_libs = []
    cflags.extend(pkg_config('harfbuzz', '--cflags-only-I'))
    platform_libs.extend(pkg_config('harfbuzz', '--libs'))
    pylib = get_python_flags(args, cflags)
    gl_libs = ['-framework', 'OpenGL'] if is_macos else pkg_config('gl', '--libs')
    libpng = pkg_config('libpng', '--libs')
    lcms2 = pkg_config('lcms2', '--libs')
    ans.ldpaths += pylib + platform_libs + gl_libs + libpng + lcms2 + libcrypto_ldflags
    if is_macos:
        ans.ldpaths.extend('-framework Cocoa'.split())
    elif not is_openbsd:
        ans.ldpaths += ['-lrt']
        if '-ldl' not in ans.ldpaths:
            ans.ldpaths.append('-ldl')
    if '-lz' not in ans.ldpaths:
        ans.ldpaths.append('-lz')

    os.makedirs(build_dir, exist_ok=True)
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


@lru_cache
def get_vcs_rev() -> str:
    ans = ''
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

        ans = rev.strip()
    return ans


def get_source_specific_defines(env: Env, src: str) -> Tuple[str, Optional[List[str]]]:
    if src == 'kitty/vt-parser-dump.c':
        return 'kitty/vt-parser.c', ['DUMP_COMMANDS']
    if src == 'kitty/data-types.c':
        if not env.vcs_rev:
            env.vcs_rev = get_vcs_rev()
        return src, [f'KITTY_VCS_REV="{env.vcs_rev}"', f'WRAPPED_KITTENS="{wrapped_kittens()}"']
    try:
        return src, env.library_paths[src]
    except KeyError:
        return src, None


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
                if path.startswith(src_base):
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
        src, defines = get_source_specific_defines(kenv, src)
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
    ans.append('kitty/vt-parser-dump.c')
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


def kittens_env(args: Options) -> Env:
    kenv = env.copy()
    cflags = kenv.cflags
    cflags.append('-pthread')
    cflags.append('-Ikitty')
    pylib = get_python_flags(args, cflags)
    kenv.ldpaths += pylib
    return kenv


def compile_kittens(args: Options) -> None:
    kenv = kittens_env(args)

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
        files('transfer', 'rsync', libraries=pkg_config('libxxhash', '--libs'), includes=pkg_config('libxxhash', '--cflags-only-I')),
    ):
        final_env = kenv.copy()
        final_env.cflags.extend(f'-I{x}' for x in includes)
        final_env.ldpaths[:0] = list(libraries)
        compile_c_extension(
            final_env, dest, args.compilation_database, sources, all_headers + ['kitty/data-types.h'])


def init_env_from_args(args: Options, native_optimizations: bool = False) -> None:
    global env
    env = init_env(
        args.debug, args.sanitize, native_optimizations, args.link_time_optimization, args.profile,
        args.egl_library, args.startup_notification_library, args.canberra_library, args.fontconfig_library,
        args.extra_logging, args.extra_include_dirs, args.ignore_compiler_warnings,
        args.build_universal_binary, args.extra_library_dirs, verbose=args.verbose > 0, vcs_rev=args.vcs_rev,
    )


@lru_cache
def extract_rst_targets() -> Dict[str, Dict[str, str]]:
    m = runpy.run_path('docs/extract-rst-targets.py')
    return cast(Dict[str, Dict[str, str]], m['main']())


def build_ref_map(skip_generation: bool = False) -> str:
    dest = 'kitty/docs_ref_map_generated.h'
    if not skip_generation:
        d = extract_rst_targets()
        h = 'static const char docs_ref_map[] = {\n' + textwrap.fill(', '.join(map(str, bytearray(json.dumps(d, sort_keys=True).encode('utf-8'))))) + '\n};\n'
        q = ''
        with suppress(FileNotFoundError), open(dest) as f:
            q = f.read()
        if q != h:
            with open(dest, 'w') as f:
                f.write(h)
    return dest


def build_uniforms_header(skip_generation: bool = False) -> str:
    dest = 'kitty/uniforms_generated.h'
    if skip_generation:
        return dest
    lines = ['#include "gl.h"', '']
    a = lines.append
    uniform_names: Dict[str, Tuple[str, ...]] = {}
    class_names = {}
    function_names = {}

    def find_uniform_names(raw: str) -> Iterator[str]:
        for m in re.finditer(r'^uniform\s+\S+\s+(.+?);', raw, flags=re.MULTILINE):
            for x in m.group(1).split(','):
                yield x.strip().partition('[')[0]

    for x in sorted(glob.glob('kitty/*.glsl')):
        name = os.path.basename(x).partition('.')[0]
        name, sep, shader_type = name.partition('_')
        if not sep or shader_type not in ('fragment', 'vertex'):
            continue
        class_names[name] = f'{name.capitalize()}Uniforms'
        function_names[name] = f'get_uniform_locations_{name}'
        with open(x) as f:
            raw = f.read()
        uniform_names[name] = uniform_names.setdefault(name, ()) + tuple(find_uniform_names(raw))
    for name in sorted(class_names):
        class_name, function_name, uniforms = class_names[name], function_names[name], uniform_names[name]
        a(f'typedef struct {class_name} ''{')
        for n in uniforms:
            a(f'    GLint {n};')
        a('}'f' {class_name};')
        a('')
        a(f'static inline void\n{function_name}(int program, {class_name} *ans) ''{')
        for n in uniforms:
            a(f'    ans->{n} = get_uniform_location(program, "{n}");')
        a('}')
        a('')
    src = '\n'.join(lines)
    try:
        with open(dest) as f:
            current = f.read()
    except FileNotFoundError:
        current = ''
    if src != current:
        with open(dest, 'w') as f:
            f.write(src)
    return dest


@lru_cache
def wrapped_kittens() -> str:
    with open('shell-integration/ssh/kitty') as f:
        for line in f:
            if line.startswith('    wrapped_kittens="'):
                val = line.strip().partition('"')[2][:-1]
                return ' '.join(sorted(filter(None, val.split())))
    raise Exception('Failed to read wrapped kittens from kitty wrapper script')


def build(args: Options, native_optimizations: bool = True, call_init: bool = True) -> None:
    if call_init:
        init_env_from_args(args, native_optimizations)
    sources, headers = find_c_files()
    headers.append(build_ref_map(args.skip_code_generation))
    headers.append(build_uniforms_header(args.skip_code_generation))
    compile_c_extension(
        kitty_env(args), 'kitty/fast_data_types', args.compilation_database, sources, headers
    )
    compile_glfw(args.compilation_database)
    compile_kittens(args)


def safe_makedirs(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def update_go_generated_files(args: Options, kitty_exe: str) -> None:
    if args.skip_code_generation:
        print('Skipping generation of Go files due to command line option', flush=True)
        return
    # update all the various auto-generated go files, if needed
    if args.verbose:
        print('Updating Go generated files...', flush=True)

    env = os.environ.copy()
    env['ASAN_OPTIONS'] = 'detect_leaks=0'
    cp = subprocess.run([kitty_exe, '+launch', os.path.join(src_base, 'gen/go_code.py')], stdout=subprocess.PIPE, env=env)
    if cp.returncode != 0:
        raise SystemExit(cp.returncode)


def parse_go_version(x: str) -> Tuple[int, int, int]:
    def safe_int(x: str) -> int:
        with suppress(ValueError):
            return int(x)
        return int(re.split(r'[-a-zA-Z]', x)[0])
    ans = list(map(safe_int, x.split('.')))
    while len(ans) < 3:
        ans.append(0)
    return ans[0], ans[1], ans[2]


def build_static_kittens(
    args: Options, launcher_dir: str, destination_dir: str = '', for_freeze: bool = False,
    for_platform: Optional[Tuple[str, str]] = None
) -> str:
    sys.stdout.flush()
    sys.stderr.flush()
    go = shutil.which('go')
    if not go:
        raise SystemExit('The go tool was not found on this system. Install Go')
    required_go_version = subprocess.check_output([go] + 'list -f {{.GoVersion}} -m'.split(), env=dict(os.environ, GO111MODULE="on")).decode().strip()
    current_go_version = subprocess.check_output([go, 'version']).decode().strip().split()[2][2:]
    if parse_go_version(required_go_version) > parse_go_version(current_go_version):
        raise SystemExit(f'The version of go on this system ({current_go_version}) is too old. go >= {required_go_version} is needed')
    if not for_platform:
        update_go_generated_files(args, os.path.join(launcher_dir, appname))
    if args.skip_building_kitten:
        print('Skipping building of the kitten binary because of a command line option. Build is incomplete', file=sys.stderr)
        return ''
    cmd = [go, 'build', '-v']
    vcs_rev = args.vcs_rev or get_vcs_rev()
    ld_flags: List[str] = []
    binary_data_flags = [f"-X kitty.VCSRevision={vcs_rev}"]
    if for_freeze:
        binary_data_flags.append("-X kitty.IsFrozenBuild=true")
    if for_platform:
        binary_data_flags.append("-X kitty.IsStandaloneBuild=true")
    if not args.debug:
        ld_flags.append('-s')
        ld_flags.append('-w')
    cmd += ['-ldflags', ' '.join(binary_data_flags + ld_flags)]
    dest = os.path.join(destination_dir or launcher_dir, 'kitten')
    if for_platform:
        dest += f'-{for_platform[0]}-{for_platform[1]}'
    src = os.path.abspath('tools/cmd')

    def run_one(dest: str, **env: str) -> None:
        c = cmd + ['-o', dest, src]
        if args.verbose:
            print(shlex.join(c))
        e = os.environ.copy()
        e.update(env)
        # https://github.com/kovidgoyal/kitty/issues/6051#issuecomment-1441369828
        e.pop('PWD', None)
        if for_platform:
            e['CGO_ENABLED'] = '0'
            e['GOOS'] = for_platform[0]
            e['GOARCH'] = for_platform[1]
        cp = subprocess.run(c, env=e)
        if cp.returncode != 0:
            raise SystemExit(cp.returncode)

    if args.build_universal_binary and not for_platform:
        outs = []
        for arch in ('amd64', 'arm64'):
            d = dest + f'-{arch}'
            run_one(d, GOOS='darwin', GOARCH=arch)
            outs.append(d)
        subprocess.check_call(['lipo', '-create', '-output', dest] + outs)
        for x in outs:
            os.remove(x)
    else:
        run_one(dest)
    return dest


def build_static_binaries(args: Options, launcher_dir: str) -> None:
    arches = 'amd64', 'arm64'
    for os_, arches_ in {
        'darwin': arches, 'linux': arches + ('arm', '386'), 'freebsd': arches, 'netbsd': arches, 'openbsd': arches,
        'dragonfly': ('amd64',),
    }.items():
        for arch in arches_:
            print('Cross compiling static kitten for:', os_, arch)
            build_static_kittens(args, launcher_dir, args.dir_for_static_binaries, for_platform=(os_, arch))


def build_launcher(args: Options, launcher_dir: str = '.', bundle_type: str = 'source') -> None:
    werror = '' if args.ignore_compiler_warnings else '-pedantic-errors -Werror'
    cflags = f'-Wall {werror} -fpie'.split()
    cppflags = [define(f'WRAPPED_KITTENS=" {wrapped_kittens()} "')]
    libs: List[str] = []
    ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    if args.profile or args.sanitize:
        if args.sanitize:
            cflags.append('-g3')
            sanitize_args = get_sanitize_args(env.cc, env.ccver)
            cflags.extend(sanitize_args)
            ldflags.extend(sanitize_args)
            libs += ['-lasan'] if is_gcc(env.cc) and not is_macos else []
        else:
            cflags.append('-g')
        if args.profile:
            libs.append('-lprofiler')
    else:
        cflags.append('-g3' if args.debug else '-O3')
    if bundle_type.endswith('-freeze'):
        cppflags.append('-DFOR_BUNDLE')
        cppflags.append(f'-DPYVER="{sysconfig.get_python_version()}"')
        cppflags.append(f'-DKITTY_LIB_DIR_NAME="{args.libdir_name}"')
    elif bundle_type == 'source':
        cppflags.append('-DFROM_SOURCE')
    elif bundle_type == 'develop':
        cppflags.append('-DFROM_SOURCE')
        ph = os.path.relpath(os.environ["DEVELOP_ROOT"], '.')
        cppflags.append(f'-DSET_PYTHON_HOME="{ph}"')
        if not is_macos:
            ldflags += ['-Wl,--disable-new-dtags', f'-Wl,-rpath,$ORIGIN/../../{ph}/lib']
    if bundle_type.startswith('macos-'):
        klp = '../Resources/kitty'
    elif bundle_type.startswith('linux-'):
        klp = '../{}/kitty'.format(args.libdir_name.strip('/'))
    elif bundle_type == 'source':
        klp = os.path.relpath('.', launcher_dir)
    elif bundle_type == 'develop':
        # make the kitty executable relocatable
        klp = src_base
    else:
        raise SystemExit(f'Unknown bundle type: {bundle_type}')
    cppflags.append(f'-DKITTY_LIB_PATH="{klp}"')
    pylib = get_python_flags(args, cflags, for_main_executable=True)
    cppflags += shlex.split(os.environ.get('CPPFLAGS', ''))
    cflags += shlex.split(os.environ.get('CFLAGS', ''))
    for path in args.extra_include_dirs:
        cflags.append(f'-I{path}')
    if args.build_universal_binary:
        set_arches(cflags)
        set_arches(ldflags)
    if bundle_type == 'linux-freeze':
        # --disable-new-dtags prevents -rpath from generating RUNPATH instead of
        # RPATH entries in the launcher. The ld dynamic linker does not search
        # RUNPATH locations for transitive dependencies, unlike RPATH.
        ldflags += ['-Wl,--disable-new-dtags', '-Wl,-rpath,$ORIGIN/../lib']
    os.makedirs(launcher_dir, exist_ok=True)
    os.makedirs(build_dir, exist_ok=True)
    objects = []
    for src in ('kitty/launcher/main.c',):
        obj = os.path.join(build_dir, src.replace('/', '-').replace('.c', '.o'))
        objects.append(obj)
        cmd = env.cc + cppflags + cflags + ['-c', src, '-o', obj]
        key = CompileKey(src, os.path.basename(obj))
        args.compilation_database.add_command(f'Compiling {emphasis(src)} ...', cmd, partial(newer, obj, src), key=key, keyfile=src)
    dest = os.path.join(launcher_dir, 'kitty')
    desc = f'Linking {emphasis("launcher")} ...'
    cmd = env.cc + ldflags + objects + libs + pylib + ['-o', dest]
    args.compilation_database.add_command(desc, cmd, partial(newer, dest, *objects), key=CompileKey('', 'kitty'))
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
    for root, dirs, files in os.walk(base_path):
        for f in files:
            if f.rpartition('.')[-1] in ('pyc', 'pyo'):
                os.remove(os.path.join(root, f))

    exclude = re.compile('.*/shell-integration/ssh/bootstrap.py')
    compileall.compile_dir(
        base_path, rx=exclude, force=True, optimize=(0, 1, 2), quiet=1, workers=0,  # type: ignore
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH, ddir='')


def create_linux_bundle_gunk(ddir: str, args: Options) -> None:
    libdir_name = args.libdir_name
    base = Path(ddir)
    in_src_launcher = base / (f'{libdir_name}/kitty/kitty/launcher/kitty')
    launcher = base / 'bin/kitty'
    skip_docs = False
    if not os.path.exists('docs/_build/html'):
        kitten_exe = os.path.join(os.path.dirname(str(launcher)), 'kitten')
        if os.path.exists(kitten_exe):
            os.environ['KITTEN_EXE_FOR_DOCS'] = kitten_exe
            make = 'gmake' if is_freebsd else 'make'
            run_tool([make, 'docs'])
        else:
            if args.skip_building_kitten:
                skip_docs = True
                print('WARNING: You have chosen to skip building kitten.'
                      ' This means docs could not be generated and will not be included in the linux package.'
                      ' You should build kitten and then re-run this build.', file=sys.stderr)
            else:
                raise SystemExit(f'kitten binary not found at: {kitten_exe}')
    if not skip_docs:
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
MimeType=image/*;application/x-sh;application/x-shellscript;inode/directory;text/*;x-scheme-handler/kitty;x-scheme-handler/ssh;
'''
            )

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
        NSBluetoothAlwaysUsageDescription=access('Bluetooth.'),
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


def create_minimal_macos_bundle(args: Options, launcher_dir: str, relocate: bool = False) -> None:
    kapp = os.path.join(launcher_dir, 'kitty.app')
    if os.path.exists(kapp):
        shutil.rmtree(kapp)
    bin_dir = os.path.join(kapp, 'Contents/MacOS')
    resources_dir = os.path.join(kapp, 'Contents/Resources')
    os.makedirs(resources_dir)
    os.makedirs(bin_dir)
    with open(os.path.join(kapp, 'Contents/Info.plist'), 'wb') as f:
        f.write(macos_info_plist())
    if relocate:
        shutil.copy2(os.path.join(launcher_dir, "kitty"), bin_dir)
        shutil.copy2(os.path.join(launcher_dir, "kitten"), bin_dir)
    else:
        build_launcher(args, bin_dir)
        build_static_kittens(args, launcher_dir=bin_dir)
        kitty_exe = os.path.join(launcher_dir, appname)
        with suppress(FileNotFoundError):
            os.remove(kitty_exe)
        os.symlink(os.path.join(os.path.relpath(bin_dir, launcher_dir), appname), kitty_exe)
    create_macos_app_icon(resources_dir)


def create_macos_bundle_gunk(dest: str, for_freeze: bool, args: Options) -> str:
    ddir = Path(dest)
    os.mkdir(ddir / 'Contents')
    with open(ddir / 'Contents/Info.plist', 'wb') as fp:
        fp.write(macos_info_plist())
    copy_man_pages(str(ddir))
    copy_html_docs(str(ddir))
    os.rename(ddir / 'share', ddir / 'Contents/Resources')
    os.rename(ddir / 'bin', ddir / 'Contents/MacOS')
    os.rename(ddir / 'lib', ddir / 'Contents/Frameworks')
    os.rename(ddir / 'Contents/Frameworks/kitty', ddir / 'Contents/Resources/kitty')
    kitty_exe = ddir / 'Contents/MacOS/kitty'
    in_src_launcher = ddir / 'Contents/Resources/kitty/kitty/launcher/kitty'
    if os.path.exists(in_src_launcher):
        os.remove(in_src_launcher)
    os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
    os.symlink(os.path.relpath(kitty_exe, os.path.dirname(in_src_launcher)), in_src_launcher)
    create_macos_app_icon(os.path.join(ddir, 'Contents', 'Resources'))
    if not for_freeze:
        kitten_exe = build_static_kittens(args, launcher_dir=os.path.dirname(kitty_exe))
        if not kitten_exe:
            raise SystemExit('kitten not built cannot create macOS bundle')
        os.symlink(os.path.relpath(kitten_exe, os.path.dirname(in_src_launcher)),
                   os.path.join(os.path.dirname(in_src_launcher), os.path.basename(kitten_exe)))
    return str(kitty_exe)


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
        build_terminfo['compile_terminfo'](odir)
    shutil.copy2('terminfo/kitty.terminfo', os.path.join(libdir, 'terminfo'))
    shutil.copy2('terminfo/kitty.termcap', os.path.join(libdir, 'terminfo'))
    shutil.copy2('__main__.py', libdir)
    shutil.copy2('logo/kitty-128.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/kitty.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/beam-cursor.png', os.path.join(libdir, 'logo'))
    shutil.copy2('logo/beam-cursor@2x.png', os.path.join(libdir, 'logo'))
    shutil.copytree('shell-integration', os.path.join(libdir, 'shell-integration'), dirs_exist_ok=True)
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

    def should_be_executable(path: str) -> bool:
        if path.endswith('.so'):
            return True
        q = path.split(os.sep)[-2:]
        if len(q) == 2 and q[0] == 'ssh' and q[1] in ('kitty', 'kitten'):
            return True
        return False

    for root, dirs, files in os.walk(libdir):
        for f_ in files:
            path = os.path.join(root, f_)
            os.chmod(path, 0o755 if should_be_executable(path) else 0o644)
    if not for_freeze and not bundle_type.startswith('macos-'):
        build_static_kittens(args, launcher_dir=launcher_dir)
    if not is_macos:
        create_linux_bundle_gunk(ddir, args)

    if bundle_type.startswith('macos-'):
        create_macos_bundle_gunk(ddir, for_freeze, args)
# }}}


def clean_launcher_dir(launcher_dir: str) -> None:
    for x in glob.glob(os.path.join(launcher_dir, 'kitt*')):
        if os.path.isdir(x):
            shutil.rmtree(x)
        else:
            os.remove(x)


def clean(for_cross_compile: bool = False) -> None:

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
        'kitty-profile')
    if not for_cross_compile:
        safe_remove('docs/generated')
    clean_launcher_dir('kitty/launcher')

    def excluded(root: str, d: str) -> bool:
        q = os.path.relpath(os.path.join(root, d), src_base).replace(os.sep, '/')
        return q in ('.git', 'bypy/b', 'dependencies')

    for root, dirs, files in os.walk(src_base, topdown=True):
        dirs[:] = [d for d in dirs if not excluded(root, d)]
        remove_dirs = {d for d in dirs if d == '__pycache__' or d.endswith('.dSYM')}
        for d in remove_dirs:
            shutil.rmtree(os.path.join(root, d))
            dirs.remove(d)
        for f in files:
            ext = f.rpartition('.')[-1]
            if ext in ('so', 'dylib', 'pyc', 'pyo') or (not for_cross_compile and (
                    f.endswith('_generated.h') or f.endswith('_generated.go') or f.endswith('_generated.bin'))
            ):
                os.unlink(os.path.join(root, f))
    for x in glob.glob('glfw/wayland-*-protocol.[ch]'):
        os.unlink(x)
    for x in glob.glob('kittens/*'):
        if os.path.isdir(x) and not os.path.exists(os.path.join(x, '__init__.py')):
            shutil.rmtree(x)
    subprocess.check_call(['go', 'clean', '-cache', '-testcache', '-modcache', '-fuzzcache'])


def option_parser() -> argparse.ArgumentParser:  # {{{
    p = argparse.ArgumentParser()
    p.add_argument(
        'action',
        nargs='?',
        default=Options.action,
        choices=('build',
                 'test',
                 'develop',
                 'linux-package',
                 'kitty.app',
                 'linux-freeze',
                 'macos-freeze',
                 'build-launcher',
                 'build-frozen-launcher',
                 'build-frozen-tools',
                 'clean',
                 'export-ci-bundles',
                 'build-dep',
                 'build-static-binaries',
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
        '--dir-for-static-binaries',
        default=Options.dir_for_static_binaries,
        help='Where to create the static kitten binary'
    )
    p.add_argument(
        '--skip-code-generation',
        default=Options.skip_code_generation,
        action='store_true',
        help='Do not create the *_generated.* source files. This is useful if they'
        ' have already been generated by a previous build, for example during a two-stage cross compilation.'
    )
    p.add_argument(
        '--skip-building-kitten',
        default=Options.skip_building_kitten,
        action='store_true',
        help='Do not build the kitten binary. Useful if you want to build it separately.'
    )
    p.add_argument(
        '--clean-for-cross-compile',
        default=Options.clean_for_cross_compile,
        action='store_true',
        help='Do not clean generated Go source files. Useful for cross-compilation.'
    )
    p.add_argument(
        '--python-compiler-flags', default=Options.python_compiler_flags,
        help='Compiler flags for compiling against Python. Typically include directives. If not set'
        ' the Python used to run setup.py is queried for these.'
    )
    p.add_argument(
        '--python-linker-flags', default=Options.python_linker_flags,
        help='Linker flags for linking against Python. Typically dynamic library names and search paths directives. If not set'
        ' the Python used to run setup.py is queried for these.'
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
        '--vcs-rev', default='',
        help='The VCS revision to embed in the binary. The default is to read it from the .git directory when present.'
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
        '--fontconfig-library',
        type=str,
        default=Options.fontconfig_library,
        help='The filename argument passed to dlopen for libfontconfig.'
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
        default=Options.ignore_compiler_warnings, action='store_true',
        help='Ignore any warnings from the compiler while building'
    )
    p.add_argument(
        '--build-universal-binary',
        default=Options.build_universal_binary, action='store_true',
        help='Build a universal binary (ARM + Intel on macOS, ignored on other platforms)'
    )
    return p
# }}}


def build_dep() -> None:
    class Options:
        platform: str = 'all'
        deps: List[str] = []

    p = argparse.ArgumentParser(prog=f'{sys.argv[0]} build-dep', description='Build dependencies for the kitty binary packages')
    p.add_argument(
        '--platform',
        default=Options.platform,
        choices='all macos linux linux-32 linux-arm64 linux-64'.split(),
        help='Platforms to build the dep for'
    )
    p.add_argument(
        'deps',
        nargs='*',
        default=Options.deps,
        help='Names of the dependencies, if none provided, build all'
    )
    args = p.parse_args(sys.argv[2:], namespace=Options())
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
    os.chdir(src_base)
    launcher_dir = 'kitty/launcher'

    if args.action == 'test':
        texe = os.path.abspath(os.path.join(launcher_dir, 'kitty'))
        os.execl(texe, texe, '+launch', 'test.py')
    if args.action == 'clean':
        clean(for_cross_compile=args.clean_for_cross_compile)
        return

    with CompilationDatabase(args.incremental) as cdb:
        args.compilation_database = cdb
        if args.action == 'build':
            build(args)
            if is_macos:
                create_minimal_macos_bundle(args, launcher_dir)
            else:
                build_launcher(args, launcher_dir=launcher_dir)
                build_static_kittens(args, launcher_dir=launcher_dir)
        elif args.action == 'develop':
            build(args)
            build_launcher(args, launcher_dir=launcher_dir, bundle_type='develop')
            build_static_kittens(args, launcher_dir=launcher_dir)
            if is_macos:
                create_minimal_macos_bundle(args, launcher_dir, relocate=True)
        elif args.action == 'build-launcher':
            init_env_from_args(args, False)
            build_launcher(args, launcher_dir=launcher_dir)
            build_static_kittens(args, launcher_dir=launcher_dir)
        elif args.action == 'build-frozen-launcher':
            init_env_from_args(args, False)
            bundle_type = ('macos' if is_macos else 'linux') + '-freeze'
            build_launcher(args, launcher_dir=os.path.join(args.prefix, 'bin'), bundle_type=bundle_type)
        elif args.action == 'build-frozen-tools':
            build_static_kittens(args, launcher_dir=args.prefix, for_freeze=True)
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
        elif args.action == 'build-static-binaries':
            build_static_binaries(args, launcher_dir)


if __name__ == '__main__':
    main()
