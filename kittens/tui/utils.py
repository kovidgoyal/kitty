#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import suppress
from typing import Tuple

from .operations import raw_mode, set_cursor_visible


def get_key_press(allowed: str, default: str) -> str:
    response = default
    with raw_mode():
        print(set_cursor_visible(False), end='', flush=True)
        try:
            while True:
                q = sys.stdin.buffer.read(1)
                if q:
                    if q in b'\x1b\x03':
                        break
                    with suppress(Exception):
                        response = q.decode('utf-8').lower()
                        if response in allowed:
                            break
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            print(set_cursor_visible(True), end='', flush=True)
    return response


def format_number(val: float, max_num_of_decimals: int = 2) -> str:
    ans = str(val)
    pos = ans.find('.')
    if pos > -1:
        ans = ans[:pos + max_num_of_decimals + 1]
    return ans.rstrip('0').rstrip('.')


def human_size(
    size: int, sep: str = ' ',
    max_num_of_decimals: int = 2,
    unit_list: Tuple[str, ...] = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB')
) -> str:
    """ Convert a size in bytes into a human readable form """
    if size < 2:
        return f'{size}{sep}{unit_list[0]}'
    from math import log
    exponent = min(int(log(size, 1024)), len(unit_list) - 1)
    return format_number(size / 1024**exponent, max_num_of_decimals) + sep + unit_list[exponent]


def report_unhandled_error(msg: str = '') -> None:
    ' Report an unhandled exception also sending the overlay ready message to ensure kitten is visible '
    from .operations import overlay_ready
    print(end=overlay_ready())
    if msg:
        print(msg, file=sys.stderr)
    cls, e, tb = sys.exc_info()
    if not isinstance(e, (SystemExit, KeyboardInterrupt)):
        import traceback
        traceback.print_exc()
    input('Press Enter to quit.')
    raise SystemExit(1)
