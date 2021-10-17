#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING, Iterable, Optional

from kitty.fast_data_types import get_options
from kitty.options.utils import parse_layout_names

from .base import (
    MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions,
    RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetEnabledLayoutsRCOptions as CLIOptions


def layout_names() -> Iterable[str]:
    from kitty.layout.interface import all_layouts
    return all_layouts.keys()


class SetEnabledLayouts(RemoteCommand):

    '''
    layouts+: The list of layout names
    match: Which tab to change the layout of
    configured: Boolean indicating whether to change the configured value
    '''

    short_desc = 'Set the enabled layouts in a tab'
    desc = (
        'Set the enabled layouts in the specified tab (or the active tab if not specified).'
        ' You can use special match value :italic:`all` to set the layout in all tabs. If the'
        ' current layout of the tab is not included in the enabled layouts its layout is changed'
        ' to the first enabled layout.'
    )
    options_spec = MATCH_TAB_OPTION + '''\n\n
--configured
type=bool-set
Change the default enabled layout value so that the new value takes effect for all newly created tabs
as well.
'''
    argspec = 'LAYOUTS'
    args_completion = {'names': ('Layouts', layout_names)}

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('At least one layout must be specified')
        try:
            layouts = parse_layout_names(args)
        except ValueError as err:
            self.fatal(str(err))
        return {'layouts': layouts, 'match': opts.match}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        tabs = self.tabs_for_match_payload(boss, window, payload_get)
        layouts = parse_layout_names(payload_get('layouts'))
        if payload_get('configured'):
            get_options().enabled_layouts = list(layouts)
        for tab in tabs:
            if tab:
                tab.set_enabled_layouts(layouts)


set_enabled_layouts = SetEnabledLayouts()
