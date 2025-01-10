#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>


from typing import TYPE_CHECKING

from kitty.constants import appname

from .base import (
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
    from kitty.cli_stub import LoadConfigRCOptions as CLIOptions


class LoadConfig(RemoteCommand):

    protocol_spec = __doc__ = '''
    paths/list.str: List of config file paths to load
    override/list.str: List of individual config overrides
    ignore_overrides/bool: Whether to apply previous overrides
    '''

    short_desc = '(Re)load a config file'
    desc = (
        '(Re)load the specified kitty.conf config files(s). If no files are specified the previously specified config file is reloaded.'
        ' Note that the specified paths must exist and be readable by the kitty process on the computer that process is running on.'
        ' Relative paths are resolved with respect to the kitty config directory on the computer running kitty.'
    )
    options_spec = f'''\
--ignore-overrides
type=bool-set
By default, any config overrides previously specified at the kitty invocation command line
or a previous load-config-file command are respected. Use this option to have them ignored instead.


--override -o
type=list
completion=type:special group:complete_kitty_override
Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`{appname} -o` font_size=20


--no-response
type=bool-set
default=false
Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.
'''

    args = RemoteCommand.Args(spec='CONF_FILE ...', json_field='paths',
                              completion=RemoteCommand.CompletionSpec.from_string('type:file group:"CONF files", ext:conf'))

    def message_to_kitty(self, global_opts: RCOptions, opts: 'CLIOptions', args: ArgsType) -> PayloadType:
        return {'paths': args, 'override': opts.override, 'ignore_overrides': opts.ignore_overrides}

    def response_from_kitty(self, boss: Boss, window: Window | None, payload_get: PayloadGetType) -> ResponseType:
        from kitty.cli import parse_override
        from kitty.utils import resolve_abs_or_config_path
        paths = tuple(map(resolve_abs_or_config_path, payload_get('paths', missing=())))
        boss.load_config_file(
            *paths, apply_overrides=not payload_get('ignore_overrides', missing=False),
            overrides=tuple(map(parse_override, payload_get('override', missing=())))
        )
        return None


load_config = LoadConfig()
