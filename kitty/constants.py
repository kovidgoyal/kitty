#!/usr/bin/env python3
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import errno
import os
import pwd
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any, FrozenSet, Iterator, NamedTuple, Optional, Set

from .types import run_once

if TYPE_CHECKING:
    from .options.types import Options


class Version(NamedTuple):
    major: int
    minor: int
    patch: int


appname: str = 'kitty'
kitty_face = '🐱'
version: Version = Version(0, 29, 1)
str_version: str = '.'.join(map(str, version))
_plat = sys.platform.lower()
is_macos: bool = 'darwin' in _plat
is_freebsd: bool = 'freebsd' in _plat
is_running_from_develop: bool = False
RC_ENCRYPTION_PROTOCOL_VERSION = '1'
website_base_url = 'https://sw.kovidgoyal.net/kitty/'
default_pager_for_help = ('less', '-iRXF')
if getattr(sys, 'frozen', False):
    extensions_dir: str = getattr(sys, 'kitty_run_data')['extensions_dir']

    def get_frozen_base() -> str:
        global is_running_from_develop
        try:
            from bypy_importer import running_in_develop_mode  # type: ignore
        except ImportError:
            pass
        else:
            is_running_from_develop = running_in_develop_mode()

        if is_running_from_develop:
            q = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            try:
                if os.path.isdir(q):
                    return q
            except OSError:
                pass
        ans = os.path.dirname(extensions_dir)
        if is_macos:
            ans = os.path.dirname(os.path.dirname(ans))
        ans = os.path.join(ans, 'kitty')
        return ans
    kitty_base_dir = get_frozen_base()
    del get_frozen_base
else:
    kitty_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extensions_dir = os.path.join(kitty_base_dir, 'kitty')


@run_once
def kitty_exe() -> str:
    rpath = getattr(sys, 'kitty_run_data').get('bundle_exe_dir')
    if not rpath:
        items = os.environ.get('PATH', '').split(os.pathsep) + [os.path.join(kitty_base_dir, 'kitty', 'launcher')]
        seen: Set[str] = set()
        for candidate in filter(None, items):
            if candidate not in seen:
                seen.add(candidate)
                if os.access(os.path.join(candidate, 'kitty'), os.X_OK):
                    rpath = candidate
                    break
        else:
            raise RuntimeError('kitty binary not found')
    return os.path.join(rpath, 'kitty')


@run_once
def kitten_exe() -> str:
    return os.path.join(os.path.dirname(kitty_exe()), 'kitten')


def _get_config_dir() -> str:
    if 'KITTY_CONFIG_DIRECTORY' in os.environ:
        return os.path.abspath(os.path.expanduser(os.environ['KITTY_CONFIG_DIRECTORY']))

    locations = []
    if 'XDG_CONFIG_HOME' in os.environ:
        locations.append(os.path.abspath(os.path.expanduser(os.environ['XDG_CONFIG_HOME'])))
    locations.append(os.path.expanduser('~/.config'))
    if is_macos:
        locations.append(os.path.expanduser('~/Library/Preferences'))
    for loc in filter(None, os.environ.get('XDG_CONFIG_DIRS', '').split(os.pathsep)):
        locations.append(os.path.abspath(os.path.expanduser(loc)))
    for loc in locations:
        if loc:
            q = os.path.join(loc, appname)
            if os.access(q, os.W_OK) and os.path.exists(os.path.join(q, 'kitty.conf')):
                return q

    def make_tmp_conf() -> None:
        import atexit
        import tempfile
        ans = tempfile.mkdtemp(prefix='kitty-conf-')

        def cleanup() -> None:
            import shutil
            with suppress(Exception):
                shutil.rmtree(ans)
        atexit.register(cleanup)

    candidate = os.path.abspath(os.path.expanduser(os.environ.get('XDG_CONFIG_HOME') or '~/.config'))
    ans = os.path.join(candidate, appname)
    try:
        os.makedirs(ans, exist_ok=True)
    except FileExistsError:
        raise SystemExit(f'A file {ans} already exists. It must be a directory, not a file.')
    except PermissionError:
        make_tmp_conf()
    except OSError as err:
        if err.errno != errno.EROFS:  # Error other than read-only file system
            raise
        make_tmp_conf()
    return ans


config_dir = _get_config_dir()
del _get_config_dir
defconf = os.path.join(config_dir, 'kitty.conf')


@run_once
def cache_dir() -> str:
    if 'KITTY_CACHE_DIRECTORY' in os.environ:
        candidate = os.path.abspath(os.environ['KITTY_CACHE_DIRECTORY'])
    elif is_macos:
        candidate = os.path.join(os.path.expanduser('~/Library/Caches'), appname)
    else:
        candidate = os.environ.get('XDG_CACHE_HOME', '~/.cache')
        candidate = os.path.join(os.path.expanduser(candidate), appname)
    os.makedirs(candidate, exist_ok=True)
    return candidate


@run_once
def runtime_dir() -> str:
    if 'KITTY_RUNTIME_DIRECTORY' in os.environ:
        candidate = os.path.abspath(os.environ['KITTY_RUNTIME_DIRECTORY'])
    elif is_macos:
        from .fast_data_types import user_cache_dir
        candidate = user_cache_dir()
    elif 'XDG_RUNTIME_DIR' in os.environ:
        candidate = os.path.abspath(os.environ['XDG_RUNTIME_DIR'])
    else:
        candidate = f'/run/user/{os.geteuid()}'
        if not os.path.isdir(candidate) or not os.access(candidate, os.X_OK | os.W_OK | os.R_OK):
            candidate = os.path.join(cache_dir(), 'run')
    os.makedirs(candidate, exist_ok=True)
    import stat
    if stat.S_IMODE(os.stat(candidate).st_mode) != 0o700:
        os.chmod(candidate, 0o700)
    return candidate


def wakeup_io_loop() -> None:
    from .fast_data_types import get_boss
    b = get_boss()
    if b is not None:
        b.child_monitor.wakeup()


terminfo_dir = os.path.join(kitty_base_dir, 'terminfo')
logo_png_file = os.path.join(kitty_base_dir, 'logo', 'kitty.png')
beam_cursor_data_file = os.path.join(kitty_base_dir, 'logo', 'beam-cursor.png')
shell_integration_dir = os.path.join(kitty_base_dir, 'shell-integration')
try:
    shell_path = pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'
except KeyError:
    with suppress(Exception):
        print('Failed to read login shell via getpwuid() for current user, falling back to /bin/sh', file=sys.stderr)
    shell_path = '/bin/sh'
# Keep this short as it is limited to 103 bytes on macOS
# https://github.com/ansible/ansible/issues/11536#issuecomment-153030743
ssh_control_master_template = 'kssh-{kitty_pid}-{ssh_placeholder}'


def glfw_path(module: str) -> str:
    prefix = 'kitty.' if getattr(sys, 'frozen', False) else ''
    return os.path.join(extensions_dir, f'{prefix}glfw-{module}.so')


def detect_if_wayland_ok() -> bool:
    if 'WAYLAND_DISPLAY' not in os.environ:
        return False
    if 'KITTY_DISABLE_WAYLAND' in os.environ:
        return False
    wayland = glfw_path('wayland')
    if not os.path.exists(wayland):
        return False
    return True


def is_wayland(opts: Optional['Options'] = None) -> bool:
    if is_macos:
        return False
    if opts is None:
        return bool(getattr(is_wayland, 'ans'))
    if opts.linux_display_server == 'auto':
        ans = detect_if_wayland_ok()
    else:
        ans = opts.linux_display_server == 'wayland'
    setattr(is_wayland, 'ans', ans)
    return ans


supports_primary_selection = not is_macos


def running_in_kitty(set_val: Optional[bool] = None) -> bool:
    if set_val is not None:
        setattr(running_in_kitty, 'ans', set_val)
    return bool(getattr(running_in_kitty, 'ans', False))


def list_kitty_resources(package: str = 'kitty') -> Iterator[str]:
    try:
        if sys.version_info[:2] < (3, 10):
            raise ImportError("importlib.resources.files() doesn't work with frozen builds on python 3.9")
        from importlib.resources import files
    except ImportError:
        from importlib.resources import contents
        return iter(contents(package))
    else:
        return (path.name for path in files(package).iterdir())


def read_kitty_resource(name: str, package_name: str = 'kitty') -> bytes:
    try:
        if sys.version_info[:2] < (3, 10):
            raise ImportError("importlib.resources.files() doesn't work with frozen builds on python 3.9")
        from importlib.resources import files
    except ImportError:
        from importlib.resources import read_binary
        return read_binary(package_name, name)
    else:
        return (files(package_name) / name).read_bytes()


def website_url(doc_name: str = '', website: str = website_base_url) -> str:
    if doc_name:
        base, _, frag = doc_name.partition('#')
        base = base.rstrip('/')
        if base:
            base += '/'
        doc_name = base + (f'#{frag}' if frag else '')
    return website + doc_name.lstrip('/')


handled_signals: Set[int] = set()


def clear_handled_signals(*a: Any) -> None:
    if not handled_signals:
        return
    import signal
    if hasattr(signal, 'pthread_sigmask'):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, handled_signals)
    for s in handled_signals:
        signal.signal(s, signal.SIG_DFL)


@run_once
def local_docs() -> str:
    d = os.path.dirname
    base = d(d(kitty_exe()))
    from_source = getattr(sys, 'kitty_run_data').get('from_source')
    if is_macos and from_source and '/kitty.app/Contents/' in kitty_exe():
        base = d(d(d(base)))
    subdir = os.path.join('doc', 'kitty', 'html')
    linux_ans = os.path.join(base, 'share', subdir)
    if getattr(sys, 'frozen', False):
        if is_macos:
            return os.path.join(d(d(d(extensions_dir))), subdir)
        return linux_ans
    if os.path.isdir(linux_ans):
        return linux_ans
    if from_source:
        sq = os.path.join(d(base), 'docs', '_build', 'html')
        if os.path.isdir(sq):
            return sq
    for candidate in ('/usr', '/usr/local', '/opt/homebrew'):
        q = os.path.join(candidate, 'share', subdir)
        if os.path.isdir(q):
            return q
    return ''


@run_once
def wrapped_kitten_names() -> FrozenSet[str]:
    import kitty.fast_data_types as f
    return frozenset(f.wrapped_kitten_names())
