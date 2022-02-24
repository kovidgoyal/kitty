#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import subprocess
from contextlib import suppress
from typing import Dict, List, Optional

from .constants import shell_integration_dir
from .options.types import Options
from .utils import log_error, which
from .fast_data_types import get_options


def setup_fish_env(env: Dict[str, str], argv: List[str]) -> None:
    val = env.get('XDG_DATA_DIRS')
    env['KITTY_FISH_XDG_DATA_DIR'] = shell_integration_dir
    if not val:
        env['XDG_DATA_DIRS'] = shell_integration_dir
    else:
        dirs = list(filter(None, val.split(os.pathsep)))
        dirs.insert(0, shell_integration_dir)
        env['XDG_DATA_DIRS'] = os.pathsep.join(dirs)


def is_new_zsh_install(env: Dict[str, str], zdotdir: Optional[str]) -> bool:
    # if ZDOTDIR is empty, zsh will read user rc files from /
    # if there aren't any, it'll run zsh-newuser-install
    # the latter will bail if there are rc files in $HOME
    if not zdotdir:
        zdotdir = env.get('HOME', os.path.expanduser('~'))
        assert isinstance(zdotdir, str)
        if zdotdir == '~':
            return True
    for q in ('.zshrc', '.zshenv', '.zprofile', '.zlogin'):
        if os.path.exists(os.path.join(zdotdir, q)):
            return False
    return True


def get_zsh_zdotdir_from_global_zshenv(env: Dict[str, str], argv: List[str]) -> Optional[str]:
    exe = which(argv[0], only_system=True) or 'zsh'
    with suppress(Exception):
        return subprocess.check_output([exe, '--norcs', '--interactive', '-c', 'echo -n $ZDOTDIR'], env=env).decode('utf-8')
    return None


def setup_zsh_env(env: Dict[str, str], argv: List[str]) -> None:
    zdotdir = env.get('ZDOTDIR')
    if is_new_zsh_install(env, zdotdir):
        if zdotdir is None:
            # Try to get ZDOTDIR from /etc/zshenv, when all startup files are not present
            zdotdir = get_zsh_zdotdir_from_global_zshenv(env, argv)
            if zdotdir is None or is_new_zsh_install(env, zdotdir):
                return
        else:
            # dont prevent zsh-newuser-install from running
            # zsh-newuser-install never runs as root but we assume that it does
            return
    if zdotdir is not None:
        env['KITTY_ORIG_ZDOTDIR'] = zdotdir
    else:
        # KITTY_ORIG_ZDOTDIR can be set at this point if, for example, the global
        # zshenv overrides ZDOTDIR; we try to limit the damage in this case
        env.pop('KITTY_ORIG_ZDOTDIR', None)
    env['ZDOTDIR'] = os.path.join(shell_integration_dir, 'zsh')


def setup_bash_env(env: Dict[str, str], argv: List[str]) -> None:
    inject = {'1'}
    posix_env = rcfile = ''
    remove_args = set()
    for i in range(1, len(argv)):
        arg = argv[i]
        if arg == '--posix':
            inject.add('posix')
            posix_env = env.get('ENV', '')
            remove_args.add(i)
        elif arg == '--norc':
            inject.add('no-rc')
            remove_args.add(i)
        elif arg == '--noprofile':
            inject.add('no-profile')
            remove_args.add(i)
        elif arg in ('--rcfile', '--init-file') and i + 1 < len(argv):
            rcfile = argv[i+1]
            remove_args |= {i, i+1}
    env['ENV'] = os.path.join(shell_integration_dir, 'bash', 'kitty.bash')
    env['KITTY_BASH_INJECT'] = ' '.join(inject)
    if posix_env:
        env['KITTY_BASH_POSIX_ENV'] = posix_env
    if rcfile:
        env['KITTY_BASH_RCFILE'] = rcfile
    for i in sorted(remove_args, reverse=True):
        del argv[i]
    if 'HISTFILE' not in env and 'posix' not in inject:
        # In POSIX mode the default history file is ~/.sh_history instead of ~/.bash_history
        env['HISTFILE'] = os.path.expanduser('~/.bash_history')
        env['KITTY_BASH_UNEXPORT_HISTFILE'] = '1'
    argv.insert(1, '--posix')


ENV_MODIFIERS = {
    'fish': setup_fish_env,
    'zsh': setup_zsh_env,
    'bash': setup_bash_env,
}


def get_supported_shell_name(path: str) -> Optional[str]:
    name = os.path.basename(path)
    if name.lower().endswith('.exe'):
        name = name.rpartition('.')[0]
    if name.startswith('-'):
        name = name[1:]
    return name if name in ENV_MODIFIERS else None


def shell_integration_allows_rc_modification(opts: Options) -> bool:
    return not (opts.shell_integration & {'disabled', 'no-rc'})


def get_effective_ksi_env_var(opts: Optional[Options] = None) -> str:
    opts = opts or get_options()
    if 'disabled' in opts.shell_integration:
        return ''
    return ' '.join(opts.shell_integration)


def modify_shell_environ(opts: Options, env: Dict[str, str], argv: List[str]) -> None:
    shell = get_supported_shell_name(argv[0])
    ksi = get_effective_ksi_env_var(opts)
    if shell is None or not ksi:
        return
    env['KITTY_SHELL_INTEGRATION'] = ksi
    if not shell_integration_allows_rc_modification(opts):
        return
    f = ENV_MODIFIERS.get(shell)
    if f is not None:
        try:
            f(env, argv)
        except Exception:
            import traceback
            traceback.print_exc()
            log_error(f'Failed to setup shell integration for: {shell}')
    return
