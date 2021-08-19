#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

from base64 import standard_b64decode
from enum import Enum, auto
from typing import Optional

from .utils import log_error


class Action(Enum):
    send = auto()
    data = auto()
    end_data = auto()
    receive = auto()
    invalid = auto()


class Container(Enum):
    zip = auto()
    tar = auto()
    tgz = auto()
    tbz2 = auto()
    txz = auto()
    none = auto()


class Compression(Enum):
    zlib = auto()
    none = auto()


class Encoding(Enum):
    base64 = auto()


class FileTransmissionCommand:

    action = Action.invalid
    container_fmt = Container.none
    compression = Compression.none
    encoding = Encoding.base64
    id: str = ''
    secret: str = ''
    mime: str = ''

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
        elif k == 'container_fmt':
            ans.container_fmt = Container[v]
        elif k == 'compression':
            ans.compression = Compression[v]
        elif k == 'encoding':
            ans.encoding = Encoding[v]
        elif k in ('secret', 'mime', 'id'):
            setattr(ans, k, v)

    if ans.action is Action.invalid:
        raise ValueError('No valid action specified in file transmission command')

    return ans


class FileTransmission:

    active_cmd: Optional[FileTransmissionCommand] = None

    def __init__(self, window_id: int):
        self.window_id = window_id

    def handle_serialized_command(self, data: str) -> None:
        try:
            cmd = parse_command(data)
        except Exception as e:
            log_error(f'Failed to parse file transmission command with error: {e}')
            return
        if self.active_cmd is not None:
            if cmd.action not in (Action.data, Action.end_data):
                log_error('File transmission command received while another is in flight, aborting')
                self.abort_in_flight()
        if cmd.action is Action.send:
            self.start_send(cmd)

    def start_send(self, cmd: FileTransmissionCommand) -> None:
        self.active_cmd = cmd

    def abort_in_flight(self) -> None:
        self.active_cmd = None
