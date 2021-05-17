#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING, Optional

from .base import (
    MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType,
    RCOptions, RemoteCommand, ResponseType, Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import GetTextRCOptions as CLIOptions


class GetText(RemoteCommand):

    '''
    match: The tab to focus
    extent: One of :code:`screen`, :code:`all`, or :code:`selection`
    ansi: Boolean, if True send ANSI formatting codes
    cursor: Boolean, if True send cursor position/style as ANSI codes
    wrap_markers: Boolean, if True add wrap markers to output
    self: Boolean, if True use window command was run in
    '''

    short_desc = 'Get text from the specified window'
    options_spec = MATCH_WINDOW_OPTION + '''\n
--extent
default=screen
choices=screen, all, selection
What text to get. The default of screen means all text currently on the screen. all means
all the screen+scrollback and selection means currently selected text.


--ansi
type=bool-set
By default, only plain text is returned. If you specify this flag, the text will
include the formatting escape codes for colors/bold/italic/etc. Note that when
getting the current selection, the result is always plain text.


--add-cursor
type=bool-set
Add ANSI escape codes specifying the cursor position and style to the end of the text.


--add-wrap-markers
type=bool-set
Add carriage returns at every line wrap location (where long lines are wrapped at
screen edges).


--self
type=bool-set
If specified get text from the window this command is run in, rather than the active window.
'''
    argspec = ''

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {
            'match': opts.match,
            'extent': opts.extent,
            'ansi': opts.ansi,
            'self': opts.self,
            'cursor': opts.add_cursor,
            'wrap_markers': opts.add_wrap_markers,
        }

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        window = self.windows_for_match_payload(boss, window, payload_get)[0]
        if payload_get('extent') == 'selection':
            ans = window.text_for_selection()
        else:
            ans = window.as_text(
                as_ansi=bool(payload_get('ansi')),
                add_history=payload_get('extent') == 'all',
                add_cursor=bool(payload_get('cursor')),
                add_wrap_markers=bool(payload_get('wrap_markers')),
            )
        return ans


get_text = GetText()
