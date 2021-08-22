#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2021, Kovid Goyal <kovid at kovidgoyal.net>

import os
import sys
from contextlib import suppress
from typing import List, Optional, Tuple, Iterator

from kitty.constants import cache_dir
from kitty.types import run_once
from kitty.typing import TypedDict
from kitty.config import atomic_save

from ..tui.operations import clear_screen, set_window_title, styled, set_cursor_shape
from ..tui.utils import get_key_press


def history_path() -> str:
    return os.path.join(cache_dir(), 'transfer-ask.history')


class Response(TypedDict):
    dest: str
    allowed: bool


def sort_key(item: str) -> Tuple[int, str]:
    return len(item), item.lower()


def get_filesystem_matches(prefix: str) -> Iterator[str]:
    fp = os.path.abspath(os.path.expanduser(prefix))
    base = os.path.dirname(fp)
    with suppress(OSError):
        for x in os.listdir(base):
            q = os.path.join(base, x)
            if q.startswith(fp):
                yield prefix + q[len(fp):]


class ReadPath:

    def __enter__(self) -> 'ReadPath':
        self.matches: List[str] = []
        import readline

        from kitty.shell import init_readline
        init_readline()
        readline.set_completer(self.complete)
        self.delims = readline.get_completer_delims()
        readline.set_completer_delims('\n\t')
        readline.clear_history()
        for x in history_list():
            readline.add_history(x)
        return self

    def input(self, add_to_history: str = '', prompt: str = '> ') -> str:
        import readline
        print(end=set_cursor_shape('bar'))
        if add_to_history:
            readline.add_history(add_to_history)
        try:
            return input(prompt)
        finally:
            print(end=set_cursor_shape())

    def complete(self, text: str, state: int) -> Optional[str]:
        if state == 0:
            self.matches = sorted(get_filesystem_matches(text), key=sort_key)
        with suppress(IndexError):
            return self.matches[state]

    def add_history(self, x: str) -> None:
        hl = history_list()
        with suppress(ValueError):
            hl.remove(x)
        hl.append(x)
        del hl[:-50]
        atomic_save('\n'.join(hl).encode('utf-8'), history_path())

    def __exit__(self, *a: object) -> None:
        import readline
        readline.set_completer()
        readline.set_completer_delims(self.delims)


@run_once
def history_list() -> List[str]:
    with suppress(FileNotFoundError), open(history_path()) as f:
        return f.read().splitlines()
    return []


def guess_destination(requested: str) -> str:
    if os.path.isabs(requested):
        return requested
    if history_list():
        return os.path.join(history_list()[-1], requested)
    for q in ('~/Downloads', '~/downloads', '/tmp'):
        q = os.path.expanduser(q)
        if os.path.isdir(q) and os.access(q, os.X_OK):
            return os.path.join(q, requested)
    return os.path.join(os.path.expanduser('~'), requested)


def a(x: str) -> str:
    return styled(x.upper(), fg='red', fg_intense=True)


def draw_put_main_screen(is_multiple: bool, dest: str) -> None:
    print(end=clear_screen())
    sd = styled(dest, fg='green', fg_intense=True, bold=True)

    if is_multiple:
        print('The remote machine wants to send you multiple files')
        print('They will be placed in the', sd, 'directory')
    else:
        print('The remote machine wants to send you a single file')
        print('It will be saved as', sd)

    if os.path.exists(dest):
        print()
        print(styled(f'{dest} already exists and will be replaced', fg='magenta', fg_intense=True, bold=True))
        print()

    print()
    print(f'{a("A")}llow the download')
    print(f'{a("R")}efuse the download')
    print(f'{a("C")}hange the download location')


def change_destination(is_multiple: bool, dest: str) -> str:
    print(end=clear_screen())
    print('Choose a destination')
    print('Current: ', styled(dest, italic=True))
    print()
    with ReadPath() as r:
        new_dest = r.input(dest)
        if new_dest:
            r.add_history(os.path.dirname(new_dest))
            new_dest = os.path.abspath(os.path.expanduser(new_dest))
    return new_dest or dest


def put_main(args: List[str]) -> Response:
    print(end=set_window_title('Receive a file?'))
    is_multiple = args[1] == 'multiple'
    dest = guess_destination(args[2])
    while True:
        draw_put_main_screen(is_multiple, dest)
        res = get_key_press('arc', 'r')
        if res == 'r':
            return {'dest': '', 'allowed': False}
        if res == 'a':
            return {'dest': dest, 'allowed': True}
        if res == 'c':
            dest = change_destination(is_multiple, dest)


def get_main(args: List[str]) -> Response:
    dest = os.path.abspath(os.path.expanduser(args[1]))
    if not os.path.exists(dest) or not os.access(dest, os.R_OK):
        return {'dest': dest, 'allowed': False}
    is_dir = os.path.isdir(dest)
    q = 'directory' if is_dir else 'file'
    print(end=set_window_title(f'Send a {q}?'))
    sd = styled(dest, fg='green', fg_intense=True, bold=True)
    while True:
        print(end=clear_screen())
        print(f'The remote machine is asking for the {q}: {sd}')
        print()
        print(f'{a("A")}llow the download')
        print(f'{a("R")}efuse the download')
        res = get_key_press('ar', 'r')
        if res == 'r':
            return {'dest': '', 'allowed': False}
        if res == 'a':
            return {'dest': dest, 'allowed': True}


def main(args: List[str]) -> Response:
    q = args[1]
    del args[1]
    if q == 'put':
        return put_main(args)
    return get_main(args)


if __name__ == '__main__':
    ans = main(sys.argv)
    if ans:
        print(ans)
