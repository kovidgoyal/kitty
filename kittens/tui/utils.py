#!/usr/bin/env python
# License: GPLv3 Copyright: 2020, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, Optional, cast

from kitty.types import run_once

from .operations import raw_mode, set_cursor_visible

if TYPE_CHECKING:
    from kitty.options.types import Options


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
    unit_list: tuple[str, ...] = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB')
) -> str:
    """ Convert a size in bytes into a human readable form """
    if size < 2:
        return f'{size}{sep}{unit_list[0]}'
    from math import log
    exponent = min(int(log(size, 1024)), len(unit_list) - 1)
    return format_number(size / 1024**exponent, max_num_of_decimals) + sep + unit_list[exponent]


def kitty_opts() -> 'Options':
    from kitty.fast_data_types import get_options, set_options
    try:
        ans = cast(Optional['Options'], get_options())
    except RuntimeError:
        ans = None
    if ans is None:
        from kitty.cli import create_default_opts
        from kitty.utils import suppress_error_logging
        with suppress_error_logging():
            ans = create_default_opts()
            set_options(ans)
    return ans


def set_kitty_opts(paths: Sequence[str], overrides: Sequence[str] = ()) -> 'Options':
    from kitty.config import load_config
    from kitty.fast_data_types import set_options
    from kitty.utils import suppress_error_logging
    with suppress_error_logging():
        opts = load_config(*paths, overrides=overrides or None)
        set_options(opts)
        return opts


def report_error(msg: str = '', return_code: int = 1, print_exc: bool = False) -> None:
    ' Report an error also sending the overlay ready message to ensure kitten is visible '
    from .operations import overlay_ready
    print(end=overlay_ready())
    if msg:
        print(msg, file=sys.stderr)
    if print_exc:
        cls, e, tb = sys.exc_info()
        if e and not isinstance(e, (SystemExit, KeyboardInterrupt)):
            import traceback
            traceback.print_exc()
    with suppress(KeyboardInterrupt, EOFError):
        input('Press Enter to quit')
    raise SystemExit(return_code)


def report_unhandled_error(msg: str = '') -> None:
    ' Report an unhandled exception with the overlay ready message '
    return report_error(msg, print_exc=True)


@run_once
def running_in_tmux() -> str:
    socket = os.environ.get('TMUX')
    if not socket:
        return ''
    parts = socket.split(',')
    if len(parts) < 2:
        return ''
    try:
        if not os.access(parts[0], os.R_OK | os.W_OK):
            return ''
    except OSError:
        return ''
    from kitty.child import cmdline_of_pid
    c = cmdline_of_pid(int(parts[1]))
    if not c:
        return ''
    exe = os.path.basename(c[0])
    if exe.lower() == 'tmux':
        return exe
    return ''
