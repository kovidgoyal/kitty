#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from base64 import standard_b64encode
from gettext import gettext as _
from typing import Any, Dict, List, Optional, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import BroadcastCLIOptions
from kitty.key_encoding import encode_key_event
from kitty.rc.base import MATCH_TAB_OPTION, MATCH_WINDOW_OPTION
from kitty.remote_control import create_basic_command, encode_send
from kitty.typing import KeyEventType, ScreenSize

from ..tui.handler import Handler
from ..tui.line_edit import LineEdit
from ..tui.loop import Loop
from ..tui.operations import RESTORE_CURSOR, SAVE_CURSOR, styled


class Broadcast(Handler):

    def __init__(self, opts: BroadcastCLIOptions, initial_strings: List[str]) -> None:
        self.opts = opts
        self.initial_strings = initial_strings
        self.payload = {'exclude_active': True, 'data': '', 'match': opts.match_tab, 'match_tab': opts.match_tab}
        self.line_edit = LineEdit()
        if not opts.match and not opts.match_tab:
            self.payload['all'] = True

    def initialize(self) -> None:
        self.print('Type the text to broadcast below, press', styled('Ctrl+c', fg='yellow'), 'to quit:')
        for x in self.initial_strings:
            self.write_broadcast_text(x)
        self.write(SAVE_CURSOR)

    def commit_line(self) -> None:
        self.write(RESTORE_CURSOR + SAVE_CURSOR)
        self.cmd.clear_to_end_of_screen()
        self.line_edit.write(self.write, screen_cols=self.screen_size.cols)

    def on_resize(self, screen_size: ScreenSize) -> None:
        super().on_resize(screen_size)
        self.commit_line()

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        self.write_broadcast_text(text)
        self.line_edit.on_text(text, in_bracketed_paste)
        self.commit_line()

    def on_interrupt(self) -> None:
        self.quit_loop(0)

    def on_eot(self) -> None:
        self.write_broadcast_text('\x04')

    def on_key(self, key_event: KeyEventType) -> None:
        if self.line_edit.on_key(key_event):
            self.commit_line()
        if key_event.matches('enter'):
            self.write_broadcast_text('\r')
            self.print('')
            self.line_edit.clear()
            self.write(SAVE_CURSOR)
            return

        ek = encode_key_event(key_event)
        ek = standard_b64encode(ek.encode('utf-8')).decode('ascii')
        self.write_broadcast_data('kitty-key:' + ek)

    def write_broadcast_text(self, text: str) -> None:
        self.write_broadcast_data('base64:' + standard_b64encode(text.encode('utf-8')).decode('ascii'))

    def write_broadcast_data(self, data: str) -> None:
        payload = self.payload.copy()
        payload['data'] = data
        send = create_basic_command('send-text', payload, no_response=True)
        self.write(encode_send(send))


OPTIONS = (MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t')).format
help_text = 'Broadcast typed text to all kitty windows. By default text is sent to all windows, unless one of the matching options is specified'
usage = '[initial text to send ...]'


def parse_broadcast_args(args: List[str]) -> Tuple[BroadcastCLIOptions, List[str]]:
    return parse_args(args, OPTIONS, usage, help_text, 'kitty +kitten broadcast', result_class=BroadcastCLIOptions)


def main(args: List[str]) -> Optional[Dict[str, Any]]:
    try:
        opts, items = parse_broadcast_args(args[1:])
    except SystemExit as e:
        if e.code != 0:
            print(e.args[0], file=sys.stderr)
            input(_('Press Enter to quit'))
        return None

    print('Type text to be broadcast below, Ctrl-C to quit:', end='\r\n')
    sys.stdout.flush()
    loop = Loop()
    handler = Broadcast(opts, items)
    loop.loop(handler)


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
