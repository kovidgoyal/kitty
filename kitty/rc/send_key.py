#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import TYPE_CHECKING

from .base import (
    MATCH_TAB_OPTION,
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import SendKeyRCOptions as CLIOptions


class SendKey(RemoteCommand):
    disallow_responses = True
    protocol_spec = __doc__ = '''
    keys+/list.str: The keys to send
    match/str: A string indicating the window to send text to
    match_tab/str: A string indicating the tab to send text to
    all/bool: A boolean indicating all windows should be matched.
    exclude_active/bool: A boolean that prevents sending text to the active window
    '''
    short_desc = 'Send arbitrary key presses to the specified windows'
    desc = (
        'Send arbitrary key presses to specified windows. All specified keys are sent first as press events'
        ' then as release events in reverse order. Keys are sent to the programs running in the windows.'
        ' They are sent only if the current keyboard mode for the program supports the particular key.'
        ' For example: send-key ctrl+a ctrl+b. Note that errors are not reported, for technical reasons,'
        ' so send-key always succeeds, even if no key was sent to any window.'
   )
    # since send-key can send data over the tty to the window in which it was
    # run --no-reponse is always in effect for it, hence errors are not
    # reported.
    options_spec = MATCH_WINDOW_OPTION + '\n\n' + MATCH_TAB_OPTION.replace('--match -m', '--match-tab -t') + '''\n
--all
type=bool-set
Match all windows.


--exclude-active
type=bool-set
Do not send text to the active window, even if it is one of the matched windows.
'''
    args = RemoteCommand.Args(spec='[KEYS TO SEND ...]', json_field='keys')

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        ret = {'match': opts.match, 'keys': args, 'match_tab': opts.match_tab, 'all': opts.all, 'exclude_active': opts.exclude_active}
        return ret

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        windows = self.windows_for_payload(boss, None, payload_get, window_match_name='match')
        keys = payload_get('keys')
        for w in windows:
            w.send_key(*keys)
        return None


send_key = SendKey()
