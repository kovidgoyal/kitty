#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>


import os
import shutil
from tempfile import mkstemp
from typing import Optional, Union

from .constants import shell_integration_dir
from .fast_data_types import get_options
from .types import run_once
from .utils import log_error, resolved_shell

SUPPORTED_SHELLS = ('zsh',)
posix_template = '''
# BEGIN_KITTY_SHELL_INTEGRATION
[[ -a {path} ]] && source {path}
# END_KITTY_SHELL_INTEGRATION
'''


def atomic_write(path: str, data: Union[str, bytes]) -> None:
    mode = 'w' + ('b' if isinstance(data, bytes) else '')
    fd, tpath = mkstemp(dir=os.path.dirname(path), text=isinstance(data, str))
    with open(fd, mode) as f:
        shutil.copystat(path, tpath)
        f.write(data)
    os.rename(tpath, path)


def setup_integration(shell_name: str, rc_path: str, template: str = posix_template) -> None:
    import re
    rc_path = os.path.realpath(rc_path)
    if not os.access(rc_path, os.W_OK, effective_ids=os.access in os.supports_effective_ids):
        return
    try:
        with open(rc_path) as f:
            rc = f.read()
    except FileNotFoundError:
        rc = ''
    except Exception:
        raise
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


def setup_zsh_integration() -> None:
    base = os.environ.get('ZDOTDIR', os.path.expanduser('~'))
    rc = os.path.join(base, '.zshrc')
    setup_integration('zsh', rc)


def get_supported_shell_name(path: str) -> Optional[str]:
    name = os.path.basename(path).split('.')[0].lower()
    if name in SUPPORTED_SHELLS:
        return name


@run_once
def setup_shell_integration() -> None:
    opts = get_options()
    q = opts.shell_integration.split()
    if opts.shell_integration == 'disabled' or 'no-rc' in q:
        return
    shell = get_supported_shell_name(resolved_shell(opts)[0])
    if shell is None:
        return
    func = {'zsh': setup_zsh_integration}[shell]
    try:
        func()
    except Exception:
        import traceback
        traceback.print_exc()
        log_error(f'Failed to setup shell integration for: {shell}')
