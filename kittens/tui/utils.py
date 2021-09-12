#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from contextlib import suppress

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


def human_size(size: int, sep: str = ' ') -> str:
    """ Convert a size in bytes into a human readable form """
    divisor, suffix = 1, "B"
    for i, candidate in enumerate(('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB')):
        if size < (1 << ((i + 1) * 10)):
            divisor, suffix = (1 << (i * 10)), candidate
            break
    ans = str(size / divisor)
    if ans.find(".") > -1:
        ans = ans[:ans.find(".")+2]
    if ans.endswith('.0'):
        ans = ans[:-2]
    return ans + sep + suffix
