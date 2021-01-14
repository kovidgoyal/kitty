#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import base64
import os
import sys
from typing import TYPE_CHECKING, Dict, Generator, List, Optional

from kitty.config import parse_send_text_bytes
from kitty.key_encoding import decode_key_event_as_window_system_key
from kitty.fast_data_types import KeyEvent as WindowSystemKeyEvent

from .base import (
    MATCH_TAB_OPTION, MATCH_WINDOW_OPTION, ArgsType, Boss, MatchError,
    PayloadGetType, PayloadType, RCOptions, RemoteCommand, ResponseType,
    Window
)

if TYPE_CHECKING:
    from kitty.cli_stub import SendTextRCOptions as CLIOptions


class SendText(RemoteCommand):
    '''
    data+: The data being sent. Can be either: text: followed by text or base64: followed by standard base64 encoded bytes
    match: A string indicating the window to send text to
    match_tab: A string indicating the tab to send text to
    all: A boolean indicating all windows should be matched.
    exclude_active: A boolean that prevents sending text to the active window
    '''
    short_desc = 'Send arbitrary text to specified windows'
    desc = (
        'Send arbitrary text to specified windows. The text follows Python'
        ' escaping rules. So you can use escapes like :italic:`\\x1b` to send control codes'
        ' and :italic:`\\u21fa` to send unicode characters. If you use the :option:`kitty @ send-text --match` option'
        ' the text will be sent to all matched windows. By default, text is sent to'
        ' only the currently active window.'
    )
    options_spec = MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t') + '''\n
--all
type=bool-set
Match all windows.


--stdin
type=bool-set
Read the text to be sent from :italic:`stdin`. Note that in this case the text is sent as is,
not interpreted for escapes. If stdin is a terminal, you can press Ctrl-D to end reading.


--from-file
Path to a file whose contents you wish to send. Note that in this case the file contents
are sent as is, not interpreted for escapes.


--exclude-active
type=bool-set
Do not send text to the active window, even if it is one of the matched windows.
'''
    no_response = True
    argspec = '[TEXT TO SEND]'

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        limit = 1024
        ret = {'match': opts.match, 'data': '', 'match_tab': opts.match_tab, 'all': opts.all, 'exclude_active': opts.exclude_active}

        def pipe() -> Generator[Dict, None, None]:
            if sys.stdin.isatty():
                ret['exclude_active'] = True
                import select
                fd = sys.stdin.fileno()
                keep_going = True
                while keep_going:
                    rd = select.select([fd], [], [])[0]
                    if not rd:
                        break
                    data = os.read(fd, limit)
                    if not data:
                        break  # eof
                    decoded_data = data.decode('utf-8')
                    if '\x04' in decoded_data:
                        decoded_data = decoded_data[:decoded_data.index('\x04')]
                        keep_going = False
                    ret['data'] = 'text:' + decoded_data
                    yield ret
            else:
                while True:
                    data = sys.stdin.buffer.read(limit)
                    if not data:
                        break
                    ret['data'] = 'base64:' + base64.standard_b64encode(data).decode('ascii')
                    yield ret

        def chunks(text: str) -> Generator[Dict, None, None]:
            data = parse_send_text_bytes(text).decode('utf-8')
            while data:
                ret['data'] = 'text:' + data[:limit]
                yield ret
                data = data[limit:]

        def file_pipe(path: str) -> Generator[Dict, None, None]:
            with open(path, 'rb') as f:
                while True:
                    data = f.read(limit)
                    if not data:
                        break
                    ret['data'] = 'base64:' + base64.standard_b64encode(data).decode('ascii')
                    yield ret

        sources = []
        if opts.stdin:
            sources.append(pipe())

        if opts.from_file:
            sources.append(file_pipe(opts.from_file))

        text = ' '.join(args)
        sources.append(chunks(text))

        def chain() -> Generator[Dict, None, None]:
            for src in sources:
                yield from src
        return chain()

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        if payload_get('all'):
            windows: List[Optional[Window]] = list(boss.all_windows)
        else:
            windows = [boss.active_window]
            match = payload_get('match')
            if match:
                windows = list(boss.match_windows(match))
            mt = payload_get('match_tab')
            if mt:
                windows = []
                tabs = tuple(boss.match_tabs(mt))
                if not tabs:
                    raise MatchError(payload_get('match_tab'), 'tabs')
                for tab in tabs:
                    windows += tuple(tab)
        encoding, _, q = payload_get('data').partition(':')
        if encoding == 'text':
            data = q.encode('utf-8')
        elif encoding == 'base64':
            data = base64.standard_b64decode(q)
        elif encoding == 'kitty-key':
            data = base64.standard_b64decode(q)
            data = decode_key_event_as_window_system_key(data)
        else:
            raise TypeError(f'Invalid encoding for send-text data: {encoding}')
        exclude_active = payload_get('exclude_active')
        for window in windows:
            if window is not None:
                if not exclude_active or window is not boss.active_window:
                    if isinstance(data, WindowSystemKeyEvent):
                        kdata = window.encoded_key(data)
                        if kdata:
                            window.write_to_child(kdata)
                    else:
                        window.write_to_child(data)


send_text = SendText()
