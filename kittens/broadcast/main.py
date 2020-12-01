#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from base64 import standard_b64encode
from gettext import gettext as _
from typing import Any, Dict, List, Optional, Tuple

from kitty.cli import parse_args
from kitty.cli_stub import BroadcastCLIOptions
from kitty.key_encoding import RELEASE, key_defs as K
from kitty.rc.base import MATCH_TAB_OPTION, MATCH_WINDOW_OPTION
from kitty.remote_control import create_basic_command, encode_send
from kitty.typing import KeyEventType

from ..tui.handler import Handler
from ..tui.loop import Loop
from ..tui.operations import styled


class Broadcast(Handler):

    def __init__(self, opts: BroadcastCLIOptions, initial_strings: List[str]) -> None:
        self.opts = opts
        self.initial_strings = initial_strings
        self.payload = {'exclude_active': True, 'data': '', 'match': opts.match_tab, 'match_tab': opts.match_tab}
        if not opts.match and not opts.match_tab:
            self.payload['all'] = True

    def initialize(self) -> None:
        self.print('Type the text to broadcast below, press', styled('Ctrl+c', fg='yellow'), 'to quit:')
        for x in self.initial_strings:
            self.write_broadcast_text(x)

    def on_text(self, text: str, in_bracketed_paste: bool = False) -> None:
        self.write_broadcast_text(text)
        self.write(text)

    def on_interrupt(self) -> None:
        self.quit_loop(0)

    def on_eot(self) -> None:
        self.write_broadcast_text('\x04')

    def on_key(self, key_event: KeyEventType) -> None:
        if key_event.type is not RELEASE and not key_event.mods:
            if key_event.key is K['TAB']:
                self.write_broadcast_text('\t')
                self.write('\t')
            elif key_event.key is K['BACKSPACE']:
                self.write_broadcast_text('\177')
                self.write('\x08\x1b[X')
            elif key_event.key is K['ENTER']:
                self.write_broadcast_text('\r')
                self.print('')

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
