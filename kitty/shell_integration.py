#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
from contextlib import suppress
from typing import Optional, Union, Dict

from .options.types import Options
from .config import atomic_save
from .constants import shell_integration_dir
from .utils import log_error, resolved_shell

posix_template = '''\
# BEGIN_KITTY_SHELL_INTEGRATION
if test -n "$KITTY_INSTALLATION_DIR" -a -e "$KITTY_INSTALLATION_DIR/{path}"; then source "$KITTY_INSTALLATION_DIR/{path}"; fi
# END_KITTY_SHELL_INTEGRATION\
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
    integration = template.format(path=f"shell-integration/{shell_name}/kitty.{shell_name}")
    newrc, num_subs = re.subn(
        r'^# BEGIN_KITTY_SHELL_INTEGRATION.+?^# END_KITTY_SHELL_INTEGRATION',
        integration, rc, flags=re.DOTALL | re.MULTILINE)
    if num_subs < 1:
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


def is_new_zsh_install(env: Dict[str, str]) -> bool:
    # if ZDOTDIR is empty, zsh will read user rc files from /
    # if there aren't any, it'll run zsh-newuser-install
    # the latter will bail if there are rc files in $HOME
    zdotdir = env.get('ZDOTDIR')
    if not zdotdir:
        zdotdir = os.path.expanduser('~')
        if zdotdir == '~':
            return True
    for q in ('.zshrc', '.zshenv', '.zprofile', '.zlogin'):
        if os.path.exists(os.path.join(zdotdir, q)):
            return False
    return True


def setup_zsh_env(env: Dict[str, str]) -> None:
    if is_new_zsh_install(env):
        # dont prevent zsh-newuser-install from running
        # zsh-newuser-install never runs as root but we assume that it does
        return
    zdotdir = env.get('ZDOTDIR')
    if zdotdir is not None:
        env['KITTY_ORIG_ZDOTDIR'] = zdotdir
    else:
        # KITTY_ORIG_ZDOTDIR can be set at this point if, for example, the global
        # zshenv overrides ZDOTDIR; we try to limit the damage in this case
        env.pop('KITTY_ORIG_ZDOTDIR', None)
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


def shell_integration_allows_rc_modification(opts: Options) -> bool:
    return not (opts.shell_integration & {'disabled', 'no-rc'})


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
    shell = get_supported_shell_name(argv0)
    if shell is None or 'disabled' in opts.shell_integration:
        return
    env['KITTY_SHELL_INTEGRATION'] = ' '.join(opts.shell_integration)
    if not shell_integration_allows_rc_modification(opts):
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
