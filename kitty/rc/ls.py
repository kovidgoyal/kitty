#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from kitty.constants import appname

from .base import MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Tab, Window

if TYPE_CHECKING:
    from kitty.cli_stub import LSRCOptions as CLIOptions


class LS(RemoteCommand):
    protocol_spec = __doc__ = '''
    all_env_vars/bool: Whether to send all environment variables for every window rather than just differing ones
    match/str: Window to change colors in
    match_tab/str: Tab to change colors in
    self/bool: Boolean indicating whether to list only the window the command is run in
    '''

    short_desc = 'List tabs/windows'
    desc = (
        'List windows. The list is returned as JSON tree. The top-level is a list of'
        f' operating system {appname} windows. Each OS window has an :italic:`id` and a list'
        ' of :italic:`tabs`. Each tab has its own :italic:`id`, a :italic:`title` and a list of :italic:`windows`.'
        ' Each window has an :italic:`id`, :italic:`title`, :italic:`current working directory`, :italic:`process id (PID)`,'
        ' :italic:`command-line` and :italic:`environment` of the process running in the window. Additionally, when'
        ' running the command inside a kitty window, that window can be identified by the :italic:`is_self` parameter.\n\n'
        'You can use these criteria to select windows/tabs for the other commands.\n\n'
        'You can limit the windows/tabs in the output by using the :option:`--match` and :option:`--match-tab` options.'
    )
    options_spec = '''\
--all-env-vars
type=bool-set
Show all environment variables in output, not just differing ones.


--self
type=bool-set
Only list the window this command is run in.
''' + '\n\n' + MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t', 1)

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'all_env_vars': opts.all_env_vars, 'match': opts.match, 'match_tab': opts.match_tab}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        tab_filter: Callable[[Tab], bool] | None = None
        window_filter: Callable[[Window], bool] | None = None

        if payload_get('self'):
            def wf(w: Window) -> bool:
                return w is window
            window_filter = wf
        elif payload_get('match') is not None or payload_get('match_tab') is not None:
            window_ids = frozenset(w.id for w in self.windows_for_payload(boss, window, payload_get, window_match_name='match'))
            def wf(w: Window) -> bool:
                return w.id in window_ids
            window_filter = wf
        data = list(boss.list_os_windows(window, tab_filter, window_filter))
        if not payload_get('all_env_vars'):
            all_env_blocks: list[dict[str, str]] = []
            common_env_vars: set[tuple[str, str]] = set()
            for osw in data:
                for tab in osw.get('tabs', ()):
                    for w in tab.get('windows', ()):
                        env: dict[str, str] = w.get('env', {})
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
