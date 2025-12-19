#!/usr/bin/env python
# License: GPLv3 Copyright: 2025, Kovid Goyal <kovid at kovidgoyal.net>

import json
from typing import TYPE_CHECKING

from .base import ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import MRURCOptions as CLIOptions


class MRU(RemoteCommand):
    protocol_spec = __doc__ = '''
    all_os_windows/bool: Include tabs from all OS windows, not just the active one
    '''

    short_desc = 'List tabs in MRU order'
    desc = (
        'List tabs in most recently used (MRU) order. Returns a JSON list of tabs '
        'with their ID and last visited timestamp. The most recently used tab appears first. '
        'By default, only tabs from the active OS window are listed. Use --all-os-windows '
        'to include tabs from all OS windows.'
    )
    options_spec = '''
--all-os-windows
type=bool-set
Include tabs from all OS windows, not just the active one.
'''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'all_os_windows': opts.all_os_windows}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        all_os_windows = payload_get('all_os_windows')

        if all_os_windows:
            # Get MRU tabs from all OS windows
            data = boss.get_mru_tabs_all_os_windows()
        else:
            # Get MRU tabs from active OS window only
            tm = boss.active_tab_manager
            if tm is None:
                data = []
            else:
                data = tm.get_mru_tabs()
                # Add os_window_id for consistency
                for tab_data in data:
                    tab_data['os_window_id'] = tm.os_window_id

        return json.dumps(data, indent=2, sort_keys=True)


mru = MRU()
