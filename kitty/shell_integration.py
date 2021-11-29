#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
from contextlib import suppress
from typing import Dict, Optional, Set, Union

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
    pass  # this is handled in the zsh env modifier


def setup_bash_integration(env: Dict[str, str]) -> None:
    setup_integration('bash', os.path.expanduser('~/.bashrc'))


def setup_fish_integration(env: Dict[str, str]) -> None:
    pass  # this is handled in the fish env modifier


def setup_fish_env(env: Dict[str, str]) -> None:
    val = env.get('XDG_DATA_DIRS')
    env['KITTY_FISH_XDG_DATA_DIR'] = shell_integration_dir
    if not val:
        env['XDG_DATA_DIRS'] = shell_integration_dir
    else:
        dirs = list(filter(None, val.split(os.pathsep)))
        dirs.insert(0, shell_integration_dir)
        env['XDG_DATA_DIRS'] = os.pathsep.join(dirs)


def is_new_zsh_install() -> bool:
    zdotdir = os.environ.get('ZDOTDIR')
    base = zdotdir or os.path.expanduser('~')
    for q in ('.zshrc', '.zshenv', '.zprofile', '.zlogin'):
        if os.path.exists(os.path.join(base, q)):
            return False
    return True


def setup_zsh_env(env: Dict[str, str]) -> None:
    zdotdir = os.environ.get('ZDOTDIR')
    base = zdotdir or os.path.expanduser('~')
    if is_new_zsh_install():
        # dont prevent zsh-newuser-install from running
        return
    if zdotdir is not None:
        env['KITTY_ORIG_ZDOTDIR'] = zdotdir
    env['KITTY_ZSH_BASE'] = base
    env['ZDOTDIR'] = os.path.join(shell_integration_dir, 'zsh')


SUPPORTED_SHELLS = {
    'zsh': setup_zsh_integration,
    'bash': setup_bash_integration,
    'fish': setup_fish_integration,
}
ENV_MODIFIERS = {
    'fish': setup_fish_env,
    'zsh': setup_zsh_env,
}


def get_supported_shell_name(path: str) -> Optional[str]:
    name = os.path.basename(path).split('.')[0].lower()
    name = name.replace('-', '')
    if name in SUPPORTED_SHELLS:
        return name
    return None


def is_shell_integration_allowed(shell: str, opts_set: Set[str]) -> bool:
    if shell is None or 'disabled' in opts_set:
        return False
    elif shell in ENV_MODIFIERS:
        return 'no-env' not in opts_set
    elif 'no-rc' in opts_set:
        return False
    return True


def setup_shell_integration(opts: Options, env: Dict[str, str]) -> bool:
    shell = get_supported_shell_name(resolved_shell(opts)[0])
    if not is_shell_integration_allowed(shell, set(opts.shell_integration.split())):
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
    shell = get_supported_shell_name(argv0)
    if shell is None:
        return
    q = set(opts.shell_integration.split())
    if 'disabled' in q:
        return
    env['KITTY_SHELL_INTEGRATION'] = opts.shell_integration
    if not is_shell_integration_allowed(shell, q):
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
