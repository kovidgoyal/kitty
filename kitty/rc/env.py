#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any, Optional

from .base import (
    ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand,
    ResponseType, Window
)


class Env(RemoteCommand):

    protocol_spec = __doc__ = '''
    env+/dict.str: Dictionary of environment variables to values. Empty values cause the variable to be removed.
    '''

    short_desc = 'Change environment variables seen by future children'
    desc = (
        'Change the environment variables that will be seen in newly launched windows.'
        ' Similar to the :opt:`env` option in :file:`kitty.conf`, but affects running kitty instances.'
        ' Empty values cause the environment variable to be removed.'
    )
    argspec = 'env_var1=val env_var2=val ...'

    def message_to_kitty(self, global_opts: RCOptions, opts: Any, args: ArgsType) -> PayloadType:
        if len(args) < 1:
            self.fatal('Must specify at least one env var to set')
        env = {}
        for x in args:
            key, val = x.split('=', 1)
            env[key] = val
        return {'env': env}

    def response_from_kitty(self, boss: Boss, window: Optional[Window], payload_get: PayloadGetType) -> ResponseType:
        from kitty.child import default_env, set_default_env
        from kitty.utils import expandvars
        new_env = payload_get('env') or {}
        env = default_env().copy()
        for k, v in new_env.items():
            if v:
                env[k] = expandvars(v, env)
            else:
                env.pop(k, None)
        set_default_env(env)
        return None


env = Env()
