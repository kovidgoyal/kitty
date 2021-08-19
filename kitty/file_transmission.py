#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from enum import Enum, auto
from base64 import standard_b64decode


class Action(Enum):
    send = auto()
    data = auto()
    receive = auto()
    invalid = auto()


class FileTransmissionCommand:

    action = Action.invalid
    id: str = ''
    secret: str = ''

    payload = b''


def parse_command(data: str) -> FileTransmissionCommand:
    parts = data.split(':', 1)
    ans = FileTransmissionCommand()
    if len(parts) == 1:
        control, payload = parts[0], ''
    else:
        control, payload = parts
        ans.payload = standard_b64decode(payload)

    for x in control.split(','):
        k, v = x.partition('=')[::2]
        if k == 'action':
            ans.action = Action[v]
        elif k == 'id':
            ans.id = v
        elif k == 'secret':
            ans.secret = v

    if ans.action is Action.invalid:
        raise ValueError('No valid action specified in file transmission command')

    return ans
