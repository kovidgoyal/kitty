#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from .base import (
    MATCH_WINDOW_OPTION,
    ArgsType,
    Boss,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    RemoteControlErrorWithoutTraceback,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import ActionRCOptions as CLIOptions


class Action(RemoteCommand):

    protocol_spec = __doc__ = '''
    action+/str: The action to perform. Of the form: action [optional args...]
    match_window/str: Window to run the action on
    self/bool: Whether to use the window this command is run in as the active window
    '''

    short_desc = 'Run the specified mappable action'
    desc = (
        'Run the specified mappable action. For a list of all available mappable actions, see :doc:`actions`.'
        ' Any arguments for ACTION should follow the action. Note that parsing of arguments is action dependent'
        ' so for best results specify all arguments as single string on the command line in the same format as you would'
        ' use for that action in kitty.conf.'
    )
    options_spec = '''\
--self
type=bool-set
Run the action on the window this command is run in instead of the active window.


--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
''' + '\n\n' + MATCH_WINDOW_OPTION

    args = RemoteCommand.Args(
        spec='ACTION [ARGS FOR ACTION...]', json_field='action', minimum_count=1,
        completion=RemoteCommand.CompletionSpec.from_string('type:special group:complete_actions')
    )

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'action': ' '.join(args), 'self': opts.self, 'match_window': opts.match}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        w = self.windows_for_match_payload(boss, window, payload_get)
        if w:
            window = w[0]
        ac = payload_get('action')
        if not ac:
            raise RemoteControlErrorWithoutTraceback('Must specify an action')

        try:
            consumed = boss.combine(str(ac), window, raise_error=True)
        except (Exception, SystemExit) as e:
            raise RemoteControlErrorWithoutTraceback(str(e))

        if not consumed:
            raise RemoteControlErrorWithoutTraceback(f'Unknown action: {ac}')
        return None


action = Action()
