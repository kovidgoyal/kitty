#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from base64 import standard_b64decode, standard_b64encode
from typing import TYPE_CHECKING

from kitty.launch import env_docs, remote_control_password_docs
from kitty.options.utils import env as parse_env
from kitty.types import AsyncResponse

from .base import (
    ArgsType,
    Boss,
    CmdGenerator,
    ParsingOfArgsFailed,
    PayloadGetType,
    PayloadType,
    RCOptions,
    RemoteCommand,
    ResponseType,
    Window,
)

if TYPE_CHECKING:
    from kitty.cli_stub import RunRCOptions as CLIOptions


class Run(RemoteCommand):
    protocol_spec = __doc__ = '''
    data+/str: Chunk of STDIN data, base64 encoded no more than 4096 bytes. Must send an empty chunk to indicate end of data.
    cmdline+/list.str: The command line to run
    env/list.str: List of environment variables of the form NAME=VALUE
    allow_remote_control/bool: A boolean indicating whether to allow remote control
    remote_control_password/list.str: A list of remote control passwords
    '''

    short_desc = 'Run a program on the computer in which kitty is running and get the output'
    desc = (
        'Run the specified program on the computer in which kitty is running. When STDIN is not a TTY it is forwarded'
        ' to the program as its STDIN. STDOUT and STDERR from the the program are forwarded here. The exit status of this'
        ' invocation will be the exit status of the executed program. If you wish to just run a program without waiting for a response, '
        ' use @ launch --type=background instead.'
    )

    options_spec = f'''\n
--env
{env_docs}


--allow-remote-control
type=bool-set
The executed program will have privileges to run remote control commands in kitty.


--remote-control-password
{remote_control_password_docs}
'''
    args = RemoteCommand.Args(
        spec='CMD ...', json_field='data', special_parse='+cmdline:!read_run_data(io_data, args, &payload)', minimum_count=1,
        completion=RemoteCommand.CompletionSpec.from_string('type:special group:cli.CompleteExecutableFirstArg')
    )
    reads_streaming_data = True
    is_asynchronous = True

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        if not args:
            self.fatal('Must specify command to run')
        import secrets
        ret = {
            'stream_id': secrets.token_urlsafe(),
            'cmdline': args,
            'env': opts.env,
            'allow_remote_control': opts.allow_remote_control,
            'remote_control_password': opts.remote_control_password,
            'data': '',
        }
        def pipe() -> CmdGenerator:
            if sys.stdin.isatty():
                yield ret
            else:
                limit = 4096
                while True:
                    data = sys.stdin.buffer.read(limit)
                    if not data:
                        break
                    ret['data'] = standard_b64encode(data).decode("ascii")
                    yield ret
        return pipe()

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        import os
        import tempfile
        data = payload_get('data')
        q = self.handle_streamed_data(standard_b64decode(data) if data else b'', payload_get)
        if isinstance(q, AsyncResponse):
            return q
        stdin_data = q.getvalue()
        from kitty.launch import parse_remote_control_passwords
        cmdline = payload_get('cmdline')
        allow_remote_control = payload_get('allow_remote_control')
        pw = payload_get('remote_control_password')
        rcp = parse_remote_control_passwords(allow_remote_control, pw)
        if not cmdline:
            raise ParsingOfArgsFailed('No cmdline to run specified')
        responder = self.create_async_responder(payload_get, window)
        stdout, stderr = tempfile.TemporaryFile(), tempfile.TemporaryFile()

        def on_death(exit_status: int, err: Exception | None) -> None:
            with stdout, stderr:
                if err:
                    responder.send_error(f'Failed to run: {cmdline} with err: {err}')
                else:
                    exit_code = os.waitstatus_to_exitcode(exit_status)
                    stdout.seek(0)
                    stderr.seek(0)
                    responder.send_data({
                        'stdout': standard_b64encode(stdout.read()).decode('ascii'),
                        'stderr': standard_b64encode(stderr.read()).decode('ascii'),
                        'exit_code': exit_code, 'exit_status': exit_status,
                    })

        env: dict[str, str] = {}
        for x in payload_get('env') or ():
            for k, v in parse_env(x, env):
                env[k] = v

        boss.run_background_process(
            cmdline, env=env, stdin=stdin_data, stdout=stdout.fileno(), stderr=stderr.fileno(),
            notify_on_death=on_death, remote_control_passwords=rcp, allow_remote_control=allow_remote_control
        )
        return AsyncResponse()


run = Run()
