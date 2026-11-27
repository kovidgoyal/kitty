#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

# Requesting XDG activation tokens (OSC 5524), see docs/misc-protocol.rst

from base64 import standard_b64encode
from typing import NamedTuple

OSC_CODE = 5524
# The maximum length of an identifier, see docs/misc-protocol.rst
MAX_ID_LENGTH = 64
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


def is_valid_identifier(ident: str) -> bool:
    # The same identifiers as the desktop notifications protocol (OSC 99),
    # which are echoed in replies, so anything else is rejected
    from .notifications import sanitize_identifier_pat

    return 0 < len(ident) <= MAX_ID_LENGTH and sanitize_identifier_pat().search(ident) is None


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
    if not is_valid_identifier(ident):
        raise InvalidRequest(f'missing or invalid identifier: {ident!r}')
    return Request(ident, is_query)


def query_reply(req: Request) -> str:
    return f'{OSC_CODE};i={req.id}:p=?;ok'


def token_reply(req: Request, token: str) -> str:
    return f'{OSC_CODE};i={req.id};{standard_b64encode(token.encode()).decode()}'


def error_reply(req: Request, code: str) -> str:
    return f'{OSC_CODE};i={req.id}:e={code}'
