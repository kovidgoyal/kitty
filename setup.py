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
import struct
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
from glfw.glfw import ISA, BinaryArch, Command, CompileKey, CompilerType

src_base = os.path.dirname(os.path.abspath(__file__))

def check_version_info() -> None:
    with open(os.path.join(src_base, 'pyproject.toml')) as f:
        raw = f.read()
    m = re.search(r'''^requires-python\s*=\s*['"](.+?)['"]''', raw, flags=re.MULTILINE)
    assert m is not None
    minver = m.group(1)
    match = re.match(r'(>=?)(\d+)\.(\d+)', minver)
    assert match is not None
    q = int(match.group(2)), int(match.group(3))
    if match.group(1) == '>=':
        is_ok = sys.version_info >= q
    else:
        is_ok = sys.version_info > q
    if not is_ok:
        exit(f'calibre requires Python {minver}. Current Python version: {".".join(map(str, sys.version_info[:3]))}')


check_version_info()
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
is_windows = sys.platform == 'win32'
is_arm = platform.processor() == 'arm' or platform.machine() in ('arm64', 'aarch64')
c_std = '' if is_openbsd else '-std=c11'
Env = glfw.Env
env = Env()
PKGCONFIG = os.environ.get('PKGCONFIG_EXE', 'pkg-config')
link_targets: List[str] = []
macos_universal_arches = ('arm64', 'x86_64') if is_arm else ('x86_64', 'arm64')


def LinkKey(output: str) -> CompileKey:
    return CompileKey('', output)


class CompilationDatabase:

    def __init__(self, incremental: bool = False):
        self.incremental = incremental
        self.compile_commands: List[Command] = []
        self.link_commands: List[Command] = []
        self.post_link_commands: List[Command] = []

    def add_command(
        self,
        desc: str,
        cmd: List[str],
        is_newer_func: Callable[[], bool],
        key: Optional[CompileKey] = None,
        on_success: Optional[Callable[[], None]] = None,
        keyfile: Optional[str] = None,
        is_post_link: bool = False,
    ) -> None:
        def no_op() -> None:
            pass

        if is_post_link:
            queue = self.post_link_commands
        else:
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

        items = []
        for compile_cmd in self.post_link_commands:
            if not self.incremental or compile_cmd.is_newer_func():
                items.append(compile_cmd)
        parallel_run(items)

    def cmd_changed(self, compile_cmd: Command) -> bool:
        key, cmd = compile_cmd.key, compile_cmd.cmd
        dkey = self.db.get(key)
        if dkey != cmd:
            return True
        return False

    def __enter__(self) -> 'CompilationDatabase':
        self.all_keys: Set[CompileKey] = set()
        self.dbpath = os.path.abspath(os.path.join(build_dir, 'compile_commands.json'))
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
    build_dsym: bool = False
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
    systemd_library: Optional[str] = os.getenv('KITTY_SYSTEMD_LIBRARY')
    fontconfig_library: Optional[str] = os.getenv('KITTY_FONTCONFIG_LIBRARY')
    building_arch: str = ''

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
    except FileNotFoundError:
        if is_windows:
            raise SystemExit(
                f'The command {error(PKGCONFIG)} was not found. You might need to install MSYS2 and its'
                ' mingw-w64-x86_64-pkg-config package, or use WSL.')
        raise
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
            else:
                raise SystemExit(f'Failed to find OpenSSL version {v[0]}.{v[1]} on your system')
            extra_pc_dir = os.pathsep.join(openssl_dirs)
        cflags = pkg_config('libcrypto', '--cflags-only-I', extra_pc_dir=extra_pc_dir)
    ldflags = pkg_config('libcrypto', '--libs', extra_pc_dir=extra_pc_dir)
    # Workaround bug in homebrew openssl package. This bug appears in CI only
    if is_macos and ldflags and 'homebrew/Cellar' in ldflags[0] and not ldflags[0].endswith('/lib'):
        ldflags.insert(0, ldflags[0] + '/lib')
    return cflags, ldflags


@lru_cache(maxsize=2)
def xxhash_flags() -> tuple[list[str], list[str]]:
    return pkg_config('libxxhash', '--cflags-only-I'), pkg_config('libxxhash', '--libs')



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
        if is_windows:
            if shutil.which('cl.exe'):
                q = 'cl.exe'
            elif shutil.which('gcc'):
                q = 'gcc'
            elif shutil.which('clang'):
                q = 'clang'
            else:
                raise SystemExit('No C compiler found. On Windows, install Visual Studio (MSVC) or MinGW-w64 (gcc/clang).')
        elif is_macos:
            q = 'clang'
        else:
            if shutil.which('gcc'):
                q = 'gcc'
            elif shutil.which('clang'):
                q = 'clang'
            else:
                q = 'cc'
    cc = shlex.split(q)
    if is_windows and cc[0].lower() == 'cl.exe':
        raw = subprocess.check_output(cc + ['/?']).decode()
        if m := re.search(r'Compiler Version ([\d\.]+)', raw):
            parts = tuple(map(int, m.group(1).split('.')))
            return cc, (parts[0], parts[1])
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
    return ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']


def get_binary_arch(path: str) -> BinaryArch:
    with open(path, 'rb') as f:
        sig = f.read(64)
    if sig.startswith(b'\x7fELF'):  # ELF
        bits = {1: 32, 2: 64}[sig[4]]
        endian = {1: '<', 2: '>'}[sig[5]]
        machine, = struct.unpack_from(endian + 'H', sig, 0x12)
        isa = {i.value:i for i in ISA}.get(machine, ISA.Other)
    elif sig[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'): # Mach-O
        s, cpu_type, = struct.unpack_from('<II', sig, 0)
        bits = {0xfeedface: 32, 0xfeedfacf: 64}[s]
        cpu_type &= 0xff
        isa = {0x7: ISA.AMD64, 0xc: ISA.ARM64}[cpu_type]
    else:
        raise SystemExit(f'Unknown binary format with signature: {sig[:4]!r}')
    return BinaryArch(bits=bits, isa=isa)


def test_compile(
    cc: List[str], *cflags: str,
    src: str = '',
    source_ext: str = 'c',
    link_also: bool = True,
    show_stderr: bool = False,
    libraries: Iterable[str] = (),
    ldflags: Iterable[str] = (),
    get_output_arch: bool = False,
) -> Union[bool, BinaryArch]:
    src = src or 'int main(void) { return 0; }'
    with tempfile.TemporaryDirectory(prefix='kitty-test-compile-') as tdir:
        with open(os.path.join(tdir, f'source.{source_ext}'), 'w', encoding='utf-8') as srcf:
            print(src, file=srcf)
        output = os.path.join(tdir, 'source.output')
        ret = subprocess.Popen(
            cc + ['-Werror=implicit-function-declaration'] + list(cflags) + ([] if link_also else ['-c']) +
            ['-o', output, srcf.name] +
            [f'-l{x}' for x in libraries] + list(ldflags),
            stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            stderr=None if show_stderr else subprocess.DEVNULL
        ).wait()
        if get_output_arch:
            if ret != 0:
                raise SystemExit(f'Failed to determine target architecture compiling test program failed with exit code: {ret}')
            return get_binary_arch(output)
        return ret == 0


def first_successful_compile(cc: List[str], *cflags: str, src: str = '', source_ext: str = 'c') -> str:
    for x in cflags:
        if test_compile(cc, *shlex.split(x), src=src, source_ext=source_ext):
            return x
    return ''


def set_arches(flags: List[str], *arches: str) -> None:
    while True:
        try:
            idx = flags.index('-arch')
        except ValueError:
            break
        del flags[idx]
        del flags[idx]
    for arch in arches:
        flags.extend(('-arch', arch))


def init_env(
    debug: bool = False,
    sanitize: bool = False,
    native_optimizations: bool = True,
    link_time_optimization: bool = True,
    profile: bool = False,
    egl_library: Optional[str] = None,
    startup_notification_library: Optional[str] = None,
    canberra_library: Optional[str] = None,
    systemd_library: Optional[str] = None,
    fontconfig_library: Optional[str] = None,
    extra_logging: Iterable[str] = (),
    extra_include_dirs: Iterable[str] = (),
    ignore_compiler_warnings: bool = False,
    building_arch: str = '',
    extra_library_dirs: Iterable[str] = (),
    verbose: bool = True,
    vcs_rev: str = '',
) -> Env:
    native_optimizations = native_optimizations and not sanitize
    cc, ccver = cc_version()
    if verbose:
        print('CC:', cc, ccver)
    stack_protector = first_successful_compile(cc, '-fstack-protector-strong', '-fstack-protector')
    missing_braces = ''
    if ccver < (5, 2):
        missing_braces = '-Wno-missing-braces'
    df = '-g3'
    float_conversion = ''
    if ccver >= (5, 0):
        df += ' -Og'
        float_conversion = '-Wfloat-conversion'
    fortify_source = '' if sanitize and is_macos else '-D_FORTIFY_SOURCE=2'
    optimize = df if debug or sanitize else '-O3'
    sanitize_args = get_sanitize_args(cc, ccver) if sanitize else []
    cppflags_ = os.environ.get(
        'OVERRIDE_CPPFLAGS', '-D{}DEBUG'.format('' if debug else 'N'),
    )
    cppflags = shlex.split(cppflags_)
    for el in extra_logging:
        cppflags.append('-DDEBUG_{}'.format(el.upper().replace('-', '_')))
    has_copy_file_range = test_compile(cc, src='#define _GNU_SOURCE 1\n#include <unistd.h>\nint main() { copy_file_range(1, NULL, 2, NULL, 0, 0); return 0; }')
    werror = '' if ignore_compiler_warnings else '-pedantic-errors -Werror'
    sanitize_flag = ' '.join(sanitize_args)
    env_cflags = shlex.split(os.environ.get('CFLAGS', ''))
    env_cppflags = shlex.split(os.environ.get('CPPFLAGS', ''))
    env_ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    # Newer clang does not use -fno-plt leading to an error
    no_plt = '-fno-plt' if test_compile(cc, '-fno-plt', '-Werror') else ''

    cflags_ = os.environ.get(
        'OVERRIDE_CFLAGS', (
            f'-Wextra {float_conversion} -Wno-missing-field-initializers -Wall -Wstrict-prototypes {c_std}'
            f' {werror} {optimize} {sanitize_flag} -fwrapv {stack_protector} {missing_braces}'
            f' -pipe -fvisibility=hidden {no_plt}'
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
    if fortify_source:
        for x in cflags:
            if '_FORTIFY_SOURCE' in x:
                break
        else:
            cflags.append(fortify_source)
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

    if debug or profile:
        cflags.append('-fno-omit-frame-pointer')

    library_paths: Dict[str, List[str]] = {}

    def add_lpath(which: str, name: str, val: Optional[str]) -> None:
        if val:
            if '"' in val:
                raise SystemExit(f'Cannot have quotes in library paths: {val}')
            library_paths.setdefault(which, []).append(f'{name}="{val}"')

    add_lpath('glfw/egl_context.c', '_GLFW_EGL_LIBRARY', egl_library)
    add_lpath('kitty/desktop.c', '_KITTY_STARTUP_NOTIFICATION_LIBRARY', startup_notification_library)
    add_lpath('kitty/desktop.c', '_KITTY_CANBERRA_LIBRARY', canberra_library)
    add_lpath('kitty/systemd.c', '_KITTY_SYSTEMD_LIBRARY', systemd_library)
    add_lpath('kitty/fontconfig.c', '_KITTY_FONTCONFIG_LIBRARY', fontconfig_library)

    for path in extra_include_dirs:
        cflags.append(f'-I{path}')

    ldpaths = []
    for path in extra_library_dirs:
        ldpaths.append(f'-L{path}')

    if os.environ.get("DEVELOP_ROOT"):
        cflags.insert(0, f'-I{os.environ["DEVELOP_ROOT"]}/include')
        ldpaths.insert(0, f'-L{os.environ["DEVELOP_ROOT"]}/lib')

    if building_arch:
        set_arches(cflags, building_arch)
        set_arches(ldflags, building_arch)
    ba = test_compile(cc, *(cppflags + cflags), ldflags=ldflags, get_output_arch=True)
    assert isinstance(ba, BinaryArch)
    if ba.isa not in (ISA.AMD64, ISA.X86, ISA.ARM64):
        cppflags.append('-DKITTY_NO_SIMD')

    control_flow_protection = ''
    if ba.isa == ISA.AMD64:
        control_flow_protection = '-fcf-protection=full' if ccver >= (9, 0) else ''
    elif ba.isa == ISA.ARM64:
        # Using -mbranch-protection=standard causes crashes on Linux ARM, reported
        # in https://github.com/kovidgoyal/kitty/issues/6845#issuecomment-1835886938
        if is_macos:
            control_flow_protection = '-mbranch-protection=standard'

    if control_flow_protection:
        cflags.append(control_flow_protection)

    if native_optimizations and ba.isa in (ISA.AMD64, ISA.X86):
        cflags.extend('-march=native -mtune=native'.split())

    ans = Env(
        cc, cppflags, cflags, ldflags, library_paths, binary_arch=ba, native_optimizations=native_optimizations,
        ccver=ccver, ldpaths=ldpaths, vcs_rev=vcs_rev,
    )
    ans.has_copy_file_range = bool(has_copy_file_range)
    if ans.compiler_type is CompilerType.gcc:
        cflags.append('-Wno-packed-bitfield-compat')
    if verbose:
        print(ans.cc_version_string.strip())
        print('Detected:', ans.compiler_type)
    return ans


def kitty_env(args: Options) -> Env:
    ans = env.copy()
    cflags = ans.cflags
    cflags.append('-pthread')
    cppflags = ans.cppflags
    # We add 4000 to the primary version because vim turns on SGR mouse mode
    # automatically if this version is high enough
    ans.primary_version = version[0] + 4000
    ans.secondary_version = version[1]
    ans.xt_version = '.'.join(map(str, version))

    xxhash = xxhash_flags()
    at_least_version('harfbuzz', 1, 5)
    cflags.extend(pkg_config('libpng', '--cflags-only-I'))
    cflags.extend(pkg_config('lcms2', '--cflags-only-I'))
    cflags.extend(xxhash[0])
    # simde doesnt come with pkg-config files but some Linux distros add
    # them and on macOS when building with homebrew it is required
    with suppress(SystemExit, subprocess.CalledProcessError):
        cflags.extend(pkg_config('simde', '--cflags-only-I', fatal=False))
    libcrypto_cflags, libcrypto_ldflags = libcrypto_flags()
    cflags.extend(libcrypto_cflags)
    if is_macos:
        platform_libs = [
            '-framework', 'Carbon', '-framework', 'CoreText', '-framework', 'CoreGraphics',
            '-framework', 'AudioToolbox',
        ]
        test_program_src = '''#include <UserNotifications/UserNotifications.h>
        int main(void) { return 0; }\n'''
        user_notifications_framework = first_successful_compile(
            ans.cc, '-framework UserNotifications', src=test_program_src, source_ext='m')
        if user_notifications_framework:
            platform_libs.extend(shlex.split(user_notifications_framework))
        else:
            raise SystemExit('UserNotifications framework missing')
        # Apple deprecated OpenGL in Mojave (10.14) silence the endless
        # warnings about it
        cppflags.append('-DGL_SILENCE_DEPRECATION')
    else:
        cflags.extend(pkg_config('cairo-fc', '--cflags-only-I'))
        platform_libs = []
        platform_libs.extend(pkg_config('cairo-fc', '--libs'))
    cflags.extend(pkg_config('harfbuzz', '--cflags-only-I'))
    platform_libs.extend(pkg_config('harfbuzz', '--libs'))
    pylib = get_python_flags(args, cflags)
    gl_libs = ['-framework', 'OpenGL'] if is_macos else pkg_config('gl', '--libs')
    libpng = pkg_config('libpng', '--libs')
    lcms2 = pkg_config('lcms2', '--libs')
    ans.ldpaths += pylib + platform_libs + gl_libs + libpng + lcms2 + libcrypto_ldflags + xxhash[1]
    if is_macos:
        ans.ldpaths.extend('-framework Cocoa'.split())
    elif not is_openbsd:
        ans.ldpaths += ['-lrt']
        if '-ldl' not in ans.ldpaths:
            ans.ldpaths.append('-ldl')
    if '-lz' not in ans.ldpaths:
        ans.ldpaths.append('-lz')

    return ans


def define(x: str) -> str:
    return f'-D{x}'


def run_tool(cmd: Union[str, List[str]], desc: Optional[str] = None) -> None:
    if verbose:
        desc = None

    if is_windows:
        # On Windows, it's generally safer to pass a single string to Popen with shell=True
        # for commands that might involve shell built-ins or complex paths.
        if isinstance(cmd, list):
            wcmd_to_execute = shlex.join(cmd)
        else:
            wcmd_to_execute = cmd
        print(desc or wcmd_to_execute)
        p = subprocess.Popen(wcmd_to_execute, shell=True)
    else:
        # On Unix-like systems, passing a list is generally preferred for security and clarity.
        if isinstance(cmd, str):
            cmd_to_execute = shlex.split(cmd) # Split the string into a list of arguments
        else:
            cmd_to_execute = cmd
        print(desc or ' '.join(cmd_to_execute))
        p = subprocess.Popen(cmd_to_execute)

    ret = p.wait()
    if ret != 0:
        if desc:
            print(wcmd_to_execute if is_windows else cmd_to_execute) # Print the actual command that was executed
        raise SystemExit(ret)


@lru_cache
def get_vcs_rev() -> str:
    ans = ''
    git_exe = shutil.which('git') or 'git'
    if os.path.exists('.git'):
        try:
            rev = subprocess.check_output([git_exe, 'rev-parse', 'HEAD']).decode('utf-8')
            ans = rev.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback for older git versions or other issues
            try:
                with open(os.path.join('.git', 'HEAD')) as f:
                    head_content = f.read().strip()
                if head_content.startswith('ref:'):
                    ref_path = head_content[5:].strip()
                    with open(os.path.join('.git', ref_path)) as f:
                        ans = f.read().strip()
                else:
                    ans = head_content
            except Exception as e:
                print(error(f'Warning: Failed to get git revision from .git directory: {e}'), file=sys.stderr)
    return ans


@lru_cache
def base64_defines(isa: ISA) -> List[str]:
    defs = {
        'HAVE_AVX512': 0,
        'HAVE_AVX2': 0,
        'HAVE_NEON32': 0,
        'HAVE_NEON64': 0,
        'HAVE_SSSE3': 0,
        'HAVE_SSE41': 0,
        'HAVE_SSE42': 0,
        'HAVE_AVX': 0,
    }
    if isa == ISA.ARM64:
        defs['HAVE_NEON64'] = 1
    elif isa == ISA.AMD64:
        defs['HAVE_AVX2'] = 1
        defs['HAVE_AVX'] = 1
        defs['HAVE_SSE42'] = 1
        defs['HAVE_SSE41'] = 1
        defs['HAVE_SSE3'] = 1
    elif isa == ISA.X86:
        defs['HAVE_SSE42'] = 1
        defs['HAVE_SSE41'] = 1
        defs['HAVE_SSE3'] = 1
    return [f'{k}={v}' for k, v in defs.items()]


def get_source_specific_defines(env: Env, src: str) -> Tuple[str, List[str], Optional[List[str]]]:
    if src == 'kitty/vt-parser-dump.c':
        return 'kitty/vt-parser.c', [], ['DUMP_COMMANDS']
    if src == 'kitty/data-types.c':
        if not env.vcs_rev:
            env.vcs_rev = get_vcs_rev()
        return src, [], [f'KITTY_VCS_REV="{env.vcs_rev}"', f'WRAPPED_KITTENS="{wrapped_kittens()}"']
    if src.startswith('3rdparty/base64/'):
        return src, ['3rdparty/base64',], base64_defines(env.binary_arch.isa)
    if src == 'kitty/screen.c':
        return src, [], [f'PRIMARY_VERSION={env.primary_version}', f'SECONDARY_VERSION={env.secondary_version}', f'XT_VERSION="{env.xt_version}"']
    if src == 'kitty/fast-file-copy.c':
        return src, [], (['HAS_COPY_FILE_RANGE'] if env.has_copy_file_range else None)
    try:
        return src, [], env.library_paths[src]
    except KeyError:
        return src, [], None


def get_source_specific_cflags(env: Env, src: str) -> List[str]:
    ans = list(env.cflags)
    # SIMD specific flags
    if src in ('kitty/simd-string-128.c', 'kitty/simd-string-256.c'):
        # simde recommends these are used for best performance
        ans.extend(('-fopenmp-simd', '-DSIMDE_ENABLE_OPENMP'))
        if env.binary_arch.isa in (ISA.AMD64, ISA.X86):
            ans.append('-msse4.2' if '128' in src else '-mavx2')
            if '256' in src:
                # We have manual vzeroupper so prevent compiler from emitting it causing duplicates
                if env.compiler_type is CompilerType.clang:
                    ans.append('-mllvm')
                    ans.append('-x86-use-vzeroupper=0')
                else:
                    ans.append('-mno-vzeroupper')
    elif src.startswith('3rdparty/base64/lib/arch/'):
        if env.binary_arch.isa in (ISA.AMD64, ISA.X86):
            q = src.split(os.path.sep)
            if 'sse3' in q:
                ans.append('-msse3')
            elif 'sse41' in q:
                ans.append('-msse4.1')
            elif 'sse42' in q:
                ans.append('-msse4.2')
            elif 'avx' in q:
                ans.append('-mavx')
            elif 'avx2' in q:
                ans.append('-mavx2')
    return ans


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
                print(f'\r\x1b[K[{num}/{total}] {compile_cmd.desc}', end='')  # ]]
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


def add_builtin_fonts(args: Options) -> None:
    fonts_dir = os.path.join(src_base, 'fonts')
    os.makedirs(fonts_dir, exist_ok=True)

    for psname, (filename, human_name) in {
        'SymbolsNFM': ('SymbolsNerdFontMono-Regular.ttf', 'Symbols NERD Font Mono')
    }.items():
        dest = os.path.join(fonts_dir, filename)
        if os.path.exists(dest):
            continue
        font_file = ''
        if is_macos:
            for candidate in (os.path.expanduser('~/Library/Fonts'), '/Library/Fonts', '/System/Library/Fonts', '/Network/Library/Fonts'):
                q = os.path.join(candidate, filename)
                if os.path.exists(q):
                    font_file = q
                    break
        elif is_windows:
            for candidate in (
                    os.path.expandvars(r'%userprofile%\AppData\Local\Microsoft\Windows\Fonts'),
                    os.path.expandvars(r'%windir%\Fonts'),
            ):
                q = os.path.join(candidate, filename)
                if os.path.exists(q):
                    font_file = q
                    break
        else:
            lines = subprocess.check_output([
                'fc-match', '--format', '%{file}\n%{postscriptname}', f'term:postscriptname={psname}', 'file', 'postscriptname']).decode().splitlines()
            if len(lines) != 2:
                raise SystemExit(f'fc-match returned unexpected output: {lines}')
            if lines[1] != psname:
                raise SystemExit(f'The font {human_name!r} was not found on your system, please install it')
            font_file = lines[0]
        if not font_file:
            raise SystemExit(f'The font {human_name!r} was not found on your system, please install it')
        print(f'Copying {human_name!r} from {font_file}')
        shutil.copy(font_file, dest)
        os.chmod(dest, 0o644)


def compile_c_extension(
    kenv: Env,
    module: str,
    compilation_database: CompilationDatabase,
    sources: List[str],
    headers: List[str],
    desc_prefix: str = '',
    build_dsym: bool = False,
) -> None:
    prefix = os.path.basename(module)
    objects = [
        os.path.join(build_dir, f'{prefix}-{src.replace("/", "-")}.o')
        for src in sources
    ]

    for original_src, dest in zip(sources, objects):
        src = original_src
        cppflags = kenv.cppflags[:]
        src, include_paths, defines = get_source_specific_defines(kenv, src)
        if defines is not None:
            cppflags.extend(map(define, defines))
        cflags = get_source_specific_cflags(kenv, src)
        cmd = kenv.cc + ['-MMD'] + cppflags + [f'-I{x}' for x in include_paths] + cflags
        cmd += ['-c', src] + ['-o', dest]
        key = CompileKey(original_src, os.path.basename(dest))
        desc = f'Compiling {emphasis(desc_prefix + src)} ...'
        compilation_database.add_command(desc, cmd, partial(newer, dest, *dependecies_for(src, dest, headers)), key=key, keyfile=src)
    dest = os.path.join(build_dir, f'{module}.so')
    real_dest = f'{module}.so'
    link_targets.append(os.path.abspath(real_dest))
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

    compilation_database.add_command(desc, cmd, partial(newer, real_dest, *objects), on_success=on_success, key=LinkKey(f'{module}.so'))
    if is_macos and build_dsym:
        real_dest = os.path.abspath(real_dest)
        desc = f'Linking dSYM {emphasis(desc_prefix + module)} ...'
        dsym = f'{real_dest}.dSYM/Contents/Resources/DWARF/{os.path.basename(real_dest)}'
        compilation_database.add_command(desc, ['dsymutil', real_dest], partial(newer, dsym, real_dest), key=LinkKey(dsym), is_post_link=True)


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

    # ringbuf
    ans.append('3rdparty/ringbuf/ringbuf.c')
    # base64
    ans.extend(glob.glob('3rdparty/base64/lib/arch/*/codec.c'))
    ans.append('3rdparty/base64/lib/tables/tables.c')
    ans.append('3rdparty/base64/lib/codec_choose.c')
    ans.append('3rdparty/base64/lib/lib.c')
    return ans, headers


def compile_glfw(compilation_database: CompilationDatabase, build_dsym: bool = False) -> None:
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
            sources, all_headers, desc_prefix=f'[{module}] ', build_dsym=build_dsym)


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

    xxhash = xxhash_flags()
    for kitten, sources, all_headers, dest, includes, libraries in (
        files('transfer', 'rsync', libraries=xxhash[1], includes=xxhash[0]),
    ):
        final_env = kenv.copy()
        final_env.cflags.extend(includes)
        final_env.ldpaths[:0] = list(libraries)
        compile_c_extension(
            final_env, dest, args.compilation_database, sources, all_headers + ['kitty/data-types.h'], build_dsym=args.build_dsym)


def init_env_from_args(args: Options, native_optimizations: bool = False) -> None:
    global env
    env = init_env(
        args.debug, args.sanitize, native_optimizations, args.link_time_optimization, args.profile,
        args.egl_library, args.startup_notification_library, args.canberra_library, args.systemd_library, args.fontconfig_library,
        args.extra_logging, args.extra_include_dirs, args.ignore_compiler_warnings,
        args.building_arch, args.extra_library_dirs, verbose=args.verbose > 0, vcs_rev=args.vcs_rev,
    )


@lru_cache
def extract_rst_targets() -> Dict[str, Dict[str, str]]:
    m = runpy.run_path('docs/extract-rst-targets.py')
    return cast(Dict[str, Dict[str, str]], m['main']())


def update_if_changed(path: str, text: str) -> None:
    q = ''
    with suppress(FileNotFoundError), open(path) as f:
        q = f.read()
    if q != text:
        with open(path, 'w') as f:
            f.write(text)


def build_ref_map(skip_generation: bool = False) -> str:
    dest = 'kitty/docs_ref_map_generated.h'
    if not skip_generation:
        d = extract_rst_targets()
        h = 'static const char docs_ref_map[] = {\n' + textwrap.fill(', '.join(map(str, bytearray(json.dumps(d, sort_keys=True).encode('utf-8'))))) + '\n};\n'
        update_if_changed(dest, h)
    return dest


def build_cli_parser_specs(skip_generation: bool = False) -> str:
    dest = 'kitty/launcher/cli-parser-data_generated.h'
    if not skip_generation:
        m = runpy.run_path('kitty/simple_cli_definitions.py', {'appname': appname})
        h = '\n'.join(m['generate_c_parsers']())
        update_if_changed(dest, h)
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
    headers.append(build_cli_parser_specs(args.skip_code_generation))
    headers.append(build_uniforms_header(args.skip_code_generation))
    compile_c_extension(
        kitty_env(args), 'kitty/fast_data_types', args.compilation_database, sources, headers,
        build_dsym=args.build_dsym,
    )
    compile_glfw(args.compilation_database, args.build_dsym)
    compile_kittens(args)
    add_builtin_fonts(args)


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
    cp = subprocess.run([kitty_exe, '+launch', os.path.join(src_base, 'gen/go_code.py')], stdout=subprocess.DEVNULL, env=env)
    if cp.returncode != 0:
        if os.environ.get('CI') == 'true' and cp.returncode < 0 and shutil.which('coredumpctl'):
            subprocess.run(['sh', '-c', 'echo bt | coredumpctl debug'])
        raise SystemExit(f'Generating go code failed with exit code: {cp.returncode}')


def parse_go_version(x: str) -> Tuple[int, int, int]:
    def safe_int(x: str) -> int:
        with suppress(ValueError):
            return int(x)
        return int(re.split(r'[-a-zA-Z]', x)[0])
    ans = list(map(safe_int, x.split('.')))
    while len(ans) < 3:
        ans.append(0)
    return ans[0], ans[1], ans[2]


@lru_cache(2)
def go_cmd() -> list[str]:
    go = shutil.which('go')
    if go:
        return [go]
    return []


def build_static_kittens(
    args: Options, launcher_dir: str, destination_dir: str = '', for_freeze: bool = False,
    for_platform: Optional[Tuple[str, str]] = None
) -> str:
    sys.stdout.flush()
    sys.stderr.flush()
    go = go_cmd()
    if not go:
        raise SystemExit('The go tool was not found on this system. Install Go')
    required_go_version = subprocess.check_output(go + 'list -f {{.GoVersion}} -m'.split(), env=dict(os.environ, GO111MODULE="on")).decode().strip()
    go_version_raw = subprocess.check_output(go + ['version']).decode().strip().split()
    if go_version_raw[2] != "devel":
        current_go_version = go_version_raw[2][2:]
    else:
        current_go_version = go_version_raw[3][2:]
    if parse_go_version(required_go_version) > parse_go_version(current_go_version):
        raise SystemExit(f'The version of go on this system ({current_go_version}) is too old. go >= {required_go_version} is needed')
    if not for_platform:
        update_go_generated_files(args, os.path.join(launcher_dir, appname))
    if args.skip_building_kitten:
        print('Skipping building of the kitten binary because of a command line option. Build is incomplete', file=sys.stderr)
        return ''
    cmd = go + ['build', '-v']
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

    def run_one(dest: str) -> None:
        c = cmd + ['-o', dest, src]
        if args.verbose:
            print(shlex.join(c))
        e = os.environ.copy()
        # https://github.com/kovidgoyal/kitty/issues/6051#issuecomment-1441369828
        e.pop('PWD', None)
        if for_platform:
            e['CGO_ENABLED'] = '0'
            e['GOOS'] = for_platform[0]
            e['GOARCH'] = for_platform[1]
        elif args.building_arch:
            e['GOARCH'] = {'x86_64': 'amd64', 'arm64': 'arm64'}[args.building_arch]
        cp = subprocess.run(c, env=e)
        if cp.returncode != 0:
            raise SystemExit(cp.returncode)

    if is_macos and for_freeze and not for_platform:
        adests = []
        for arch in macos_universal_arches:
            args.building_arch = arch
            adest = dest + '-' + arch
            adests.append(adest)
            run_one(adest)
        lipo({dest: adests})
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


def read_bool_options(path: str = 'kitty/cli.py') -> Tuple[str, ...]:
    with open(os.path.join(src_base, path)) as f:
        raw = f.read()
    m = re.search(r"^\s*OPTIONS = r?'''(.+?)'''", raw, flags=re.MULTILINE | re.DOTALL)
    assert m is not None
    ans: List[str] = []
    in_option: List[str] = []
    prev_line_was_blank = False
    for line in m.group(1).splitlines():
        if in_option:
            is_blank = not line.strip()
            if is_blank:
                if prev_line_was_blank:
                    in_option = []
            prev_line_was_blank = is_blank
            if line.startswith('type=bool-'):
                ans.extend(x.lstrip('-') for x in in_option)
        else:
            if line.startswith('-'):
                in_option = line.strip().split()
    return tuple(ans)


def build_launcher(args: Options, launcher_dir: str = '.', bundle_type: str = 'source') -> str:
    werror = '' if args.ignore_compiler_warnings else '-pedantic-errors -Werror'
    cflags = f'-Wall {werror} -fpie {c_std}'.strip().split()
    cppflags = [define(f'WRAPPED_KITTENS=" {wrapped_kittens()} "')]
    ldflags = shlex.split(os.environ.get('LDFLAGS', ''))
    xxhash = xxhash_flags()
    cppflags.extend(xxhash[0])
    libs: list[str] = xxhash[1]
    if args.profile or args.sanitize:
        cflags.append('-g3')
        if args.sanitize:
            sanitize_args = get_sanitize_args(env.cc, env.ccver)
            cflags.extend(sanitize_args)
            ldflags.extend(sanitize_args)
            libs += ['-lasan'] if not is_macos and env.compiler_type is not CompilerType.clang else []
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
    if args.building_arch:
        set_arches(cflags, args.building_arch)
        set_arches(ldflags, args.building_arch)
    if bundle_type == 'linux-freeze':
        # --disable-new-dtags prevents -rpath from generating RUNPATH instead of
        # RPATH entries in the launcher. The ld dynamic linker does not search
        # RUNPATH locations for transitive dependencies, unlike RPATH.
        ldflags += ['-Wl,--disable-new-dtags', '-Wl,-rpath,$ORIGIN/../lib']
    os.makedirs(launcher_dir, exist_ok=True)
    os.makedirs(build_dir, exist_ok=True)
    objects = []
    headers = glob.glob('kitty/launcher/*.h')
    cppflags.append('-DKITTY_VERSION="' + '.'.join(map(str, version)) + '"')
    for src in ('kitty/launcher/main.c', 'kitty/launcher/single-instance.c', 'kitty/launcher/cmdline.c'):
        obj = os.path.join(build_dir, src.replace('/', '-').replace('.c', '.o'))
        objects.append(obj)
        cmd = env.cc + cppflags + cflags + ['-c', src, '-o', obj]
        key = CompileKey(src, os.path.basename(obj))
        args.compilation_database.add_command(
            f'Compiling {emphasis(src)} ...', cmd, partial(newer, obj, src, *dependecies_for(src, obj, headers)), key=key, keyfile=src)
    dest = kitty_exe = os.path.join(launcher_dir, 'kitty')
    link_targets.append(os.path.abspath(dest))
    desc = f'Linking {emphasis("launcher")} ...'
    cmd = env.cc + ldflags + objects + libs + pylib + ['-o', dest]
    args.compilation_database.add_command(desc, cmd, partial(newer, dest, *objects), key=LinkKey('kitty'))
    if args.build_dsym and is_macos:
        desc = f'Linking dSYM {emphasis("launcher")} ...'
        dsym = f'{dest}.dSYM/Contents/Resources/DWARF/{os.path.basename(dest)}'
        args.compilation_database.add_command(desc, ['dsymutil', dest], partial(newer, dsym, dest), key=LinkKey(dsym), is_post_link=True)
    args.compilation_database.build_all()
    return kitty_exe


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
StartupNotify=true
Exec=kitty
Icon=kitty
Categories=System;TerminalEmulator;
X-TerminalArgExec=--
X-TerminalArgTitle=--title
X-TerminalArgAppId=--class
X-TerminalArgDir=--working-directory
X-TerminalArgHold=--hold
''')
    with open(os.path.join(deskdir, 'kitty-open.desktop'), 'w') as f:
        f.write(
            '''\
[Desktop Entry]
Version=1.0
Type=Application
Name=kitty URL Launcher
GenericName=Terminal emulator
Comment=Open URLs with kitty
StartupNotify=true
TryExec=kitty
Exec=kitty +open %U
Icon=kitty
Categories=System;TerminalEmulator;
NoDisplay=true
MimeType=image/*;application/x-sh;application/x-shellscript;inode/directory;text/*;x-scheme-handler/kitty;x-scheme-handler/ssh;
''')

    if os.path.exists(in_src_launcher):
        os.remove(in_src_launcher)
    os.makedirs(os.path.dirname(in_src_launcher), exist_ok=True)
    os.symlink(os.path.relpath(launcher, os.path.dirname(in_src_launcher)), in_src_launcher)


def macos_info_plist(for_quake: str = '') -> bytes:
    import plistlib
    VERSION = '.'.join(map(str, version))

    def access(what: str, verb: str = 'would like to access') -> str:
        return f'A program running inside kitty {verb} {what}'

    docs = [] if for_quake else [
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

    url_schemes = [] if for_quake else [
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
            'NSMenuItem': {'default': for_quake},
            'NSMessage': 'quickAccessTerminal',
            'NSRequiredContext': {'NSServiceCategory': 'None'},
        },
    ] if for_quake else [
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
        CFBundleName=f'{appname}-quick-access' if for_quake else appname,
        CFBundleDisplayName=f'{appname}-quick-access' if for_quake else appname,
        # Identification
        CFBundleIdentifier=f'net.kovidgoyal.{appname}' + ('-quick-access' if for_quake else ''),
        # Bundle Version Info
        CFBundleVersion=VERSION,
        CFBundleShortVersionString=VERSION,
        CFBundleInfoDictionaryVersion='6.0',
        NSHumanReadableCopyright=time.strftime('Copyright %Y, Kovid Goyal'),
        CFBundleGetInfoString='kitty - The fast, feature-rich, GPU based terminal emulator. https://sw.kovidgoyal.net/kitty/',
        # Operating System Version
        LSMinimumSystemVersion='11.0.0',
        # Categorization
        CFBundlePackageType='APPL',
        CFBundleSignature='????',
        LSApplicationCategoryType='public.app-category.utilities',
        # App Execution
        CFBundleExecutable=quake_name if for_quake else appname,
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
    if for_quake:
        # exclude from dock and menubar
        pl['LSBackgroundOnly'] = True
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


quake_name = f'{appname}-quick-access'


def create_quick_access_bundle(kapp: str, quake_desc: str = 'Quick access to kitty') -> None:
    qapp = os.path.join(kapp, 'Contents', f'{quake_name}.app')
    base_exe_dir = os.path.join(kapp, 'Contents/MacOS')
    if os.path.exists(qapp):
        shutil.rmtree(qapp)
    bin_dir = os.path.join(qapp, 'Contents/MacOS')
    os.makedirs(bin_dir)
    with open(os.path.join(qapp, 'Contents/Info.plist'), 'wb') as f:
        f.write(macos_info_plist(quake_desc))
    for exe in os.listdir(base_exe_dir):
        os.symlink(f'../../../MacOS/{exe}', os.path.join(bin_dir, exe))
    base_exe = os.path.join(base_exe_dir, 'kitty')
    if os.path.exists(base_exe):  # during freeze launcher is built after bundle is created
        shutil.copy2(base_exe, os.path.join(bin_dir, quake_name))
    for x in ('Frameworks', 'Resources'):
        os.symlink(f'../../{x}', os.path.join(qapp, 'Contents', x))


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
    create_quick_access_bundle(kapp, 'Quick access to kitty built from source')


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
    create_quick_access_bundle(dest)
    return str(kitty_exe)


def package(args: Options, bundle_type: str, do_build_all: bool = True) -> None:
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
        if do_build_all:
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
    shutil.copytree('fonts', os.path.join(libdir, 'fonts'), dirs_exist_ok=True)
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
            tname = 'frozenset[str]'
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
    if not is_macos and not is_windows:
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
        'kitty-profile')  # no fonts as that is not generated by build
    if not for_cross_compile:
        safe_remove('docs/generated')
    clean_launcher_dir('kitty/launcher')

    def excluded(root: str, d: str) -> bool:
        q = os.path.relpath(os.path.join(root, d), src_base).replace(os.sep, '/')
        return q in ('.git', 'bypy/b', 'dependencies')

    def is_generated(f: str) -> bool:
        e = f.endswith
        return (
            e('_generated.h') or e('_generated.go') or e('_generated.bin') or
            e('_generated.s') or e('_generated_test.s') or e('_generated_test.go')
        )

    for root, dirs, files in os.walk(src_base, topdown=True):
        dirs[:] = [d for d in dirs if not excluded(root, d)]
        remove_dirs = {d for d in dirs if d == '__pycache__' or d.endswith('.dSYM')}
        for d in remove_dirs:
            shutil.rmtree(os.path.join(root, d))
            dirs.remove(d)
        for f in files:
            ext = f.rpartition('.')[-1]
            if ext in ('so', 'pyc', 'pyo', 'pyd', 'dylib') or (not for_cross_compile and is_generated(f)):
                os.unlink(os.path.join(root, f))
    for x in glob.glob('glfw/wayland-*-protocol.[ch]'):
        os.unlink(x)
    for x in glob.glob('kittens/*'):
        if os.path.isdir(x) and not os.path.exists(os.path.join(x, '__init__.py')):
            shutil.rmtree(x)
    if go := go_cmd():
        subprocess.check_call(go + ['clean', '-cache', '-testcache', '-modcache', '-fuzzcache'])


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
        '--systemd-library',
        type=str,
        default=Options.systemd_library,
        help='The filename argument passed to dlopen for libsystemd.'
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
        '--build-dSYM', dest='build_dsym',
        default=Options.build_dsym, action='store_true',
        help='Build the dSYM bundle on macOS, ignored on other platforms'
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
        choices='all macos linux linux-arm64 linux-64'.split(),
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


def lipo(target_map: Dict[str, List[str]]) -> None:
    print(f'Using lipo to generate {len(target_map)} universal binaries...')
    for dest, inputs in target_map.items():
        cmd = ['lipo', '-create', '-output', dest] + inputs
        subprocess.check_call(cmd)
        for x in inputs:
            os.remove(x)


def macos_freeze(args: Options, launcher_dir: str, only_frozen_launcher: bool = False) -> None:
    global build_dir
    # Need to build a universal binary in two stages
    orig_build_dir = build_dir
    link_target_map: Dict[str, List[str]] = {}
    bundle_type = 'macos-freeze'
    for arch in macos_universal_arches:
        args.building_arch = arch
        build_dir = os.path.join(orig_build_dir, arch)
        os.makedirs(build_dir, exist_ok=True)
        print('Building for arch:', arch, 'in', build_dir)
        if arch is not macos_universal_arches[0]:
            args.skip_code_generation = True  # cant run kitty as its not a native arch
        link_targets.clear()
        with CompilationDatabase() as cdb:
            args.compilation_database = cdb
            init_env_from_args(args, native_optimizations=False)
            if only_frozen_launcher:
                kitty_exe_path = build_launcher(args, launcher_dir=launcher_dir, bundle_type=bundle_type)
            else:
                build_launcher(args, launcher_dir=launcher_dir)
                build(args, native_optimizations=False, call_init=False)
            cdb.build_all()
        for x in link_targets:
            arch_specific = x + '-' + arch
            link_target_map.setdefault(x, []).append(arch_specific)
            os.rename(x, arch_specific)
    build_dir = orig_build_dir
    lipo(link_target_map)
    if only_frozen_launcher:
        if is_macos:
            shutil.copy2(kitty_exe_path, os.path.dirname(kitty_exe_path) + f'/../Contents/{quake_name}.app/Contents/MacOS/{quake_name}')
    else:
        package(args, bundle_type=bundle_type, do_build_all=False)


def do_build(args: Options) -> None:
    launcher_dir = 'kitty/launcher'

    if args.action == 'test':
        texe = os.path.abspath(os.path.join(launcher_dir, 'kitty'))
        os.execl(texe, texe, '+launch', 'test.py')
    if args.action == 'clean':
        clean(for_cross_compile=args.clean_for_cross_compile)
        return
    if args.action == 'macos-freeze':
        return macos_freeze(args, launcher_dir)
    if args.action == 'build-frozen-launcher' and is_macos:
        launcher_dir=os.path.join(args.prefix, 'bin')
        return macos_freeze(args, launcher_dir, only_frozen_launcher=True)

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


def main() -> None:
    global verbose, build_dir
    if len(sys.argv) > 1 and sys.argv[1] == 'build-dep':
        return build_dep()
    args = option_parser().parse_args(namespace=Options())
    verbose = args.verbose > 0
    args.prefix = os.path.abspath(args.prefix)
    os.chdir(src_base)
    os.makedirs(build_dir, exist_ok=True)
    do_build(args)


if __name__ == '__main__':
    main()
