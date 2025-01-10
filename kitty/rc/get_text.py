#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import MATCH_WINDOW_OPTION, ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType, Window

if TYPE_CHECKING:
    from kitty.cli_stub import GetTextRCOptions as CLIOptions


class GetText(RemoteCommand):

    protocol_spec = __doc__ = '''
    match/str: The window to get text from
    extent/choices.screen.first_cmd_output_on_screen.last_cmd_output.last_visited_cmd_output.all.selection: \
        One of :code:`screen`, :code:`first_cmd_output_on_screen`, :code:`last_cmd_output`, \
        :code:`last_visited_cmd_output`, :code:`all`, or :code:`selection`
    ansi/bool: Boolean, if True send ANSI formatting codes
    cursor/bool: Boolean, if True send cursor position/style as ANSI codes
    wrap_markers/bool: Boolean, if True add wrap markers to output
    clear_selection/bool: Boolean, if True clear the selection in the matched window
    self/bool: Boolean, if True use window the command was run in
    '''

    short_desc = 'Get text from the specified window'
    options_spec = MATCH_WINDOW_OPTION + '''\n
--extent
default=screen
choices=screen, all, selection, first_cmd_output_on_screen, last_cmd_output, last_visited_cmd_output, last_non_empty_output
What text to get. The default of :code:`screen` means all text currently on the screen.
:code:`all` means all the screen+scrollback and :code:`selection` means the
currently selected text. :code:`first_cmd_output_on_screen` means the output of the first
command that was run in the window on screen. :code:`last_cmd_output` means
the output of the last command that was run in the window. :code:`last_visited_cmd_output` means
the first command output below the last scrolled position via scroll_to_prompt.
:code:`last_non_empty_output` is the output from the last command run in the window that had
some non empty output. The last four require :ref:`shell_integration` to be enabled.


--ansi
type=bool-set
By default, only plain text is returned. With this flag, the text will
include the ANSI formatting escape codes for colors, bold, italic, etc.


--add-cursor
type=bool-set
Add ANSI escape codes specifying the cursor position and style to the end of the text.


--add-wrap-markers
type=bool-set
Add carriage returns at every line wrap location (where long lines are wrapped at
screen edges).


--clear-selection
type=bool-set
Clear the selection in the matched window, if any.


--self
type=bool-set
Get text from the window this command is run in, rather than the active window.
'''

    field_to_option_map = {'wrap_markers': 'add_wrap_markers', 'cursor': 'add_cursor'}

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {
            'match': opts.match,
            'extent': opts.extent,
            'ansi': opts.ansi,
            'cursor': opts.add_cursor,
            'wrap_markers': opts.add_wrap_markers,
            'clear_selection': opts.clear_selection,
            'self': opts.self,
        }

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        from kitty.window import CommandOutput
        windows = self.windows_for_match_payload(boss, window, payload_get)
        if windows and windows[0]:
            window = windows[0]
        else:
            return None
        if payload_get('extent') == 'selection':
            ans = window.text_for_selection(as_ansi=payload_get('ansi'))
        elif payload_get('extent') == 'first_cmd_output_on_screen':
            ans = window.cmd_output(
                CommandOutput.first_on_screen,
                as_ansi=bool(payload_get('ansi')),
                add_wrap_markers=bool(payload_get('wrap_markers')),
            )
        elif payload_get('extent') == 'last_cmd_output':
            ans = window.cmd_output(
                CommandOutput.last_run,
                as_ansi=bool(payload_get('ansi')),
                add_wrap_markers=bool(payload_get('wrap_markers')),
            )
        elif payload_get('extent') == 'last_non_empty_output':
            ans = window.cmd_output(
                CommandOutput.last_non_empty,
                as_ansi=bool(payload_get('ansi')),
                add_wrap_markers=bool(payload_get('wrap_markers')),
            )
        elif payload_get('extent') == 'last_visited_cmd_output':
            ans = window.cmd_output(
                CommandOutput.last_visited,
                as_ansi=bool(payload_get('ansi')),
                add_wrap_markers=bool(payload_get('wrap_markers')),
            )
        else:
            ans = window.as_text(
                as_ansi=bool(payload_get('ansi')),
                add_history=payload_get('extent') == 'all',
                add_cursor=bool(payload_get('cursor')),
                add_wrap_markers=bool(payload_get('wrap_markers')),
            )
        if payload_get('clear_selection'):
            window.clear_selection()
        return ans


get_text = GetText()
