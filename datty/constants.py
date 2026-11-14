#!/usr/bin/env python
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import os
import pwd
import sys
from collections.abc import Iterator
from contextlib import suppress
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from .types import run_once

if TYPE_CHECKING:
    from .options.types import Options


class Version(NamedTuple):
    major: int
    minor: int
    patch: int


appname: str = 'datty'
datty_face = '🐱'
version: Version = Version(0, 50, 0)
str_version: str = '.'.join(map(str, version))
_plat = sys.platform.lower()
is_macos: bool = 'darwin' in _plat
is_freebsd: bool = 'freebsd' in _plat
is_running_from_develop: bool = False
RC_ENCRYPTION_PROTOCOL_VERSION = '1'
website_base_url = 'https://sw.kovidgoyal.net/datty/'
default_pager_for_help = ('less', '-iRXF')
datty_run_data: dict[str, Any] = getattr(sys, 'datty_run_data', {})
launched_by_launch_services = datty_run_data.get('launched_by_launch_services', False)
is_quick_access_terminal_app = datty_run_data.get('is_quick_access_terminal_app', False)
unserialize_launch_flag = 'datty-unserialize-data='
_slangc: tuple[str, ...] = ()


def slangc() -> tuple[str, ...]:
    global _slangc
    if not _slangc:
        from datty.fast_data_types import DEVELOP_ROOT, Shlex

        if DEVELOP_ROOT:
            _slangc = (os.path.join(DEVELOP_ROOT, 'bin', 'slangc'),)
        else:
            _slangc = tuple(Shlex(os.environ.get('SLANGC', 'slangc'), False))
    return _slangc


if getattr(sys, 'frozen', False):
    extensions_dir: str = datty_run_data['extensions_dir']

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
        ans = os.path.join(ans, 'datty')
        return ans

    datty_base_dir = get_frozen_base()
    if rpath := datty_run_data.get('bundle_exe_dir'):
        _slangc = (os.path.join(rpath, 'slangc'),)
    del get_frozen_base, rpath
else:
    datty_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extensions_dir = os.path.join(datty_base_dir, 'datty')


@run_once
def datty_exe() -> str:
    rpath = datty_run_data.get('bundle_exe_dir')
    if not rpath:
        items = os.environ.get('PATH', '').split(os.pathsep) + [os.path.join(datty_base_dir, 'datty', 'launcher')]
        seen: set[str] = set()
        for candidate in filter(None, items):
            if candidate not in seen:
                seen.add(candidate)
                if os.access(os.path.join(candidate, 'datty'), os.X_OK):
                    rpath = candidate
                    break
        else:
            raise RuntimeError('datty binary not found')
    return os.path.join(rpath, 'datty')


@run_once
def daddy_exe() -> str:
    return os.path.join(os.path.dirname(datty_exe()), 'daddy')


def _get_config_dir() -> str:
    cdir = datty_run_data.get('config_dir', '')
    if cdir:
        return str(cdir)
    import atexit
    import tempfile

    ans = tempfile.mkdtemp(prefix='datty-conf-')

    def cleanup() -> None:
        import shutil

        with suppress(Exception):
            shutil.rmtree(ans)

    atexit.register(cleanup)
    return ans


config_dir = _get_config_dir()
del _get_config_dir
defconf = os.path.join(config_dir, 'datty.conf')
# When True, auxiliary files in config_dir that datty loads implicitly, such as
# the automatic color theme files, open-actions.conf, etc. are ignored. Set when
# datty is run with --config=NONE.
_ignore_config_dir_files = False


def set_ignore_config_dir_files(val: bool) -> None:
    global _ignore_config_dir_files
    _ignore_config_dir_files = val


def config_dir_files_ignored() -> bool:
    return _ignore_config_dir_files


@run_once
def cache_dir() -> str:
    if 'DATTY_CACHE_DIRECTORY' in os.environ:
        candidate = os.path.abspath(os.environ['DATTY_CACHE_DIRECTORY'])
    elif is_macos:
        candidate = os.path.join(os.path.expanduser('~/Library/Caches'), appname)
    else:
        candidate = os.environ.get('XDG_CACHE_HOME', '~/.cache')
        candidate = os.path.join(os.path.expanduser(candidate), appname)
    os.makedirs(candidate, exist_ok=True)
    return candidate


@run_once
def runtime_dir() -> str:
    if 'DATTY_RUNTIME_DIRECTORY' in os.environ:
        candidate = os.path.abspath(os.environ['DATTY_RUNTIME_DIRECTORY'])
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


terminfo_dir = os.path.join(datty_base_dir, 'terminfo')
logo_png_file = os.path.join(datty_base_dir, 'logo', 'datty.png')
beam_cursor_data_file = os.path.join(datty_base_dir, 'logo', 'beam-cursor.png')
shell_integration_dir = os.path.join(datty_base_dir, 'shell-integration')
fonts_dir = os.path.join(datty_base_dir, 'fonts')
shaders_dir = os.path.join(datty_base_dir, 'shaders')
try:
    shell_path = os.environ.get('SHELL') or pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh'
except KeyError:
    with suppress(Exception):
        print('Failed to read login shell via getpwuid() for current user, falling back to /bin/sh', file=sys.stderr)
    shell_path = '/bin/sh'
# Keep this short as it is limited to 103 bytes on macOS
# https://github.com/ansible/ansible/issues/11536#issuecomment-153030743
ssh_control_master_template = 'kssh-{datty_pid}-{ssh_placeholder}'

# See https://specifications.freedesktop.org/icon-naming-spec/latest/ar01s04.html
# Update the spec in docs/desktop-notifications.rst if you change this.
standard_icon_names = {
    'error': ('dialog-error', '☠'),
    'warning': ('dialog-warning', '⚠'),
    'warn': ('dialog-warning', '⚠'),
    'info': ('dialog-information', 'ℹ'),
    'question': ('dialog-question', '❔'),
    'help': ('system-help', '📖'),
    'file-manager': ('system-file-manager', '🗄'),
    'system-monitor': ('utilities-system-monitor', '🎛'),
    'text-editor': ('utilities-text-editor', '📄'),
}

# See https://github.com/TUNER88/iOSSystemSoundsLibrary for Apple's system
# sound ids not all of which are available on macOS.
standard_sound_names = {
    'error': ('dialog-error', 1),
    'info': ('dialog-information', 2),
    'warning': ('dialog-warning', 3),
    'warn': ('dialog-warning', 3),
    'question': ('dialog-question', 4),
}


def glfw_path(module: str) -> str:
    prefix = 'datty.' if getattr(sys, 'frozen', False) else ''
    return os.path.join(extensions_dir, f'{prefix}glfw-{module}.so')


def detect_if_wayland_ok() -> bool:
    if not os.environ.get('WAYLAND_DISPLAY') and not os.environ.get('WAYLAND_SOCKET'):
        return False
    if os.environ.get('DATTY_DISABLE_WAYLAND'):
        return False
    wayland = glfw_path('wayland')
    if not os.path.exists(wayland):
        return False
    import ctypes

    with suppress(Exception):
        setattr(detect_if_wayland_ok, 'keep_module_loaded', ctypes.CDLL(wayland))
        return True
    return False


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


def running_in_datty(set_val: bool | None = None) -> bool:
    if set_val is not None:
        setattr(running_in_datty, 'ans', set_val)
    return bool(getattr(running_in_datty, 'ans', False))


def list_datty_resources(package: str = 'datty') -> Iterator[str]:
    from importlib.resources import files

    return (path.name for path in files(package).iterdir())


def read_datty_resource(name: str, package_name: str = 'datty') -> bytes:
    from importlib.resources import files

    return (files(package_name) / name).read_bytes()


def website_url(doc_name: str = '', website: str = website_base_url) -> str:
    if doc_name:
        base, _, frag = doc_name.partition('#')
        base = base.rstrip('/')
        if base:
            base += '/'
        doc_name = base + (f'#{frag}' if frag else '')
    return website + doc_name.lstrip('/')


handled_signals: set[int] = set()


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
    base = d(d(datty_exe()))
    from_source = datty_run_data.get('from_source')
    if is_macos and from_source and '/datty.app/Contents/' in datty_exe():
        base = d(d(d(base)))
    subdir = os.path.join('doc', 'datty', 'html')
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
def wrapped_daddy_names() -> frozenset[str]:
    import datty.fast_data_types as f

    return frozenset(f.wrapped_daddy_names())


_supports_window_occlusion = False


def supports_window_occlusion(set: bool | None = None) -> bool:
    global _supports_window_occlusion
    if set is not None:
        _supports_window_occlusion = set
    return _supports_window_occlusion
