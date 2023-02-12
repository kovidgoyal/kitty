#!/usr/bin/env python
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import secrets
from contextlib import contextmanager
from datetime import timedelta
from typing import Generator, Union

from kitty.fast_data_types import truncate_point_for_length, wcswidth
from kitty.guess_mime_type import guess_type

from ..tui.operations import styled
from ..tui.progress import render_progress_bar
from ..tui.utils import format_number, human_size

_cwd = _home = ''


def safe_divide(numerator: Union[int, float], denominator: Union[int, float], zero_val: float = 0.) -> float:
    return numerator / denominator if denominator else zero_val


def reduce_to_single_grapheme(text: str) -> str:
    limit = len(text)
    if limit < 2:
        return text
    x = 1
    while x < limit:
        pos = truncate_point_for_length(text, x)
        if pos > 0:
            return text[:pos]
        x += 1
    return text


def render_path_in_width(path: str, width: int) -> str:
    if os.altsep:
        path = path.replace(os.altsep, os.sep)
    if wcswidth(path) <= width:
        return path
    parts = path.split(os.sep)
    reduced = os.sep.join(map(reduce_to_single_grapheme, parts[:-1]))
    path = os.path.join(reduced, parts[-1])
    if wcswidth(path) <= width:
        return path
    x = truncate_point_for_length(path, width - 1)
    return f'{path[:x]}…'


def render_seconds(val: float) -> str:
    ans = str(timedelta(seconds=int(val)))
    if ',' in ans:
        days = int(ans.split(' ')[0])
        if days > 99:
            ans = '∞'
        else:
            ans = f'>{days} days'
    elif len(ans) == 7:
        ans = '0' + ans
    return ans.rjust(8)


def ljust(text: str, width: int) -> str:
    w = wcswidth(text)
    if w < width:
        text += ' ' * (width - w)
    return text


def rjust(text: str, width: int) -> str:
    w = wcswidth(text)
    if w < width:
        text = ' ' * (width - w) + text
    return text


def render_progress_in_width(
    path: str,
    max_path_length: int = 80,
    spinner_char: str = '⠋',
    bytes_per_sec: float = 1024,
    secs_so_far: float = 100.,
    bytes_so_far: int = 33070,
    total_bytes: int = 50000,
    width: int = 80,
    is_complete: bool = False,
) -> str:
    unit_style = styled('|', dim=True)
    sep, trail = unit_style.split('|')
    if is_complete or bytes_so_far >= total_bytes:
        ratio = human_size(total_bytes, sep=sep)
        rate = human_size(int(safe_divide(total_bytes, secs_so_far)), sep=sep) + '/s'
        eta = styled(render_seconds(secs_so_far), fg='green')
    else:
        tb = human_size(total_bytes, sep=' ', max_num_of_decimals=1)
        val = float(tb.split(' ', 1)[0])
        ratio = format_number(val * safe_divide(bytes_so_far, total_bytes), max_num_of_decimals=1) + '/' + tb.replace(' ', sep)
        rate = human_size(int(bytes_per_sec), sep=sep) + '/s'
        bytes_left = total_bytes - bytes_so_far
        eta_seconds = safe_divide(bytes_left, bytes_per_sec)
        eta = render_seconds(eta_seconds)
    lft = f'{spinner_char} '
    max_space_for_path = width // 2 - wcswidth(lft)
    w = min(max_path_length, max_space_for_path)
    p = lft + render_path_in_width(path, w)
    w += wcswidth(lft)
    p = ljust(p, w)
    q = f'{ratio}{trail}{styled(" @ ", fg="yellow")}{rate}{trail}'
    q = rjust(q, 25) + ' '
    eta = ' ' + eta
    extra = width - w - wcswidth(q) - wcswidth(eta)
    if extra > 4:
        q += render_progress_bar(safe_divide(bytes_so_far, total_bytes), extra) + eta
    else:
        q += eta.strip()
    return p + q


def should_be_compressed(path: str) -> bool:
    ext = path.rpartition(os.extsep)[-1].lower()
    if ext in ('zip', 'odt', 'odp', 'pptx', 'docx', 'gz', 'bz2', 'xz', 'svgz'):
        return False
    mt = guess_type(path) or ''
    if mt:
        if mt.endswith('+zip'):
            return False
        if mt.startswith('image/') and mt not in ('image/svg+xml',):
            return False
        if mt.startswith('video/'):
            return False
    return True


def abspath(path: str, use_home: bool = False) -> str:
    base = home_path() if use_home else (_cwd or os.getcwd())
    return os.path.normpath(os.path.join(base, path))


def home_path() -> str:
    return _home or os.path.expanduser('~')


def cwd_path() -> str:
    return _cwd or os.getcwd()


def expand_home(path: str) -> str:
    if path.startswith('~' + os.sep) or (os.altsep and path.startswith('~' + os.altsep)):
        return os.path.join(home_path(), path[2:].lstrip(os.sep + (os.altsep or '')))
    return path


def random_id() -> str:
    ans = hex(os.getpid())[2:]
    x = secrets.token_hex(2)
    return ans + x


@contextmanager
def set_paths(cwd: str = '', home: str = '') -> Generator[None, None, None]:
    global _cwd, _home
    orig = _cwd, _home
    try:
        _cwd, _home = cwd, home
        yield
    finally:
        _cwd, _home = orig


class IdentityCompressor:

    def compress(self, data: bytes) -> bytes:
        return data

    def flush(self) -> bytes:
        return b''


class ZlibCompressor:

    def __init__(self) -> None:
        import zlib
        self.c = zlib.compressobj()

    def compress(self, data: bytes) -> bytes:
        return self.c.compress(data)

    def flush(self) -> bytes:
        return self.c.flush()


def print_rsync_stats(total_bytes: int, delta_bytes: int, signature_bytes: int) -> None:
    print('Rsync stats:')
    print(f'  Delta size: {human_size(delta_bytes)} Signature size: {human_size(signature_bytes)}')
    frac = (delta_bytes + signature_bytes) / max(1, total_bytes)
    print(f'  Transmitted: {human_size(delta_bytes + signature_bytes)} of a total of {human_size(total_bytes)} ({frac:.1%})')
