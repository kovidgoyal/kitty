#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import json
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from kitty.constants import appname

from .base import (
    ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand,
    ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import LSRCOptions as CLIOptions


class LS(RemoteCommand):
    '''
    all_env_vars: Whether to send all environment variables for ever window rather than just differing ones
    '''

    short_desc = 'List all tabs/windows'
    desc = (
        'List all windows. The list is returned as JSON tree. The top-level is a list of'
        f' operating system {appname} windows. Each OS window has an :italic:`id` and a list'
        ' of :italic:`tabs`. Each tab has its own :italic:`id`, a :italic:`title` and a list of :italic:`windows`.'
        ' Each window has an :italic:`id`, :italic:`title`, :italic:`current working directory`, :italic:`process id (PID)`, '
        ' :italic:`command-line` and :italic:`environment` of the process running in the window. Additionally, when'
        ' running the command inside a kitty window, that window can be identified by the :italic:`is_self` parameter.\n\n'
        'You can use these criteria to select windows/tabs for the other commands.'
    )
    options_spec = '''\
--all-env-vars
type=bool-set
Show all environment variables in output not just differing ones.
'''

    argspec = ''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'all_env_vars': opts.all_env_vars}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        data = list(boss.list_os_windows(window))
        if not payload_get('all_env_vars'):
            all_env_blocks: List[Dict[str, str]] = []
            common_env_vars: Set[Tuple[str, str]] = set()
            for osw in data:
                for tab in osw.get('tabs', ()):
                    for w in tab.get('windows', ()):
                        env: Dict[str, str] = w.get('env', {})
                        frozen_env = set(env.items())
                        if all_env_blocks:
                            common_env_vars &= frozen_env
                        else:
                            common_env_vars = frozen_env
                        all_env_blocks.append(env)
            if common_env_vars and len(all_env_blocks) > 1:
                remove_env_vars = {k for k, v in common_env_vars}
                for env in all_env_blocks:
                    for r in remove_env_vars:
                        env.pop(r, None)
        return json.dumps(data, indent=2, sort_keys=True)


ls = LS()
