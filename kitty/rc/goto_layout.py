#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from collections.abc import Iterable
from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, UnknownLayout, Window

if TYPE_CHECKING:
    from kitty.cli_stub import GotoLayoutRCOptions as CLIOptions


def layout_names() -> Iterable[str]:
    from kitty.layout.interface import all_layouts
    return all_layouts.keys()


class GotoLayout(RemoteCommand):

    protocol_spec = __doc__ = '''
    layout+/str: The new layout name
    match/str: Which tab to change the layout of
    '''

    short_desc = 'Set the window layout'
    desc = (
        'Set the window layout in the specified tabs (or the active tab if not specified).'
        ' You can use special match value :code:`all` to set the layout in all tabs.'
        ' In case there are multiple layouts with the same name but different options,'
        ' specify the full layout definition or a unique prefix of the full definition.'
    )
    options_spec = MATCH_TAB_OPTION
    args = RemoteCommand.Args(
        spec='LAYOUT_NAME', count=1, json_field='layout',
        completion=RemoteCommand.CompletionSpec.from_string('type:keyword group:"Layout" kwds:' + ','.join(layout_names())),
        )

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) != 1:
            self.fatal('Exactly one layout must be specified')
        return {'layout': args[0], 'match': opts.match}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        tabs = self.tabs_for_match_payload(boss, window, payload_get)
        for tab in tabs:
            if tab:
                try:
                    tab.goto_layout(payload_get('layout'), raise_exception=True)
                except ValueError:
                    raise UnknownLayout('The layout {} is unknown or disabled or the name is ambiguous'.format(payload_get('layout')))
        return None


goto_layout = GotoLayout()
