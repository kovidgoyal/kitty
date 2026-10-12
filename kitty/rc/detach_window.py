#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import DetachWindowRCOptions as CLIOptions


class TabNotFound(MatchError):
    def __init__(self, msg: str):
        ValueError.__init__(self, msg)


class DetachWindow(RemoteCommand):
    protocol_spec = __doc__ = """
    match/str: Which window to detach
    target_tab/str: Which tab to move the detached window to
    self/bool: Boolean indicating whether to detach the window the command is run in
    stay_in_tab/bool: Boolean indicating focus should remain in the active tab after windows are moved
    tab_title/str: Title for a newly created tab
    location/choices.first.after.before.neighbor.last.by-title.default: Where to place a newly created tab
    create_if_missing/bool: Boolean indicating a new tab should be created if no tab matches target_tab
    """

    short_desc = 'Detach the specified windows and place them in a different/new tab'
    desc = (
        'Detach the specified windows and either move them into a new tab, a new OS window'
        ' or add them to the specified tab. Use the special value :code:`new` for :option:`kitten @ detach-window --target-tab`'
        ' to move to a new tab. If no target tab is specified the windows are moved to a new OS window.'
    )
    options_spec = (
        MATCH_WINDOW_OPTION
        + '\n\n'
        + MATCH_TAB_OPTION.replace('--match -m', '--target-tab -t')
        + """Use the special value :code:`new` to move to a new tab. The special value
:code:`@title` selects the tab whose title is exactly the value of
:option:`kitten @ detach-window --tab-title`, considering only the tabs shown
in the tab bar of the active OS Window, so tabs hidden by :opt:`tab_bar_filter`
are ignored.


--self
type=bool-set
Detach the window this command is run in, rather than the active window.


--stay-in-tab
type=bool-set
Keep the focus on a window in the currently focused tab after moving the specified windows.


--tab-title
The title for the tab, when moving to a newly created tab.


--location
type=choices
default=default
choices=first,after,before,neighbor,last,by-title,default
Where to place the newly created tab, when moving to a new tab. :code:`after`
and :code:`before` place it next to the currently active tab, :code:`neighbor`
is a synonym for :code:`after`. :code:`by-title` places the new tab before the
first tab whose title sorts after :option:`kitten @ detach-window --tab-title`.
The default is to place it at the end.


--create-if-missing
type=bool-set
If no tab matches :option:`kitten @ detach-window --target-tab`, create a new tab
and move the windows to it, instead of failing. Combined with :code:`@title`, this
can be used to send windows to a named tab, creating it if needed. For example::

    kitten @ detach-window --target-tab=@title --tab-title=1 --location=by-title --create-if-missing
"""
    )

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {
            'match': opts.match,
            'target_tab': opts.target_tab,
            'self': opts.self,
            'stay_in_tab': opts.stay_in_tab,
            'tab_title': opts.tab_title,
            'location': opts.location,
            'create_if_missing': opts.create_if_missing,
        }

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_match_payload(boss, window, payload_get)
        match = payload_get('target_tab')
        tab_title = payload_get('tab_title') or ''
        location = payload_get('location') or 'default'
        target_tab_id: str | int | None = None
        newval: str | int = 'new'
        create_tab = False
        if match:
            if match == 'new':
                target_tab_id = newval
            else:
                if match == '@title':
                    if not tab_title:
                        raise ValueError('--target-tab=@title requires --tab-title to also be specified')
                    # only tabs visible in the tab bar of the active OS Window, so as to respect tab_bar_filter
                    atm = boss.active_tab_manager
                    tabs = tuple(t for t in (atm.tabs_to_be_shown_in_tab_bar if atm is not None else ()) if t.effective_title == tab_title)
                else:
                    tabs = tuple(boss.match_tabs(match))
                if tabs:
                    target_tab_id = tabs[0].id
                elif payload_get('create_if_missing'):
                    target_tab_id = newval
                    create_tab = True
                elif match == '@title':
                    raise TabNotFound(f'No tab with the title {tab_title!r} exists. Use --create-if-missing to create it.')
                else:
                    raise TabNotFound(f'No tab matches the expression {match!r}. Use --create-if-missing to create a new tab instead.')
        tab = boss.active_tab
        for window in windows:
            if not window:
                continue
            if target_tab_id is None:
                boss._move_window_to(window=window, target_os_window_id=newval, new_tab_title=tab_title)
                continue
            if (src_tab := window.tabref()) is not None and src_tab.id == target_tab_id:
                continue
            boss._move_window_to(window=window, target_tab_id=target_tab_id, new_tab_title=tab_title, new_tab_location=location)
            if create_tab and (created := window.tabref()) is not None:
                # move any remaining windows into the tab that was just created
                target_tab_id, create_tab = created.id, False
        if payload_get('stay_in_tab') and tab is not None:
            tab.make_active()
        return None


detach_window = DetachWindow()
