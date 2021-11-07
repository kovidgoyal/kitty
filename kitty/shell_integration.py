#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
from contextlib import suppress
from typing import Optional, Union, Dict

from .options.types import Options
from .config import atomic_save
from .constants import shell_integration_dir
from .utils import log_error, resolved_shell

posix_template = '''
# BEGIN_KITTY_SHELL_INTEGRATION
if test -e {path}; then source {path}; fi
# END_KITTY_SHELL_INTEGRATION
'''


def atomic_write(path: str, data: Union[str, bytes]) -> None:
    if isinstance(data, str):
        data = data.encode('utf-8')
    atomic_save(data, path)


def safe_read(path: str) -> str:
    with suppress(FileNotFoundError):
        with open(path) as f:
            return f.read()
    return ''


def setup_integration(shell_name: str, rc_path: str, template: str = posix_template) -> None:
    import re
    rc_path = os.path.realpath(rc_path)
    rc = safe_read(rc_path)
    home = os.path.expanduser('~') + '/'
    path = os.path.join(shell_integration_dir, f'kitty.{shell_name}')
    if path.startswith(home):
        path = '$HOME/' + path[len(home):]
    integration = template.format(path=f'"{path}"')
    newrc = re.sub(
        r'^# BEGIN_KITTY_SHELL_INTEGRATION.+?^# END_KITTY_SHELL_INTEGRATION',
        '', rc, flags=re.DOTALL | re.MULTILINE)
    newrc = newrc.rstrip() + '\n\n' + integration
    if newrc != rc:
        atomic_write(rc_path, newrc)


def setup_zsh_integration(env: Dict[str, str]) -> None:
    base = os.environ.get('ZDOTDIR', os.path.expanduser('~'))
    rc = os.path.join(base, '.zshrc')
    if os.path.exists(rc):  # dont prevent zsh-newuser-install from running
        setup_integration('zsh', rc)


def setup_bash_integration(env: Dict[str, str]) -> None:
    setup_integration('bash', os.path.expanduser('~/.bashrc'))


def setup_fish_integration(env: Dict[str, str]) -> None:
    pass  # this is handled in the fish env modifier


def setup_fish_env(env: Dict[str, str]) -> None:
    val = env.get('XDG_DATA_DIRS')
    if val is None:
        env['XDG_DATA_DIRS'] = shell_integration_dir
    elif not val:
        env['XDG_DATA_DIRS'] = shell_integration_dir
        env['KITTY_FISH_XDG_DATA_DIRS'] = ''
    else:
        dirs = list(filter(None, val.split(os.pathsep)))
        dirs.insert(0, shell_integration_dir)
        env['KITTY_FISH_XDG_DATA_DIRS'] = val
        env['XDG_DATA_DIRS'] = os.pathsep.join(dirs)


SUPPORTED_SHELLS = {
    'zsh': setup_zsh_integration,
    'bash': setup_bash_integration,
    'fish': setup_fish_integration,
}
ENV_MODIFIERS = {
    'fish': setup_fish_env
}


def get_supported_shell_name(path: str) -> Optional[str]:
    name = os.path.basename(path).split('.')[0].lower()
    if name in SUPPORTED_SHELLS:
        return name
    return None


def shell_integration_allows_rc_modification(opts: Options) -> bool:
    q = set(opts.shell_integration.split())
    if q & {'disabled', 'no-rc'}:
        return False
    return True


def setup_shell_integration(opts: Options, env: Dict[str, str]) -> bool:
    if not shell_integration_allows_rc_modification(opts):
        return False
    shell = get_supported_shell_name(resolved_shell(opts)[0])
    if shell is None:
        return False
    func = SUPPORTED_SHELLS[shell]
    try:
        func(env)
    except Exception:
        import traceback
        traceback.print_exc()
        log_error(f'Failed to setup shell integration for: {shell}')
        return False
    return True


def modify_shell_environ(argv0: str, opts: Options, env: Dict[str, str]) -> None:
    if 'disabled' in set(opts.shell_integration.split()):
        return
    env['KITTY_SHELL_INTEGRATION'] = opts.shell_integration
    if not shell_integration_allows_rc_modification(opts):
        return
    shell = get_supported_shell_name(argv0)
    if shell is None:
        return
    f = ENV_MODIFIERS.get(shell)
    if f is not None:
        try:
            f(env)
        except Exception:
            import traceback
            traceback.print_exc()
            log_error(f'Failed to setup shell integration for: {shell}')
    return
