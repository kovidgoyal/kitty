#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Requesting XDG activation tokens (OSC 5524), see docs/misc-protocol.rst

import re
from base64 import standard_b64encode
from typing import NamedTuple

OSC_CODE = 5524
ID_PATTERN = re.compile(r'[a-zA-Z0-9_+.-]{1,64}')
# Tokens are only given if the user pressed a key or mouse button in the
# window within this many seconds
MAX_SECONDS_SINCE_INPUT = 10
# A request for which the compositor has not provided a token within this many
# seconds is considered to have failed, so that the window can request again
PENDING_REQUEST_TIMEOUT = 5


class InvalidRequest(ValueError):
    pass


class Request(NamedTuple):
    id: str
    is_query: bool = False


def parse_request(raw: str) -> Request:
    # The metadata is a list of key=value pairs separated by colons, followed
    # by an optional semi-colon and payload, which is currently unused.
    # Unknown keys are ignored for forward compatibility.
    metadata = raw.partition(';')[0]
    ident = ''
    is_query = False
    for item in metadata.split(':'):
        key, sep, val = item.partition('=')
        if not sep:
            raise InvalidRequest(f'invalid metadata: {item!r}')
        if key == 'i':
            ident = val
        elif key == 'p':
            if val != '?':
                raise InvalidRequest(f'unknown value for p: {val!r}')
            is_query = True
    if not ID_PATTERN.fullmatch(ident):
        raise InvalidRequest(f'missing or invalid identifier: {ident!r}')
    return Request(ident, is_query)


def query_reply(req: Request) -> str:
    return f'{OSC_CODE};i={req.id}:p=?;ok'


def token_reply(req: Request, token: str) -> str:
    return f'{OSC_CODE};i={req.id};{standard_b64encode(token.encode()).decode()}'


def error_reply(req: Request, code: str) -> str:
    return f'{OSC_CODE};i={req.id}:e={code}'
