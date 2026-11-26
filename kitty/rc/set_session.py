#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import (
    MATCH_TAB_OPTION,
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    MatchError,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    RemoteControlErrorWithoutTraceback,
    ResponseType,
    Tab,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import SetSessionRCOptions as CLIOptions


class SetSession(RemoteCommand):
    protocol_spec = __doc__ = """
    session+/str: The name of the session, :code:`.` for the session of the window the command is run in and :code:`!` for no session
    match/str: Which windows to change the session of
    match_tab/str: Which tabs to change the session of
    self/bool: Boolean indicating whether to change the session of the window the command is run in
    """

    short_desc = 'Change the session of existing windows and tabs'
    desc = """
Change the :ref:`session <sessions>` the specified windows or tabs belong to. By default,
the active window is affected. Use :option:`kitten @ set-session --match` to select windows
and :option:`kitten @ set-session --match-tab` to select tabs, both can be used together.
The :italic:`SESSION` is the name of a session, :code:`.` for the session of the window this
command is run in, or :code:`!` to make them belong to no session.

A window is moved along with its overlays and the docks attached to it. If no other window
in its tab remains in a different session, the tab, along with the docks of the tab, is moved
as well, otherwise the window stays in its tab, which remains in its original session. A tab
is moved along with all its windows. The docks of the OS Window are never moved.

Note that a window of no session belongs to the session of its tab, so a window removed from
its session that shares its tab with windows of another session will then belong to the
session of its tab. Use :ref:`kitten @ detach-window <at-detach-window>` to first move it to
a tab of its own.

This change is temporary, it does not edit any session files. To update the session file,
resave the session with :ac:`save_as_session`. See :ref:`moving_to_session` for details.
"""
    options_spec = (
        MATCH_WINDOW_OPTION
        + '\n\n'
        + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')
        + """\n
--self
type=bool-set
Change the session of the window this command is run in, rather than the active window.
"""
    )
    args = RemoteCommand.Args(spec='SESSION', count=1, json_field='session')

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if len(args) != 1 or not args[0]:
            self.fatal('You must specify the SESSION, use ! to make windows belong to no session')
        return {'session': args[0], 'match': opts.match, 'match_tab': opts.match_tab, 'self': opts.self}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        session_name = payload_get('session')
        if not isinstance(session_name, str) or not session_name:
            raise RemoteControlErrorWithoutTraceback('You must specify the SESSION, use ! to make windows belong to no session')
        if session_name == '.':
            w = window or boss.active_window
            if w is None:
                raise RemoteControlErrorWithoutTraceback('There is no window to get the session from, for the SESSION .')
            session_name = w.effective_session_name
        elif session_name == '!':
            session_name = ''
        tabs: list[Tab] = []
        windows: list[Window] = []
        if match_tab := payload_get('match_tab'):
            tabs = list(boss.match_tabs(match_tab))
            if not tabs:
                raise MatchError(match_tab, 'tabs')
            if payload_get('match'):
                windows = self.windows_for_match_payload(boss, window, payload_get)
        else:
            windows = self.windows_for_match_payload(boss, window, payload_get)
        boss._set_session_of(session_name, windows, tabs)
        return None


set_session = SetSession()
