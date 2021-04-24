#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

from typing import Any, Optional

from .base import (
    ArgsType, Boss, PayloadGetType, PayloadType, RCOptions, RemoteCommand,
    ResponseType, Window
)


class Env(RemoteCommand):

    '''
    env+: dictionary of environment variables to values. Empty values cause the variable to be deleted.
    '''

    short_desc = 'Change environment variables seen by future children'
    desc = (
        'Change the environment variables seen by processing in newly launched windows.'
        ' Similar to the :opt:`env` option in kitty.conf, but affects running kitty instances.'
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


env = Env()
