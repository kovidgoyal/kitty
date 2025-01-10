#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Iterable
from typing import TYPE_CHECKING

from kitty.fast_data_types import get_options
from kitty.options.utils import parse_layout_names

from .base import MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import SetEnabledLayoutsRCOptions as CLIOptions


def layout_names() -> Iterable[str]:
    from kitty.layout.interface import all_layouts
    return all_layouts.keys()


class SetEnabledLayouts(RemoteCommand):

    protocol_spec = __doc__ = '''
    layouts+/list.str: The list of layout names
    match/str: Which tab to change the layout of
    configured/bool: Boolean indicating whether to change the configured value
    '''

    short_desc = 'Set the enabled layouts in tabs'
    desc = (
        'Set the enabled layouts in the specified tabs (or the active tab if not specified).'
        ' You can use special match value :code:`all` to set the enabled layouts in all tabs. If the'
        ' current layout of the tab is not included in the enabled layouts, its layout is changed'
        ' to the first enabled layout.'
    )
    options_spec = MATCH_TAB_OPTION + '''\n\n
--configured
type=bool-set
Change the default enabled layout value so that the new value takes effect for all newly created tabs
as well.
'''
    args = RemoteCommand.Args(
        spec='LAYOUT ...', minimum_count=1, json_field='layouts',
        completion=RemoteCommand.CompletionSpec.from_string('type:keyword group:"Layout" kwds:' + ','.join(layout_names())),
        args_choices=layout_names)

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('At least one layout must be specified')
        a: list[str] = []
        for x in args:
            a.extend(y.strip() for y in x.split(','))
        try:
            layouts = parse_layout_names(a)
        except ValueError as err:
            self.fatal(str(err))
        return {'layouts': layouts, 'match': opts.match}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        tabs = self.tabs_for_match_payload(boss, window, payload_get)
        layouts = parse_layout_names(payload_get('layouts'))
        if payload_get('configured'):
            get_options().enabled_layouts = list(layouts)
        for tab in tabs:
            if tab:
                tab.set_enabled_layouts(layouts)
        return None


set_enabled_layouts = SetEnabledLayouts()
