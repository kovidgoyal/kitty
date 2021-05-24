#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Dict, Optional, List

from .base import (
    MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType,
    PayloadType, RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetSpacingRCOptions as CLIOptions
    from kitty.options_stub import Options


def patch_window_edges(w: Window, s: Dict[str, Optional[float]]) -> None:
    for k, v in s.items():
        which, edge = k.lower().split('-', 1)
        if edge == 'left':
            w.patch_edge_width(which, 'left', v)
        elif edge == 'right':
            w.patch_edge_width(which, 'right', v)
        elif edge == 'top':
            w.patch_edge_width(which, 'top', v)
        elif edge == 'bottom':
            w.patch_edge_width(which, 'bottom', v)


def patch_configured_edges(opts: 'Options', s: Dict[str, Optional[float]]) -> None:
    for k, val in s.items():
        if val is None:
            continue
        which, edge = k.lower().split('-', 1)
        q = f'window_{which}_width'
        new_edges = getattr(opts, q)._replace(**{edge: val})
        setattr(opts, q, new_edges)


class SetSpacing(RemoteCommand):

    '''
    settings+: An object mapping margins/paddings using canonical form {'margin-top': 50, 'padding-left': null} etc
    match_window: Window to change colors in
    match_tab: Tab to change colors in
    all: Boolean indicating change colors everywhere or not
    configured: Boolean indicating whether to change the configured colors. Must be True if reset is True
    '''

    short_desc = 'Set window padding and margins'
    desc = (
        'Set the padding and margins for the specified windows (defaults to active window).'
        ' For example: margin=20 or padding-left=10 or margin-h=30. The shorthand form sets'
        ' all values, the :code:`*-h` and :code:`*-v` variants set horizontal and vertical values.'
        ' The special value "default" resets to using the default value.'
        ' If you specify a tab rather than a window, all windows in that tab are affected.'
    )
    options_spec = '''\
--all -a
type=bool-set
By default, settings are only changed for the currently active window. This option will
cause colors to be changed in all windows.


--configured -c
type=bool-set
Also change the configured padding and margins (i.e. the settings kitty will use for new
windows).
''' + '\n\n' + MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')
    argspec = 'MARGIN_OR_PADDING ...'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        settings: Dict[str, Optional[float]] = {}
        mapper: Dict[str, List[str]] = {}
        for q in ('margin', 'padding'):
            mapper[q] = f'{q}-left {q}-top {q}-right {q}-bottom'.split()
            mapper[f'{q}-h'] = mapper[f'{q}-horizontal'] = f'{q}-left {q}-right'.split()
            mapper[f'{q}-v'] = mapper[f'{q}-vertical'] = f'{q}-top {q}-bottom'.split()
            for edge in ('left', 'top', 'right', 'bottom'):
                mapper[f'{q}-{edge}'] = [f'{q}-{edge}']
        if not args:
            self.fatal('At least one setting must be specified')
        for spec in args:
            parts = spec.split('=', 1)
            if len(parts) != 2:
                self.fatal(f'{spec} is not a valid setting')
            which = mapper.get(parts[0].lower())
            if not which:
                self.fatal(f'{parts[0]} is not a valid edge specification')
            if parts[1].lower() == 'default':
                val = None
            else:
                try:
                    val = float(parts[1])
                except Exception:
                    self.fatal(f'{parts[1]} is not a number')
            for q in which:
                settings[q] = val
        ans = {
            'match_window': opts.match, 'match_tab': opts.match_tab,
            'all': opts.all, 'configured': opts.configured,
            'settings': settings
        }
        return ans

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_payload(boss, window, payload_get)
        settings: Dict[str, Optional[float]] = payload_get('settings')
        dirtied_tabs = {}
        from kitty.fast_data_types import get_options
        if payload_get('configured'):
            patch_configured_edges(get_options(), settings)

        for w in windows:
            patch_window_edges(w, settings)
            tab = w.tabref()
            if tab is not None:
                dirtied_tabs[tab.id] = tab

        for tab in dirtied_tabs.values():
            tab.relayout()


set_spacing = SetSpacing()
